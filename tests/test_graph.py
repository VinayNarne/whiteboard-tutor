"""draw_graph (engine/graph.py): formulas are evaluated from a whitelist, never run; the values on the chart are computed exactly."""
import re

import pytest

from engine.graph import build_graph, compile_formula, fmt, nice_ticks
from engine.scene import DIAGRAM_LANE, SceneError

SKY = {"title": "Scattering vs wavelength", "intro": "Here is how strongly each colour scatters.",
       "x": {"label": "Wavelength (nm)", "min": 380, "max": 750}, "y": {"label": "Scattering (relative to red)"},
       "series": [{"label": "Rayleigh", "formula": "(700/x)^4", "say": "Shorter waves scatter far more."}],
       "marks": [{"x": 400, "label": "violet"}, {"x": 450, "label": "blue"}, {"x": 700, "label": "red"}],
       "marks_say": "Violet scatters about nine times more than red."}


def test_values_are_computed_exactly_and_shown():
    steps, box, report = build_graph(SKY, 2, [])
    assert [s[0] for s in steps] == ["b2_s1", "b2_s2", "b2_s3"]                   # axes, the curve, the marked points
    assert report["marks"] == [("400", "9.38"), ("450", "5.86"), ("700", "1")]  # (700/400)^4 = 9.379, (700/450)^4 = 5.856
    assert "violet (400, 9.38)" in steps[2][1] and "blue (450, 5.86)" in steps[2][1]
    assert box["x"] == DIAGRAM_LANE[0] and box["w"] == DIAGRAM_LANE[1]
    assert steps[0][2].endswith("Here is how strongly each colour scatters.") and "Wavelength (nm)" in steps[0][1]


@pytest.mark.parametrize("bad", ["__import__('os').system('x')", "x.real", "(lambda: 1)()", "open('f')", "[x]", "x if x else 1",
                                 "2**1000", "x; 1", "", "sin(x, 2)"])
def test_formulas_outside_the_whitelist_go_back_to_the_tutor(bad):
    with pytest.raises(SceneError):
        compile_formula(bad)


def test_formula_maths_and_gaps():
    f = compile_formula("1000*1.05^x")
    assert abs(f(10) - 1628.894626777442) < 1e-9                                  # compound interest, exact
    assert compile_formula("sqrt(x)")(-1) is None and compile_formula("1/x")(0) is None   # outside the domain: a gap, not a crash
    assert compile_formula("exp(x)")(10000) is None and compile_formula("x^x")(500) is None   # overflow: a gap
    assert abs(compile_formula("2*pi*sin(x) + e")(0) - 2.718281828) < 1e-6
    steps, _, _ = build_graph({**SKY, "x": {"label": "x", "min": -2, "max": 2}, "marks": [], "y": {"min": -5, "max": 5},
                               "series": [{"label": "1/x", "formula": "1/x", "say": "s"}]}, 1, [])
    assert steps[1][1].count("<polyline") == 2                                   # broken at x = 0, not joined across it


def test_data_points_ticks_and_mistakes():
    data = {**SKY, "marks": [{"x": 3}], "x": {"label": "Year", "min": 0, "max": 4},
            "series": [{"label": "Sales", "points": [[2, 30], [0, 10], [4, 50], [1, "bad"], [3, 45]], "say": "Sales grew."}]}
    steps, _, report = build_graph(data, 1, [])
    assert steps[1][1].count("<circle") == 4 and report["marks"] == [("3", "45")]  # the bad point dropped, sorted by x, mark on the data
    assert nice_ticks(380, 750) == [400, 500, 600, 700] and nice_ticks(0, 1) == [0, 0.2, 0.4, 0.6, 0.8, 1]
    assert fmt(1628.89) == "1629" and fmt(12500) == "12.5k" and fmt(0.25) == "0.25"
    for bad, words in [({**SKY, "x": {"label": "x", "min": 5, "max": 1}}, "x.min < x.max"), ({**SKY, "intro": ""}, "intro"),
                       ({**SKY, "series": []}, "one to 4 series"), ({**SKY, "marks_say": ""}, "marks_say"),
                       ({**SKY, "marks": [{"x": 9000}]}, "between"), ({**SKY, "series": [{"label": "s", "formula": "sqrt(0-x)", "say": "s"}]}, "no value")]:
        with pytest.raises(SceneError, match=re.escape(words)):
            build_graph(bad, 1, [])


def test_labels_are_escaped():
    steps, _, _ = build_graph({**SKY, "title": "<script>alert(1)</script>", "marks": []}, 1, [])
    assert "<script>" not in steps[0][1] and "&lt;script&gt;" in steps[0][1]


def test_close_marks_do_not_overlap_and_titles_read_as_text():
    quad = {"title": "Graph of $y = x^2 - 5x + 6$", "intro": "The curve.", "x": {"label": "x", "min": 0, "max": 5},
            "series": [{"label": "$y = x^2 - 5x + 6$", "formula": "x^2 - 5*x + 6", "say": "s"}],
            "marks": [{"x": 2, "label": "x = 2"}, {"x": 3, "label": "x = 3"}], "marks_say": "The roots."}
    steps, _, report = build_graph(quad, 1, [])
    assert report["marks"] == [("2", "0"), ("3", "0")] and "Graph of y = x² - 5x + 6" in steps[0][1] and "$" not in steps[0][1]
    ys = [float(y) for y in re.findall(r'<text x="[^"]+" y="([^"]+)"[^>]*>x = [23]', steps[2][1])]
    assert len(ys) == 2 and abs(ys[0] - ys[1]) >= 18                               # live: the two labels were drawn on top of each other


def test_calculate_gives_exact_values_and_refuses_code():
    from engine.graph import calculate
    r = calculate(["1000*1.07^30", "(1000*1.07^30) - (1000*1.07^20)", "1/0", "__import__('os')"])
    assert r["status"] == "ok" and "1000*1.07^30 = 7,612.26" in r["detail"] and "= 3,742.57" in r["detail"]   # live: invented $4,000 vs $1,600
    assert "1/0 = undefined" in r["detail"] and "not allowed" in r["detail"]
    assert "= 1,903,063.76" in calculate(["1903063.76"])["detail"] and "= 0.0025" in calculate(["1/400"])["detail"]   # no 1.90306e+06
    assert calculate("1+1")["status"] == "error" and calculate([])["status"] == "error"
