"""
tests/eval_tutor.py
Quality check for the live tutor. NOT part of pytest: it calls the real model and TTS (costs credits).

    python tests/eval_tutor.py            # all prompts
    python tests/eval_tutor.py --quick    # 3 prompts

Needs the backend running on 127.0.0.1:8001. Creates throwaway notebooks and deletes them at the end.

Hard checks (any failure => exit code 1):
  - the tutor replied with text and drew at least one element
  - every drawn element passes validate_geometry (bounds, labels, text overlap)
  - no two drawn elements overlap
Soft checks (reported, never fail the run):
  - layout variety across topics (a template sneaking back in shows up here)
  - latency per turn
  - dense request: tutor either fit the content cleanly or proposed a new page
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.validator import check_overlap, compute_coverage, extract_element_bboxes, find_layout_issues, validate_geometry  # noqa: E402

LOG = Path(__file__).parent.parent / "logs" / "learning_platform.jsonl"
API = os.environ.get("LP_API", "http://127.0.0.1:8001/api")
TURN_TIMEOUT = 300

# One short prompt per domain; the follow-up forces a second element so overlap/placement gets exercised.
PROMPTS = [
    ("history",   "Explain the causes of World War I", "Now show how the alliances were arranged"),
    ("maths",     "Explain what a derivative is", "Show a worked example next to it"),
    ("biology",   "Explain how photosynthesis works", "Add where each input and output goes"),
    ("code",      "Explain how binary search works", "Show the steps on a small example"),
    ("economics", "Explain supply and demand", "Show what happens when demand rises"),
    ("physics",   "Explain Newton's three laws", "Give one everyday example for each"),
    ("language",  "Explain the difference between past simple and present perfect", "Compare them with timelines"),
    ("dense",     "Draw the full 7-layer OSI model next to the TCP/IP 4-layer model, every layer labelled with an example protocol, plus a comparison between them.",
                  "Now add a full diagram of how a TCP handshake, TLS handshake and HTTP request relate"),
]


def rejections_logged():
    """Count of draw_failed events so far (guardrail rejections that forced the tutor to retry)."""
    try:
        return sum('"event": "draw_failed"' in l for l in LOG.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def run_topic(domain, first, second, created):
    nb = requests.post(f"{API}/notebooks", json={"topic": first}).json()["id"]
    created.append(nb)   # registered at once, so even a crash mid-topic is cleaned up at the end
    turns = []
    for msg in (first, second):
        t0 = time.time()
        r = requests.post(f"{API}/notebooks/{nb}/chat", json={"message": msg}, timeout=TURN_TIMEOUT)
        turns.append({"ok": r.status_code == 200, "secs": round(time.time() - t0, 1),
                      "text": (r.json().get("response", "") if r.status_code == 200 else r.text)})
    detail = requests.get(f"{API}/notebooks/{nb}").json()
    elements = []  # (page_number, element_id, fragment)
    for p in detail["pages"]:
        ev = requests.get(f"{API}/notebooks/{nb}/pages/{p['id']}/events").json()["events"]
        elements += [(p["page_number"], e["element_id"], e["svg_fragment"]) for e in ev if e["kind"] == "draw"]
    return nb, turns, elements, len(detail["pages"])


def score(domain, turns, elements, pages):
    fails, notes = [], []
    if not all(t["ok"] and t["text"].strip() for t in turns):
        fails.append("a turn failed or returned no text")
    if not elements:
        fails.append("nothing was drawn")
    by_page = {}
    for pn, eid, frag in elements:
        by_page.setdefault(pn, []).append((eid, frag))
        geo = validate_geometry(frag)
        if not geo["valid"]:
            fails.append(f"{eid}: " + "; ".join(v["detail"][:70] for v in geo["violations"]))
    for pn, items in by_page.items():
        seen = ""
        for eid, frag in items:
            clash = check_overlap(seen, frag)
            if clash:
                fails.append(f"page {pn}: {clash['new_id']} overlaps {clash['existing_id']}")
            seen += frag
    hints = [h for _, _, frag in elements for h in find_layout_issues(frag)]
    first_page = by_page.get(min(by_page), []) if by_page else []
    sig = sorted((round(b["bbox"]["x"] / 200), round(b["bbox"]["y"] / 200),
                  round(b["bbox"]["width"] / 200), round(b["bbox"]["height"] / 200))
                 for _, frag in first_page for b in extract_element_bboxes(frag))
    cov = round(compute_coverage("".join(f for _, f in first_page)), 2) if first_page else 0
    slow = [t["secs"] for t in turns if t["secs"] > 60]
    if slow:
        notes.append(f"slow turn(s): {slow}s")
    if domain == "dense":
        proposed = any("new page" in t["text"].lower() for t in turns)
        notes.append("dense: proposed a new page" if proposed else
                     ("dense: fit cleanly on one page" if pages == 1 else f"dense: tutor opened {pages} pages"))
    return {"fails": fails, "notes": notes, "sig": sig, "coverage": cov,
            "elements": len(elements), "pages": pages, "secs": [t["secs"] for t in turns],
            "unfinished_hints": hints}


def main():
    prompts = PROMPTS[:3] if "--quick" in sys.argv else PROMPTS
    try:
        requests.get(API.rsplit("/api", 1)[0] + "/health", timeout=3).raise_for_status()
    except Exception:
        sys.exit("Backend is not running on 127.0.0.1:8001 (start it first).")

    results, created = {}, []
    for domain, a, b in prompts:
        print(f"[{domain}] running...", flush=True)
        try:
            before = rejections_logged()
            nb, turns, elements, pages = run_topic(domain, a, b, created)
            results[domain] = score(domain, turns, elements, pages)
            results[domain]["rejections"] = rejections_logged() - before
        except Exception as e:  # keep going; a crash is a hard failure for that topic
            results[domain] = {"fails": [f"crashed: {e}"], "notes": [], "sig": [], "coverage": 0,
                               "elements": 0, "pages": 0, "secs": []}

    for nb in created:
        requests.delete(f"{API}/notebooks/{nb}")

    sigs = {json.dumps(r["sig"]) for r in results.values() if r["sig"]}
    n_sig = len([r for r in results.values() if r["sig"]])
    variety = round(len(sigs) / n_sig, 2) if n_sig else 0

    print("\n=== Tutor quality report ===")
    print(f"{'topic':<10} {'els':>3} {'pgs':>3} {'cover':>5} {'retry':>5} {'hint':>4} {'secs':<12} result")
    hard = 0
    for d, r in results.items():
        status = "PASS" if not r["fails"] else "FAIL"
        hard += bool(r["fails"])
        print(f"{d:<10} {r['elements']:>3} {r['pages']:>3} {r['coverage']:>5} {r.get('rejections', 0):>5} {len(r.get('unfinished_hints', [])):>4} {str(r['secs']):<12} {status}")
        for h in r.get("unfinished_hints", []):
            print(f"    ? still unfinished in final drawing: {h}")
        for f in r["fails"]:
            print(f"    x {f}")
        for n in r["notes"]:
            print(f"    - {n}")
    verdict = "ok" if variety >= 0.6 else "LOW: layouts look templated"
    print(f"\nLayout variety: {variety} distinct layouts per topic ({verdict})")
    total_rej = sum(r.get("rejections", 0) for r in results.values())
    print(f"Guardrail rejections (retries): {total_rej} total, {round(total_rej / max(1, len(results)), 1)} per topic")
    print(f"Hard failures: {hard} of {len(results)} topics")
    Path(__file__).with_name("eval_report.json").write_text(json.dumps(
        {"variety": variety, "results": results}, indent=2), encoding="utf-8")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
