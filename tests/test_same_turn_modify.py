"""
A modify of an element drawn EARLIER IN THE SAME TURN reaches the stored page.

The tutor loop keeps its own copy of the page for the overlap and id checks, and a modify looks its old group up in that copy and tells the store to replace exactly
that text. The copy used to be built from what the model WROTE, not from what was stored (sanitised, with the placeholder for control characters, with the trusted
font), so the old text never matched: the modify was silently dropped from `pages.current_svg` (the live board and the event log were right), and a NUL in the
raw text went into `old_svg_fragment`, which Postgres refuses: a 500 (K run 2 and L run 3, both the maths worked example). Both ways, on SQLite and on Postgres.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import Page, PageEvent

NUL = chr(0)


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def _model(*rounds):
    """A fake model: each round is a list of (tool, args) called together; then a plain final reply."""
    def tc(i, name, args):
        return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    replies = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
        content=None, tool_calls=[tc(i, n, a) for i, (n, a) in enumerate(r)]))], usage=None, model="fake") for r in rounds]
    replies.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="Done.", tool_calls=None))], usage=None, model="fake"))
    it = iter(replies)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: next(it))))


def card(eid, word, x=60, y=100):
    return f'<g id="{eid}"><rect x="{x}" y="{y}" width="400" height="120" fill="#cce5ff"/><text x="{x + 15}" y="{y + 50}" font-size="18">{word}</text></g>'


def draw(eid, svg, y=None):
    return ("draw_new_element", {"element_id": eid, "svg_fragment": svg, "narration": f"[[MARK:{eid}]] Here."})


def modify(eid, svg):
    return ("modify_existing_element", {"element_id": eid, "new_svg_fragment": svg})


def run(api, *rounds, message="teach me"):
    client, eng = api
    nb = client.post("/api/notebooks", json={"topic": "Same turn"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
    with patch("engine.author.get_azure_client", lambda: _model(*rounds)), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb}/chat", json={"message": message, "page_id": pg})
    with Session(eng) as db:
        svg = db.get(Page, pg).current_svg or ""
        events = db.exec(select(PageEvent).where(PageEvent.page_id == pg).order_by(PageEvent.seq)).all()
    return r, svg, events, (nb, pg)


# ---- the modify reaches the stored page ---------------------------------------------------------------------------------------------

def test_a_modify_in_the_same_turn_as_the_draw_replaces_the_element_on_the_stored_page(api):
    r, svg, events, _ = run(api, [draw("a", card("a", "BEFORE"))], [modify("a", card("a", "AFTER"))])
    assert r.status_code == 200, r.text
    assert "AFTER" in svg and "BEFORE" not in svg, "the stored page must show the modified element"
    assert svg.count('id="a"') == 1
    drawn, modified = [e for e in events if e.kind in ("draw", "modify")]
    assert modified.old_svg_fragment == drawn.svg_fragment, "the modify replaced exactly the text that was stored"


def test_the_trusted_font_is_on_the_page_once_after_a_draw_a_second_draw_and_a_modify_of_the_second(api):
    r, svg, _, _ = run(api, [draw("a", card("a", "ONE"))], [draw("b", card("b", "TWO", x=560))], [modify("b", card("b", "TWO CHANGED", x=560))])
    assert r.status_code == 200, r.text
    assert "TWO CHANGED" in svg and "ONE" in svg and "TWO<" not in svg
    assert svg.count("<style") == 1, "one copy of the font (one style block, two @font-face rules) on the page, however many elements were drawn and modified"


def test_a_drawing_the_sanitiser_changed_can_still_be_modified_in_the_same_turn(api):
    typo = card("a", "BEFORE").replace('font-size="18"', 'font-size"18"')              # repaired by the sanitiser, so the stored text differs from the written text
    r, svg, _, _ = run(api, [draw("a", typo)], [modify("a", card("a", "AFTER"))])
    assert r.status_code == 200, r.text
    assert "AFTER" in svg and "BEFORE" not in svg


# ---- the 500 of K run 2 and L run 3 ---------------------------------------------------------------------------------------------------

def test_a_nul_in_the_drawing_and_two_modifies_in_the_same_turn_is_not_a_500(api):
    """The maths worked example: control characters where the exponent should be, redrawn twice in the same turn."""
    wrote = card("a", f"f(x) = x{NUL}8")
    r, svg, events, _ = run(api, [draw("a", wrote)], [modify("a", card("a", f"f'(x) = 8x{NUL}7"))], [modify("a", card("a", "f'(x) = 8x^7"))])
    assert r.status_code == 200, r.text
    assert "8x^7" in svg and NUL not in svg
    assert all(NUL not in (e.svg_fragment or "") and NUL not in (e.old_svg_fragment or "") for e in events)
    assert [e.kind for e in events] == ["draw", "modify", "modify"]


def test_a_modify_in_a_later_turn_still_works(api):
    client, eng = api
    r, svg, _, (nb, pg) = run(api, [draw("a", card("a", "BEFORE"))])
    assert r.status_code == 200 and "BEFORE" in svg
    with patch("engine.author.get_azure_client", lambda: _model([modify("a", card("a", "AFTER"))])), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        assert client.post(f"/api/notebooks/{nb}/chat", json={"message": "fix it", "page_id": pg}).status_code == 200
    with Session(eng) as db:
        svg = db.get(Page, pg).current_svg
    assert "AFTER" in svg and "BEFORE" not in svg
