"""Mindprint phase 0 (v2): memory ceiling. Conditions: off (no memory) vs oracle (hand-written learner note injected before the learner's
message AND into the lesson-plan request). Runs the real app in-process (TestClient) on a throwaway SQLite db; real model calls.
Session 1 is not re-run: its analogy and note are read from an earlier run's json (--s1-from).
    python scripts/memory_eval.py --repeats 5 [--only S2]"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["LP_VOICE"] = "0"
os.environ["LP_MINDPRINT"] = "1" if "--real" in sys.argv else "0"   # v2 conditions (off, oracle) run without Mindprint
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="lp_mem_"), "mem.db").replace("\\", "/")
import backend.main as bm  # noqa: E402
from backend.database import init_db  # noqa: E402
from engine import author, lesson_plan  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

init_db()
COURSE = json.loads((ROOT / "tests" / "memory_eval" / "course.json").read_text(encoding="utf-8"))
ORIG_AUTHOR, ORIG_PLAN = author.build_messages, lesson_plan.build_messages
client = author.get_azure_client()
BLOCK = {"write_notes", "draw_scene", "draw_graph", "draw_table", "draw_bar_chart", "draw_venn"}
PLAN_SEEN = []   # plan messages that carried the note (printed once as a check)


def llm(system, user, retries=3):
    for i in range(retries):
        try:
            return client.chat.completions.create(model=author.AUTHOR_DEPLOYMENT, temperature=0, max_tokens=300,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]).choices[0].message.content.strip()
        except Exception as e:
            if i == retries - 1:
                return f"(judge failed: {e})"
            time.sleep(10)


def patch(note):
    """note None = off: both originals restored."""
    def b(*a):
        m = ORIG_AUTHOR(*a)
        m.insert(len(m) - 1, {"role": "system", "content": f"LEARNER NOTES (from earlier lessons; follow them): {note}"})
        return m

    def pb(*a):
        m = ORIG_PLAN(*a)
        m[-1] = {**m[-1], "content": m[-1]["content"] + COURSE["plan_suffix"].replace("{note}", note)}
        PLAN_SEEN.append(m[-1]["content"])
        return m
    author.build_messages = b if note else ORIG_AUTHOR
    lesson_plan.build_messages = pb if note else ORIG_PLAN


def texts(obj):
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [t for v in obj.values() for t in texts(v)]
    if isinstance(obj, list):
        return [t for v in obj for t in texts(v)]
    return []


def board_text(http, nb, seen):
    """Text of the board events added since the last turn: narration plus the text inside the SVG fragments."""
    out = []
    for pg in http.get(f"/api/notebooks/{nb}").json()["pages"]:
        for e in http.get(f"/api/notebooks/{nb}/pages/{pg['id']}/events").json()["events"]:
            key = (pg["id"], e["seq"])
            if key in seen:
                continue
            seen.add(key)
            svg = re.sub(r"<(style|defs)[ >].*?</(style|defs)>", " ", e.get("svg_fragment") or "", flags=re.S)
            out.append(" ".join(filter(None, [re.sub(r"\[\[MARK:[^\]]*\]\]", "", e.get("narration") or ""), re.sub(r"<[^>]+>", " ", svg)])))
    return "\n".join(out)


def session(http, topic, turns):
    nb = http.post("/api/notebooks", json={"topic": topic}).json()["id"]
    res, seen, plan = [], set(), []
    for msg in turns:
        for attempt in range(2):
            t0 = time.time()
            r = http.post(f"/api/notebooks/{nb}/chat", json={"message": msg})
            if r.status_code == 200 or attempt:
                break
            time.sleep(10)
        sec = round(time.time() - t0, 1)
        book = http.get(f"/api/notebooks/{nb}").json()
        plan = [s["title"] for s in book.get("lesson_path") or []] or plan
        tut = [t for t in book["chat_turns"] if t["role"] == "assistant"]
        recs = (tut[-1].get("tool_calls_made") or []) if tut else []
        res.append({"learner": msg, "status": r.status_code, "seconds": sec, "reply": tut[-1]["content"] if tut else "",
                    "board": board_text(http, nb, seen), "blocks": sum(1 for x in recs if x.get("tool") in BLOCK and x.get("status") == "ok"), "records": recs})
        print(f"   {msg[:40]!r} {r.status_code} {sec}s blocks={res[-1]['blocks']}", flush=True)
    return res, plan


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def judge(q, scored, quote_needed=True):
    """YES needs an exact quote found in the scored text, else it is downgraded to NO (downgraded=True)."""
    ask = " If YES, the second line must be QUOTE: followed by an exact, verbatim quote from the tutor text (one sentence)." if quote_needed else ""
    out = llm("You grade a tutor's replies strictly. Answer YES or NO on the first line, then give the reason." + ask, f"{q}\n\nTutor text:\n{scored}") or ""
    v = out.split()[0].strip(".,:").upper() if out.split() else "?"
    m = re.search(r"QUOTE:\s*[\"“']?(.+?)[\"”']?\s*$", out, re.S | re.M)
    quote = m.group(1).strip() if m else ""
    down = False
    if v == "YES" and quote_needed:
        q = norm(quote)
        if len(q) < 15 or q not in norm(scored):
            v, down = "NO", True
    return {"verdict": v, "raw": out, "quote": quote, "downgraded": down}


def full(s):
    return "\n\n".join(f"[Reply {i + 1}]\n{t['reply']}\n[Board {i + 1}]\n{t['board']}" for i, t in enumerate(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--only", default="")
    ap.add_argument("--real", action="store_true", help="the real Mindprint condition (no patches, LP_MINDPRINT=1, one db per repeat)")
    ap.add_argument("--s1-from", default=str(ROOT / "docs" / "lesson_evals" / "2026-11-22-0010-memory-ceiling.json"))
    a = ap.parse_args()
    if a.real:
        return main_real(a)
    http = TestClient(bm.app, raise_server_exceptions=False)
    s1 = json.loads(Path(a.s1_from).read_text(encoding="utf-8"))
    later = [x for x in COURSE["later"] if not a.only or x["id"] in a.only.split(",")]
    data = []
    out = ROOT / "docs" / "lesson_evals" / f"{datetime.now():%Y-%m-%d-%H%M}-memory-ceiling-v2"
    for rep in range(a.repeats):
        print(f"repeat {rep}", flush=True)
        analogy, note = s1[rep]["analogy"], s1[rep]["note"]
        item = {"rep": rep, "analogy": analogy, "note": note, "runs": []}
        for cond in ("off", "oracle"):
            patch(note if cond == "oracle" else None)
            for l in later:
                print(f" {cond} {l['id']}", flush=True)
                s, plan = session(http, l["topic"], l["turns"])
                txt = full(s)
                m = {}
                if l["id"] in ("S2", "S3"):
                    m["M1"] = judge("Does the tutor teach the basics of DNS again: explaining what DNS is or that it turns names into IP addresses in two or more sentences, OR asking the learner a question about why/how browsers use DNS? A single reminder clause is NO.", txt)
                    m["M2"] = judge("Does the tutor explicitly state that DNS does NOT carry, route or deliver the data itself (or explicitly that something else, e.g. routers/TCP, carries the data)? Merely describing a DNS lookup is NO.", txt)
                    m["M5"] = judge(f"Is there a sentence that is factually incompatible with: '{analogy or 'DNS is like a phone book'}' or 'DNS translates names into IP addresses'? Adding detail (MX records, spoofing, caching) is NOT a contradiction. Quote the incompatible sentence.", txt)
                    if analogy:
                        m["M4"] = judge(f"Does the tutor reuse this analogy: {analogy}?", txt)
                first = f"[First reply]\n{s[0]['reply']}\n[Board]\n{s[0]['board']}"
                m["M3"] = judge("Does the FIRST reply open with a concrete example or scenario before any definition?", first)
                item["runs"].append({"cond": cond, "id": l["id"], "plan": plan, "turns": s, "measures": m})
        data.append(item)
        out.with_suffix(".json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        if rep == 0:
            print("PLAN MESSAGES CARRY NOTE:", bool(PLAN_SEEN) and note in PLAN_SEEN[0], "| count", len(PLAN_SEEN), flush=True)
    print("raw:", out.with_suffix(".json"))


# ---------------------------------------------------------------------------------------------------------------------------------
# Condition "real": Mindprint on, no patches, one database per repeat shared by session 1 and the later sessions.
# ---------------------------------------------------------------------------------------------------------------------------------
import backend.mindprint_store as mps  # noqa: E402
from sqlmodel import SQLModel, Session, select  # noqa: E402
from backend.database import engine as db_engine  # noqa: E402
from backend.models import Concept  # noqa: E402

CAPTURED = []   # LEARNER NOTES system messages seen by the tutor call (read only)


def capture_notes():
    def b(*a):
        m = ORIG_AUTHOR(*a)
        CAPTURED.extend(x["content"] for x in m if x.get("role") == "system" and str(x.get("content", "")).startswith("LEARNER NOTES"))
        return m
    author.build_messages = b
    lesson_plan.build_messages = ORIG_PLAN


def wipe_db():
    with db_engine.begin() as conn:
        for t in reversed(SQLModel.metadata.sorted_tables):
            if t.name != "learners":
                conn.execute(t.delete())


def wait_tasks(timeout=180):
    t0 = time.time()
    while mps._TASKS and time.time() - t0 < timeout:
        time.sleep(0.5)
    return not mps._TASKS


def concept_rows():
    with Session(db_engine) as db:
        return [{"name": c.name, "level": c.level, "right_turns": len(c.right_turns or []), "misconception": c.misconception} for c in db.exec(select(Concept)).all()]


def answerer(reply):
    if "?" not in reply:
        return "ok"
    return llm("You are an adult beginner learner who has understood the lesson so far. Answer the tutor's last question correctly in one or two plain sentences. "
               "Reply with the answer only.", f"Tutor said:\n{reply}") or "ok"


def session_real(http, topic, turns, adaptive=None):
    """turns: fixed learner messages; a None entry is answered by the answerer. Waits for Mindprint background work after every turn."""
    nb = http.post("/api/notebooks", json={"topic": topic}).json()["id"]
    res, seen = [], set()
    last = ""
    for msg in turns:
        if msg is None:
            msg = answerer(last)
        CAPTURED.clear()
        for attempt in range(2):
            t0 = time.time()
            r = http.post(f"/api/notebooks/{nb}/chat", json={"message": msg})
            if r.status_code == 200 or attempt:
                break
            time.sleep(10)
        sec = round(time.time() - t0, 1)
        settled = wait_tasks()
        book = http.get(f"/api/notebooks/{nb}").json()
        tut = [t for t in book["chat_turns"] if t["role"] == "assistant"]
        recs = (tut[-1].get("tool_calls_made") or []) if tut else []
        last = tut[-1]["content"] if tut else ""
        res.append({"learner": msg, "status": r.status_code, "seconds": sec, "reply": last, "board": board_text(http, nb, seen),
                    "blocks": sum(1 for x in recs if x.get("tool") in BLOCK and x.get("status") == "ok"), "records": recs,
                    "notes": list(CAPTURED), "settled": settled, "path": [{"title": s["title"], "level": s.get("level"), "from_memory": s.get("from_memory")} for s in book.get("lesson_path") or []],
                    "concepts": concept_rows()})
        print(f"   {msg[:50]!r} {r.status_code} {sec}s settled={settled} notes={len(CAPTURED)}", flush=True)
    return res


def main_real(a):
    s1c = COURSE["session1"]["turns"]    # question, ok, preference, misconception, ok
    S1_TURNS = [s1c[0], None, "ok", s1c[2], s1c[3], None, None, None, None]
    prev = json.loads((ROOT / "docs" / "lesson_evals" / "2026-11-22-0027-memory-ceiling-v2.json").read_text(encoding="utf-8"))
    mps.warm_up()
    later = [x for x in COURSE["later"] if not a.only or x["id"] in a.only.split(",")]
    capture_notes()
    out = ROOT / "docs" / "lesson_evals" / f"{datetime.now():%Y-%m-%d-%H%M}-memory-real"
    data = []
    with TestClient(bm.app, raise_server_exceptions=False) as http:     # one event loop for the whole run: background tasks must survive between requests
        for rep in range(a.repeats):
            print(f"repeat {rep}", flush=True)
            wipe_db()
            analogy = prev[rep]["analogy"]
            s1 = session_real(http, COURSE["session1"]["topic"], S1_TURNS)
            rows = concept_rows()
            print("CONCEPTS after session 1:", json.dumps(rows, ensure_ascii=False), flush=True)
            item = {"rep": rep, "session1": s1, "concepts_after_s1": rows, "runs": []}
            for l in later:
                print(f" real {l['id']}", flush=True)
                s = session_real(http, l["topic"], l["turns"])
                txt = full(s)
                m = {}
                if l["id"] in ("S2", "S3"):
                    m["M1"] = judge("Does the tutor teach the basics of DNS again: explaining what DNS is or that it turns names into IP addresses in two or more sentences, OR asking the learner a question about why/how browsers use DNS? A single reminder clause is NO.", txt)
                    m["M2"] = judge("Does the tutor explicitly state that DNS does NOT carry, route or deliver the data itself (or explicitly that something else, e.g. routers/TCP, carries the data)? Merely describing a DNS lookup is NO.", txt)
                    m["M5"] = judge(f"Is there a sentence that is factually incompatible with: '{analogy or 'DNS is like a phone book'}' or 'DNS translates names into IP addresses'? Adding detail (MX records, spoofing, caching) is NOT a contradiction. Quote the incompatible sentence.", txt)
                    if analogy:
                        m["M4"] = judge(f"Does the tutor reuse this analogy: {analogy}?", txt)
                first = f"[First reply]\n{s[0]['reply']}\n[Board]\n{s[0]['board']}"
                m["M3"] = judge("Does the FIRST reply open with a concrete example or scenario before any definition?", first)
                item["runs"].append({"cond": "real", "id": l["id"], "turns": s, "measures": m})
            data.append(item)
            out.with_suffix(".json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("raw:", out.with_suffix(".json"))


if __name__ == "__main__":
    main()
