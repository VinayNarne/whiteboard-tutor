"""Playbook end-to-end: tutor with the teaching-move line (on) vs without (off), Mindprint on in both. Reuses scripts/memory_eval.py.
Run from an EMPTY folder:   python - --cond on,off --repeats 3 < scripts/playbook_eval.py     (one process per condition may run in parallel)
Report from the raw files:   python - --report < scripts/playbook_eval.py"""
import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\narne\Desktop\personal_projects\Learning platform")
OUT = ROOT / "docs" / "lesson_evals"
RAW = OUT / "playbook-e2e-raw-{cond}.json"
TOPICS = ["How does DNS resolution work?", "How do Python for-loops work?"]
LEARNERS = {"L1": {"intake": {"self_level": "new", "purpose": "curiosity"}},
            "L2": {"intake": {"self_level": "comfortable", "purpose": "work", "time_budget": "quick"}}}
DIFF = "I don't get it, can you explain it differently?"


def setup():
    argv = sys.argv[:]
    sys.argv = [argv[0], "--real"]        # memory_eval turns Mindprint on only with --real
    sys.path.insert(0, str(ROOT / "scripts"))
    global me
    import memory_eval as me
    sys.argv = argv
    me.mps.warm_up()
    return me


def answer(role, reply):
    if role == "L1":
        sysmsg = ("You are an adult complete beginner guessing. Answer the tutor's last question in one or two sentences in a VAGUE or partly wrong way: "
                  "half-remember something, mix up a detail, sound unsure. Never give a correct precise answer. If there is no question, react to what was said with a guess. Reply with the answer only.")
    else:
        sysmsg = ("You are an experienced practitioner. Answer the tutor's last question correctly and precisely in one or two sentences, with technical accuracy. "
                  "If there is no question, say what you already know about the point. Reply with the answer only.")
    return me.llm(sysmsg, f"Tutor said:\n{reply[:2500]}") or "ok"


def run_session(http, cond, lid, topic, state):
    nb = http.post("/api/notebooks", json={"topic": topic, **LEARNERS[lid]["intake"]}).json()["id"]
    n = 7 if lid == "L1" else 6
    res, seen, last = [], set(), ""
    for i in range(n):
        if i == 0:
            msg = f"Teach me: {topic}"
        elif lid == "L1" and i == 5:
            msg = DIFF
        else:
            msg = answer(lid, last)
        state["sent"], state["picked"], state["line"] = [], None, ""
        r, sec = me.post_chat(http, nb, msg)
        settled = me.wait_tasks()
        book = http.get(f"/api/notebooks/{nb}").json()
        tut = [t for t in book["chat_turns"] if t["role"] == "assistant"]
        last = tut[-1]["content"] if tut else ""
        res.append({"i": i, "learner": msg, "status": r.status_code, "seconds": sec, "reply": last, "board": me.board_text(http, nb, seen),
                    "move_line": state["line"], "move_sent": bool(state["line"]), "picked": state["picked"], "settled": settled})
        print(f"   {cond} {lid} t{i} {r.status_code} {sec}s move={state['line'][:60]!r} {state['picked']}", flush=True)
    return res


def install(cond, state):
    """Wrap playbook_for_turn in backend.main (on: records what came back; off: no move line, intake kept) and capture build_messages."""
    import backend.main as bm
    import backend.playbook_store as ps
    from engine.playbook import MOVES, intake_sentence
    from backend.models import Notebook, TeachingLog
    from sqlmodel import Session, select
    orig = ps.playbook_for_turn

    def wrapped(db_engine, notebook_id, plan, records, known, message, topic, page_id, turn_id, *a, **k):
        if cond == "off":
            with Session(db_engine) as db:
                nb = db.get(Notebook, notebook_id)
                return "", (intake_sentence(nb.purpose, nb.time_budget, nb.self_level) if nb else "")
        turn_note, intake = orig(db_engine, notebook_id, plan, records, known, message, topic, page_id, turn_id, *a, **k)
        if turn_note:
            with Session(db_engine) as db:
                new = db.exec(select(TeachingLog).where(TeachingLog.turn_id == turn_id)).first()
            label = turn_note.split("chosen for this learner): ")[-1].split(":")[0]
            mv = next((m for m, v in MOVES.items() if v[0] == label), label)
            state["picked"] = "picked:" + mv if new else "reused:" + mv
        return turn_note, intake
    bm.playbook_for_turn = wrapped
    ps.playbook_for_turn = wrapped

    base = me.ORIG_AUTHOR

    def cap(*a):
        m = base(*a)
        for x in m:
            c = str(x.get("content", "")) if isinstance(x.get("content"), str) else ""
            if x.get("role") == "system" and "TEACHING MOVE" in c:
                state["line"] = c[c.index("TEACHING MOVE"):][:200]
        return m
    me.author.build_messages = cap


def collect(cond, reps):
    state = {}
    install(cond, state)
    data = []
    from fastapi.testclient import TestClient
    with TestClient(me.bm.app, raise_server_exceptions=False) as http:
        for rep in range(reps):
            for lid in LEARNERS:
                for ti, topic in enumerate(TOPICS):
                    print(f"{cond} rep{rep} {lid} topic{ti}", flush=True)
                    me.wipe_db()
                    data.append({"cond": cond, "rep": rep, "learner": lid, "topic": topic, "turns": run_session(http, cond, lid, topic, state)})
                    RAW.with_name(RAW.name.format(cond=cond)).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------------------------------- judging
def judge_session(s):
    t = s["turns"]
    R = lambda i: f"[Reply {i + 1}] (learner had said: {t[i]['learner']})\n{t[i]['reply']}\n[Board]\n{t[i]['board']}"
    m = {}
    ok = lambda idx: all(t[i]["status"] == 200 for i in idx)     # a measure is skipped when a turn it reads failed
    if s["learner"] == "L1":
        m["P1"] = me.judge("The learner then asked to have it explained differently. Does the LAST reply use a clearly different approach (e.g. analogy vs. step list, worked example vs. definition, "
                           "different framing) from the reply just before it, rather than the same explanation reworded? Quote from the last reply.", R(4) + "\n\n" + R(5))
        m["P2"] = me.judge("The learner gave vague or partly wrong answers in replies 2 and 3 (learner messages shown). Does the LAST reply (Reply 4) change approach compared with Replies 2-3 "
                           "(e.g. a worked example, a contrast, a simpler explanation) rather than repeating the same explanation? Quote from Reply 4.", "\n\n".join(R(i) for i in (1, 2, 3)))
    else:
        later = "\n\n".join(R(i) for i in range(2, 6))
        m["P3"] = me.judge("The learner is an experienced person and has shown in their messages that they know the basics. Do the tutor's replies (Replies 3 to 6) re-explain basics the learner has just "
                           "shown they know (explaining the fundamentals again as if they were new to them)? Quote the re-explanation.", "[Learner messages]\n" + "\n".join(x["learner"] for x in t[1:]) + "\n\n" + later)
        m["P4"] = me.judge("Do the tutor's replies (Replies 3 to 6) raise the level: a harder question, a trade-off, an edge case or a real-world use? Quote the sentence that does.", later)
    m["P5"] = me.judge("Does a concrete example (a specific worked case, scenario, or sample with real values or names) appear in these first two replies? Quote the sentence.", R(0) + "\n\n" + R(1))
    return {k: v for k, v in m.items() if ok({"P1": (4, 5), "P2": (1, 2, 3), "P3": range(1, 6), "P4": range(2, 6), "P5": (0, 1)}[k])}


def report():
    allr = []
    for c in ("off", "on"):
        p = RAW.with_name(RAW.name.format(cond=c))
        if p.exists():
            allr += json.loads(p.read_text(encoding="utf-8"))
    me.client                                                        # judge uses the same deployment, temperature 0
    for s in allr:
        s["measures"] = judge_session(s)
        print("judged", s["cond"], s["rep"], s["learner"], {k: v["verdict"] for k, v in s["measures"].items()}, flush=True)
    stamp = f"{datetime.now():%Y-%m-%d-%H%M}-playbook-e2e"
    (OUT / f"{stamp}.json").write_text(json.dumps(allr, indent=1, ensure_ascii=False), encoding="utf-8")

    def count(meas, cond, learner):
        rows = [s for s in allr if s["cond"] == cond and (s["learner"] == learner if learner else True) and meas in s["measures"]]
        return sum(1 for s in rows if s["measures"][meas]["verdict"] == "YES"), len(rows)
    lines = ["# Playbook end-to-end (on vs off)", "", "| Measure | off | on |", "|--|--|--|"]
    for meas, lr, name in (("P1", "L1", "P1 L1 differently after 'explain differently' (good)"), ("P2", "L1", "P2 L1 changes approach after 2 vague answers (good)"),
                           ("P3", "L2", "P3 L2 re-explains basics (BAD)"), ("P4", "L2", "P4 L2 raises the level (good)"), ("P5", None, "P5 concrete example in first 2 replies (good)")):
        a, b = count(meas, "off", lr), count(meas, "on", lr)
        lines.append(f"| {name} | {a[0]}/{a[1]} | {b[0]}/{b[1]} |")
    turns = lambda c: [t for s in allr if s["cond"] == c for t in s["turns"]]
    lines += ["", "## Timings (median seconds per turn)"] + [f"- {c}: {statistics.median([t['seconds'] for t in turns(c)]):.1f}" for c in ("off", "on") if turns(c)]
    bad = [(s["cond"], s["learner"], s["rep"], t["i"], t["status"]) for s in allr for t in s["turns"] if t["status"] != 200]
    lines += ["", f"Non-200 turns: {bad or 'none'}"]
    sent = {c: (sum(t["move_sent"] for t in turns(c)), len(turns(c))) for c in ("off", "on")}
    lines += [f"Turns with a TEACHING MOVE line in the tutor call: off {sent['off']}, on {sent['on']} (sent/turns)"]
    dist, pr = {}, {"picked": 0, "reused": 0}
    for t in turns("on"):
        if t["picked"]:
            k, mv = t["picked"].split(":")
            dist[mv] = dist.get(mv, 0) + 1
            pr[k] += 1
    lines += ["", f"## Move distribution (on): {dict(sorted(dist.items(), key=lambda x: -x[1]))}", f"Picks vs reuses: {pr}"]
    for meas, lr in (("P1", "L1"), ("P4", "L2")):
        for c in ("off", "on"):
            ex = next((s for s in allr if s["cond"] == c and s["learner"] == lr and meas in s["measures"] and s["measures"][meas]["verdict"] == ("YES")), None) or \
                 next((s for s in allr if s["cond"] == c and s["learner"] == lr), None)
            if ex:
                v = ex["measures"][meas]
                lines += ["", f"### {meas} {c} (rep {ex['rep']}, {ex['topic']}): {v['verdict']}", f"> {v['quote'] or v['raw'][:200]}"]
    (OUT / f"{stamp}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("wrote", stamp)


if __name__ == "__main__" or True:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", default="on,off")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    setup()
    if a.report:
        report()
    else:
        for c in a.cond.split(","):
            collect(c, a.repeats)
