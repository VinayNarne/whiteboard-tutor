"""
The overlap rejection names the element it overlaps, gives the drawing's size and ONE free region computed in code from the existing elements (or says plainly that nothing
that large is left and how much room there is), and a repeated rejection stops repeating the full message.

Why (docs/OVERLAP_ROUND.md): in two real sessions the tutor was told "Redraw in free space (see occupied_regions in get_current_page_state), or ... propose a new page" and then
asked the learner for a new page on pages that held one to four drawings; once it sent the same rejected drawing four times at the same coordinates. Nothing is moved for the tutor:
the region is only described. Both ways: a region that fits is really free and big enough, and when the code says nothing fits, nothing does.
"""
import json
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EngineEvent
from engine.author import OVERLAP_MESSAGES_PER_ELEMENT, _overlap_message
from engine.validator import CANVAS_HEIGHT, CANVAS_WIDTH, FREE_GAP, FREE_MARGIN, check_overlap, extract_element_bboxes, find_free_region


def card(eid, x, y, w, h):
    return f'<g id="{eid}"><rect x="{x}" y="{y}" width="{w}" height="{h}"/><text x="{x + 10}" y="{y + 30}" font-size="16">{eid}</text></g>'


def region_of(message):
    m = re.search(r"x:(\d+), y:(\d+), width:(\d+), height:(\d+)", message.split("(x:")[-1] if "free region" not in message.lower() else message[message.lower().index("free region"):])
    return tuple(int(v) for v in m.groups())


# ---- the region, computed in code ---------------------------------------------------------------------------------------------------------

def test_a_region_that_fits_is_inside_the_canvas_margin_clear_of_every_element_and_big_enough():
    rng = random.Random(7)
    for _ in range(150):
        page = "".join(card(f"e{i}", rng.randrange(20, 900, 10), rng.randrange(60, 600, 10), rng.randrange(60, 400, 10), rng.randrange(40, 300, 10)) for i in range(rng.randrange(1, 7)))
        w, h = rng.randrange(40, 700, 10), rng.randrange(40, 500, 10)
        free = find_free_region(page, w, h)
        if not free["fits"]:
            continue
        x, y, rw, rh = free["x"], free["y"], free["width"], free["height"]
        assert rw >= w and rh >= h and x >= FREE_MARGIN and y >= FREE_MARGIN and x + rw <= CANVAS_WIDTH - FREE_MARGIN and y + rh <= CANVAS_HEIGHT - FREE_MARGIN
        for el in extract_element_bboxes(page):
            b = el["bbox"]
            assert x + rw <= b["x"] - FREE_GAP + 1e-6 or x >= b["x"] + b["width"] + FREE_GAP - 1e-6 or y + rh <= b["y"] - FREE_GAP + 1e-6 or y >= b["y"] + b["height"] + FREE_GAP - 1e-6, (free, b)


def test_when_the_code_says_nothing_fits_nothing_does():
    """Brute force on the same grid: no placement of a w x h box clear of every element (with the gap) exists."""
    rng = random.Random(11)
    said_no = 0
    for _ in range(80):
        page = "".join(card(f"e{i}", rng.randrange(20, 700, 10), rng.randrange(60, 500, 10), rng.randrange(200, 600, 10), rng.randrange(100, 400, 10)) for i in range(rng.randrange(2, 6)))
        w, h = rng.randrange(150, 700, 10), rng.randrange(150, 500, 10)
        if find_free_region(page, w, h)["fits"]:
            continue
        said_no += 1
        boxes = [e["bbox"] for e in extract_element_bboxes(page)]
        for x in range(FREE_MARGIN, CANVAS_WIDTH - FREE_MARGIN - w + 1, 10):
            for y in range(FREE_MARGIN, CANVAS_HEIGHT - FREE_MARGIN - h + 1, 10):
                assert any(x < b["x"] + b["width"] + FREE_GAP and x + w > b["x"] - FREE_GAP and y < b["y"] + b["height"] + FREE_GAP and y + h > b["y"] - FREE_GAP for b in boxes), (x, y, w, h)
    assert said_no >= 5, "the property was exercised"


def test_the_empty_page_and_a_page_with_a_thin_connector_are_free():
    assert find_free_region(None, 300, 200)["fits"] and find_free_region("", 300, 200)["free_pct"] == 100
    thin = '<g id="line"><line x1="60" y1="300" x2="1100" y2="300" stroke="#000"/></g>'
    assert find_free_region(thin, 900, 600)["fits"], "shapes thinner than 20 px are ignored, as in the overlap check"


# ---- the message ----------------------------------------------------------------------------------------------------------------------------

def test_the_message_names_both_elements_gives_the_size_and_a_region_the_drawing_really_fits_in():
    page = card("diagram_overview", 60, 120, 700, 350)
    new = card("external_mic", 120, 410, 120, 80)
    clash = check_overlap(page, new)
    msg = _overlap_message(clash, page)
    assert "'external_mic' overlaps existing 'diagram_overview' (x:60-760, y:120-470)." in msg
    assert "Your drawing is about 120x80 px. A free region where it fits:" in msg and msg.endswith("Redraw it inside that region.")
    assert "see occupied_regions" not in msg and "propose a new page" not in msg, "the old wording is gone"
    x, y, w, h = region_of(msg)
    assert w >= 120 and h >= 80
    assert check_overlap(page, card("external_mic", x, y, 120, 80)) is None, "drawing at the corner of the region is accepted"


def test_when_nothing_fits_it_says_so_plainly_and_how_much_room_is_left():
    page = card("a", 20, 20, 1160, 380) + card("b", 20, 400, 560, 380)
    big = card("big", 100, 100, 700, 400)
    msg = _overlap_message(check_overlap(page, big), page)
    assert "Your drawing is about 700x400 px and no free region that large is left on this page: about" in msg
    assert re.search(r"about \d+% of the canvas is free, and the largest free region is x:\d+, y:\d+, width:\d+, height:\d+\.", msg)
    assert msg.endswith("Draw something that fits there, or tell the learner the page is full.")


def test_the_hint_only_form_is_short_and_has_the_region_but_not_the_overlap_sentence():
    page = card("diagram_overview", 60, 120, 700, 350)
    clash = check_overlap(page, card("external_mic", 120, 410, 120, 80))
    hint = _overlap_message(clash, page, hint_only=True)
    assert hint.startswith("Free region for 'external_mic' (about 120x80 px): x:") and "overlaps" not in hint
    full_page = card("a", 20, 20, 1160, 380) + card("b", 20, 400, 1160, 380)
    assert _overlap_message(check_overlap(full_page, card("big", 100, 100, 500, 400)), full_page, hint_only=True).startswith("No free region for 'big'")


# ---- the repeat cap, through the tutor loop -------------------------------------------------------------------------------------------------

def _tc(i, name, args):
    return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _model(rounds, final="Done."):
    out = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
        content=None, tool_calls=[_tc(i, n, a) for i, (n, a) in enumerate(r)]))], usage=None, model="fake") for r in rounds]
    out.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=final, tool_calls=None))], usage=None, model="fake"))
    it, seen = iter(out), {"results": []}

    def create(**kw):
        seen["results"] = [json.loads(m["content"]) for m in kw["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
        return next(it)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), seen


def _draw(eid, x, y, w, h):
    return ("draw_new_element", {"element_id": eid, "svg_fragment": card(eid, x, y, w, h), "narration": f"[[MARK:{eid}]] Here."})


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def turn(api, rounds, nb=None, message="teach me"):
    client, eng = api
    nb = nb or client.post("/api/notebooks", json={"topic": "Overlap"}).json()["id"]
    m, seen = _model(rounds)
    with patch("engine.author.get_azure_client", lambda: m), patch("engine.author.generate_narration_audio", side_effect=_fake_tts), patch("engine.author.logger") as log:
        r = client.post(f"/api/notebooks/{nb}/chat", json={"message": message})
    caps = [c.kwargs["data"] for c in log.warn.call_args_list if c.args and c.args[0] == EngineEvent.OVERLAP_CAP_REACHED]
    return r, seen["results"], caps, nb


def test_the_same_rejection_gets_the_full_message_twice_then_only_the_hint_and_is_logged(api):
    base = _draw("base", 60, 120, 700, 350)
    bad = _draw("mic", 120, 410, 120, 80)
    r, results, caps, _ = turn(api, [[base], [bad], [bad], [bad], [bad]])
    assert r.status_code == 200
    rejections = [x["detail"] for x in results if x["status"] == "error"]
    assert len(rejections) == 4 and OVERLAP_MESSAGES_PER_ELEMENT == 2
    assert all("overlaps existing 'base'" in d for d in rejections[:2])
    assert all(d.startswith("Free region for 'mic'") and "overlaps" not in d for d in rejections[2:])
    assert [(c["element_id"], c["existing_id"], c["count"], c["cap"]) for c in caps] == [("mic", "base", 3, 2), ("mic", "base", 4, 2)]


def test_a_different_element_has_its_own_count_a_new_turn_starts_again_and_a_normal_drawing_is_untouched(api):
    base = _draw("base", 60, 120, 700, 350)
    r, results, caps, nb = turn(api, [[base], [_draw("mic", 120, 410, 120, 80)], [_draw("mic", 120, 410, 120, 80)], [_draw("speaker", 120, 410, 120, 80)], [_draw("ok", 800, 120, 200, 100)]])
    errors = [x for x in results if x["status"] == "error"]
    assert len(errors) == 3 and all("overlaps existing 'base'" in e["detail"] for e in errors) and caps == [], "three rejections, none past the cap: two for mic, one for speaker"
    assert results[-1]["status"] == "ok", "a drawing in free space is accepted"
    r2, results2, caps2, _ = turn(api, [[_draw("mic", 120, 410, 120, 80)]], nb=nb, message="again")
    assert "overlaps existing 'base'" in results2[0]["detail"] and caps2 == [], "a new turn starts again"
