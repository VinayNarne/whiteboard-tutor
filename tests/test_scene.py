"""
Scene mode (engine/scene.py, LP_SCENE_MODE=1): the tutor says what to show, the code lays it out on a lesson board.

- normalise(): slips the code can repair are repaired (unsafe ids, an arrow listed before its ends, parts never shown, a group shown
  after its members); slips it cannot repair go back to the tutor as one error.
- build_diagram(): every label fits its shape (measured with the board's own Inter), no geometry issues on a representative scene,
  one <g id="b{n}_s{k}"> per teaching step whose narration starts with its marker, and the sanitiser keeps every fragment whole.
- build_notes(): **bold** and ==highlight== become bold runs and highlighter bands, recap cards get checks, numbered lines no bullet.
- place_block(): blocks never overlap; a diagram sits beside the notes it follows; a wide block goes below everything.
- the chat API with the flag on: blocks pile up on one board (ids prefixed per block), a node id can be annotated in a later turn,
  start_new_page opens a new board, and with the flag off the tutor is not offered the board tools.
"""
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import Page, PageEvent
from engine.sanitiser import sanitize_svg
from engine.scene import (LAYOUT_DIR, LABEL, NOTE_LANE, WIDE_LANE, SceneError, board_blocks, build_diagram, build_notes, measure, normalise,
                          page_view, place_block, prefix_ids)

needs_elk = pytest.mark.skipif(not shutil.which("node") or not (LAYOUT_DIR / "node_modules" / "elkjs").exists()
                               or not (LAYOUT_DIR / "node_modules" / "@fontsource" / "caveat").exists(),
                               reason="needs Node and `npm install` in engine/scene_layout")


def diagram(scene, n=1, blocks=()):
    return build_diagram(prefix_ids(normalise(scene), f"b{n}_"), n, list(blocks))

SCENE = {
    "title": "How a busy website is built", "layout": "flow", "direction": "right",
    "groups": [{"id": "web", "label": "Web tier"}],
    "nodes": [
        {"id": "browser", "label": "Browser", "shape": "pill", "category": "client", "icon": "monitor"},
        {"id": "lb", "label": "Load Balancer", "detail": "Shares the requests", "shape": "box", "category": "infra", "tone": "accent"},
        {"id": "w1", "label": "Web Server 1", "shape": "box", "category": "server", "group": "web", "icon": "server"},
        {"id": "w2", "label": "Web Server 2", "shape": "box", "category": "server", "group": "web", "icon": "server"},
        {"id": "db", "label": "Database", "shape": "cylinder", "category": "storage", "icon": "database"},
        {"id": "ok", "label": "Healthy?", "shape": "diamond", "category": "infra"},
    ],
    "edges": [
        {"id": "e1", "from": "browser", "to": "lb", "label": "request"},
        {"id": "e2", "from": "lb", "to": "w1"}, {"id": "e3", "from": "lb", "to": "w2"},
        {"id": "e4", "from": "w1", "to": "db", "label": "query"}, {"id": "e5", "from": "w2", "to": "db", "label": "query", "dashed": True},
        {"id": "e6", "from": "lb", "to": "ok"},
    ],
    "steps": [
        {"say": "Your browser sends a request.", "show": ["browser", "e1"]},     # e1 listed before its end 'lb': must wait
        {"say": "The load balancer shares it out.", "show": ["lb", "w1", "w2", "e2", "e3"]},
        {"say": "Each server reads the database.", "show": ["e4", "e5", "db"]},  # 'ok' and 'e6' never shown: last step
    ],
}


# ---- normalise ---------------------------------------------------------------------------------------------------------------------

def test_repairs_what_the_code_can_repair():
    s = normalise(SCENE)
    w = s["when"]
    assert w["browser"] == 0 and w["e1"] == 1                 # the arrow waits until both ends are on the board
    assert w["ok"] == 2 and w["e6"] == 2                      # never listed: shown in the last step
    assert w["web"] == 1                                      # the group appears with its first member
    s2 = normalise({**SCENE, "nodes": [{**SCENE["nodes"][0], "id": "my browser!", "icon": "no-such-icon", "shape": "hexagon"}],
                    "edges": [], "groups": [], "steps": [{"say": "Hi.", "show": ["my browser!"]}]})
    n = s2["nodes"][0]
    assert n["id"] == "my_browser_" and "icon" not in n and n["shape"] == "box" and s2["when"]["my_browser_"] == 0
    s3 = normalise({**SCENE, "steps": [{"say": "x", "show": [{"id": "browser"}, 7, ["odd"]]}]})   # JSON slips in ids: repaired, not a crash
    long = normalise({**SCENE, "nodes": [{**SCENE["nodes"][0], "label": "x" * 5000}], "edges": [], "groups": [], "steps": [{"say": "y" * 9000, "show": []}]})
    assert len(long["nodes"][0]["label"]) == 160 and len(long["steps"][0]["say"]) == 600       # text is cut, not drawn or spoken at any length
    assert s3["when"]["browser"] == 0
    assert normalise({**SCENE, "nodes": [{**SCENE["nodes"][0], "id": "step_1"}], "edges": [], "groups": [],
                      "steps": [{"say": "x", "show": []}]})["nodes"][0]["id"] == "x_step_1"   # step ids belong to the code


@pytest.mark.parametrize("change, words", [
    ({"edges": [{"id": "e", "from": "browser", "to": "nowhere"}]}, "both ends must be node ids"),
    ({"nodes": SCENE["nodes"] + [{"id": "browser", "label": "Again", "shape": "box"}]}, "repeated"),
    ({"steps": [{"say": "  ", "show": []}]}, "needs 'say'"),
    ({"nodes": [{"id": f"n{i}", "label": "x", "shape": "box"} for i in range(17)], "edges": [], "groups": []}, "two scenes"),
    ({"nodes": [{"id": "a", "label": "A", "shape": "box", "group": "missing"}], "edges": [], "groups": []}, "not in groups"),
    ({"steps": [{"say": "x", "show": []}] * 13}, "at most 40 edges and 12 steps"),            # every step is a paid voice clip (security review)
])
def test_unrepairable_slips_go_back_to_the_tutor(change, words):
    with pytest.raises(SceneError, match=re.escape(words)):
        normalise({**SCENE, **change})


# ---- diagrams ---------------------------------------------------------------------------------------------------------------------

@needs_elk
def test_steps_fit_and_are_clean():
    steps, box, report = diagram(SCENE)
    assert report["issues"] == [], report["issues"]
    assert [sid for sid, _, _ in steps] == ["b1_s1", "b1_s2", "b1_s3"]
    for sid, frag, narration in steps:
        assert frag.startswith(f'<g id="{sid}">') and narration.startswith(f"[[MARK:{sid}]] ")
        assert len(sanitize_svg(frag)) >= 0.95 * len(frag)              # nothing of ours is stripped by the board's sanitiser
    assert 'id="b1_e1"' in steps[1][1] and 'id="b1_e1"' not in steps[0][1]     # the repaired step order is what is drawn
    assert all(f'class="cam cam-{box["x"]}-{box["y"]}-' in f for _, f, _ in steps)   # every step carries its block's box
    # every label line fits inside its node's box (same font, same measurement as the board)
    board = "".join(f for _, f, _ in steps)
    for nid in ("b1_lb", "b1_w1", "b1_w2"):          # rectangle nodes: every text line is narrower than the rectangle, with padding
        g = re.search(rf'<g id="{nid}">(.*?)</g>', board).group(1)
        width = float(re.search(r'<rect\b[^>]*\swidth="([\d.]+)"', g).group(1))   # \s: not stroke-width
        lines = re.findall(r'font-size="([\d.]+)" font-weight="(\d+)"[^>]*>([^<]+)<', g)
        assert lines
        for size, weight, txt in lines:
            assert measure(txt, float(size), int(weight)) <= width - 16, (nid, txt, width)
    assert report["label_px_framed"] >= LABEL[0] * 0.9          # what the learner sees once the camera frames the block


@needs_elk
def test_loop_is_drawn_as_a_ring_without_overlaps():
    loop = {"title": "Water cycle", "layout": "cycle", "edges": [], "groups": [],
            "nodes": [{"id": k, "label": k.title(), "detail": "A short line that wraps onto two lines here", "shape": "circle", "icon": "droplet"}
                      for k in ("collection", "evaporation", "condensation", "precipitation")],
            "steps": [{"say": "Round and round.", "show": []}]}
    loop["edges"] = [{"id": f"e{i}", "from": a["id"], "to": b["id"], "label": "then"} for i, (a, b) in enumerate(zip(loop["nodes"], loop["nodes"][1:] + loop["nodes"][:1]))]
    _, _, report = diagram(loop)
    assert report["issues"] == [], report["issues"]


@needs_elk
@pytest.mark.parametrize("n", [4, 6, 7])
def test_chains_of_any_length_lay_out(n):     # a 4-node chain asked in 3 rows used to leave an empty row and crash (code review)
    ids = [f"n{i}" for i in range(n)]
    chain = {"title": "", "layout": "flow", "groups": [], "nodes": [{"id": i, "label": i, "shape": "box"} for i in ids],
             "edges": [{"id": a + b, "from": a, "to": b} for a, b in zip(ids, ids[1:])], "steps": [{"say": "x", "show": []}]}
    assert diagram(chain)[2]["issues"] == []


@needs_elk
def test_long_chain_turns_back_on_itself_and_stays_readable():
    ids = ["a", "b", "c", "d", "e"]
    chain = {"title": "A chain", "layout": "flow", "groups": [],
             "nodes": [{"id": i, "label": f"Step {i.upper()}", "detail": "A supporting line of detail", "shape": "box", "icon": "server"} for i in ids],
             "edges": [{"id": f"{a}{b}", "from": a, "to": b, "label": "leads to"} for a, b in zip(ids, ids[1:])],
             "steps": [{"say": "x", "show": [i]} for i in ids]}
    _, _, report = diagram(chain)
    assert report["issues"] == [] and report["label_px_framed"] >= LABEL[0], report   # once framed by the camera; in one line it was ~11 px (live DNS lesson)


@needs_elk
def test_converging_arrows_stay_converging_and_a_loop_breaks_where_the_tutor_goes_back():
    from engine.scene import arrange
    node = lambda i: {"id": i, "label": i.title(), "shape": "box"}
    fan_in = {"title": "", "layout": "flow", "direction": "down", "groups": [], "nodes": [node(i) for i in ("buyers", "demand", "price", "supply", "sellers")],
              "edges": [{"id": "e1", "from": "buyers", "to": "demand"}, {"id": "e2", "from": "demand", "to": "price"},
                        {"id": "e3", "from": "sellers", "to": "supply"}, {"id": "e4", "from": "supply", "to": "price"}],
              "steps": [{"say": "x", "show": []}]}
    pos = arrange(normalise(fan_in))[1][0]["pos"]          # top-down: both sources on the first row, price below both (live lesson, 2026-11-05)
    assert pos["buyers"]["y"] == pos["sellers"]["y"] < pos["demand"]["y"] < pos["price"]["y"]
    loop = {**fan_in, "nodes": [node(i) for i in ("report", "fix", "test", "deploy")],
            "edges": [{"id": "a", "from": "report", "to": "fix"}, {"id": "b", "from": "fix", "to": "test"}, {"id": "c", "from": "test", "to": "fix", "label": "fail"},
                      {"id": "d", "from": "test", "to": "deploy", "label": "pass"}]}
    pos = arrange(normalise(loop))[1][0]["pos"]
    assert pos["report"]["y"] < pos["fix"]["y"] < pos["test"]["y"] < pos["deploy"]["y"]   # the fail edge is the one that goes back


# ---- notes, recap cards and placement ----------------------------------------------------------------------------------------------

@needs_elk
def test_notes_markup_becomes_bold_runs_and_highlighter_bands():
    steps, box, report = build_notes({"title": "DNS", "lines": [
        {"text": "**DNS** is the internet's ==phone book==", "say": "Think of DNS as a phone book."},
        {"text": "1. Check the cache"}, {"text": "an **unclosed marker ==stays as written"}]}, 4, [])
    frags = [f for _, f, _ in steps]
    assert [sid for sid, _, _ in steps] == ["b4_s1", "b4_s2", "b4_s3"] and report == {"kind": "notes", "lines": 3}
    assert '>DNS</text>' in frags[0] and 'font-weight="700"' in frags[0]                       # title and the bold term
    band = frags[0].index('fill="#FDE68A"')
    assert band < frags[0].index("phone book</text>")                                          # highlighter band first, so the text sits on top
    assert "•" in frags[0] and "•" not in frags[1]                                            # numbered lines carry no bullet
    assert "**unclosed" in frags[2] and "==stays" in frags[2]
    assert steps[0][2] == "[[MARK:b4_s1]] Think of DNS as a phone book." and steps[1][2] == "[[MARK:b4_s2]] 1. Check the cache"
    assert all(len(sanitize_svg(f)) >= 0.95 * len(f) for f in frags)
    recap, _, r2 = build_notes({"style": "recap", "lines": [{"text": "A"}, {"text": "B"}]}, 5, [])
    assert r2["kind"] == "recap" and ">Recap</text>" in recap[0][1] and recap[0][1].count("<svg") == 1 and "<rect" in recap[0][1]
    with pytest.raises(SceneError):
        build_notes({"lines": [{"text": f"line {i}"} for i in range(9)]}, 1, [])
    for empty in ("  ", "== ==", "**  **"):                                                  # markers alone are not a line (crashed: code review)
        with pytest.raises(SceneError):
            build_notes({"lines": [{"text": empty}]}, 1, [])
    glued = build_notes({"lines": [{"text": "**Supply**: what sellers ==offer==, today", "say": "**Supply** is ==this=="}]}, 1, [])[0][0]
    assert ">Supply:</text>" in glued[1] and glued[2] == "[[MARK:b1_s1]] Supply is this"     # no "Supply :", no markers in the voice


def test_blocks_are_placed_in_teaching_order_without_overlapping():
    notes = {"x": NOTE_LANE[0], "y": 32, "w": NOTE_LANE[1], "h": 170}
    assert place_block(NOTE_LANE, 100, []) == (NOTE_LANE[0], 32)
    x, y = place_block((580, 580), 300, [notes])
    assert (x, y) == (580, 32)                                                                 # a diagram sits beside the notes it follows
    diag = {"x": 580, "y": 32, "w": 580, "h": 300}
    assert place_block(NOTE_LANE, 100, [notes, diag]) == (NOTE_LANE[0], 32 + 170 + 48)        # next notes: below the notes...
    later = {"x": 40, "y": 250, "w": 500, "h": 100}
    assert place_block((580, 580), 50, [notes, diag, later])[1] == 32 + 300 + 48              # ...and never above the latest block
    assert place_block(WIDE_LANE, 100, [notes, diag, later]) == (40, 250 + 100 + 48)          # wide: below everything


def test_page_view_lists_ids_and_words_without_svg():
    svg = ('<g id="b1_s1"><desc class="cam cam-40-32-500-170"/><text>Blue &amp; violet</text></g><g id="b1_s2"><text>scatter most</text></g>'
           '<g id="b2_s1"><desc class="cam cam-580-32-580-300"/><g id="b2_db"></g></g>')
    assert page_view(svg) == {"blocks_on_board": 2, "already_written": {"b1": "Blue & violet scatter most", "b2": ""},
                              "annotatable_ids": ["b1_s1", "b1_s2", "b2_s1", "b2_db"]}             # the words, so it stops rewriting them
    assert page_view(None) == {"blocks_on_board": 0, "already_written": {}, "annotatable_ids": []}


# ---- through the chat API --------------------------------------------------------------------------------------------------------

def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def _model(rounds, final="Here it is."):
    out = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(content=None, tool_calls=[
        SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(r)]))], usage=None, model="fake")
           for r in rounds]
    out.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=final, tool_calls=None))], usage=None, model="fake"))
    it, calls = iter(out), []

    def create(**kw):
        calls.append(kw)
        return next(it)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def _chat(client, nb_id, m):
    with patch("engine.author.get_azure_client", lambda: m), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        return client.post(f"/api/notebooks/{nb_id}/chat", json={"message": "Teach me"})


def _draws(eng, nb_id):
    with Session(eng) as db:
        pages = db.exec(select(Page).where(Page.notebook_id == nb_id).order_by(Page.page_number)).all()
        return {p.id: [(e.kind, e.element_id) for e in db.exec(select(PageEvent).where(PageEvent.page_id == p.id).order_by(PageEvent.seq)).all()] for p in pages}


NOTES = {"title": "Why a load balancer", "lines": [{"text": "One server **cannot** take every request", "say": "One server alone cannot take them all."},
                                                  {"text": "The balancer ==shares the load=="}]}


def _tool_results(calls, i):
    return [json.loads(msg["content"]) for msg in calls[i]["messages"] if isinstance(msg, dict) and msg.get("role") == "tool"]


@needs_elk
def test_chat_turns_build_one_lesson_board(api, monkeypatch):
    client, eng = api
    monkeypatch.setenv("LP_SCENE_MODE", "1")
    nb_id = client.post("/api/notebooks", json={"topic": "Scenes"}).json()["id"]
    ring = ("annotate_element", {"annotation_id": "r1", "style": "circle", "target_element_id": "b2_lb", "narration": "[[MARK:r1]] This one."})
    m, calls = _model([[("write_notes", NOTES), ("draw_scene", SCENE)], [ring]])
    r = _chat(client, nb_id, m)
    assert r.status_code == 200, r.text
    names = {t["function"]["name"] for t in calls[0]["tools"]}
    assert {"write_notes", "draw_scene", "start_new_page"} <= names and "draw_new_element" not in names
    board = [p for p in _draws(eng, nb_id).values() if p]
    assert board == [[("draw", "b1_s1"), ("draw", "b1_s2"), ("draw", "b2_s1"), ("draw", "b2_s2"), ("draw", "b2_s3"), ("annotate", "r1")]]
    notes_result, diagram_result = _tool_results(calls, 1)[:2]   # the fake model keeps one growing message list: the round's first two
    assert notes_result["status"] == diagram_result["status"] == "ok" and "b2_lb" in diagram_result["detail"]
    sys_msg = calls[1]["messages"][1]["content"]
    assert "<svg" not in sys_msg and "<g " not in sys_msg                       # the tutor gets ids, not the board's SVG

    later = ("annotate_element", {"annotation_id": "r2", "style": "circle", "target_element_id": "b2_db", "narration": "[[MARK:r2]] Here."})
    recap = ("write_notes", {"style": "recap", "lines": [{"text": "Spread the load"}, {"text": "Cache the reads"}]})
    m_later, later_calls = _model([[later, recap]])                           # a later turn: point at a node, then add a recap below
    assert _chat(client, nb_id, m_later).status_code == 200
    assert [x["status"] for x in _tool_results(later_calls, 1)] == ["ok", "ok"]
    board = [p for p in _draws(eng, nb_id).values() if p]
    assert len(board) == 1 and board[0][-2:] == [("draw", "b3_s1"), ("draw", "b3_s2")]
    with Session(eng) as db:
        page = db.exec(select(Page).where(Page.notebook_id == nb_id)).first()
        blocks = board_blocks(page.current_svg)
    assert len(blocks) == 3 and all(not _overlap(a, b) for i, a in enumerate(blocks) for b in blocks[i + 1:])
    # the board's fonts, once, as faces with their own names and no blanket text rule (that rule turned the notes into Inter, live)
    assert page.current_svg.count("@font-face") == 4 and "'Caveat Board'" in page.current_svg and "'Inter'" not in page.current_svg
    assert not re.search(r"(^|[}\s])text\s*[,{]", page.current_svg.split("<style")[1].split("</style>")[0])

    m2, _ = _model([[("start_new_page", {"title": "Caching"}), ("draw_scene", {**SCENE, "title": "Second"})]])   # a new topic: a new board
    assert _chat(client, nb_id, m2).status_code == 200
    pages = [p for p in _draws(eng, nb_id).values() if p]
    assert len(pages) == 2 and [e for _, e in pages[1]] == ["b1_s1", "b1_s2", "b1_s3"]


def _overlap(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def test_scene_mode_off_keeps_the_raw_svg_tools(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv("LP_SCENE_MODE", "0")
    nb_id = client.post("/api/notebooks", json={"topic": "Off"}).json()["id"]
    m, calls = _model([], final="Just text.")
    assert _chat(client, nb_id, m).status_code == 200
    names = {t["function"]["name"] for t in calls[0]["tools"]}
    assert "draw_new_element" in names and not {"draw_scene", "write_notes"} & names


# ---- hostile and malformed tool arguments (security review) ------------------------------------------------------------------------

JUNK = [None, True, 3, 2.5, [], {}, ["x"], {"id": "a"}, "", "<script>alert(1)</script>", '"><img src=x onerror=alert(1)>', chr(0) + chr(27), "x" * 5000]


@needs_elk
@pytest.mark.parametrize("junk", JUNK, ids=range(len(JUNK)))
def test_any_json_in_any_field_is_repaired_or_refused_never_a_crash_or_markup(junk):
    scene = {"title": junk, "layout": junk, "direction": junk, "groups": junk, "edges": junk,
             "nodes": [{"id": "a", "label": "A", "shape": junk, "icon": junk, "category": junk, "tone": junk, "detail": junk, "sections": junk},
                       {"id": junk, "label": junk, "shape": "box", "group": junk}],
             "steps": [{"say": "x", "show": junk}, {"say": junk, "show": [junk]}]}
    notes = {"title": junk, "style": junk, "lines": [{"text": junk, "say": junk}, {"text": "ok", "say": junk}]}
    for build in (lambda: diagram(scene), lambda: build_notes(notes, 1, [])):
        try:
            steps = build()[0]
        except SceneError:
            continue
        for _, frag, _ in steps:
            tags = set(re.findall(r"<\s*([a-zA-Z:]+)", sanitize_svg(frag)))
            assert tags <= {"g", "desc", "rect", "ellipse", "polygon", "path", "text", "svg", "circle", "line", "polyline"}, tags


@needs_elk
def test_one_turn_cannot_order_unlimited_voice(api, monkeypatch):   # security review: each block is up to 12 paid voice clips
    client, eng = api
    monkeypatch.setenv("LP_SCENE_MODE", "1")
    nb_id = client.post("/api/notebooks", json={"topic": "Cap"}).json()["id"]
    words = "apple banana cherry damson elder fig grape".split()             # different blocks: identical ones are refused as repeats
    m, calls = _model([[("write_notes", {"lines": [{"text": f"{w} orchard"}]}) for w in words]])
    assert _chat(client, nb_id, m).status_code == 200
    statuses = [r["status"] for r in _tool_results(calls, 1)[:7]]
    assert statuses == ["ok"] * 6 + ["error"]



@needs_elk
def test_learner_can_point_at_a_node_inside_a_step(api, monkeypatch):   # pen circling used to map only to whole steps
    client, eng = api
    monkeypatch.setenv("LP_SCENE_MODE", "1")
    nb_id = client.post("/api/notebooks", json={"topic": "Point"}).json()["id"]
    m, _ = _model([[("draw_scene", SCENE)]])
    assert _chat(client, nb_id, m).status_code == 200
    m2, calls = _model([], final="That box shares the load.")
    with patch("engine.author.get_azure_client", lambda: m2), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb_id}/chat", json={"message": "What does this do?", "selected_element_ids": ["b1_lb", "b1_nope"],
                                                               "gesture_type": "circle", "match_score": 0.9})
    assert r.status_code == 200, r.text
    asked = calls[0]["messages"][-1]["content"]
    assert "'b1_lb' (Lb)" in asked and "b1_nope" not in asked                       # a real node is accepted (named without its block), an unknown id is not


def test_missing_parts_names_what_scene_mode_needs(monkeypatch):
    import engine.scene as scene
    assert scene.missing_parts() == [] or all(isinstance(m, str) for m in scene.missing_parts())
    monkeypatch.setattr(scene.shutil, "which", lambda _: None)
    assert "Node is not on PATH" in scene.missing_parts()


@needs_elk
def test_a_question_on_a_saved_lesson_board_is_answered_and_new_blocks_go_to_a_fresh_page(api, monkeypatch):
    client, eng = api
    monkeypatch.setenv("LP_SCENE_MODE", "1")
    nb_id = client.post("/api/notebooks", json={"topic": "Saved"}).json()["id"]
    m, _ = _model([[("write_notes", {"lines": [{"text": "first board"}]})]])
    assert _chat(client, nb_id, m).status_code == 200
    with Session(eng) as db:
        page_id = db.exec(select(Page).where(Page.notebook_id == nb_id)).first().id
    assert client.post(f"/api/notebooks/{nb_id}/pages/{page_id}/save").status_code == 200
    m2, _ = _model([[("write_notes", {"lines": [{"text": "the answer"}]})]], final="Here is how it works.")
    with patch("engine.author.get_azure_client", lambda: m2), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb_id}/chat", json={"message": "What did the first board mean?", "page_id": page_id})
    assert r.status_code == 200, r.text                                              # was a 400 (seen live while pointing at an old board)
    pages = [p for p in _draws(eng, nb_id).values() if p]
    assert pages == [[("draw", "b1_s1")], [("draw", "b1_s1")]]                       # the saved board is untouched; the answer has its own page
    monkeypatch.setenv("LP_SCENE_MODE", "0")
    assert client.post(f"/api/notebooks/{nb_id}/chat", json={"message": "x", "page_id": page_id}).status_code == 400   # raw-SVG mode: unchanged



@needs_elk
def test_asking_about_an_old_board_continues_the_current_one(api, monkeypatch):   # code review: it locked the current lesson
    client, eng = api
    monkeypatch.setenv("LP_SCENE_MODE", "1")
    nb_id = client.post("/api/notebooks", json={"topic": "Two boards"}).json()["id"]
    m, _ = _model([[("draw_scene", SCENE)]])
    assert _chat(client, nb_id, m).status_code == 200
    m2, _ = _model([[("start_new_page", {"title": "Caching"}), ("write_notes", {"lines": [{"text": "board two"}]})]])
    assert _chat(client, nb_id, m2).status_code == 200
    with Session(eng) as db:
        old, cur = db.exec(select(Page).where(Page.notebook_id == nb_id).order_by(Page.page_number)).all()
        old_id, cur_id = old.id, cur.id
    m3, calls = _model([[("write_notes", {"lines": [{"text": "more on the old idea"}]})]], final="Done.")
    with patch("engine.author.get_azure_client", lambda: m3), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb_id}/chat", json={"message": "Explain this", "page_id": old_id, "selected_element_ids": ["b1_lb"],
                                                               "gesture_type": "circle", "match_score": 0.9})
    assert r.status_code == 200 and r.json()["page_id"] == cur_id, r.text           # answered on the current board...
    with Session(eng) as db:
        pages = db.exec(select(Page).where(Page.notebook_id == nb_id).order_by(Page.page_number)).all()
    assert [p.status for p in pages] == ["saved", "active"]                          # ...which stays open; no third page
    assert [e for _, e in _draws(eng, nb_id)[cur_id]] == ["b1_s1", "b2_s1"]           # the answer's block continues it
    asked = next(msg["content"] for msg in calls[0]["messages"] if isinstance(msg, dict) and msg.get("role") == "user" and "Explain this" in msg["content"])
    assert "'b1_lb'" in asked                                                          # pointing at the old board still reaches the tutor


def test_each_block_is_stored_as_data_beside_its_picture(api, monkeypatch):
    """The board as data (GenSVG and tldraw study, 2026-11-20): a block's first step keeps what the tutor asked for and where code put
    it; its other steps keep none; the SVG stays the picture."""
    client, eng = api
    monkeypatch.setenv("LP_SCENE_MODE", "1")
    nb_id = client.post("/api/notebooks", json={"topic": "Load balancers"}).json()["id"]
    m, _ = _model([[("write_notes", NOTES), ("draw_scene", SCENE)]])
    assert _chat(client, nb_id, m).status_code == 200
    with Session(eng) as db:
        page = db.exec(select(Page).where(Page.notebook_id == nb_id)).one()
        events = db.exec(select(PageEvent).where(PageEvent.page_id == page.id).order_by(PageEvent.seq)).all()
    records = [e.block for e in events if e.block]
    assert [r["tool"] for r in records] == ["write_notes", "draw_scene"] and [r["n"] for r in records] == [1, 2]
    notes, diagram = records
    assert notes["args"]["lines"][0]["text"] == NOTES["lines"][0]["text"] and notes["steps"] == ["b1_s1", "b1_s2"]
    assert set(notes["box"]) == {"x", "y", "w", "h"} and events[0].block == notes             # on the first step only
    assert all(e.block is None for e in events if e.element_id not in ("b1_s1", records[1]["steps"][0])) and events[1].block is None
    assert {n["id"] for n in diagram["args"]["nodes"]} and all(i.startswith("b2_") for i in diagram["ids"])
    assert all(e.svg_fragment for e in events)                                                    # the picture is still stored


def test_a_formula_line_is_part_of_the_boards_text():
    """A formula is drawn as shapes, so the tutor's view of the board had a gap where it was (and could write it again)."""
    from engine.scene import build_notes, page_view
    steps, _, _ = build_notes({"title": "Energy", "lines": [{"text": "Mass is energy"}, {"text": "$E = mc^2$", "say": "E equals m c squared"}]}, 1, [])
    assert page_view("\n".join(f for _, f, _ in steps))["already_written"]["b1"].endswith("E = mc^2")
