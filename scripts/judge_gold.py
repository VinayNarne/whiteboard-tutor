"""Judge calibration set. No model calls.
    python scripts/judge_gold.py            extract items from saved runs -> docs/lesson_evals/judge_gold/items.json (the "human" field is left empty)
    python scripts/judge_gold.py --score    after you fill "human" with YES or NO: agreement % and Cohen's kappa per measure
P1: reply after "explain it differently" plus the tutor's previous explanation (playbook runs). M2: does the tutor state that DNS does not carry the data (memory runs)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "docs" / "lesson_evals"
ITEMS = EV / "judge_gold" / "items.json"
sys.path.insert(0, str(ROOT / "scripts"))


def latest(pattern, skip=()):
    fs = sorted((f for f in EV.glob(pattern) if not any(x in f.name for x in skip)), key=lambda f: f.stat().st_mtime)
    return fs[-1] if fs else None


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def p1_items(limit=30):
    """The judged playbook run (has the saved verdicts) -> L1 sessions, both conditions."""
    f = latest("*-playbook-e2e*.json", skip=("raw", "pairwise"))
    out = []
    for s in load(f) if f else []:
        v = s.get("measures", {}).get("P1")
        t = s["turns"]
        if s["learner"] != "L1" or not v or len(t) < 6 or t[4]["status"] != 200 or t[5]["status"] != 200:
            continue
        out.append({"measure": "P1", "source": f"{f.name} {s['cond']} rep{s['rep']} {s['topic']}", "previous_explanation": t[4]["reply"],
                    "learner_said": t[5]["learner"], "reply": t[5]["reply"], "judge": v["verdict"], "judge_quote": v.get("quote", ""), "human": ""})
    return out[:limit]


def m2_items(limit=20):
    """Latest memory-real run first, then the off/oracle run; DNS sessions (S2, S3) only."""
    out = []
    files = [latest("*-memory-real*.json"), latest("*-memory-ceiling-v2.json")]
    for f in filter(None, files):
        for r in load(f):
            for x in r["runs"]:
                v = x["measures"].get("M2")
                if x["id"] not in ("S2", "S3") or not v:
                    continue
                text = "\n\n".join(f"[Reply {i + 1}]\n{t['reply']}\n[Board {i + 1}]\n{t['board']}" for i, t in enumerate(x["turns"]))
                out.append({"measure": "M2", "source": f"{f.name} {x['cond']} rep{r['rep']} {x['id']}", "tutor_text": text,
                            "judge": v["verdict"], "judge_quote": v.get("quote", ""), "human": ""})
    return out[:limit]


def score():
    import eval_stats as st
    items = load(ITEMS)
    for m in sorted({i["measure"] for i in items}):
        rows = [i for i in items if i["measure"] == m and str(i.get("human", "")).strip().upper() in ("YES", "NO")]
        if not rows:
            print(f"{m}: no human labels yet")
            continue
        a, b = [r["judge"] for r in rows], [r["human"] for r in rows]
        agree = sum(x.upper() == y.strip().upper() for x, y in zip(a, b))
        print(f"{m}: n={len(rows)} agreement {100 * agree / len(rows):.0f}% ({agree}/{len(rows)}), Cohen's kappa {st.cohen_kappa(a, b):.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    if a.score:
        score()
    else:
        items = p1_items() + m2_items()
        for n, i in enumerate(items):
            i["id"] = n
        ITEMS.parent.mkdir(parents=True, exist_ok=True)
        ITEMS.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
        print("wrote", ITEMS, {m: sum(i["measure"] == m for i in items) for m in ("P1", "M2")})
