"""
scripts/logs_query.py (ported: the project had a reference to it and no file), and the names in core/log.py (no "webinar", no deck or slide: this
project has pages).
"""
import gzip
import io
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import logs_query

ROOT = Path(__file__).parent.parent


def rec(ts, level, event, message, session="n1", page="p1", service="engine", data=None, legacy=False):
    r = {"ts": ts, "level": level, "service": service, "event": event, "message": message, "session_id": session}
    r["deck_id" if legacy else "page_id"] = page
    if data is not None:
        r["data"] = data
    return r


@pytest.fixture()
def log(tmp_path):
    path = tmp_path / "learning_platform.jsonl"
    rows = [rec("2026-10-08T10:00:00.1Z", "INFO", "draw_completed", "Element 'a' drawn OK"),
            rec("2026-10-08T10:00:05.0Z", "WARN", "draw_failed", "Element 'b' rejected: overlaps", data={"element_id": "b"}),
            rec("2026-10-08T11:00:00.0Z", "INFO", "model_usage", "Model call", session="n2", page="p2", data={"prompt_tokens": 100}),
            rec("2026-10-09T09:00:00.0Z", "WARN", "draw_failed", "Element 'c' rejected: label", session="n2", page="p2", service="backend")]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nthis is not json\n\n", encoding="utf-8")
    old = tmp_path / "learning_platform.jsonl.2026-10-07.gz"
    with gzip.open(old, "wt", encoding="utf-8") as f:
        f.write(json.dumps(rec("2026-10-07T08:00:00.0Z", "ERROR", "draw_failed", "an old one", page="p0", legacy=True)) + "\n")
    return path


def run(log, *args):
    buf = io.StringIO()
    code = logs_query.main(["--file", str(log), *args], out=buf)
    return code, buf.getvalue().strip().splitlines()


def test_by_default_every_record_is_one_readable_line_and_bad_lines_are_skipped(log):
    code, lines = run(log)
    assert code == 0 and len(lines) == 4
    assert lines[0] == "2026-10-08 10:00:00 INFO engine draw_completed Element 'a' drawn OK (session=n1 page=p1)"
    assert lines[1].endswith('(session=n1 page=p1) data={"element_id": "b"}')


@pytest.mark.parametrize("args,expected", [
    (["--event", "draw_failed"], 2), (["--event", "draw_failed,model_usage"], 3), (["--level", "warn"], 2), (["--service", "backend"], 1),
    (["--session", "n2"], 2), (["--page", "p2"], 2), (["--since", "2026-10-08T10:30"], 2), (["--until", "2026-10-08T10:30"], 2),
    (["--since", "2026-10-09"], 1), (["--grep", "REJECTED"], 2), (["--grep", "prompt_tokens"], 1),
    (["--event", "draw_failed", "--session", "n2"], 1), (["--event", "nothing"], 0),
])
def test_each_filter_and_their_combinations(log, args, expected):
    assert run(log, "--count", *args) == (0, [str(expected)])


def test_head_and_tail_limit_the_lines(log):
    assert [l[:19] for l in run(log, "--head", "1")[1]] == ["2026-10-08 10:00:00"]
    assert [l[:19] for l in run(log, "--tail", "2")[1]] == ["2026-10-08 11:00:00", "2026-10-09 09:00:00"]


def test_json_prints_the_raw_records(log):
    _, lines = run(log, "--json", "--event", "model_usage")
    assert json.loads(lines[0])["data"] == {"prompt_tokens": 100}


def test_summary_counts_by_level_and_event(log):
    _, lines = run(log, "--summary")
    assert lines[0] == "4 records" and lines[1] == "by level: INFO 2, WARN 2"
    assert any(re.match(r"\s+2\s+draw_failed$", l) for l in lines)


def test_rotated_files_are_read_only_when_asked_and_the_old_deck_id_is_the_page(log):
    assert run(log, "--count")[1] == ["4"]
    assert run(log, "--all", "--count") == (0, ["5"])
    _, lines = run(log, "--all", "--page", "p0")
    assert len(lines) == 1 and "an old one" in lines[0] and "page=p0" in lines[0]


def test_a_missing_log_is_an_error_not_an_empty_answer(tmp_path, capsys):
    assert logs_query.main(["--file", str(tmp_path / "nope.jsonl"), "--count"], out=io.StringIO()) == 2
    assert "no log file" in capsys.readouterr().err


# ---- the names in core/log.py ---------------------------------------------------------------------------------------------------------

def test_core_log_has_no_webinar_deck_or_slide_in_it():
    source = (ROOT / "core" / "log.py").read_text(encoding="utf-8")
    assert not re.search(r"webinar|deck|slide", source, re.IGNORECASE)


def test_a_record_carries_the_page_id_and_the_logger_is_named_for_this_project(tmp_path):
    import logging
    from core.log import get_logger, init_logging, log_context
    path = tmp_path / "x.jsonl"
    init_logging(log_file=path, force=True)
    try:
        with log_context(session_id="nb-1", page_id="pg-1"):
            get_logger("engine").info("probe", "hello")
        for h in logging.getLogger("learning_platform").handlers:
            h.flush()
        r = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert r["session_id"] == "nb-1" and r["page_id"] == "pg-1" and "deck_id" not in r and "slide_id" not in r
        assert get_logger("engine")._underlying.name == "learning_platform.engine"
    finally:
        init_logging(log_file=ROOT / "logs" / "app.jsonl", force=True)
