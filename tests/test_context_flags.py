"""
The two TEST-ONLY switches of eval M and the context_built event.

LP_TEST_SUMMARIES_OFF=1 hides every page summary from the tutor's context (page titles stay: "Page 1: Title — No summary."); unset, the default, summaries are shown.
LP_TEST_HISTORY_TURNS shrinks the history window (default 15) so an earlier page is out of it. Every chat turn logs `context_built`: how many earlier pages, how many
show a summary, how many history turns, and which switches were on, so a run can say how often the summaries were really in the tutor's context.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.main as bm
from backend.models import Page
from backend.page_state import prior_pages_summary, summaries_in_context
from core.events import BackendEvent

PAGES = [SimpleNamespace(page_number=1, title="Binary search", summary="Taught halving."), SimpleNamespace(page_number=2, title="Cost", summary=None)]


def test_by_default_summaries_are_shown_and_counted(monkeypatch):
    monkeypatch.delenv("LP_TEST_SUMMARIES_OFF", raising=False)
    assert prior_pages_summary(PAGES) == "Page 1: Binary search — Taught halving.\nPage 2: Cost — No summary."
    assert summaries_in_context(PAGES) == 1


@pytest.mark.parametrize("value", ["1"])
def test_the_off_switch_hides_every_summary_but_keeps_the_titles(monkeypatch, value):
    monkeypatch.setenv("LP_TEST_SUMMARIES_OFF", value)
    assert prior_pages_summary(PAGES) == "Page 1: Binary search — No summary.\nPage 2: Cost — No summary."
    assert summaries_in_context(PAGES) == 0


def test_any_other_value_leaves_summaries_on(monkeypatch):
    monkeypatch.setenv("LP_TEST_SUMMARIES_OFF", "0")
    assert summaries_in_context(PAGES) == 1


def _model():
    sent = []

    def create(**kw):
        sent.append(kw["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="Fine.", tool_calls=None))], usage=None, model="fake")
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), sent


def _turns(api, n_turns, monkeypatch, off=False, history=None):
    client, eng = api
    if off:
        monkeypatch.setenv("LP_TEST_SUMMARIES_OFF", "1")
    if history is not None:
        monkeypatch.setattr(bm, "HISTORY_TURNS", history)
    nb = client.post("/api/notebooks", json={"topic": "Flags"}).json()["id"]
    with Session(eng) as db:                       # an earlier saved page with a summary, then the active page
        first = db.exec(select(Page).where(Page.notebook_id == nb)).one()
        first.title, first.summary, first.status = "Earlier page", "SUMMARY OF THE EARLIER PAGE", "saved"
        db.add(first)
        db.add(Page(notebook_id=nb, page_number=2, status="active"))
        db.commit()
    events, sents = [], []
    for i in range(n_turns):
        m, sent = _model()
        with patch("engine.author.get_azure_client", lambda: m), patch("backend.main.logger") as log:
            assert client.post(f"/api/notebooks/{nb}/chat", json={"message": f"question {i}"}).status_code == 200
        events += [c.kwargs["data"] for c in log.info.call_args_list if c.args and c.args[0] == BackendEvent.CONTEXT_BUILT]
        sents.append(sent[0])
    return events, sents


def test_the_context_reaches_the_tutor_with_the_summary_and_the_event_says_so(api, monkeypatch):
    events, sents = _turns(api, 2, monkeypatch)
    assert [e["with_summary"] for e in events] == [1, 1] and events[0]["prior_pages"] == 1 and events[0]["summaries_off"] is False
    context = next(m["content"] for m in sents[0] if isinstance(m, dict) and m["role"] == "system" and m["content"].startswith("NOTEBOOK CONTEXT"))
    assert "SUMMARY OF THE EARLIER PAGE" in context
    assert [e["history_turns"] for e in events] == [0, 2]


def test_with_the_off_switch_the_tutor_reads_the_title_only_and_the_event_says_so(api, monkeypatch):
    events, sents = _turns(api, 1, monkeypatch, off=True)
    assert events[0]["with_summary"] == 0 and events[0]["summaries_off"] is True and events[0]["prior_pages"] == 1
    context = next(m["content"] for m in sents[0] if isinstance(m, dict) and m["role"] == "system" and m["content"].startswith("NOTEBOOK CONTEXT"))
    assert "Earlier page — No summary." in context and "SUMMARY OF THE EARLIER PAGE" not in context


def test_the_history_window_can_be_shrunk_for_the_test_and_defaults_to_15(api, monkeypatch):
    assert bm.HISTORY_TURNS == 15
    events, _ = _turns(api, 3, monkeypatch, history=2)
    assert [e["history_turns"] for e in events] == [0, 2, 2] and events[0]["history_limit"] == 2
