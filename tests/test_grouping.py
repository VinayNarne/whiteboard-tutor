"""
An element is one <g id="element_id"> group, however the model wrote it (engine/grouping.py).

Why the code owns this: the sanitiser parses a fragment as one XML document and keeps only the FIRST top-level node, so a card
sent as sibling tags (<rect/><text>...</text>) was stored as the bare <rect> and its text was silently dropped, while the tool
answered "ok". From baseline C on, 48-88% of the tutor's drawings were written that way (docs/BASELINE.md).
"""
import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import patch

import lxml.etree as LET
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EngineEvent
from engine import voice
from engine.author import _handle_draw_new_element, _handle_modify_existing_element
from engine.grouping import ensure_group
from engine.sanitiser import sanitize_svg

RECT = '<rect x="60" y="120" width="330" height="180" fill="#cce5ff"/>'
TEXT = '<text x="75" y="160" font-size="20">First law</text>'
LINE = '<line x1="75" y1="170" x2="300" y2="170" stroke="#000"/>'
GROUP = f'<g id="el">{RECT}{TEXT}</g>'
ALIGN = {"characters": list("x"), "character_start_times_seconds": [0.0], "character_end_times_seconds": [1.0]}


def _parts(svg):
    """(tag names of the children of the root, ids found anywhere) of a sanitised fragment."""
    root = LET.fromstring(svg.encode("utf-8"))
    return [c.tag.split("}")[-1] for c in root], [e.get("id") for e in root.iter() if e.get("id")], root.tag.split("}")[-1]


# ---- a) what becomes one group -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("fragment,reason", [
    (RECT, "bare_tag"),
    (TEXT, "bare_tag"),
    (RECT + TEXT + LINE, "multiple_top_level"),
    (RECT + "\n  " + TEXT, "multiple_top_level"),
    (f'<g id="other">{RECT}</g>', "group_id"),
    (f"<g>{RECT}{TEXT}</g>", "group_id"),
    (f'<g id="el">{RECT}</g>{TEXT}', "multiple_top_level"),
    (f'<g id="a">{RECT}</g><g id="b">{TEXT}</g>', "multiple_top_level"),
])
def test_anything_that_is_not_exactly_one_group_with_the_elements_id_becomes_one_valid_group(fragment, reason):
    fixed, why = ensure_group(fragment, "el")
    assert why == reason
    kids, ids, root = _parts(sanitize_svg(fixed))
    assert root == "g" and ids.count("el") == 1 and ids[0] == "el"


def test_a_single_bare_rect_a_bare_text_and_three_sibling_tags_each_keep_everything_the_model_drew():
    for fragment, tags in [(RECT, ["rect"]), (TEXT, ["text"]), (RECT + TEXT + LINE, ["rect", "text", "line"])]:
        kids, ids, root = _parts(sanitize_svg(ensure_group(fragment, "el")[0]))
        assert kids == tags and ids == ["el"], (fragment, kids, ids)


def test_without_the_repair_the_sanitiser_drops_every_sibling_after_the_first():
    """The bug this module exists for, pinned so it cannot come back unnoticed."""
    assert "<text" not in sanitize_svg(RECT + TEXT)
    assert "<text" in sanitize_svg(ensure_group(RECT + TEXT, "el")[0])


def test_a_correct_group_is_not_touched():
    assert ensure_group(GROUP, "el") == (GROUP, None)
    padded = f"  \n{GROUP}\n  "
    assert ensure_group(padded, "el") == (padded, None)


def test_the_id_moves_to_the_wrapper_so_the_page_never_holds_two():
    bare = '<rect id="el" x="1" y="1" width="100" height="50"/>'
    fixed, why = ensure_group(bare, "el")
    assert why == "bare_tag" and len(re.findall(r'\bid=', fixed)) == 1
    assert _parts(sanitize_svg(fixed))[1] == ["el"]
    siblings, _ = ensure_group(f'<rect id="el" x="1" y="1" width="100" height="50"/><text id=\'el\' x="5" y="9">A</text>', "el")
    assert _parts(sanitize_svg(siblings))[1] == ["el"]


def test_other_ids_inside_the_drawing_are_left_alone():
    fixed, _ = ensure_group('<rect id="box" x="1" y="1" width="100" height="50"/><text x="5" y="9">A</text>', "el")
    assert _parts(sanitize_svg(fixed))[1] == ["el", "box"]


def test_an_element_id_with_characters_that_need_escaping_stays_one_valid_attribute():
    fixed, _ = ensure_group(RECT + TEXT, 'a"b&c')
    assert _parts(sanitize_svg(fixed))[1] == ['a"b&c']


def test_text_with_stray_markup_is_kept_whole():
    fixed, why = ensure_group('<rect x="1" y="1" width="100" height="50"/><text x="5" y="30">low <= high & more</text>', "el")
    assert why == "multiple_top_level"
    assert "low &lt;= high &amp; more" in sanitize_svg(fixed)


def test_an_empty_fragment_is_left_for_the_sanitiser_to_report():
    assert ensure_group("", "el") == ("", None) and ensure_group("   ", "el") == ("   ", None)


# ---- b) the existing guards still decide -------------------------------------------------------------------------------------

def test_script_content_is_still_removed_by_the_sanitiser_whether_or_not_the_fragment_was_wrapped():
    wrapped = sanitize_svg(ensure_group(RECT + "<script>alert(1)</script>" + TEXT, "el")[0])
    assert "script" not in wrapped and "alert" not in wrapped and "First law" in wrapped
    inside_correct_group = sanitize_svg(ensure_group(f'<g id="el">{RECT}<script>alert(1)</script></g>', "el")[0])
    assert "script" not in inside_correct_group and "alert" not in inside_correct_group


def test_event_handlers_and_foreign_objects_are_still_removed():
    s = sanitize_svg(ensure_group(f'<rect onclick="x()" x="1" y="1" width="100" height="50"/><foreignObject><div>hi</div></foreignObject>', "el")[0])
    assert "onclick" not in s and "foreignObject" not in s


# ---- c) through the real handlers: stored, emitted, counted -----------------------------------------------------------------

def _draw(fragment, current_svg=None, element_id="el"):
    saved = []

    async def emit(kind, payload):
        pass

    async def persist(**k):
        saved.append(k)
    with patch.object(voice, "_call_elevenlabs_tts", lambda t: (b"MP3", ALIGN, 1.0, False)), patch("engine.author.logger") as log:
        r = asyncio.run(_handle_draw_new_element("nb", "pg", "active", element_id, fragment, "[[MARK:el]] Hello.", current_svg, emit, persist))
    repairs = [c.kwargs["data"] for c in log.info.call_args_list if c.args[0] == EngineEvent.GROUP_REPAIRED]
    return r, saved, repairs


def test_a_card_sent_as_sibling_tags_is_stored_whole_as_one_group_and_the_repair_is_counted():
    r, saved, repairs = _draw(RECT + TEXT + LINE)
    assert r["status"] == "ok"
    kids, ids, root = _parts(saved[0]["svg_fragment"])
    assert root == "g" and ids == ["el"] and [k for k in kids if k != "defs"] == ["rect", "text", "line"]
    assert repairs == [{"element_id": "el", "kind": "draw", "reason": "multiple_top_level"}]


def test_a_bare_rect_is_stored_as_a_group_with_the_id_and_a_correct_group_is_not_counted():
    r, saved, repairs = _draw(RECT)
    assert r["status"] == "ok" and 'id="el"' in saved[0]["svg_fragment"] and repairs[0]["reason"] == "bare_tag"
    r, saved, repairs = _draw(GROUP)
    assert r["status"] == "ok" and repairs == []


def test_an_id_that_already_exists_on_the_page_is_still_rejected_before_any_wrapping():
    r, saved, repairs = _draw(RECT + TEXT, current_svg='<g id="el"><rect x="500" y="500" width="50" height="50"/></g>')
    assert r["status"] == "error" and "already exists" in r["detail"] and saved == [] and repairs == []


def test_a_background_frame_among_sibling_tags_is_still_rejected():
    r, saved, repairs = _draw('<rect x="0" y="0" width="1100" height="700"/>' + TEXT)
    assert r["status"] == "error" and "background frame" in r["detail"] and saved == []


def test_a_transform_among_sibling_tags_is_still_rejected():
    r, saved, repairs = _draw(RECT + '<text x="5" y="9" transform="rotate(90)">A</text>')
    assert r["status"] == "error" and "transform" in r["detail"].lower() and saved == []


def test_a_modified_element_is_replaced_by_a_whole_group_too():
    saved = []

    async def emit(kind, payload):
        pass

    async def persist(**k):
        saved.append(k)
    current = '<g xmlns="http://www.w3.org/2000/svg" id="el"><rect x="60" y="120" width="330" height="180"/></g>'
    with patch("engine.author.logger") as log:
        r = asyncio.run(_handle_modify_existing_element("pg", "active", "el", RECT + TEXT, current, {"el"}, emit, persist))
    assert r["status"] == "ok"
    kids, ids, root = _parts(saved[0]["svg_fragment"])
    assert root == "g" and ids == ["el"] and [k for k in kids if k != "defs"] == ["rect", "text"]
    assert saved[0]["old_svg_fragment"] == current        # found by id now, so the page's stored SVG is replaced as well
    assert [c.kwargs["data"]["kind"] for c in log.info.call_args_list if c.args[0] == EngineEvent.GROUP_REPAIRED] == ["modify"]


# ---- d) the author loop's own copy of the page holds the repaired groups, so later checks in the same turn see them ----------

def _scripted(*calls):
    """A fake model: one assistant message with all `calls` (name, args), then a plain final reply. Returns (client, tool_results)."""
    import json
    from types import SimpleNamespace
    sent = []

    def tc(i, name, args):
        return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    first = SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
        content=None, tool_calls=[tc(i, n, a) for i, (n, a) in enumerate(calls)]))], usage=None, model="fake")
    last = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="Done.", tool_calls=None))],
                           usage=None, model="fake")
    replies = iter([first, last])

    def create(**kw):
        sent.append(kw["messages"])
        return next(replies)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), sent


def _run_turn(client, sent):
    from engine import author

    async def noop(*a, **k):
        pass
    with patch.object(voice, "_call_elevenlabs_tts", lambda t: (b"MP3", ALIGN, 1.0, False)), \
            patch.object(author, "get_azure_client", lambda: client), patch("engine.author.logger"):
        asyncio.run(author.run_whiteboard_author("nb", "pg", "active", "teach me", [], {"current_svg": None, "element_count": 0},
                                                 "", set(), noop, noop))
    return [m for m in sent[-1] if isinstance(m, dict) and m.get("role") == "tool"]


CARD_A = '<rect x="100" y="100" width="300" height="200" fill="#cce5ff"/><text x="120" y="150" font-size="20">First law</text>'
CARD_B = '<rect x="150" y="150" width="300" height="200" fill="#d4edda"/><text x="170" y="200" font-size="20">Second law</text>'


def test_a_card_drawn_earlier_in_the_same_turn_as_sibling_tags_is_seen_by_the_overlap_check():
    client, sent = _scripted(("draw_new_element", {"element_id": "a", "svg_fragment": CARD_A, "narration": "[[MARK:a]] One."}),
                             ("draw_new_element", {"element_id": "b", "svg_fragment": CARD_B, "narration": "[[MARK:b]] Two."}))
    results = _run_turn(client, sent)
    assert '"status": "ok"' in results[0]["content"]
    assert '"status": "error"' in results[1]["content"] and "overlaps existing 'a'" in results[1]["content"]


def test_the_free_space_map_the_tutor_is_shown_holds_the_card_it_just_drew():
    client, sent = _scripted(("draw_new_element", {"element_id": "a", "svg_fragment": CARD_A, "narration": "[[MARK:a]] One."}))
    results = _run_turn(client, sent)
    assert '"element_id": "a"' in results[0]["content"] and '"occupied_regions"' in results[0]["content"]


def test_a_reused_id_in_the_same_turn_is_rejected_even_when_the_first_drawing_was_sibling_tags():
    client, sent = _scripted(("draw_new_element", {"element_id": "a", "svg_fragment": CARD_A, "narration": "[[MARK:a]] One."}),
                             ("draw_new_element", {"element_id": "a", "svg_fragment": '<rect x="700" y="500" width="100" height="100"/>',
                                                   "narration": "[[MARK:a]] Again."}))
    results = _run_turn(client, sent)
    assert "already exists" in results[1]["content"]
