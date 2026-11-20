"""
The lesson-board camera (frontend/src/utils/boardCamera.ts) and the caption words (narrationPlayback.captionWords), in headless Chromium
against the Vite dev server (fixtures from test_rough_renderer_markers.py). The block box is read from a fragment the server really built.
"""
import pytest

pytest.importorskip("playwright.sync_api")
from test_rough_renderer_markers import frontend_url, page  # noqa: E402,F401  (fixtures)

from engine.scene import build_notes  # noqa: E402

CAM = "/src/utils/boardCamera.ts"
PLAY = "/src/utils/narrationPlayback.ts"


def call(page, mod, fn, *args):
    return page.evaluate("async ([m, f, a]) => (await import(m))[f](...a)", [mod, fn, list(args)])


def test_block_box_from_a_server_fragment_and_framing(page):
    steps, box, _ = build_notes({"lines": [{"text": "**DNS** is the ==phone book=="}]}, 1, [])
    got = call(page, CAM, "camBox", steps[0][1])
    assert got == {"x": box["x"], "y": box["y"], "w": box["w"], "h": -(-box["h"] // 1)}
    assert call(page, CAM, "camBox", '<g id="a"><rect x="1" y="1" width="9" height="9"/></g>') is None   # raw-SVG pages: no camera
    f = call(page, CAM, "frame", {"x": 40, "y": 32, "w": 500, "h": 170})
    assert abs(f["w"] / f["h"] - 1.5) < 1e-9 and f["w"] >= 600                  # board's shape, never closer than 2x
    assert f["x"] <= 40 and f["x"] + f["w"] >= 540 and f["y"] <= 32 and f["y"] + f["h"] >= 202   # the block is inside the view
    tall = call(page, CAM, "frame", {"x": 580, "y": 0, "w": 580, "h": 900})
    assert tall["h"] >= 900 and abs(tall["w"] / tall["h"] - 1.5) < 1e-9


def test_overview_is_the_whole_board_or_nothing(page):
    frags = ['<desc class="cam cam-40-32-500-170"/>', '<desc class="cam cam-40-1250-1120-300"/>']
    ov = call(page, CAM, "overview", frags)
    assert ov["y"] <= 0 and ov["y"] + ov["h"] >= 1550 and ov["x"] <= 0 and ov["x"] + ov["w"] >= 1200
    assert call(page, CAM, "overview", ['<g id="x"/>']) is None
    mid = call(page, CAM, "between", {"x": 0, "y": 0, "w": 100, "h": 100}, {"x": 100, "y": 100, "w": 200, "h": 200}, 0.5)
    assert mid == {"x": 50, "y": 50, "w": 150, "h": 150}


def test_caption_words_follow_the_alignment(page):
    al = {"characters": list("Hi  there!"), "character_start_times_seconds": [0, .1, .2, .25, .3, .35, .4, .45, .5, .55]}
    assert call(page, PLAY, "captionWords", al) == [{"text": "Hi", "start": 0}, {"text": "there!", "start": 0.3}]
    assert call(page, PLAY, "captionWords", None) == []


def test_block_frame_leaves_room_for_the_caption(page):
    frag = '<g id="b1_s1"><desc class="cam cam-580-32-580-300"/></g>'
    room, close = page.evaluate("async (m) => { const c = await import(m); return [c.CAPTION_ROOM, c.CLOSE_ENOUGH]; }", CAM)
    f = call(page, CAM, "blockFrame", frag)
    assert f["y"] + f["h"] >= 32 + 300 + room - 1e-6 and f["w"] <= close           # caption room below; small enough to frame whole
    tall = call(page, CAM, "blockFrame", '<desc class="cam cam-580-32-580-700"/>')
    assert tall["w"] > close                                                       # a tall block is followed step by step
    assert call(page, CAM, "blockFrame", "<g/>") is None


def test_step_view_keeps_the_block_title_when_it_still_reads_close(page):
    block = {"x": 40, "y": 32, "w": 500, "h": 700}
    near = call(page, CAM, "stepView", block, [{"x": 74, "y": 150, "w": 300, "h": 40}, {"x": 74, "y": 195, "w": 300, "h": 40}])
    assert near["y"] <= 32 and near["w"] <= 900                                     # the title at the top is still in view
    far = call(page, CAM, "stepView", block, [{"x": 74, "y": 660, "w": 300, "h": 40}])
    assert far["y"] > 32 and far["y"] <= 660 and far["w"] <= 900                    # deep in a tall block: just the step, close up


def test_learner_zoom_keeps_the_point_under_the_pointer_and_stays_within_limits(page):
    v = {"x": 0, "y": 0, "w": 1200, "h": 800}
    z = call(page, CAM, "zoomAt", v, 2, 300, 200)                                   # 2x closer around (300, 200)
    assert z["w"] == 600 and z["h"] == 400 and (300 - z["x"]) / z["w"] == 300 / 1200 and (200 - z["y"]) / z["h"] == 200 / 800
    assert call(page, CAM, "zoomAt", v, 1000)["w"] == 150 and call(page, CAM, "zoomAt", v, 0.001)["w"] == 6000   # 8x in, 5x out at most
    assert call(page, CAM, "panBy", v, 50, -20) == {"x": 50, "y": -20, "w": 1200, "h": 800}
    assert call(page, CAM, "zoomOf", z) == 2


def test_small_boards_open_on_the_latest_block(page):
    frags = ['<g><desc class="cam cam-40-32-500-170"/></g>', '<g><desc class="cam cam-580-32-580-300"/></g>']
    big, small = call(page, CAM, "openingView", frags, 0.51), call(page, CAM, "openingView", frags, 0.24)   # 1440x900 desktop, 200% zoom (measured)
    assert big == call(page, CAM, "overview", frags)                                # a wide board opens on everything
    assert small == call(page, CAM, "blockFrame", frags[-1])                        # 200% zoom / phone: the latest block, readable
    assert call(page, CAM, "openingView", ["<g/>"], 0.24) is None


def test_pen_points_at_nodes_on_a_lesson_board_and_at_whole_elements_elsewhere(page):
    board = ('<g id="b1_s2"><desc class="cam cam-580-32-580-300"/>'
             '<g id="b1_e1"><path class="edge" d="M0,0 L9,9"/></g><g id="b1_lb"><rect/><text>Load Balancer</text><text>Shares requests</text></g></g>')
    raw = '<g id="server"><g id="server_label"><text>Server</text></g></g><g id=\'a"b\'><rect/></g>'
    parts = page.evaluate("""async ([m, board, raw]) => { const c = await import(m);
        const div = document.createElement('div'); div.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg">${board}${raw}</svg>`; document.body.appendChild(div);
        const out = ['b1_s2', 'server', 'a"b'].map(id => c.pointableParts(div, id)); div.remove(); return out; }""", [CAM, board, raw])
    assert parts[0] == [{"id": "b1_lb", "label": "Load Balancer Shares requests"}]                 # the node inside the step, by its text; the arrow is not offered
    assert parts[1] == [{"id": "server"}]                                            # raw-SVG drawings stay whole (code review: regression)
    assert parts[2] == [{"id": 'a"b'}]                                               # an id with a quote does not throw
