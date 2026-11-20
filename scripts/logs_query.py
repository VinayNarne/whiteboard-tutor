#!/usr/bin/env python
"""
scripts/logs_query.py
Ask the structured log (JSON lines, logs/learning_platform.jsonl) a question without writing a throwaway script.

    python scripts/logs_query.py --event draw_failed --since 2026-10-08
    python scripts/logs_query.py --level WARN --page <page_id> --tail 20
    python scripts/logs_query.py --session <notebook_id> --summary
    python scripts/logs_query.py --event content_lost --json
    python scripts/logs_query.py --all --event model_usage --count        # also the rotated .gz files of the same log

Filters (all optional, all must match): --event (comma list), --level, --service, --session (the notebook id), --page, --since, --until (ISO, UTC),
--grep (case-insensitive text in the message or the data). Output: one line per record (default), the raw JSON (--json), only the number (--count),
or counts by event and level (--summary); --head N / --tail N limit the lines. Lines that are not JSON are skipped. Older logs wrote the page id as
`deck_id`: it is read as the page id.
"""
import argparse
import gzip
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "logs" / "learning_platform.jsonl"


def log_files(path: Path, include_rotated: bool):
    """The log file, preceded (oldest first) by its rotated .gz files when asked for."""
    files = sorted(path.parent.glob(path.name + ".*.gz")) if include_rotated else []
    return files + ([path] if path.exists() else [])


def read_records(files):
    for f in files:
        opener = gzip.open if str(f).endswith(".gz") else open
        with opener(f, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec


def parse_time(text: str) -> datetime:
    dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def record_time(rec: dict):
    try:
        return parse_time(str(rec.get("ts", "")))
    except ValueError:
        return None


def page_of(rec: dict):
    return rec.get("page_id") or rec.get("deck_id")


def matches(rec: dict, a) -> bool:
    if a.event and rec.get("event") not in a.event:
        return False
    if a.level and str(rec.get("level", "")).upper() != a.level.upper():
        return False
    if a.service and rec.get("service") != a.service:
        return False
    if a.session and rec.get("session_id") != a.session:
        return False
    if a.page and page_of(rec) != a.page:
        return False
    if a.since or a.until:
        t = record_time(rec)
        if t is None or (a.since and t < a.since) or (a.until and t >= a.until):
            return False
    if a.grep:
        hay = (str(rec.get("message", "")) + " " + json.dumps(rec.get("data", ""), ensure_ascii=False)).lower()
        if a.grep.lower() not in hay:
            return False
    return True


def format_record(rec: dict) -> str:
    ts = str(rec.get("ts", ""))[:19].replace("T", " ")
    ids = " ".join(f"{k}={v}" for k, v in (("session", rec.get("session_id")), ("page", page_of(rec))) if v)
    data = f" data={json.dumps(rec['data'], ensure_ascii=False)}" if rec.get("data") else ""
    return f"{ts} {rec.get('level', '')} {rec.get('service', '')} {rec.get('event', '')} {rec.get('message', '')}" + (f" ({ids})" if ids else "") + data


def build_parser():
    ap = argparse.ArgumentParser(description="Query the structured log (JSON lines).")
    ap.add_argument("--file", type=Path, default=DEFAULT_LOG, help="the log file (default logs/learning_platform.jsonl)")
    ap.add_argument("--all", action="store_true", help="also read the rotated .gz files of the same log")
    ap.add_argument("--event", type=lambda s: s.split(","), help="event name(s), comma separated")
    ap.add_argument("--level")
    ap.add_argument("--service")
    ap.add_argument("--session", help="the notebook id")
    ap.add_argument("--page", help="the page id")
    ap.add_argument("--since", type=parse_time)
    ap.add_argument("--until", type=parse_time)
    ap.add_argument("--grep")
    out = ap.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="print the raw JSON lines")
    out.add_argument("--count", action="store_true", help="print only how many records match")
    out.add_argument("--summary", action="store_true", help="print counts by event and by level")
    ap.add_argument("--head", type=int, help="only the first N matches")
    ap.add_argument("--tail", type=int, help="only the last N matches")
    return ap


def main(argv=None, out=None) -> int:
    out = out or sys.stdout
    a = build_parser().parse_args(argv)
    files = log_files(a.file, a.all)
    if not files:
        print(f"no log file at {a.file}", file=sys.stderr)
        return 2
    found = [r for r in read_records(files) if matches(r, a)]
    if a.head:
        found = found[:a.head]
    if a.tail:
        found = found[-a.tail:]
    if a.count:
        print(len(found), file=out)
    elif a.summary:
        print(f"{len(found)} records", file=out)
        print("by level: " + ", ".join(f"{k} {v}" for k, v in Counter(str(r.get('level', '')) for r in found).most_common()), file=out)
        for event, n in Counter(str(r.get("event", "")) for r in found).most_common():
            print(f"{n:6d}  {event}", file=out)
    else:
        for r in found:
            print(json.dumps(r, ensure_ascii=False) if a.json else format_record(r), file=out)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
