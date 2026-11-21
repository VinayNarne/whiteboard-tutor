"""replace_block: the tutor changes a block already on the board, in place (engine/author.replace_block)."""
import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine import author
from engine.scene import CAM_RE, LAYOUT_DIR, board_blocks

needs_elk = pytest.mark.skipif(not shutil.which("node") or not (LAYOUT_DIR / "node_modules" / "elkjs").exists()
                               or not (LAYOUT_DIR / "node_modules" / "@fontsource" / "caveat").exists(), reason="needs Node and elk")


def notes(*lines):
    return {"title": "T", "lines": [{"text": t, "say": f"say {t}"} for t in lines]}


class Board:
    def __init__(self, monkeypatch):
        async def no_voice(*a, **k):
            return None, None, False
        monkeypatch.setattr(author, "synthesise_voice", no_voice)
        self.events, self.emitted = [], []

        self.turn = author.Turn(notebook_id="nb", page_id="pg", page_status="active", page_state={"element_count": 0}, learner_message="", existing_element_ids=set(),
                                emit_fn=self.emit, persist_fn=self.persist, new_page_fn=None, plan_page_fn=None, tool_log=[], lesson_plan="", lesson_path=None,
                                lesson_final=None, path=[], tools=[], current_svg=None)

    async def emit(self, kind, payload):
        self.emitted.append((kind, payload))

    async def persist(self, **f):
        self.events.append(f)
        if f["kind"] in ("draw", "modify"):
            self.turn.stored[f["element_id"]] = f["svg_fragment"]

    def run(self, tool, args):
        return json.loads(asyncio.run(author.run_tool(self.turn, tool, args)))

    def replace(self, n, tool, args, say="Fixed it."):
        return self.run("replace_block", {"block": f"b{n}", "tool": tool, "args": args, "say": say})


def test_same_height_correction_in_place(monkeypatch):
    b = Board(monkeypatch)
    b.run("write_notes", notes("DNS is a phone book", "It maps names to addresses"))
    b.run("write_notes", notes("A second block", "with two lines"))
    before = board_blocks(b.turn.current_svg)
    r = b.replace(1, "write_notes", notes("DNS is an address book", "It maps names to addresses"))
    assert r["status"] == "ok", r
    svg = b.turn.current_svg
    assert "address book" in svg.replace("\ufffd", "") or "address" in svg
    assert "phone" not in svg and "phone" not in "".join(x["svg_fragment"] for x in b.events if x["kind"] == "modify")
    assert board_blocks(svg) == before                      # same boxes: nothing moved, no new block number
    assert not any(e["kind"] == "draw" and e["element_id"].startswith("b3") for e in b.events)
    mods = [e for e in b.events if e["kind"] == "modify"]
    assert len(mods) == 1 and mods[0]["narration"].endswith("Fixed it.") and mods[0]["block"]["n"] == 1   # only the changed step speaks; the record is updated
    assert mods[0]["block"]["args"]["lines"][0]["text"].startswith("DNS is an address")


def test_taller_block_pushes_the_next_one_down(monkeypatch):
    b = Board(monkeypatch)
    b.run("write_notes", notes("one", "two"))
    b.run("write_notes", notes("below", "block"))
    old = board_blocks(b.turn.current_svg)
    assert b.replace(1, "write_notes", notes("one", "two", "three", "four", "five"))["status"] == "ok"
    new = board_blocks(b.turn.current_svg)
    assert len(new) == 2
    grow = new[0]["h"] - old[0]["h"]
    assert grow > 0 and new[1]["y"] == old[1]["y"] + grow and new[1]["y"] >= new[0]["y"] + new[0]["h"]
    assert [e for e in b.events if e["kind"] == "draw" and e["element_id"] in ("b1_s3", "b1_s4", "b1_s5")]   # new lines are drawn and narrated
    assert all(e["narration"] for e in b.events if e["kind"] == "draw" and e["element_id"].startswith("b1_s") and e["element_id"] > "b1_s2")


def test_refusals_leave_the_page_alone(monkeypatch):
    b = Board(monkeypatch)
    b.run("write_notes", notes("one", "two"))
    svg, n = b.turn.current_svg, len(b.events)
    for r in (b.replace(7, "write_notes", notes("x", "y")), b.replace(1, "draw_table", {"headers": ["a"], "rows": [["b"]]}),
              b.replace(1, "write_notes", {"lines": []}), b.replace(1, "write_notes", notes("one", "two"))):
        assert r["status"] == "error" and r["detail"]
    assert b.turn.current_svg == svg and len(b.events) == n


def test_replacing_is_not_a_repeat(monkeypatch):
    b = Board(monkeypatch)
    b.run("write_notes", notes("Routers forward packets between networks", "Each router reads the destination address"))
    assert b.run("write_notes", notes("Routers forward packets between networks", "Each router reads the destination address"))["status"] == "error"
    r = b.replace(1, "write_notes", notes("Routers forward packets between networks", "Each router reads the destination address carefully"))
    assert r["status"] == "ok", r


@needs_elk
def test_extending_a_diagram_keeps_old_steps(monkeypatch):
    b = Board(monkeypatch)
    nodes = [{"id": "a", "label": "Browser"}, {"id": "b", "label": "Resolver"}, {"id": "c", "label": "Root server"}]
    edges = [{"id": "x1", "from": "a", "to": "b"}, {"id": "x2", "from": "b", "to": "c"}]
    scene = {"nodes": nodes, "edges": edges, "steps": [{"say": "The browser asks.", "show": ["a", "b"]}, {"say": "Then the root.", "show": ["c"]}]}
    r = b.run("draw_scene", scene)
    assert r["status"] == "ok", r
    drawn = [e["element_id"] for e in b.events]
    longer = {"nodes": nodes + [{"id": "d", "label": "Cache"}, {"id": "e", "label": "Answer"}], "edges": edges + [{"id": "x3", "from": "b", "to": "d"}, {"id": "x4", "from": "d", "to": "e"}],
              "steps": scene["steps"] + [{"say": "The cache may know.", "show": ["d", "e"]}]}
    r = b.replace(1, "draw_scene", longer, say="Adding the cache.")
    assert r["status"] == "ok", r
    assert board_blocks(b.turn.current_svg) and len({m for m in CAM_RE.findall(b.turn.current_svg)}) <= 2
    assert "b1_s3" in [e["element_id"] for e in b.events if e["kind"] == "draw"] and "b1_s3" not in drawn
    assert b.turn.records[1]["args"]["nodes"][-1]["id"] == "e"
    assert sum(1 for e in b.events if e["kind"] == "modify" and e["narration"]) <= 1   # old steps stay silent; the new step speaks as a draw
    assert [e for e in b.events if e["element_id"] == "b1_s3"][0]["narration"]


def test_missing_say_still_narrates_first_changed_step(monkeypatch):
    b = Board(monkeypatch)
    b.run("write_notes", notes("DNS is a phone book", "It maps names to addresses"))
    assert b.replace(1, "write_notes", notes("DNS is an address book", "It maps names to addresses"), say="")["status"] == "ok"
    mods = [e for e in b.events if e["kind"] == "modify"]
    assert len(mods) == 1 and mods[0]["narration"] and "address book" in mods[0]["narration"]
