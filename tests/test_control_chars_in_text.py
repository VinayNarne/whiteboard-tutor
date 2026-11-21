"""
A control character in text a person typed, pasted or dictated must not end the request as a 500.

Found in the L round: Postgres refuses a NUL (0x00) in any text column ("A string literal cannot contain NUL"), and a chat message, a topic or a narration went
straight into one. The text types of backend/limits.py now replace control characters with the visible placeholder the sanitiser uses on the board (U+FFFD),
and keep tab, newline and carriage return. Both ways, on SQLite and on Postgres (the `db_url` fixture): normal text is stored exactly as sent, and a NUL
never reaches the database.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import ChatTurn, Notebook

PLACEHOLDER = "�"
GOOD = [
    "What is binary search?",
    "Explain équation, Δx → 0, 你好 and an emoji \U0001F600 please",
    "In code: print(\"a\\n\") if x < 3 && y > 2 else 'b'",
    "line one\nline two\r\nline three\twith a tab",
    "A literal entity written as text: &#0; and &amp;",
]


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def _model():
    sent = []

    def create(**kw):
        sent.append(kw["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="Fine.", tool_calls=None))], usage=None, model="fake")
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), sent


def _chat(client, nb, message):
    model, sent = _model()
    with patch("engine.author.get_azure_client", lambda: model), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb}/chat", json={"message": message})
    return r, sent


# ---- unit: what the validator does ----------------------------------------------------------------------------------------------------

def test_every_control_character_but_tab_newline_and_carriage_return_becomes_the_placeholder():
    from backend.limits import no_control_chars
    assert no_control_chars("a\x00b\x01c\x1bd\x7fe\x85f") == f"a{PLACEHOLDER}b{PLACEHOLDER}c{PLACEHOLDER}d{PLACEHOLDER}e{PLACEHOLDER}f"
    for text_ in GOOD:
        assert no_control_chars(text_) == text_


# ---- through the API, on both databases -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("message", GOOD)
def test_normal_text_is_stored_exactly_as_sent(api, message):
    client, eng = api
    nb = client.post("/api/notebooks", json={"topic": "Plain"}).json()["id"]
    r, sent = _chat(client, nb, message)
    assert r.status_code == 200, r.text
    with Session(eng) as db:
        assert db.exec(select(ChatTurn).where(ChatTurn.role == "user")).one().content == message.strip()
    assert sent[0][-1]["content"] == message.strip()


def test_a_nul_in_a_chat_message_never_reaches_the_database_and_the_turn_still_works(api):
    client, eng = api
    nb = client.post("/api/notebooks", json={"topic": "Nul"}).json()["id"]
    r, sent = _chat(client, nb, "before\x00after \x1b[31m and a bell\x07")
    assert r.status_code == 200, r.text
    expected = f"before{PLACEHOLDER}after {PLACEHOLDER}[31m and a bell{PLACEHOLDER}"
    with Session(eng) as db:
        user = db.exec(select(ChatTurn).where(ChatTurn.role == "user")).one()
        assert user.content == expected
        assert db.exec(select(ChatTurn).where(ChatTurn.role == "assistant")).one().status == "ok"
        stored = [row[0] for row in db.connection().execute(text("select content from chat_turns")).fetchall()]
    assert all("\x00" not in c for c in stored)
    assert sent[0][-1]["content"] == expected, "the tutor reads the placeholder, not the NUL"


def test_a_nul_in_a_topic_and_a_title_is_replaced_too(api):
    client, eng = api
    r = client.post("/api/notebooks", json={"topic": "Top\x00ic", "title": "Ti\x00tle"})
    assert r.status_code == 201, r.text
    nb = r.json()["id"]
    with Session(eng) as db:
        n = db.get(Notebook, nb)
        assert n.topic == f"Top{PLACEHOLDER}ic" and n.title == f"Ti{PLACEHOLDER}tle"


def test_a_nul_in_lesson_board_notes_is_never_stored(api):
    from backend.models import Page, PageEvent
    from test_scene import _chat as scene_chat, _model as scene_model
    client, eng = api
    nb = client.post("/api/notebooks", json={"topic": "Board"}).json()["id"]
    notes = {"title": "T", "lines": [{"text": "bad\x00text", "say": "bad\x00say"}]}
    m, _ = scene_model([[("write_notes", notes)]])
    r = scene_chat(client, nb, m)
    assert r.status_code == 200, r.text
    with Session(eng) as db:
        events = db.exec(select(PageEvent).join(Page, Page.id == PageEvent.page_id).where(Page.notebook_id == nb, PageEvent.kind == "draw")).all()
        assert events
        assert all("\x00" not in (e.narration or "") and "\x00" not in (e.svg_fragment or "") for e in events)
