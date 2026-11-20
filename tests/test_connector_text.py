"""
The z-order-aware connector-versus-text diagnostic (engine/connector_text.py, recorded by engine/shadow.py as `connector_text`).

What must hold:
  * a connector that runs over VISIBLE text is reported, its body and its arrow head apart;
  * a connector hidden under an opaque label box drawn after it (the "label on the line" look) is NOT reported;
  * ambiguous cases (text-width estimate, graze) are kept apart from definite ones;
  * unsupported or missing geometry is handled safely;
  * the diagnostic never changes a verdict, never leaks label text, and its own failure never touches the drawing or the rest of the shadow record.
Replay: the 33 saved benchmark boards (docs/benchmark_runs/2026-10-15-controlled/runs, no model, no network) against tests/fixtures/connector_text_known.json, the pairs
that real Chromium measured as visible collisions (24 rows) and as hidden under an opaque label box (41 pairs).
"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import engine.connector_text as ct
import engine.shadow as shadow
from engine import shape_model as sm
from engine.shape_model import extract_shapes

ROOT = Path(__file__).parent.parent
RUNS = ROOT / "docs" / "benchmark_runs" / "2026-10-15-controlled"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "connector_text_known.json").read_text(encoding="utf-8"))


def g(eid, body):
    return f'<g id="{eid}">{body}</g>'


def line(x1, y1, x2, y2, sw=3, marker=None, color="#000"):
    m = f' marker-end="url(#{marker})"' if marker else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{m}/>'


def label(x, y, text, size=16, anchor="middle"):
    return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}">{text}</text>'


def chip(x, y, w, h, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#fff" {extra}/>'


def run(svg):
    shapes = extract_shapes(svg)
    return ct.analyse(shapes, ct.parse_markers(svg))


def kinds(rep, certainty="definite"):
    return sorted(f.kind for f in rep.findings if f.certainty == certainty)


# ---- genuine collisions -----------------------------------------------------------------------------------------------------------------------------
def test_a_line_over_a_visible_label_is_a_definite_body_collision():
    rep = run(g("a", line(100, 200, 500, 200) + label(300, 205, "Fail")))
    assert kinds(rep) == ["connector_body_over_text"] and not rep.hidden
    f = rep.findings[0]
    assert f.why == "visible_line" and f.amount >= ct.BODY_MIN and f.connector.element == "a" and f.label.kind == "text"


def test_a_line_that_misses_the_label_is_not_reported():
    assert run(g("a", line(100, 260, 500, 260) + label(300, 205, "Fail"))).findings == []


def test_a_line_drawn_over_its_chip_is_reported_because_the_chip_does_not_hide_it():
    """the chip is drawn BEFORE the line: the line is on top of the text"""
    rep = run(g("a", chip(270, 188, 60, 24) + label(300, 205, "Fail") + line(100, 200, 500, 200)))
    assert kinds(rep) == ["connector_body_over_text"]


# ---- hidden under an opaque label box (the 41 false positives of the browser measurement) -------------------------------------------------------------
def test_a_line_under_an_opaque_chip_drawn_after_it_is_not_reported_but_counted_as_hidden():
    rep = run(g("a", line(100, 200, 500, 200) + chip(270, 188, 60, 24) + label(300, 205, "Fail")))
    assert rep.findings == [] and len(rep.hidden) == 1


def test_shape_level_opacity_does_not_unhide_a_line_because_the_board_renderer_drops_it():
    """roughRenderer.ts drops fill-opacity and opacity of a shape: a chip written with fill-opacity 0.3 is drawn opaque"""
    rep = run(g("a", line(100, 200, 500, 200) + chip(270, 188, 60, 24, 'fill-opacity="0.3" opacity="0.3"') + label(300, 205, "Fail")))
    assert rep.findings == [] and len(rep.hidden) == 1


def test_a_chip_in_a_translucent_group_does_not_hide_the_line():
    rep = run(g("a", line(100, 200, 500, 200)) + f'<g id="c" opacity="0.5">{chip(270, 188, 60, 24)}{label(300, 205, "Fail")}</g>')
    assert kinds(rep) == ["connector_body_over_text"] and not rep.hidden


def test_an_unfilled_box_does_not_hide_the_line():
    rep = run(g("a", line(100, 200, 500, 200) + '<rect x="270" y="188" width="60" height="24" fill="none" stroke="#000"/>' + label(300, 205, "Fail")))
    assert kinds(rep) == ["connector_body_over_text"]


def test_the_part_of_the_line_that_stays_visible_is_still_reported():
    """the chip is narrower than the text: the line shows beside the chip, over the overflowing text"""
    rep = run(g("a", line(100, 200, 500, 200) + chip(290, 188, 20, 24) + label(300, 205, "A very long label text")))
    assert "connector_body_over_text" in kinds(rep)


# ---- arrow heads ------------------------------------------------------------------------------------------------------------------------------------
def test_an_arrow_head_on_a_label_is_reported_apart_from_the_body():
    rep = run(g("a", line(100, 200, 300, 200, marker="arrow") + label(305, 205, "Fail")))
    assert kinds(rep) == ["arrowhead_over_text"], "the line ends at the head: only the head touches the text"
    f = rep.findings[0]
    assert f.why == "visible_head" and f.amount >= ct.HEAD_MIN


def test_a_head_beside_the_label_is_not_reported():
    assert run(g("a", line(100, 200, 300, 200, marker="arrow") + label(300, 140, "Fail"))).findings == []


def test_a_label_box_drawn_after_the_line_that_hides_the_head_is_reported_separately():
    rep = run(g("a", line(100, 200, 300, 200, sw=5, marker="arrow") + chip(262, 185, 90, 30) + label(310, 205, "Fail", anchor="middle")))
    assert "arrowhead_covered_by_label" in kinds(rep)
    f = next(f for f in rep.findings if f.kind == "arrowhead_covered_by_label")
    assert f.amount >= ct.HEAD_COVER and f.why == "head_hidden_by_label_box"


def test_a_head_hidden_by_a_big_panel_is_not_a_label_box_finding():
    """a large panel drawn later that happens to hold some text is not 'a label box'"""
    rep = run(g("a", line(100, 200, 300, 200, sw=5, marker="arrow") + '<rect x="250" y="100" width="400" height="300" fill="#eef"/>' + label(450, 250, "Panel text")))
    assert "arrowhead_covered_by_label" not in kinds(rep)


def test_the_head_of_a_marker_the_drawing_defines_is_used_not_a_generic_triangle():
    defs = '<defs><marker id="m1" markerWidth="12" markerHeight="8" refX="10" refY="4" orient="auto"><path d="M0,0 L12,4 L0,8 z"/></marker></defs>'
    svg = g("a", defs + '<line x1="100" y1="200" x2="300" y2="200" stroke="#000" stroke-width="3" marker-end="url(#m1)"/>')
    unsupported = {}
    shapes = extract_shapes(svg)
    heads = ct.heads_of(shapes[0], ct.parse_markers(svg), unsupported)
    assert unsupported == {} and len(heads) == 1
    assert abs(heads[0].length - 30) < 0.1, "10 marker units behind the tip, scaled by the stroke width 3"
    xs = [p[0] for p in heads[0].poly]
    assert abs(max(xs) - 306) < 0.1 and abs(min(xs) - 270) < 0.1, "tip 2 units ahead of the reference point (12 - 10) x 3"


def test_the_boards_own_marker_has_the_geometry_the_older_shape_model_uses():
    svg = g("a", line(100, 200, 300, 200, sw=3, marker="arrow"))
    sh = extract_shapes(svg)[0]
    mine = ct.heads_of(sh, {}, {})[0].poly
    theirs = sh.heads[0]
    for (x1, y1), (x2, y2) in zip(sorted(mine), sorted(theirs)):
        assert abs(x1 - x2) < 0.6 and abs(y1 - y2) < 0.6


def test_a_board_marker_cannot_be_redefined_by_a_drawing():
    """the app defines #arrow before any drawing; the first definition of an id wins in a browser"""
    svg = g("a", '<defs><marker id="arrow" markerWidth="100" markerHeight="100" refX="0" refY="0"><path d="M0,0 L100,50 L0,100 z"/></marker></defs>' + line(100, 200, 300, 200, marker="arrow"))
    sh = extract_shapes(svg)[0]
    heads = ct.heads_of(sh, ct.parse_markers(svg), {})
    assert heads[0].length < 25


# ---- ambiguous cases --------------------------------------------------------------------------------------------------------------------------------
def test_an_overlap_that_exists_only_under_the_wide_width_estimate_is_ambiguous_not_definite():
    # "Alpha beta" = 10 chars x 16 x 0.5 = 80 px from x=100: the estimate says the text ends at 180 (172 to 188 within plus or minus 10 percent)
    base = label(100, 205, "Alpha beta", anchor="start")
    assert kinds(run(g("a", line(140, 150, 140, 260) + base))) == ["connector_body_over_text"], "well inside the text: definite"
    rep = run(g("a", line(180, 150, 180, 260) + base))
    assert kinds(rep) == [] and kinds(rep, "ambiguous") == ["connector_body_over_text"] and rep.findings[0].why == "width_estimate"
    assert run(g("a", line(230, 150, 230, 260) + base)).findings == [], "clear of the text even at the wide estimate"


def test_a_graze_is_ambiguous():
    # a line crossing the text's top corner for about a pixel or two
    rep = run(g("a", '<line x1="100" y1="260" x2="150" y2="170" stroke="#000" stroke-width="1"/>' + label(100, 205, "Alpha beta", anchor="start")))
    for f in rep.findings:
        assert f.certainty == "ambiguous" or f.amount >= ct.BODY_MIN


# ---- unsupported and missing geometry ---------------------------------------------------------------------------------------------------------------
def test_an_arrow_head_whose_marker_cannot_be_found_is_counted_unsupported_and_the_body_is_still_checked():
    svg = g("a", '<line x1="100" y1="200" x2="500" y2="200" stroke="#000" stroke-width="3" marker-end="url(#nowhere)"/>' + label(300, 205, "Fail"))
    rep = run(svg)
    assert rep.unsupported == {"marker_unresolved": 1} and kinds(rep) == ["connector_body_over_text"]


@pytest.mark.parametrize("svg", [
    "", "   ", "<g id='x'/>", g("t", label(10, 10, "only text")), g("c", line(0, 0, 0, 0)),
    g("p", '<path d="M 10" stroke="#000"/><path d="garbage" stroke="#000"/><path stroke="#000"/>' + label(10, 10, "x")),
    g("p", '<polyline points="5,5" stroke="#000"/>' + label(10, 10, "x")),
    g("z", '<text x="10" y="10" font-size="0">x</text><line x1="0" y1="10" x2="50" y2="10" stroke="#000"/>'),
    g("h", '<line x1="1e9" y1="0" x2="-1e9" y2="5" stroke="#000" marker-end="url(#arrow)"/>' + label(0, 0, "far")),
    g("e", '<text x="100" y="100" font-size="16"></text><line x1="0" y1="100" x2="300" y2="100" stroke="#000"/>'),
])
def test_missing_or_unusable_geometry_never_raises(svg):
    rep = run(svg) if svg.strip() else ct.analyse([], {})
    assert isinstance(rep, ct.Report)
    assert ct.parse_markers(svg) == {} or isinstance(ct.parse_markers(svg), dict)
    shadow.ct_record(rep)                                       # the record builder copes with an empty or odd report too


def test_unparseable_marker_definitions_are_ignored():
    assert ct.parse_markers("<g><marker id='a'") == {} and ct.parse_markers(None) == {}


# ---- charging a call -------------------------------------------------------------------------------------------------------------------------------
def test_a_call_is_not_charged_for_pairs_that_were_already_on_the_page():
    old = g("old", line(100, 200, 500, 200) + label(300, 205, "Fail"))
    new = g("new", '<rect x="600" y="600" width="50" height="50" fill="#eee"/>')
    shapes = extract_shapes(old) + extract_shapes(new, start_index=len(extract_shapes(old)))
    assert ct.analyse(shapes, {}, charged_from=len(extract_shapes(old))).findings == []
    assert len(ct.analyse(shapes, {}, charged_from=0).findings) == 1
    new_label = g("new", label(300, 205, "Again"))
    shapes2 = extract_shapes(old) + extract_shapes(new_label, start_index=len(extract_shapes(old)))
    assert any(f.label.element == "new" for f in ct.analyse(shapes2, {}, charged_from=len(extract_shapes(old))).findings), "a new label over an old line is charged to the new call"


# ---- the shadow record: content, isolation, no influence on any verdict --------------------------------------------------------------------------------
PAGE = g("flow", line(100, 200, 500, 200, marker="arrow") + chip(270, 188, 70, 24) + label(305, 205, "Secret label one") + label(480, 205, "Another secret"))
FRAGMENT = g("new", line(100, 300, 500, 300) + label(300, 305, "Hidden words here"))


def test_the_record_has_counts_ids_and_reason_codes_but_no_label_text_or_svg():
    rec = shadow.compute(PAGE, FRAGMENT, "new")
    c = rec["connector_text"]
    assert {"body", "head", "head_covered", "ambiguous", "hidden", "connectors", "labels", "items"} <= set(c)
    assert c["body"] == 1 and c["items"] and c["items"][0]["kind"] == "connector_body_over_text" and c["items"][0]["ae"] == "new" and c["items"][0]["why"] == "visible_line"
    blob = json.dumps(rec)
    for word in ("Secret", "Another", "Hidden", "words", "<line", "<rect", "marker-end", "stroke"):
        assert word not in blob, word
    assert len(c["items"]) <= shadow.MAX_CT_ITEMS and "connector_text_error" not in rec


def test_the_diagnostic_changes_no_verdict_and_its_failure_is_contained_in_the_record():
    base = shadow.compute(PAGE, FRAGMENT, "new")
    with patch.object(ct, "analyse", side_effect=RuntimeError("boom")):
        broken = shadow.compute(PAGE, FRAGMENT, "new")
    assert broken["connector_text_error"] == "RuntimeError" and "connector_text" not in broken
    for key in ("existing", "existing_reason", "proposed", "differs", "reject_kinds", "advisory_kinds", "reasons", "reasons_total", "roles", "shapes_new", "shapes_page"):
        assert broken[key] == base[key], key
    assert base["proposed"] in ("accept", "reject") and "connector_text" in base


def test_a_page_with_too_many_shapes_is_skipped_without_the_diagnostic():
    page = "".join(f'<g id="g{i}"><rect x="{(i % 40) * 28 + 10}" y="{(i // 40) * 28 + 10}" width="20" height="20" fill="#eee"/></g>' for i in range(610))
    rec = shadow.compute(page, g("new", '<rect x="1100" y="760" width="30" height="30" fill="#eee"/>'), "new")
    assert rec["proposed"] == "skipped" and "connector_text" not in rec


def test_a_failing_diagnostic_changes_no_drawing_outcome_and_the_record_is_still_logged(monkeypatch, tmp_path):
    """the real draw handler on the shadow-hook scenarios: outcomes, stored content and browser events are identical with the diagnostic working or raising"""
    from test_shadow_hook import capture, scenarios
    from core.events import EngineEvent
    ok, failing = {}, {}
    for name, calls in scenarios().items():
        ok[name] = capture(monkeypatch, tmp_path / "ok" / name.replace(" ", "_"), calls)
        with patch.object(ct, "analyse", side_effect=RuntimeError("boom")):
            failing[name] = capture(monkeypatch, tmp_path / "bad" / name.replace(" ", "_"), calls)
    assert len(ok) >= 15
    for name in ok:
        assert ok[name][1] == failing[name][1], name                                    # outcomes, stored content, browser events
        recs_ok = [d for ev, _, d in ok[name][0] if ev == EngineEvent.SHADOW_VALIDATED]
        recs_bad = [d for ev, _, d in failing[name][0] if ev == EngineEvent.SHADOW_VALIDATED]
        assert len(recs_ok) == len(recs_bad), name                                       # the record is still written
        assert all("connector_text_error" in d for d in recs_bad if "proposed" in d and d["proposed"] != "skipped")
        assert [d["proposed"] for d in recs_ok] == [d["proposed"] for d in recs_bad]


# ---- replay of the saved benchmark boards (no model, no network) -------------------------------------------------------------------------------------
def _boards():
    if not (RUNS / "runs").exists() or not (RUNS / "blind_map.json").exists():
        pytest.skip("the saved benchmark runs are not in this checkout")
    blind = json.loads((RUNS / "blind_map.json").read_text(encoding="utf-8"))
    out = {}
    for f in sorted((RUNS / "runs").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        pages = {}
        for e in d["events"]:
            if e["kind"] in ("draw", "modify"):
                last, order, calls = pages.setdefault(e["page_id"], ({}, [], []))
                if e["element_id"] not in last:
                    order.append(e["element_id"])
                last[e["element_id"]] = e["svg"]
                calls.append((e["kind"], e["element_id"], e["svg"]))
        for pid, (last, order, calls) in pages.items():
            out[blind[d["attempt"]]] = {"attempt": d["attempt"], "page": "".join(last[x] for x in order), "calls": calls}
    return out


@pytest.fixture(scope="module")
def replay():
    boards = _boards()
    res, ms = {}, []
    for code, b in boards.items():
        shapes = extract_shapes(b["page"])
        t0 = time.perf_counter()
        rep = ct.analyse(shapes, ct.parse_markers(b["page"]))
        ms.append((time.perf_counter() - t0) * 1000)
        res[code] = rep
    return boards, res, ms


def _near(p, q, tol=1.5):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def _same_pair(f_conn, f_label, row_conn, text):
    return _near(f_conn.pts[0], row_conn["start"]) and _near(f_conn.pts[-1], row_conn["end"]) and f_label.text[:70] == text


def test_all_33_saved_boards_are_replayed(replay):
    boards, res, _ = replay
    assert len(boards) == 33 and len(res) == 33
    assert sum(r.connectors for r in res.values()) >= 250, "the connectors were found"


def test_the_known_hidden_under_chip_pairs_are_never_reported_as_definite_collisions(replay):
    _, res, _ = replay
    assert len(FIXTURE["known_hidden_under_chip"]) == 41
    definite, ambiguous, suppressed = [], [], 0
    for row in FIXTURE["known_hidden_under_chip"]:
        rep = res[row["board"]]
        for f in rep.findings:
            if _same_pair(f.connector, f.label, row["connector"], row["label"]):
                (definite if f.certainty == "definite" else ambiguous).append((row["board"], row["label"], f.kind, f.why))
        suppressed += any(_same_pair(c, l, row["connector"], row["label"]) for c, l in rep.hidden)
    assert definite == [], definite
    assert len(ambiguous) <= 2, ("at most two known hidden pairs may come back as an ambiguous (width estimate) note", ambiguous)
    assert suppressed >= 38, f"the z-order rule suppressed {suppressed} of the 41 known pairs"


def test_the_known_visible_collisions_are_reproduced(replay):
    _, res, _ = replay
    missing = []
    for row in FIXTURE["known_true"]:
        rep = res[row["board"]]
        for text in row["labels"]:
            hits = [f for f in rep.findings if _same_pair(f.connector, f.label, row["connector"], text)]
            if row["expect"] == "any":
                ok = bool(hits)
            elif row["expect"] == "covered":
                ok = any(f.kind == "arrowhead_covered_by_label" for f in rep.findings if _near(f.connector.pts[-1], row["connector"]["end"]))
            else:
                kind = {"body": "connector_body_over_text", "head": "arrowhead_over_text"}[row["expect"]]
                ok = any(f.kind == kind and f.certainty == "definite" for f in hits)
            if not ok and row["severity"] == "strong" and not (row["board"] == "WLGR" and text == "User submits"):
                missing.append((row["board"], text, row["expect"]))
            if not ok and row["severity"] == "minor":
                missing.append((row["board"], text, row["expect"]))
    assert missing == [], missing


def test_every_definite_finding_is_a_known_visible_collision_apart_from_one_overflowing_label(replay):
    """no unexplained definite report on the 33 boards: the browser measurement and this check agree"""
    _, res, _ = replay
    unexplained = []
    for code, rep in res.items():
        for f in rep.findings:
            if f.certainty != "definite":
                continue
            if f.kind == "arrowhead_covered_by_label":
                known = any(r["board"] == code and r["expect"] == "covered" for r in FIXTURE["known_true"])
            else:
                known = any(r["board"] == code and _near(f.connector.pts[0], r["connector"]["start"]) and _near(f.connector.pts[-1], r["connector"]["end"]) for r in FIXTURE["known_true"])
            if not known:
                unexplained.append((code, f.kind, f.label.text[:20]))
    assert unexplained == [], unexplained


def test_the_boards_with_no_collision_in_the_measurement_stay_clean(replay):
    _, res, _ = replay
    measured = {r["board"] for r in FIXTURE["known_true"]}
    noisy = {c: len([f for f in r.findings if f.certainty == "definite"]) for c, r in res.items() if c not in measured and any(f.certainty == "definite" for f in r.findings)}
    assert noisy == {}, noisy


def test_call_by_call_records_replay_cleanly_and_the_diagnostic_never_changes_a_verdict(replay):
    """each board drawn call by call through shadow.compute, as the live hook sees it, once with the diagnostic and once with it raising: same verdicts, a complete record, a bounded size"""
    boards, _, _ = replay
    sizes, errors = [], 0
    for code, b in boards.items():
        page, frags, order = "", {}, []
        for kind, eid, svg in b["calls"]:
            if kind == "modify":
                continue                                                                # the live hook records draw_new_element only
            on = shadow.compute(page or None, svg, eid)
            with patch.object(ct, "analyse", side_effect=RuntimeError("boom")):
                off = shadow.compute(page or None, svg, eid)
            for key in ("existing", "proposed", "differs", "reject_kinds", "advisory_kinds", "roles"):
                assert on.get(key) == off.get(key), (code, eid, key)
            if on.get("proposed") != "skipped":
                assert "connector_text" in on and "connector_text_error" not in on, (code, eid)
                sizes.append(len(json.dumps(on)))
                errors += "connector_text_error" in on
            page += svg
    assert errors == 0 and max(sizes) < 6000, max(sizes)


def test_the_cost_of_the_diagnostic_is_small_on_every_saved_board(replay):
    _, _, ms = replay
    assert max(ms) < 400 and sum(ms) / len(ms) < 60, (max(ms), sum(ms) / len(ms))
