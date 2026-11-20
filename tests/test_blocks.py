"""draw_table, draw_bar_chart and draw_venn (engine/blocks.py): the tutor gives the content, the code lays it out and reveals it in steps."""
import json
import re

import pytest
from unittest.mock import patch

from engine.blocks import build_bar_chart, build_table, build_venn
from engine.scene import DIAGRAM_LANE, WIDE_LANE, SceneError
from test_scene import _fake_tts, _model

TABLE = {"title": "Inner planets", "intro": "Let's compare them.", "columns": ["Planet", "Moons"],
         "rows": [{"cells": ["Mercury", "0"]}, {"cells": ["Earth", "1"], "say": "Earth has one moon."}]}
BARS = {"title": "Energy", "intro": "Here are the sources.", "categories": ["Coal", "Gas", "Wind"], "y_label": "Share (%)",
        "series": [{"label": "2025", "values": [33, 22, 9], "say": "In 2025."}]}
VENN = {"title": "Animals", "sets": [{"label": "Mammals", "say": "Mammals."}, {"label": "Live in water", "say": "Water."}],
        "regions": [{"in": [1], "items": ["Dog"]}, {"in": [1, 2], "items": ["Whale"]}, {"in": [2], "items": ["Shark"]}]}
texts = lambda frag: re.findall(r"<text[^>]*>([^<]*)</text>", frag)


def test_table_reveals_the_header_then_one_row_per_step():
    steps, box, report = build_table(TABLE, 2, [])
    assert [s[0] for s in steps] == ["b2_s1", "b2_s2", "b2_s3"] and report["lane"] == "diagram" and box["w"] == DIAGRAM_LANE[1]
    assert texts(steps[0][1]) == ["Inner planets", "Planet", "Moons"] and texts(steps[1][1]) == ["Mercury", "0"]
    assert steps[1][2].endswith("Mercury: Moons 0") and steps[2][2].endswith("Earth has one moon.")   # a row without say is still spoken
    long = "a fairly long description that will not fit in one line"
    wide = {**TABLE, "columns": ["A", "B", "C", "D"], "rows": [{"cells": [long, long, long, long]}]}
    s, b, r = build_table(wide, 1, [])
    assert r["lane"] == "wide" and b["w"] == WIDE_LANE[1] and len(texts(s[1][1])) > 4          # too wide: full width and wrapped
    assert "&lt;b&gt;" in build_table({**TABLE, "rows": [{"cells": ["<b>", "1"]}]}, 1, [])[0][1][1]


def test_bar_chart_scales_bars_and_reaches_a_round_tick_above_the_tallest():
    steps, box, report = build_bar_chart({**BARS, "series": [{"label": "x", "values": [39, 22, 9], "say": "s"}]}, 1, [])
    assert report == {"kind": "bars", "categories": 3, "series": 1} and [s[0] for s in steps] == ["b1_s1", "b1_s2"]
    assert "40" in texts(steps[0][1]) and texts(steps[1][1]) == ["39", "22", "9"]               # live: the axis stopped at 30 under a 39 bar
    heights = [float(h) for h in re.findall(r'<rect x="[^"]+" y="[^"]+" width="[^"]+" height="([^"]+)" fill', steps[1][1])]
    assert abs(heights[0] / heights[2] - 39 / 9) < 0.02                                            # to scale
    neg, _, _ = build_bar_chart({**BARS, "series": [{"label": "x", "values": [5, -3, 2], "say": "s"}]}, 1, [])
    assert "-3" in texts(neg[1][1]) and "-4" in texts(neg[0][1]) or "-5" in texts(neg[0][1])       # bars below zero get an axis below zero


def test_venn_puts_items_in_their_regions():
    steps, box, report = build_venn(VENN, 1, [])
    assert report == {"kind": "venn", "sets": 2, "regions": 3} and len(steps) == 5                 # 2 circles, then 3 regions
    x = lambda frag: float(re.search(r'<text x="([^"]+)"', frag).group(1))
    dog, whale, shark = (x(steps[k][1]) for k in (2, 3, 4))
    assert dog < whale < shark                                                                     # only-1, both, only-2 from left to right
    three = {**VENN, "sets": VENN["sets"] + [{"label": "Can fly", "say": "Fly."}], "regions": [{"in": [1, 3], "items": ["Bat"]}]}
    steps, _, report = build_venn(three, 1, [])
    assert report["sets"] == 3 and "Bat" in steps[-1][1] and steps[-1][2].endswith("In Mammals and Can fly: Bat")


@pytest.mark.parametrize("build, bad, words", [
    (build_table, {**TABLE, "columns": ["Only"]}, "2 to 6"),
    (build_table, {**TABLE, "rows": [{"cells": ["Mercury"]}]}, "exactly 2 cells"),
    (build_bar_chart, {**BARS, "series": [{"label": "x", "values": [1, 2], "say": "s"}]}, "exactly 3 numbers"),
    (build_bar_chart, {**BARS, "series": [{"label": "x", "values": [1, 2, 3]}]}, "needs `say`"),
    (build_bar_chart, {**BARS, "intro": ""}, "intro"),
    (build_venn, {**VENN, "sets": VENN["sets"][:1]}, "2 or 3"),
    (build_venn, {**VENN, "regions": [{"in": [4], "items": ["x"]}]}, "set numbers from 1 to 2"),
    (build_venn, {**VENN, "regions": [{"in": [1], "items": ["a"]}, {"in": [1], "items": ["b"]}]}, "one region"),
    (build_venn, {**VENN, "regions": [{"in": [1], "items": list("abcdefg")}]}, "1 to 6"),
])
def test_mistakes_go_back_to_the_tutor(build, bad, words):
    with pytest.raises(SceneError, match=re.escape(words)):
        build(bad, 1, [])


def test_a_table_only_turn_reaches_the_board_and_is_not_an_empty_reply(api, monkeypatch):
    client, eng = api
    monkeypatch.setenv("LP_SCENE_MODE", "1")
    nb_id = client.post("/api/notebooks", json={"topic": "Tables"}).json()["id"]
    m, calls = _model([[("draw_table", TABLE)]], final="")                                         # a table and no chat text
    with patch("engine.author.get_azure_client", lambda: m), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb_id}/chat", json={"message": "Compare the planets"})
    assert r.status_code == 200, r.text                                                            # draw_graph-only turns failed this way
    assert {"draw_table", "draw_bar_chart", "draw_venn"} <= {t["function"]["name"] for t in calls[0]["tools"]}
    result = [json.loads(x["content"]) for x in calls[-1]["messages"] if isinstance(x, dict) and x.get("role") == "tool"][0]
    assert result["status"] == "ok" and "Block 1 added" in result["detail"]
