"""SVG textures (LP_PAINT=svg, proof, off by default). The p5.brush recipes (LP_PAINT=1) were archived 2026-11-21."""
import json
import re

from engine.graph import build_graph
from engine.scene import _node_svg
from test_graph import SKY

NODE = {"id": "b1_lb", "shape": "box", "rows": [], "th": 0}
BOX = {"x": 10, "y": 20, "w": 100, "h": 40}


def recipes(svg):
    return [json.loads(m) for m in re.findall(r'<desc class="paint">([^<]*)</desc>', svg)]


def test_no_texture_unless_the_flag_is_on(monkeypatch):
    monkeypatch.delenv("LP_PAINT", raising=False)
    assert "wash" not in _node_svg(NODE, BOX, 1, "#E3F1EF", "#0F766E")
    steps, _, _ = build_graph({**SKY, "shade": {"from": 400, "to": 500}}, 1, [])
    assert "hatch" not in steps[1][1] and 'fill-opacity="0.18"' in steps[1][1]               # shading works without paint too


def test_svg_textures_are_classes_only(monkeypatch):
    monkeypatch.setenv("LP_PAINT", "svg")
    svg = _node_svg(NODE, BOX, 1, "#E3F1EF", "#0F766E")
    assert 'class="wash"' in svg and 'fill="#E3F1EF"' in svg and not recipes(svg)          # the palette fill as it is (text contrast)
    steps, _, _ = build_graph({**SKY, "shade": {"from": 400, "to": 500}}, 1, [])
    assert 'class="hatch"' in steps[1][1] and not recipes(steps[1][1]) and "paint-fill" not in steps[0][1]
    assert "wash" not in _node_svg({**NODE, "shape": "cylinder"}, BOX, 1, "#E3F1EF", "#0F766E")
