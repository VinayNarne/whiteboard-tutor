"""
scripts/lesson_eval.py — the repeatable lesson check (scene mode).

Runs the fixed lesson set (tests/lesson_eval/lessons.json) against a running backend, with the same scripted learner every time
(a skip, a wrong idea, a vague guess, right answers), and checks every tutor turn automatically. Writes a report and the full
transcripts to docs/lesson_evals/, so a change can be measured against the last run instead of judged from one lesson.

Start a backend first, without voice so no ElevenLabs credits are spent (the tutor falls back to silent clips):
    $env:LP_SCENE_MODE = "1"; $env:LP_VOICE = "0"; python -m uvicorn backend.main:app --host 127.0.0.1 --port 8102
turn_failed counts 503s too: when they cluster in time, check the backend log for model timeouts (an Azure outage) first.
Then:
    python scripts/lesson_eval.py --url http://127.0.0.1:8102 --label baseline [--only sky,dns] [--judge]

--judge asks the tutor's model (AUTHOR_DEPLOYMENT), or --judge-deployment, whether a tutor reply states anything false; off by default (costs calls).
Model output varies run to run: compare totals over the whole set, and treat one lesson's result as a hint, not a verdict.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "tests" / "lesson_eval" / "lessons.json"
OUT = ROOT / "docs" / "lesson_evals"

# "right" only as a word on its own ("Right, ..."): "Right after the browser ..." is not praise (false alarm, 2026-11-20)
PRAISE = re.compile(r"^\W*(right(?=\s*[,.!:—–-])|exactly|correct|great|good job|well done|yes|perfect|nice|that's right|that is right|spot on)\b", re.I)
CORRECTION = re.compile(r"\b(not|isn'?t|aren'?t|doesn'?t|don'?t|can'?t|won'?t|actually|no,|instead|incorrect|close|myth|mistake)\b", re.I)
BLOCK_TOOLS = {"write_notes", "draw_scene", "draw_graph", "draw_table", "draw_bar_chart", "draw_venn"}

# The automatic checks: each is (name, what it means). A turn fails a check when the check applies and is not met.
CHECKS = {
    "turn_failed": "the turn did not return 200",
    "markup_in_chat": "the chat reply shows $, ** or [[ markers",
    "no_question": "the reply does not end with a question",
    "repeated_question": "the reply ends with (nearly) the same question as the turn before",
    "praised_skip": "after 'ok'/'continue' the reply opens with praise",
    "praised_wrong": "after a wrong or vague answer the reply opens with praise",
    "wrong_not_corrected": "after a wrong answer the reply has no correction wording",
    "wrong_not_recorded": "after a wrong or vague answer nothing was recorded as answered_wrong (only once a plan exists)",
    "skip_graded": "after a skip an answer was recorded (the code should refuse it)",
}


def last_question(text: str) -> str:
    qs = re.findall(r"[^.!?\n]*\?", re.sub(r"\S+://\S+", "", text or ""))
    return qs[-1].strip() if qs else ""


def check_turn(kind: str, reply: str, records: list, previous_reply: str, status: int, planned: bool) -> list:
    """The checks a tutor turn fails. kind: the scripted learner message that this turn answers (question, ok, wrong, ...)."""
    fails = []
    if status != 200:
        return ["turn_failed"]
    if re.search(r"\$(?!\d)[^$\s][^$]*\$|\*\*|\[\[", reply or ""):     # "$5 and $10" is money, not a formula
        fails.append("markup_in_chat")
    if not (reply or "").rstrip().endswith("?"):
        fails.append("no_question")
    q, pq = last_question(reply), last_question(previous_reply)
    if q and pq and SequenceMatcher(None, q.lower(), pq.lower()).ratio() >= 0.8:
        fails.append("repeated_question")
    events = [r.get("event") for r in records if isinstance(r, dict) and r.get("tool") == "record_step" and r.get("status") == "ok"]
    if kind in ("ok", "continue"):
        if PRAISE.match(reply or ""):
            fails.append("praised_skip")
        if {"answered_right", "answered_wrong"} & set(events):
            fails.append("skip_graded")
    if kind in ("wrong", "vague"):
        if PRAISE.match(reply or ""):
            fails.append("praised_wrong")
        if planned and "answered_wrong" not in events:
            fails.append("wrong_not_recorded")
    if kind == "wrong" and not CORRECTION.search((reply or "").replace("’", "'")):   # live replies use the curly apostrophe
        fails.append("wrong_not_corrected")
    return fails


def _http(url, body=None, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.load(r)


def judge(client, deployment, question, previous, learner, reply) -> str:
    """'' when the judge finds nothing false in the reply, else what it found (one line). It runs on the tutor's own model and sees the
    turn before: the cheap model with only the opening question flagged correct algebra and a new practice problem as errors."""
    msgs = [{"role": "system", "content": "You check one tutor reply for statements that are factually false. Work any maths out step "
                                          "by step before deciding. Questions, new examples, practice problems and things left out are not "
                                          "errors. Reply with OK if no statement is false; otherwise one short line quoting the false statement."},
            {"role": "user", "content": f"Lesson question: {question}\n\nTutor's previous reply: {previous or '(none)'}\n\n"
                                        f"Learner said: {learner}\n\nTutor's reply to check: {reply}"}]
    for attempt in range(3):                     # rate limits come in bursts
        try:
            out = client.chat.completions.create(model=deployment, messages=msgs, temperature=0, max_tokens=400).choices[0].message.content.strip()
            break
        except Exception as e:                   # a judge outage must not end the run (one Azure 500 did)
            if attempt == 2:
                return f"(judge failed: {type(e).__name__})"
            time.sleep(10)
    last = out.strip().splitlines()[-1].strip() if out.strip() else "OK"   # it works the maths out first; the verdict is the last line
    return "" if last.upper().startswith("OK") else last[:200]


def run_lesson(url, lesson, script, judge_fn=None) -> dict:
    _, nb = _http(f"{url}/api/notebooks", {"topic": f"Eval: {lesson['id']}"})
    nb = nb["id"]
    turns, previous = [], ""
    for k, kind in enumerate(script):
        message = lesson["question"] if kind == "question" else lesson.get(kind, kind)
        t0 = time.time()
        try:
            status, _ = _http(f"{url}/api/notebooks/{nb}/chat", {"message": message})
        except urllib.error.HTTPError as e:
            status = e.code
        elapsed = time.time() - t0
        _, book = _http(f"{url}/api/notebooks/{nb}")
        tutor = [t for t in book["chat_turns"] if t["role"] == "assistant"]
        reply = tutor[-1]["content"] if tutor else ""
        records = (tutor[-1].get("tool_calls_made") or []) if tutor else []
        planned = bool(book.get("lesson_path")) and k > 0
        fails = check_turn(kind, reply, records, previous, status, planned)
        blocks = [r.get("tool") for r in records if r.get("tool") in BLOCK_TOOLS and r.get("status") == "ok"]
        refused = [r.get("tool") for r in records if r.get("tool") in BLOCK_TOOLS and r.get("status") != "ok"]
        false = judge_fn(lesson["question"], previous, message, reply) if judge_fn and status == 200 else ""
        turns.append({"kind": kind, "learner": message, "reply": reply, "seconds": round(elapsed, 1), "fails": fails,
                      "blocks": blocks, "refused": refused, "judge": false,
                      "records": [(r.get("element_id"), r.get("event"), r.get("status")) for r in records if r.get("tool") == "record_step"]})
        previous = reply
        print(f"  {lesson['id']:18s} {kind:9s} {elapsed:5.1f}s  {', '.join(fails) or 'ok'}{'  JUDGE: ' + false if false else ''}", flush=True)
    _, book = _http(f"{url}/api/notebooks/{nb}")
    return {"id": lesson["id"], "notebook": nb, "turns": turns, "path": book.get("lesson_path") or [],
            "final": book.get("lesson_final") or {}}


def report(results, label, judged) -> str:
    total = {c: 0 for c in CHECKS}
    for r in results:
        for t in r["turns"]:
            for f in t["fails"]:
                total[f] += 1
    turns = [t for r in results for t in r["turns"]]
    firsts = [r["turns"][0]["seconds"] for r in results if r["turns"]]
    lines = [f"# Lesson check: {label}", "",
             f"{datetime.now():%Y-%m-%d %H:%M}, {len(results)} lessons, {len(turns)} tutor turns. Script: question, ok, wrong, vague, right, "
             "continue, ok, right2 (`tests/lesson_eval/lessons.json`). Model output varies: compare totals between runs.", "",
             "## Totals", "", "| Check | Failed turns | Meaning |", "|---|---|---|"]
    lines += [f"| {c} | {total[c]} | {m} |" for c, m in CHECKS.items()]
    blocks = [b for t in turns for b in t["blocks"]]
    lines += ["", f"- First answer: median {sorted(firsts)[len(firsts) // 2] if firsts else 0} s, slowest {max(firsts, default=0)} s; "
              f"all turns median {sorted(t['seconds'] for t in turns)[len(turns) // 2] if turns else 0} s.",
              f"- Blocks drawn: {len(blocks)} ({', '.join(f'{b} {blocks.count(b)}' for b in sorted(set(blocks)))}); refused attempts: "
              f"{sum(len(t['refused']) for t in turns)}.",
              f"- Plans: {sum(1 for r in results if r['path'])} of {len(results)}; final check reached: "
              f"{sum(1 for r in results if r['final'].get('active'))}, passed: {sum(1 for r in results if r['final'].get('passed'))}."]
    if judged:
        flagged = [(r["id"], t["kind"], t["judge"]) for r in results for t in r["turns"] if t["judge"]]
        real = [f for f in flagged if not f[2].startswith("(judge failed")]
        lines += [f"- Fact judge: {len(real)} of {len(turns)} replies flagged ({len(flagged) - len(real)} not judged)."] + [f"  - {i} ({k}): {j}" for i, k, j in flagged]
    lines += ["", "## Per lesson", "", "| Lesson | Failed checks | Levels at the end | Blocks |", "|---|---|---|---|"]
    for r in results:
        fails = [f for t in r["turns"] for f in t["fails"]]
        levels = ", ".join((s["level"] or "-") for s in r["path"]) or "no plan"
        lines.append(f"| {r['id']} | {', '.join(f'{f} x{fails.count(f)}' for f in sorted(set(fails))) or 'none'} | {levels} | "
                     f"{len([b for t in r['turns'] for b in t['blocks']])} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8102")
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="", help="comma-separated lesson ids")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--judge-deployment", default="", help="judge with this Azure deployment (default: the tutor's); a cheap tutor should be judged by a stronger model")
    a = ap.parse_args()
    spec = json.loads(LESSONS.read_text(encoding="utf-8"))
    lessons = [l for l in spec["lessons"] if not a.only or l["id"] in a.only.split(",")]
    judge_fn = None
    if a.judge:
        sys.path.insert(0, str(ROOT))
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from engine.author import AUTHOR_DEPLOYMENT, AZURE_OPENAI_API_VERSION, get_azure_client
        # A cheap tutor is judged by a stronger model, which may live on another Azure resource: JUDGE_AZURE_OPENAI_ENDPOINT, _API_KEY and
        # _DEPLOYMENT in .env (all three), else the tutor's own client and model.
        if os.getenv("JUDGE_AZURE_OPENAI_ENDPOINT") and os.getenv("JUDGE_AZURE_OPENAI_API_KEY"):
            from openai import AzureOpenAI
            client = AzureOpenAI(api_key=os.getenv("JUDGE_AZURE_OPENAI_API_KEY"), azure_endpoint=os.getenv("JUDGE_AZURE_OPENAI_ENDPOINT"),
                                 api_version=AZURE_OPENAI_API_VERSION)
        else:
            client = get_azure_client()
        judge_with = a.judge_deployment or os.getenv("JUDGE_AZURE_OPENAI_DEPLOYMENT") or AUTHOR_DEPLOYMENT
        print(f"fact judge: {judge_with}", flush=True)
        judge_fn = lambda *args: judge(client, judge_with, *args)
    results = []
    for lesson in lessons:
        print(f"{lesson['id']}:", flush=True)
        results.append(run_lesson(a.url.rstrip("/"), lesson, spec["script"], judge_fn))
    OUT.mkdir(parents=True, exist_ok=True)
    stem = OUT / f"{datetime.now():%Y-%m-%d-%H%M}-{re.sub(r'[^a-z0-9-]+', '-', a.label.lower())}"
    stem.with_suffix(".md").write_text(report(results, a.label, a.judge), encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport: {stem.with_suffix('.md')}")


if __name__ == "__main__":
    main()
