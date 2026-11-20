"""
scripts/shadow_review.py -- a visual review sheet for the shadow validator records (for the owner-approved review: look at the disagreements and at a sample of agreements).

    python scripts/shadow_review.py                          # up to 20 disagreements and 10 agreements from the whole log
    python scripts/shadow_review.py --since 2026-10-15 --disagreements 30 --agreements 12 --out logs/shadow_review.html
    python scripts/shadow_review.py --exclude ID1,ID2        # leave out sessions (notebook ids)

Writes ONE HTML page (open it in a browser). Each card shows the drawing as the model wrote it (from the log's draw_started record, so drawings the existing validator
rejected are included), the elements already on the page at that moment in grey (from the database), the existing and proposed verdicts, and the boxes of the shapes the
proposal blames: red dashed = a rejection reason, orange = an advisory. Nothing is changed anywhere. The page contains drawing content: it is written under logs/ (not committed).
"""
import argparse
import collections
import html
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from shadow_report import log_rows, topics_of      # noqa: E402

MARKERS = ('<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#2563eb"/></marker>'
           '<marker id="arrow-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#1e293b"/></marker>'
           '<marker id="arrow-green" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#059669"/></marker></defs>')
BOX = re.compile(r"@(-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)")


def parse(ts):
    return datetime.strptime(ts[:26].rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f")


def clean(svg):
    return re.sub(r"<style\b.*?</style>", "", svg or "", flags=re.S)


def context_before(page_id, ts, element_id):
    """The drawings that were on the page when the element was drawn (draw events of the page, by time)."""
    try:
        from sqlmodel import Session, select
        from backend.database import engine
        from backend.models import PageEvent
        with Session(engine) as db:
            evs = db.exec(select(PageEvent).where(PageEvent.page_id == page_id).order_by(PageEvent.seq)).all()
        return "".join(clean(e.svg_fragment) for e in evs if e.kind == "draw" and e.element_id != element_id and e.timestamp <= parse(ts))
    except Exception:
        return ""


def overlay(reasons, colour, dash):
    out = ""
    for r in reasons:
        for key in ("a", "b"):
            m = BOX.search(r.get(key, "") or "")
            if m:
                x0, y0, x1, y1 = map(float, m.groups())
                out += f'<rect x="{x0}" y="{y0}" width="{max(x1 - x0, 2)}" height="{max(y1 - y0, 2)}" fill="none" stroke="{colour}" stroke-width="2" stroke-dasharray="{dash}"/>'
    return out


def select_samples(ok, n_dis, n_agree, seed=7):
    rng = random.Random(seed)
    dis = [r for r in ok if r["data"].get("differs")]
    groups = collections.defaultdict(list)
    for r in dis:
        kinds = sorted(r["data"].get("reject_kinds") or {"-": 1})
        groups[(r["data"]["existing"], r["data"]["proposed"], kinds[0])].append(r)
    chosen, queues = [], [rng.sample(v, len(v)) for _, v in sorted(groups.items())]
    while len(chosen) < n_dis and any(queues):
        for q in queues:
            if q and len(chosen) < n_dis:
                chosen.append(q.pop())
    both_acc = [r for r in ok if not r["data"].get("differs") and r["data"]["proposed"] == "accept"]
    both_rej = [r for r in ok if not r["data"].get("differs") and r["data"]["proposed"] == "reject"]
    agree = rng.sample(both_acc, min(len(both_acc), (n_agree + 1) // 2)) + rng.sample(both_rej, min(len(both_rej), n_agree // 2))
    return chosen, agree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--disagreements", type=int, default=20)
    ap.add_argument("--agreements", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "logs" / "shadow_review.html"))
    a = ap.parse_args()
    excl = set(x for x in a.exclude.split(",") if x)
    rows = list(log_rows(a.since))
    ok = [r for r in rows if r.get("event") == "shadow_validated" and r.get("session_id") not in excl]
    raw = collections.defaultdict(list)
    for r in rows:
        if r.get("event") == "draw_started" and (r.get("data") or {}).get("raw_svg"):
            raw[(r.get("session_id"), r["data"]["element_id"])].append((parse(r["ts"]), r["data"]["raw_svg"]))
    topics = topics_of({r.get("session_id") for r in ok})
    dis, agree = select_samples(ok, a.disagreements, a.agreements)
    cards = []
    for label, group in (("DISAGREEMENT", dis), ("AGREEMENT", agree)):
        for r in group:
            d = r["data"]
            t = parse(r["ts"])
            cands = [(t - ts, svg) for ts, svg in raw.get((r.get("session_id"), d["element_id"]), []) if ts <= t]
            svg = min(cands, key=lambda c: c[0])[1] if cands else ""
            ctx = context_before(d.get("page_id"), r["ts"], d["element_id"])
            reasons = overlay(d.get("reasons") or [], "#dc2626", "6 4") + overlay(d.get("advisories") or [], "#f59e0b", "2 3")
            body = (f'<g opacity="0.35">{ctx}</g>{clean(svg) if svg else ""}{reasons}') if svg or ctx else ""
            kinds = ", ".join(f"{k} x{n}" for k, n in (d.get("reject_kinds") or {}).items()) or "none"
            adv = ", ".join(f"{k} x{n}" for k, n in (d.get("advisory_kinds") or {}).items()) or "none"
            cards.append(f'<div class="card {label.lower()}"><div class="h"><b>{label}</b> | {html.escape(topics.get(r.get("session_id"), "?"))} | {html.escape(d["element_id"])} | {r["ts"][:19]}</div>'
                         f'<div class="v">existing <b>{d["existing"]}</b>{(" (" + d["existing_reason"] + ")") if d.get("existing_reason") else ""} | proposed <b>{d["proposed"]}</b> | roles {html.escape(json.dumps(d.get("roles", {})))}</div>'
                         f'<div class="v">would reject: {html.escape(kinds)}<br>advisory: {html.escape(adv)}</div>'
                         + (f'<svg viewBox="0 0 1200 800" width="560">{MARKERS}{body}</svg>' if body else '<div class="v">(drawing source not in the log)</div>') + "</div>")
    page = ("<!doctype html><meta charset='utf-8'><title>Shadow validator review sheet</title><style>body{font:13px system-ui;background:#f3f1ec;margin:12px}"
            ".card{display:inline-block;vertical-align:top;background:#fffdf8;border:1px solid #ccc;margin:6px;padding:6px;width:570px}.disagreement{border-color:#dc2626}"
            ".h{font-size:12px}.v{font-size:12px;margin:2px 0}svg{background:#fffdf8;border:1px solid #eee;display:block}</style>"
            f"<h3>Shadow validator review sheet: {len(dis)} disagreements, {len(agree)} agreements (of {len(ok)} records)</h3>"
            "<p>Red dashed = the shapes a rejection reason names; orange dotted = advisory; grey = what was already on the page.</p>" + "".join(cards))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(page, encoding="utf-8")
    print(f"{len(ok)} records, sheet with {len(dis)} disagreements and {len(agree)} agreements written to {a.out}")


if __name__ == "__main__":
    main()
