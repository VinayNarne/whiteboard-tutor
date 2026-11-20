"""
tests/test_density.py
Verification plan §6 — "must catch / must pass" density check fixtures.

Two rules from the SAD (§3.5):
  Hard cap  = 25 named elements  → must REJECT
  Soft pass = 14 named elements  → must NOT block
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.validator import check_density, count_named_elements, HARD_ELEMENT_COUNT, SOFT_ELEMENT_COUNT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_svg_with_n_named_rects(n: int) -> str:
    """Produces an SVG string with n named <rect> elements."""
    rects = "\n".join(
        f'<rect id="el_{i}" x="{(i % 20) * 55}" y="{(i // 20) * 55}" width="50" height="50" fill="#abc"/>'
        for i in range(n)
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800">{rects}</svg>'


def svg_n_rects(n: int) -> str:
    """Single SVG fragment with n named rects (no outer <svg> wrapper)."""
    return "\n".join(
        f'<rect id="el_{i}" x="{(i % 20) * 55}" y="{(i // 20) * 55}" width="50" height="50" fill="#abc"/>'
        for i in range(n)
    )


# ---------------------------------------------------------------------------
# Element counting
# ---------------------------------------------------------------------------

def test_count_named_elements_basic():
    svg = '<svg><rect id="r1" /><circle id="c1" /><g id="g1"><text id="t1">hi</text></g><g>no-id</g></svg>'
    count = count_named_elements(svg)
    assert count == 4, f"Expected 4, got {count}"
    print(f"  PASS count_named_elements basic: {count} == 4")


def test_count_excludes_wrapper_g():
    svg = '<svg><g><rect id="r1" /></g></svg>'
    count = count_named_elements(svg)
    assert count == 1, f"Expected 1 (g without id not counted), got {count}"
    print(f"  PASS count_excludes_wrapper_g: {count} == 1")


# ---------------------------------------------------------------------------
# Hard cap MUST CATCH
# ---------------------------------------------------------------------------

def test_hard_cap_triggers_at_25():
    """
    A page with 25 named elements MUST trigger the hard cap.
    The 25th element is in new_fragment; existing_svg has 24.
    """
    existing = make_svg_with_n_named_rects(24)
    new_fragment = '<rect id="el_24" x="0" y="300" width="50" height="50" fill="#f00"/>'

    result = check_density(existing, new_fragment)
    assert result.hard_cap, (
        f"FAIL: hard cap should fire at element_count={result.element_count} "
        f"(threshold={HARD_ELEMENT_COUNT})"
    )
    assert result.element_count == 25, f"Expected element_count=25, got {result.element_count}"
    print(f"  PASS hard_cap_triggers_at_25: element_count={result.element_count}, hard_cap={result.hard_cap}")


def test_hard_cap_triggers_above_25():
    """A page with 30 elements must also hard-cap."""
    existing = make_svg_with_n_named_rects(29)
    new_fragment = '<rect id="el_29" x="0" y="400" width="50" height="50" fill="#f00"/>'
    result = check_density(existing, new_fragment)
    assert result.hard_cap, f"FAIL: expected hard_cap at {result.element_count} elements"
    print(f"  PASS hard_cap_triggers_above_25: element_count={result.element_count}")


# ---------------------------------------------------------------------------
# Hard cap MUST PASS
# ---------------------------------------------------------------------------

def test_hard_cap_does_not_trigger_at_14():
    """
    A page with 14 named elements MUST NOT be blocked.
    This is one below the soft signal threshold.
    """
    existing = make_svg_with_n_named_rects(13)
    new_fragment = '<rect id="el_13" x="0" y="200" width="50" height="50" fill="#0f0"/>'

    result = check_density(existing, new_fragment)
    assert not result.hard_cap, (
        f"FAIL: hard cap should NOT fire at element_count={result.element_count}"
    )
    assert result.element_count == 14, f"Expected 14, got {result.element_count}"
    print(f"  PASS hard_cap_does_not_trigger_at_14: element_count={result.element_count}, hard_cap={result.hard_cap}")


def test_hard_cap_does_not_trigger_at_24():
    """24 elements — exactly one below the hard cap (threshold=25). Must PASS without hard cap."""
    existing = make_svg_with_n_named_rects(23)
    new_fragment = '<rect id="el_23" x="0" y="350" width="50" height="50" fill="#0f0"/>'
    result = check_density(existing, new_fragment)
    assert not result.hard_cap, f"FAIL: hard cap should NOT fire at {result.element_count}"
    assert result.element_count == 24, f"Expected 24, got {result.element_count}"
    print(f"  PASS hard_cap_does_not_trigger_at_24: element_count={result.element_count}, hard_cap={result.hard_cap}")


# ---------------------------------------------------------------------------
# Soft signal
# ---------------------------------------------------------------------------

def test_soft_signal_triggers_at_15():
    """14 existing + 1 new = 15 → soft signal should fire."""
    existing = make_svg_with_n_named_rects(14)
    new_fragment = '<rect id="el_14" x="0" y="250" width="50" height="50" fill="#ff0"/>'
    result = check_density(existing, new_fragment)
    assert result.soft_signal, f"FAIL: soft signal should fire at {result.element_count}"
    assert not result.hard_cap, f"FAIL: hard cap should NOT fire at {result.element_count}"
    print(f"  PASS soft_signal_triggers_at_15: element_count={result.element_count}, soft={result.soft_signal}, hard={result.hard_cap}")


def test_soft_signal_does_not_trigger_at_14():
    """13 existing + 1 new = 14 → no soft signal, no hard cap."""
    existing = make_svg_with_n_named_rects(13)
    new_fragment = '<rect id="el_13" x="0" y="250" width="50" height="50" fill="#ff0"/>'
    result = check_density(existing, new_fragment)
    assert not result.hard_cap, f"FAIL: hard cap should not fire at {result.element_count}"
    print(f"  PASS soft_signal_does_not_trigger_at_14: element_count={result.element_count}, soft={result.soft_signal}")


# ---------------------------------------------------------------------------
# First element on blank page
# ---------------------------------------------------------------------------

def test_first_element_on_blank_page():
    """First draw on a blank page: current_svg=None, new_fragment=1 element. Must pass."""
    result = check_density(None, '<rect id="el_0" x="100" y="100" width="200" height="100" fill="#aaa"/>')
    assert not result.hard_cap, "FAIL: hard cap must not fire on first element"
    assert result.element_count == 1
    print(f"  PASS first_element_blank_page: element_count={result.element_count}")


# ---------------------------------------------------------------------------
# to_dict shape
# ---------------------------------------------------------------------------

def test_density_result_to_dict():
    result = check_density(None, '<rect id="r0" x="0" y="0" width="50" height="50"/>')
    d = result.to_dict()
    assert "hard_cap" in d
    assert "soft_signal" in d
    assert "element_count" in d
    assert "canvas_coverage" in d
    assert d["hard_cap_threshold"] == HARD_ELEMENT_COUNT
    assert d["soft_count_threshold"] == SOFT_ELEMENT_COUNT
    print(f"  PASS to_dict shape: {list(d.keys())}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_count_named_elements_basic,
        test_count_excludes_wrapper_g,
        test_hard_cap_triggers_at_25,
        test_hard_cap_triggers_above_25,
        test_hard_cap_does_not_trigger_at_14,
        test_hard_cap_does_not_trigger_at_24,
        test_soft_signal_triggers_at_15,
        test_soft_signal_does_not_trigger_at_14,
        test_first_element_on_blank_page,
        test_density_result_to_dict,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            print(f"\nRunning {t.__name__}...")
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
    print("All density check tests PASS [OK]")


# ---------------------------------------------------------------------------
# Overlap + coverage (code-side guardrails)
# ---------------------------------------------------------------------------

def _box(eid, x, y, w, h):
    return f'<g id="{eid}"><rect x="{x}" y="{y}" width="{w}" height="{h}"/><text x="{x+5}" y="{y+20}">t</text></g>'


def test_overlap_rejected_and_adjacent_allowed():
    from engine.validator import check_overlap
    existing = _box("a", 100, 100, 300, 200)
    assert check_overlap(existing, _box("b", 150, 150, 300, 200))["existing_id"] == "a"
    assert check_overlap(existing, _box("c", 420, 100, 300, 200)) is None


def test_coverage_soft_signal_without_many_elements():
    # two large elements, each under the frame limit (60% of the board), together covering well over 70%
    big = _box("big", 20, 20, 1100, 500)
    r = check_density(big, _box("two", 20, 530, 1100, 250))
    assert r.element_count < SOFT_ELEMENT_COUNT and r.soft_signal and r.coverage >= 0.7


def test_bounds_checks_children_without_ids():
    from engine.validator import validate_geometry
    off = '<g id="grp"><rect x="840" y="780" width="280" height="80"/><text x="900" y="890">t</text></g>'
    ok = '<g id="grp"><rect x="840" y="300" width="280" height="80"/><text x="900" y="340">t</text></g>'
    assert not validate_geometry(off)["valid"]
    assert validate_geometry(ok)["valid"]


def test_text_overlap_caught_and_adjacent_columns_pass():
    from engine.validator import validate_geometry
    bad = ('<g id="g"><rect x="100" y="100" width="400" height="200"/>'
           '<text x="300" y="150" text-anchor="middle" font-size="20">Heading Title</text>'
           '<text x="300" y="155" text-anchor="middle" font-size="12">caption under it</text></g>')
    ok = ('<g id="g"><rect x="100" y="100" width="500" height="200"/>'
          '<text x="120" y="150" font-size="14">7. Application Layer</text>'
          '<text x="580" y="150" text-anchor="end" font-size="14">HTTP, FTP, SMTP</text></g>')
    assert not validate_geometry(bad)["valid"]
    assert validate_geometry(ok)["valid"]
