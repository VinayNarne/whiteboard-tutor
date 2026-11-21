"""Paint recipes (LP_PAINT=1, proof): shapes keep their SVG fill as the fallback and carry a recipe the browser paints with p5.brush."""
import json
import re

from engine.graph import build_graph
from engine.sanitiser import sanitize_svg
from engine.scene import _node_svg, outline
from test_graph import SKY

NODE = {"id": "b1_lb", "shape": "box", "rows": [], "th": 0}
BOX = {"x": 10, "y": 20, "w": 100, "h": 40}


def recipes(svg):
    return [json.loads(m) for m in re.findall(r'<desc class="paint">([^<]*)</desc>', svg)]


def test_no_paint_unless_the_flag_is_on(monkeypatch):
    monkeypatch.delenv("LP_PAINT", raising=False)
    assert "paint" not in _node_svg(NODE, BOX, 1, "#E3F1EF", "#0F766E")
    steps, _, _ = build_graph({**SKY, "shade": {"from": 400, "to": 500}}, 1, [])
    assert "paint" not in steps[1][1] and 'fill-opacity="0.18"' in steps[1][1]               # shading works without paint too


def test_shapes_keep_their_fill_and_carry_a_seeded_recipe(monkeypatch):
    monkeypatch.setenv("LP_PAINT", "1")
    svg = _node_svg(NODE, BOX, 1, "#E3F1EF", "#0F766E")
    assert 'fill="#E3F1EF"' in svg and 'class="paint-fill"' in svg                          # the fallback until it is painted
    [r] = recipes(svg)
    assert r == {"kind": "wash", "points": [[10, 20], [110, 20], [110, 60], [10, 60]], "color": "#0F766E", "seed": r["seed"]}
    assert recipes(_node_svg(NODE, BOX, 1, "#E3F1EF", "#0F766E"))[0]["seed"] == r["seed"]  # same element, same seed: same paint on replay
    assert recipes(_node_svg({**NODE, "id": "b1_db"}, BOX, 1, "#E3F1EF", "#0F766E"))[0]["seed"] != r["seed"]
    assert not recipes(_node_svg({**NODE, "shape": "cylinder"}, BOX, 1, "#E3F1EF", "#0F766E"))  # shapes it cannot outline stay plain
    assert len(outline("circle", 0, 0, 10, 10)) == 28
    clean = sanitize_svg(f'<g id="b1_s1">{svg}</g>', {"transform"})
    assert recipes(clean) == [r]                                                             # the recipe survives the sanitiser


def test_chart_shading_is_painted_with_its_fallback(monkeypatch):
    monkeypatch.setenv("LP_PAINT", "1")
    steps, _, _ = build_graph({**SKY, "shade": {"from": 300, "to": 500}}, 1, [])            # clamped to the x range
    [r] = recipes(steps[1][1])
    xs = [p[0] for p in r["points"]]
    assert r["kind"] == "hatch" and min(xs) >= 644 and len(r["points"]) > 10
    assert 'fill-opacity="0.18" stroke="none" class="paint-fill"' in steps[1][1]
    assert 'stroke-width="1.5" class="paint-fill"' in steps[0][1]                           # the card gives way, or it hides the hatching
    plain, _, _ = build_graph(SKY, 1, [])
    assert "paint-fill" not in plain[0][1] and not recipes(plain[1][1])                      # no shade: no recipe, the card stays
    assert not recipes(build_graph({**SKY, "shade": {"from": 900, "to": 950}}, 1, [])[0][1][1])   # outside the range: nothing


def test_svg_textures_are_classes_only(monkeypatch):
    monkeypatch.setenv("LP_PAINT", "svg")
    svg = _node_svg(NODE, BOX, 1, "#E3F1EF", "#0F766E")
    assert 'class="wash"' in svg and 'fill="#E3F1EF"' in svg and not recipes(svg)          # the palette fill as it is (text contrast)
    steps, _, _ = build_graph({**SKY, "shade": {"from": 400, "to": 500}}, 1, [])
    assert 'class="hatch"' in steps[1][1] and not recipes(steps[1][1]) and "paint-fill" not in steps[0][1]
    assert "wash" not in _node_svg({**NODE, "shape": "cylinder"}, BOX, 1, "#E3F1EF", "#0F766E")
