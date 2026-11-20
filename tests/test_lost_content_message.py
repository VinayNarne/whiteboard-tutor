"""
No silent recovery: when the sanitiser or the repair drops anything the model wrote (tags, text, characters, control characters), the
tool result sent to the tutor says what was lost and asks it to redraw that element, and the loss is logged. It is not a rejection: the
drawing is stored and the status stays "ok". Real arrows and superscripts are never touched; control characters get a visible placeholder.
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from core.events import EngineEvent
from engine import voice
from engine.author import _handle_draw_new_element, _handle_modify_existing_element
from engine.sanitiser import CONTROL_PLACEHOLDER as PH

ALIGN = {"characters": list("x"), "character_start_times_seconds": [0.0], "character_end_times_seconds": [1.0]}
RECT = '<rect x="60" y="120" width="330" height="180" fill="#cce5ff"/>'
CLEAN = RECT + '<text x="75" y="160" font-size="20">Law 1</text><text x="75" y="190" font-size="16">Rest stays at rest</text>'
MALFORMED = (RECT + '<text x="75" y="160" font-size="20">Title stays</text>'
             '<text x="75" y="190" font-size="16" fill"#000">Second line is cut</text><text x="75" y="210" font-size="16">Third line</text>')


def _draw(fragment, element_id="el"):
    saved = []

    async def emit(kind, payload):
        pass

    async def persist(**k):
        saved.append(k)
    with patch.object(voice, "_call_elevenlabs_tts", lambda t: (b"MP3", ALIGN, 1.0, False)), patch("engine.author.logger") as log:
        r = asyncio.run(_handle_draw_new_element("nb", "pg", "active", element_id, fragment, f"[[MARK:{element_id}]] Hello.", None, emit, persist))
    events = [c.kwargs["data"] for c in log.info.call_args_list if c.args[0] == EngineEvent.CONTENT_LOST]
    return r, saved, events


# ---- a) something lost: the tutor is told, the loss is logged, the drawing is still stored --------------------------------------

def test_four_sibling_tags_with_a_malformed_attribute_tell_the_tutor_exactly_what_was_lost():
    r, saved, events = _draw(MALFORMED)
    assert r["status"] == "ok" and saved, "not a rejection: the drawing is stored"
    note = r["lost_content"]
    assert note.startswith("Not everything you wrote for 'el' reached the board: 2 text labels are missing (first: \"Second line is cut\")")
    assert "Redraw it with modify_existing_element (same element_id)" in note
    assert len(events) == 1 and events[0]["told_tutor"] is True and events[0]["text_lines"] == 2 and events[0]["element_id"] == "el"


def test_a_removed_tag_is_named():
    r, saved, events = _draw('<g id="el">' + RECT + '<script>alert(1)</script><text x="5" y="30">kept</text></g>')
    assert r["status"] == "ok" and "tags removed: <script> x1" in r["lost_content"]


def test_a_clean_drawing_gets_no_note_and_no_event():
    r, saved, events = _draw(CLEAN)
    assert r["status"] == "ok" and "lost_content" not in r and events == []


def test_formatting_tags_removed_on_purpose_are_logged_but_do_not_ask_for_a_redraw():
    r, saved, events = _draw(RECT + '<text x="5" y="30">a <b>bold</b> word<br/>next</text>')
    assert "lost_content" not in r
    assert events == [{"element_id": "el", "kind": "draw", "formatting": {"b": 1, "br": 1}, "told_tutor": False}]


# ---- b) control characters: a visible placeholder, and the tutor is told ------------------------------------------------------------

def test_control_characters_get_the_placeholder_on_the_board_and_the_tutor_is_told():
    r, saved, events = _draw(RECT + '<text x="5" y="30">f(x) = x\x00\x00 and lim h\x7f0</text>')
    assert r["status"] == "ok"
    assert f"f(x) = x{PH}{PH} and lim h{PH}0" in saved[0]["svg_fragment"]
    note = r["lost_content"]
    assert note.startswith("In 'el', 3 control characters (code 0, 127) cannot be drawn, so the board shows " + PH + " there.")
    assert "arrow or a superscript" in note and "modify_existing_element (same element_id)" in note
    assert note.endswith("writing the character itself (for example ², → or ₂) and not an escape sequence such as " + chr(92) + "u0000."), note
    assert "&#" not in note and "real character" not in note, "the old wording (an entity, 'the real character') is gone"
    assert events[0]["control"] == 3 and events[0]["told_tutor"] is True


def test_real_arrows_and_superscripts_survive_and_nothing_is_said():
    r, saved, events = _draw(RECT + '<text x="5" y="30">h → 0, x², m/s² and &rarr; &sup2;</text>')
    stored = saved[0]["svg_fragment"]
    assert "h → 0, x², m/s² and → ²" in stored and PH not in stored
    assert "lost_content" not in r and events == []


def test_loss_and_control_characters_in_one_drawing_are_both_reported():
    r, saved, events = _draw('<g id="el">' + RECT + '<script>x</script><text x="5" y="30">x\x00</text></g>')
    note = r["lost_content"]
    assert "tags removed: <script> x1" in note and "Also, 1 control character (code 0) cannot be drawn and shows as " + PH in note
    assert note.endswith("write the character itself (for example ², → or ₂), not an escape sequence such as " + chr(92) + "u0000, when you redraw."), note


# ---- c) the modify path says the same ---------------------------------------------------------------------------------------------

def test_a_lossy_replacement_is_reported_the_same_way():
    saved = []

    async def emit(kind, payload):
        pass

    async def persist(**k):
        saved.append(k)
    current = '<g xmlns="http://www.w3.org/2000/svg" id="el"><rect x="60" y="120" width="330" height="180"/></g>'
    with patch("engine.author.logger") as log:
        r = asyncio.run(_handle_modify_existing_element("pg", "active", "el", MALFORMED, current, {"el"}, emit, persist))
    assert r["status"] == "ok" and "2 text labels are missing" in r["lost_content"] and saved
    assert [c.kwargs["data"]["kind"] for c in log.info.call_args_list if c.args[0] == EngineEvent.CONTENT_LOST] == ["modify"]


# ---- d) it reaches the tutor: the tool result of the author loop carries it ----------------------------------------------------

def test_the_tool_result_the_model_reads_carries_the_note():
    from test_grouping import _run_turn, _scripted
    client, sent = _scripted(("draw_new_element", {"element_id": "a", "svg_fragment": MALFORMED, "narration": "[[MARK:a]] One."}))
    results = _run_turn(client, sent)
    body = json.loads(results[0]["content"])
    assert body["status"] == "ok" and body["lost_content"].startswith("Not everything you wrote for 'a' reached the board")


def test_the_model_reads_the_real_characters_not_escape_sequences():
    """The note names the superscript, the arrow and the subscript. The tool result used to be serialised with ensure_ascii, so the model was shown
    them as backslash-u escapes (and the placeholder as backslash-ufffd): the note taught the very thing it asked the model not to write."""
    from test_grouping import _run_turn, _scripted
    client, sent = _scripted(("draw_new_element", {"element_id": "a", "svg_fragment": RECT + '<text x="75" y="160" font-size="20">x' + chr(0) + '2</text>', "narration": "[[MARK:a]] One."}))
    results = _run_turn(client, sent)
    raw = results[0]["content"]                                   # the text the model receives
    assert "², → or ₂" in raw, "the examples arrive as the characters themselves"
    for escape in (chr(92) + "u00b2", chr(92) + "u2192", chr(92) + "u2082", chr(92) + "ufffd"):
        assert escape not in raw, f"{escape} reaches the model as an escape sequence"
    assert PH in raw and "such as " + chr(92) * 2 + "u0000" in raw, "the one escape named as the thing NOT to write is shown (JSON doubles its backslash)"
    assert json.loads(raw)["lost_content"].endswith("not an escape sequence such as " + chr(92) + "u0000.")
