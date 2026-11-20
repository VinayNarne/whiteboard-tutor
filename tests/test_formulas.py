"""Formula lines in notes ($...$, typeset by MathJax in Node) and the scene-only `transform` in the sanitiser."""
import re

import pytest

from engine.sanitiser import sanitize_svg
from engine.scene import LAYOUT_DIR, SceneError, build_notes

needs_mathjax = pytest.mark.skipif(not (LAYOUT_DIR / "node_modules" / "mathjax-full").exists(), reason="npm install in engine/scene_layout")


@needs_mathjax
def test_a_formula_line_is_typeset_and_survives_the_sanitiser():
    steps, box, _ = build_notes({"title": "Rayleigh", "lines": [
        {"text": "Short waves scatter **more**"},
        {"text": r"$\text{Scattering} \propto \frac{1}{\lambda^4}$", "say": "Scattering goes as one over wavelength to the fourth."}]}, 1, [])
    frag = steps[1][1]
    assert "<svg" in frag and 'class="ink"' in frag and "transform=" in frag and "•" not in frag    # typeset, themeable, no bullet
    assert steps[1][2].endswith("Scattering goes as one over wavelength to the fourth.") and "\\frac" not in steps[1][2]
    clean = sanitize_svg(frag, {"transform"})
    assert clean.count("transform=") == frag.count("transform=") and "<path" in clean                # the glyph positions are kept
    w = float(re.search(r'<svg x="[^"]+" y="[^"]+" width="([^"]+)"', frag).group(1))
    assert w <= box["w"]                                                                             # fits the notes lane


@needs_mathjax
@pytest.mark.parametrize("line, words", [({"text": "$\\frac{1}{$", "say": "x"}, "cannot be typeset"),
                                         ({"text": "$\\href{javascript:alert(1)}{x}$", "say": "x"}, "cannot be typeset"),
                                         ({"text": "$E = mc^2$"}, "needs `say`")])
def test_formula_mistakes_go_back_to_the_tutor(line, words):
    with pytest.raises(SceneError, match=re.escape(words)):
        build_notes({"lines": [line]}, 1, [])


def test_only_the_scene_path_keeps_transform_and_only_safe_values():
    svg = '<g id="a"><g transform="translate(10,20) scale(1,-1)"/><g transform="url(javascript:x)"/></g>'
    assert "transform" not in sanitize_svg(svg)                                                      # the raw-SVG path: as before
    out = sanitize_svg(svg, {"transform"})
    assert 'transform="translate(10,20) scale(1,-1)"' in out and "javascript" not in out
    assert "transform" not in sanitize_svg(svg)                                                      # the allowance does not leak to later calls


def test_inline_maths_reads_as_text_and_money_is_left_alone():
    from engine.scene import demath, plain
    assert demath("Set each factor to zero: $x-2=0$, $x-3=0$.") == "Set each factor to zero: x-2=0, x-3=0."   # live, in a note line
    assert demath(r"$x^2 - 5x + 6 = 0$ and $\frac{1}{\lambda^4}$ and $a \cdot b \pm c \le d$") == "x² - 5x + 6 = 0 and (1)/(λ⁴) and a · b ± c ≤ d"
    assert demath("It costs $5 and $10 today") == "It costs $5 and $10 today" and demath("$ 5 $") == "$ 5 $"
    assert plain("**$E=mc^2$** matters") == "E=mc² matters"                                    # what the voice reads
