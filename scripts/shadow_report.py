"""
scripts/shadow_report.py -- summarise the log-only shadow validator records (events shadow_validated, shadow_skipped, shadow_failed) from logs/*.jsonl and *.gz.

    python scripts/shadow_report.py                          # everything in the logs
    python scripts/shadow_report.py --since 2026-10-15       # records from that UTC date on
    python scripts/shadow_report.py --exclude ID1,ID2        # leave out sessions (notebook ids), e.g. automated test runs
    python scripts/shadow_report.py --json out.json          # also write the summary as JSON

Reads the structured log (no drawing text is stored in it) and, for topics, the notebook titles in the local database.
Answers: (1) is the review trigger met (150 drawings, 15 sessions, 5 topics, 2 days: owner-approved), (2) how often the proposal and the existing checks agree and where they differ,
(3) coverage: which kinds and sizes of drawing the data contain, (4) known gaps in coverage (rejections before the sanitiser, modify operations), (5) the hook's overhead.
"""
import argparse
import collections
import glob
import gzip
import json
import statistics
from pathlib import Path

LOG = Path(__file__).parent.parent / "logs" / "learning_platform.jsonl"
TRIGGER = {"drawings": 150, "sessions": 15, "topics": 5, "days": 2}      # the owner-approved minimum for the first review


def log_rows(since):
    for p in sorted(glob.glob(str(LOG) + "*")):
        op = gzip.open if p.endswith(".gz") else open
        with op(p, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not since or r.get("ts", "")[:10] >= since:
                    yield r


def topics_of(sessions):
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from sqlmodel import Session, select
        from backend.database import engine
        from backend.models import Notebook
        with Session(engine) as db:
            return {n.id: (n.topic or "")[:60] for n in db.exec(select(Notebook)).all() if n.id in sessions}
    except Exception:
        return {}


def pct(xs, q):
    xs = sorted(xs)
    return xs[int(q * (len(xs) - 1))] if xs else float("nan")


def kind_of(rec):
    """A drawing's type from its shape roles (records written since the roles field was added; older ones are 'unknown')."""
    roles = rec.get("roles")
    if not roles:
        return "unknown"
    conn, lab = roles.get("connector", 0), roles.get("label", 0)
    if conn >= 4:
        return "connector-heavy"
    if lab >= 8:
        return "text-heavy"
    if rec.get("shapes_new", 0) <= 5:
        return "simple"
    return "mixed"


def size_of(rec):
    n = rec.get("shapes_new", 0)
    return "small (1-5 shapes)" if n <= 5 else "medium (6-15)" if n <= 15 else "large (16+)"


def summarise(since=None, exclude=()):
    rows = [r for r in log_rows(since)]
    shadow = [r for r in rows if r.get("event", "").startswith("shadow_") and r.get("session_id") not in exclude]
    ok = [r for r in shadow if r["event"] == "shadow_validated"]
    sessions = {r.get("session_id") for r in ok}
    topics = topics_of(sessions)
    out = {"records": len(ok), "skipped": sum(r["event"] == "shadow_skipped" for r in shadow), "failed": sum(r["event"] == "shadow_failed" for r in shadow),
           "sessions": len(sessions), "days": len({r["ts"][:10] for r in ok}), "topics": len({t.lower() for t in topics.values() if t}) if topics else None}
    out["trigger"] = {k: {"have": out[k] if k != "drawings" else out["records"], "need": v} for k, v in TRIGGER.items()}
    out["trigger_met"] = all((t["have"] or 0) >= t["need"] for t in out["trigger"].values())
    out["matrix"] = dict(collections.Counter(f"existing {r['data']['existing']} / proposed {r['data']['proposed']}" for r in ok))
    out["reject_kinds"] = dict(collections.Counter(k for r in ok for k, n in (r["data"].get("reject_kinds") or {}).items() for _ in range(n)))
    out["drawings_with_reject_kind"] = dict(collections.Counter(k for r in ok for k in (r["data"].get("reject_kinds") or {})))
    out["advisory_kinds"] = dict(collections.Counter(k for r in ok for k, n in (r["data"].get("advisory_kinds") or {}).items() for _ in range(n)))
    ctr = [r["data"]["connector_text"] for r in ok if r["data"].get("connector_text")]
    out["connector_text"] = {"records": len(ctr), "errors": sum(1 for r in ok if r["data"].get("connector_text_error")),
                             **{k: sum(c.get(k, 0) for c in ctr) for k in ("body", "head", "head_covered", "ambiguous", "hidden")}}
    out["differs"] = [{"ts": r["ts"][:19], "session": (r.get("session_id") or "")[:8], "element": r["data"]["element_id"], "existing": r["data"]["existing"],
                       "existing_reason": r["data"].get("existing_reason"), "proposed": r["data"]["proposed"], "kinds": r["data"].get("reject_kinds")}
                      for r in ok if r["data"].get("differs")]
    out["coverage"] = {"by_type": dict(collections.Counter(kind_of(r["data"]) for r in ok)), "by_size": dict(collections.Counter(size_of(r["data"]) for r in ok)),
                       "by_topic": dict(collections.Counter(topics.get(r.get("session_id"), "?") for r in ok)),
                       "by_type_and_verdict": {t: dict(collections.Counter(r["data"]["proposed"] for r in ok if kind_of(r["data"]) == t)) for t in {kind_of(r["data"]) for r in ok}}}
    if ok:
        from datetime import datetime, timedelta
        parse = lambda t: datetime.strptime(t[:26].rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f")
        start = (parse(min(r["ts"] for r in ok)) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S")       # the draw call that wrote the first record is just before it
        later = [r for r in rows if r["ts"] >= start]
        pre = collections.Counter()
        for r in later:
            if r.get("event") == "draw_failed" and r.get("session_id") not in exclude:
                m = r.get("message", "")
                pre["transform"] += "transform" in m
                pre["background frame"] += "background" in m and "frame" in m.lower()
                pre["duplicate id"] += "already exists" in m
        tools = collections.Counter((r.get("data") or {}).get("tool") for r in later if r.get("event") == "tool_call" and r.get("session_id") not in exclude)
        out["gaps"] = {"rejected_before_the_sanitiser (no shadow record)": dict(pre), "modify_existing_element calls (not recorded)": tools.get("modify_existing_element", 0),
                       "draw_new_element calls": tools.get("draw_new_element", 0), "records written": len(ok)}
    ms, wait = [r["data"]["ms"] for r in ok], [r["data"]["wait_ms"] for r in ok]
    out["overhead_ms"] = {"compute_mean": round(statistics.mean(ms), 1) if ms else None, "compute_p50": pct(ms, .5), "compute_p95": pct(ms, .95), "compute_max": max(ms, default=None),
                          "waited_mean": round(statistics.mean(wait), 1) if wait else None, "waited_p95": pct(wait, .95), "waited_max": max(wait, default=None)}
    out["by_day"] = dict(sorted(collections.Counter(r["ts"][:10] for r in ok).items()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--json")
    a = ap.parse_args()
    s = summarise(a.since, tuple(x for x in a.exclude.split(",") if x))
    print("REVIEW TRIGGER (owner-approved minimum):", "MET" if s["trigger_met"] else "not met yet")
    for k, v in s["trigger"].items():
        print(f"   {k:9} {v['have']} of {v['need']}")
    print(f"shadow records: {s['records']} drawings from {s['sessions']} session(s); skipped {s['skipped']}, failed {s['failed']}")
    print("existing vs proposed:", s["matrix"])
    print("proposal would reject for (collisions):", s["reject_kinds"])
    print("... number of drawings with each:", s["drawings_with_reject_kind"])
    print("advisory only (never counted):", s["advisory_kinds"])
    print("connector over visible text (z-order aware, never counted):", s["connector_text"])
    print("coverage by drawing type:", s["coverage"]["by_type"], "| by size:", s["coverage"]["by_size"])
    print("   proposed verdict per type:", s["coverage"]["by_type_and_verdict"])
    print("   by topic:", s["coverage"]["by_topic"])
    print("known gaps:", s.get("gaps"))
    print("overhead (ms):", s["overhead_ms"])
    print("by day:", s["by_day"])
    print(f"drawings where the two differ: {len(s['differs'])}")
    for d in s["differs"][:25]:
        print("  ", d)
    if a.json:
        Path(a.json).write_text(json.dumps(s, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
