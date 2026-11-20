"""
Tests of the PURE shape model (engine/shape_model.py), the shadow-phase proposal of docs/VALIDATOR_DESIGN.md. Nothing here touches the live validator.

Three kinds of test:
  * each rule, accepted and rejected (including the intentional overlaps that must stay legal: a label in its own box, nesting, a Venn diagram of outlines);
  * the six-box architecture diagram of docs/CONNECTOR_OVERLAP_EXPERIMENT.md (the agent's own geometry, and the same boxes with edge-attached connectors) in
    the four groupings A, B, C, D: the collisions found on the FINAL page must be identical however the shapes were split into calls;
  * property tests on random layouts, both ways (clean layouts give no rejection, injected faults are found).
"""
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import shape_model as sm
from engine.shape_model import collisions_for_page, extract_shapes, flatten_path, shadow_check


def g(eid, body):
    return f'<g id="{eid}">{body}</g>'


def kinds(svg, severity="reject"):
    return sorted(c.kind for c in collisions_for_page(svg) if c.severity == severity)


def box(x, y, w, h, label=None, fill="#eef", stroke="#00f", size=16, extra=""):
    t = f'<text x="{x + w / 2}" y="{y + h / 2 + 5}" font-size="{size}" text-anchor="middle">{label}</text>' if label else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="2" {extra}/>{t}'


def line(pts, sw=3, marker=None, fill="none"):
    m = f' marker-end="url(#{marker})"' if marker else ""
    return f'<polyline points="{" ".join(f"{x},{y}" for x, y in pts)}" stroke="#000" stroke-width="{sw}" fill="{fill}"{m}/>'


# ---- extraction ---------------------------------------------------------------------------------------------------------------------------------
def test_extraction_reads_shapes_in_document_order_with_inherited_style():
    svg = g("a", '<g fill="#abc" stroke="#123" stroke-width="3" opacity="0.5"><rect x="10" y="10" width="100" height="50"/><circle cx="200" cy="50" r="30"/></g>'
                 '<text x="10" y="90" font-size="20">Hi</text><polyline points="0,0 10,10" stroke="#000"/>')
    s = extract_shapes(svg)
    assert [x.kind for x in s] == ["rect", "ellipse", "text", "connector"] and [x.index for x in s] == [0, 1, 2, 3]
    assert s[0].has_fill and s[0].stroke_w == 3 and abs(s[0].opacity - 0.5) < 1e-9, "style comes from the parent group, a group opacity survives"
    assert s[2].size == 20 and s[2].element == "a"


def test_shape_level_opacity_is_ignored_because_the_board_renderer_drops_it():
    """roughRenderer.ts copies only stroke, stroke-width and the fill colour of a shape: fill-opacity and opacity on the SHAPE do not reach the screen."""
    s = extract_shapes('<rect x="0" y="0" width="50" height="50" fill="#f00" fill-opacity="0.2" opacity="0.2"/>')[0]
    assert sm.RENDERER_DROPS_SHAPE_OPACITY and s.opacity == 1.0 and not s.see_through
    s2 = extract_shapes('<g opacity="0.4"><rect x="0" y="0" width="50" height="50" fill="#f00"/></g>')[0]
    assert s2.see_through


def test_paths_are_flattened_curves_arcs_and_relative_commands():
    subs, closed = flatten_path("M10 10 L50 10 C60 20 70 30 80 10 Q90 0 100 10 A 20 20 0 0 1 140 10 Z")
    assert len(subs) == 1 and closed == [True] and len(subs[0]) > 20
    xs, ys = [p[0] for p in subs[0]], [p[1] for p in subs[0]]
    assert min(xs) == 10 and abs(max(xs) - 140) < 1e-6 and min(ys) < 10 < max(ys)
    rel, _ = flatten_path("m10 10 l40 0 v20 h-40 z")
    assert rel[0][:4] == [(10, 10), (50, 10), (50, 30), (10, 30)]
    c = extract_shapes('<path d="M0 0 C 50 100 100 100 150 0" stroke="#000" fill="none"/>')[0]
    assert c.kind == "connector" and 40 < c.bbox[3] < 80, "the box of a curve follows the curve, not its control points (control points would give y 100)"


def test_closed_or_filled_paths_are_regions_open_unfilled_paths_with_arrows_are_connectors():
    assert extract_shapes('<path d="M0 0 L100 0 L100 50 L0 50 Z" fill="#eee" stroke="#000"/>')[0].kind == "polygon"
    assert extract_shapes('<path d="M0 0 L100 0" stroke="#000" marker-end="url(#arrow)"/>')[0].kind == "connector"
    c = extract_shapes('<path d="M0 0 L100 0" stroke="#000" stroke-width="3" marker-end="url(#arrow)"/>')[0]
    assert len(c.heads) == 1 and abs(c.heads[0][1][0] - 100) < 1e-6, "the head's tip sits on the end point"


def test_tspan_lines_become_one_label_each():
    s = extract_shapes('<text x="100" y="50" font-size="16" text-anchor="middle"><tspan x="100">first line</tspan><tspan x="100" dy="20">second</tspan></text>')
    assert [x.text for x in s] == ["first line", "second"] and s[1].bbox[1] > s[0].bbox[1] + 15


def test_roles_come_from_geometry_container_node_decoration():
    s = extract_shapes(g("a", box(50, 50, 600, 400, None, fill="none") + box(100, 100, 150, 60, "In") + box(300, 100, 150, 60, "Two") + '<rect x="100" y="300" width="300" height="4" fill="#000"/>'))
    sm.classify(s)
    assert [x.role for x in s if x.kind == "rect"] == ["container", "node", "node", "decoration"]
    ring = extract_shapes(g("a", '<circle cx="300" cy="300" r="120" fill="none" stroke="#00f"/><circle cx="300" cy="300" r="12" fill="#f80"/>'))
    sm.classify(ring)
    assert [x.role for x in ring] == ["node", "node"], "a ring with one small dot inside is not a frame"


# ---- labels ------------------------------------------------------------------------------------------------------------------------------------
def test_a_label_inside_its_own_box_is_legal_and_a_label_straddling_the_edge_is_not():
    assert kinds(g("a", box(100, 100, 200, 80, "Hello"))) == []
    assert kinds(g("a", box(100, 100, 100, 60) + '<text x="150" y="98" font-size="16" text-anchor="middle">Straddles the top edge</text>')) == ["label_straddles_region"]


def test_a_label_wider_than_its_box_is_an_advisory_not_a_rejection():
    svg = g("a", box(100, 100, 120, 60, "A fairly long label here", size=16))
    assert kinds(svg) == [] and kinds(svg, "advisory") == ["label_overflow"]


def test_label_on_label_and_a_label_hidden_under_a_later_opaque_box():
    two = g("a", '<text x="100" y="100" font-size="18">Alpha beta</text><text x="110" y="104" font-size="18">Alpha gamma</text>')
    assert kinds(two) == ["label_label"]
    assert kinds(g("a", '<text x="150" y="130" font-size="16" text-anchor="middle">Hidden</text>' + box(100, 100, 100, 60))) == ["label_covered"]
    assert kinds(g("a", box(100, 100, 100, 60) + '<text x="150" y="130" font-size="16" text-anchor="middle">Shown</text>')) == []


# ---- regions: the intentional overlaps stay legal --------------------------------------------------------------------------------------------
def test_nesting_a_card_in_a_frame_is_legal():
    assert kinds(g("a", box(50, 50, 600, 400, None, fill="#f8f8f8") + box(100, 100, 200, 80, "Card"))) == []


def test_two_opaque_boxes_that_overlap_are_rejected_stacked_duplicates_too():
    assert kinds(g("a", box(100, 100, 200, 100) + box(150, 120, 200, 100))) == ["region_overlap_hides"]
    assert kinds(g("a", box(100, 100, 200, 100) + box(102, 102, 200, 100))) == ["region_duplicate"]


def test_a_venn_diagram_of_outlines_is_legal_but_the_same_circles_filled_and_opaque_are_not():
    outlines = g("v", '<circle cx="200" cy="200" r="100" fill="none" stroke="#00f" stroke-width="3"/><circle cx="300" cy="200" r="100" fill="none" stroke="#f00" stroke-width="3"/>')
    assert kinds(outlines) == []
    filled = g("v", '<circle cx="200" cy="200" r="100" fill="#8af"/><circle cx="300" cy="200" r="100" fill="#fa8"/>')
    assert kinds(filled) == ["region_overlap_hides"]
    outline_on_fill = g("v", '<circle cx="200" cy="200" r="100" fill="#8af"/><circle cx="300" cy="200" r="100" fill="none" stroke="#f00" stroke-width="3"/>')
    assert kinds(outline_on_fill) == [], "the top shape lets the lower one show through"
    translucent_group = g("v", '<g opacity="0.4"><circle cx="200" cy="200" r="100" fill="#8af"/><circle cx="300" cy="200" r="100" fill="#fa8"/></g>')
    assert kinds(translucent_group) == [], "a group opacity survives the renderer: a see-through Venn can be drawn"
    shape_opacity = g("v", '<circle cx="200" cy="200" r="100" fill="#8af" fill-opacity="0.3"/><circle cx="300" cy="200" r="100" fill="#fa8" fill-opacity="0.3"/>')
    assert kinds(shape_opacity) == ["region_overlap_hides"], "fill-opacity on a shape never reaches the screen, so it is not see-through"


def test_a_small_marker_on_the_edge_of_a_node_is_legal_but_a_node_straddling_a_frame_edge_or_a_label_chip_over_a_box_is_not():
    big = '<circle cx="300" cy="300" r="120" fill="none" stroke="#00f" stroke-width="3"/>'
    assert kinds(g("a", big + '<circle cx="300" cy="180" r="18" fill="#f80"/>')) == [], "the phone on the circle: a dot on the edge"
    frame = box(50, 50, 700, 300, None, fill="none") + box(100, 100, 150, 60, "Inside") + box(300, 100, 150, 60, "Also")   # a frame that holds content is a container
    assert "region_overlap_hides" in kinds(g("a", frame + '<circle cx="750" cy="200" r="60" fill="#8af"/>')), "a circle sticking out of its frame"
    assert "region_overlap_hides" in kinds(g("a", box(100, 100, 220, 80, "User") + '<rect x="190" y="90" width="100" height="36" fill="#dbeafe" stroke="#00f"/>'))


def test_a_small_overlap_below_the_limit_is_legal():
    assert kinds(g("a", box(100, 100, 200, 100) + box(290, 100, 200, 100))) == []


# ---- connectors ----------------------------------------------------------------------------------------------------------------------------------
def two_boxes():
    return box(60, 120, 220, 80, "User") + box(320, 120, 220, 80, "Frontend")


def test_a_connector_that_meets_the_box_edges_is_legal_one_through_the_boxes_is_not():
    assert kinds(g("a", two_boxes() + line([(280, 140), (320, 140)], marker="arrow"))) == []
    svg = g("a", two_boxes() + line([(140, 160), (400, 160)]))
    assert "connector_through_node" in kinds(svg) and "connector_through_label" in kinds(svg, "advisory"), "the label crossing is recorded, never a rejection"


def test_running_along_an_edge_and_touching_inside_the_band_is_legal():
    assert kinds(g("a", two_boxes() + line([(60, 202), (540, 202)]))) == []         # runs just under the boxes
    assert kinds(g("a", two_boxes() + line([(280, 160), (322, 160)]))) == []        # the tip dips 2 px into the second box (inside the attach band)


def test_an_arrow_that_ends_inside_a_box_is_rejected_with_the_edge_point_in_the_message():
    c = [x for x in collisions_for_page(g("a", two_boxes() + line([(280, 140), (430, 140)], marker="arrow"))) if x.kind == "connector_through_node"]
    assert c and abs(c[0].data["edge_point"][0] - 320) <= 3 and "(32" in c[0].message()


def test_an_arrow_head_that_runs_beside_a_box_into_its_edge_is_rejected():
    # the line itself stays 3 px outside the box, but the head (half-width about 17 px at stroke 6) reaches into it
    svg = g("a", box(100, 100, 200, 100, "B") + line([(303, 260), (303, 150)], sw=6, marker="arrow"))
    assert "arrowhead_in_node" in kinds(svg)


def test_a_connector_may_cross_a_container_and_other_connectors_but_not_a_node_inside_it():
    frame = box(50, 50, 700, 300, None, fill="none")
    node = box(300, 120, 150, 80, "Node")
    assert kinds(g("a", frame + node + line([(80, 300), (700, 300)]))) == []
    assert "connector_through_node" in kinds(g("a", frame + node + line([(80, 160), (700, 160)])))
    assert kinds(g("a", frame + line([(80, 100), (700, 300)]) + line([(80, 300), (700, 100)]))) == []


def test_a_connector_that_crosses_a_label_in_free_space_is_an_advisory_not_a_rejection():
    svg = g("a", '<text x="200" y="150" font-size="18" text-anchor="middle">Caption</text>' + line([(100, 146), (300, 146)]))
    assert kinds(svg) == [] and kinds(svg, "advisory") == ["connector_through_label"]
    assert kinds(g("a", '<text x="200" y="150" font-size="18" text-anchor="middle">Caption</text>' + line([(100, 180), (300, 180)]))) == []


def test_a_short_connector_wholly_inside_one_box_is_a_glyph_not_a_collision():
    assert kinds(g("a", box(100, 100, 300, 120) + line([(120, 130), (170, 130)], marker=None))) == []


def test_curves_connector_between_boxes_through_free_space_legal_through_a_third_box_not():
    A, B, C = box(60, 100, 120, 60, "A"), box(500, 100, 120, 60, "B"), box(260, 90, 140, 80, "C")
    over = f'<path d="M180 130 C 250 20 430 20 500 130" stroke="#000" stroke-width="2" fill="none" marker-end="url(#arrow)"/>'
    assert kinds(g("a", A + B + C + over)) == []
    through = '<path d="M180 130 C 250 130 430 130 500 130" stroke="#000" stroke-width="2" fill="none"/>'
    assert "connector_through_node" in kinds(g("a", A + B + C + through))
    # the control points of this curve lie inside box C, the curve itself passes 12 px above it: a box test on control points would reject it
    A2, B2, C2 = box(60, 10, 120, 60, "A"), box(500, 10, 120, 60, "B"), box(260, 120, 140, 60, "C")
    graze = '<path d="M180 40 C 300 130 360 130 500 40" stroke="#000" stroke-width="2" fill="none"/>'
    assert kinds(g("a", A2 + B2 + C2 + graze)) == []


def test_two_connectors_on_top_of_each_other_are_an_advisory():
    svg = g("a", line([(100, 100), (400, 100)]) + line([(400, 101), (100, 101)]))
    assert kinds(svg) == [] and kinds(svg, "advisory") == ["connectors_overlap"]


# ---- the six-box architecture diagram: four groupings, one verdict on the final page -------------------------------------------------------------
BOXES = (
    '<rect x="60" y="120" width="220" height="80" rx="18" fill="#f3f4f6" stroke="#2563eb" stroke-width="2"/><text x="170" y="164" font-size="22" text-anchor="middle" fill="#1e293b">User</text>'
    '<rect x="320" y="120" width="220" height="80" rx="18" fill="#e0f2fe" stroke="#2563eb" stroke-width="2"/><text x="430" y="164" font-size="22" text-anchor="middle" fill="#1e293b">Frontend</text>'
    '<rect x="580" y="120" width="220" height="80" rx="18" fill="#f1f5f9" stroke="#2563eb" stroke-width="2"/><text x="690" y="164" font-size="22" text-anchor="middle" fill="#1e293b">API Gateway</text>'
    '<rect x="580" y="220" width="220" height="80" rx="18" fill="#f1f5f9" stroke="#38bdf8" stroke-width="2"/><text x="690" y="264" font-size="20" text-anchor="middle" fill="#0e7490">Authentication Service</text>'
    '<rect x="820" y="120" width="220" height="80" rx="18" fill="#ede9fe" stroke="#7c3aed" stroke-width="2"/><text x="930" y="164" font-size="22" text-anchor="middle" fill="#4c1d95">Backend Service</text>'
    '<rect x="820" y="220" width="220" height="80" rx="18" fill="#fff7ed" stroke="#f59e42" stroke-width="2"/><text x="930" y="264" font-size="20" text-anchor="middle" fill="#c2410c">Database</text>')
AGENT_ARROWS = [  # the 11 connectors the agent wrote in Test 2 (request forwards, response backwards, on the same coordinates)
    [(140, 160), (320, 160)], [(430, 160), (580, 160)], [(690, 160), (820, 160)], [(690, 200), (690, 220)], [(690, 300), (930, 300)], [(930, 200), (930, 220)],
    [(930, 300), (930, 200)], [(930, 160), (820, 160)], [(820, 160), (690, 160)], [(580, 160), (430, 160)], [(320, 160), (140, 160)]]
AGENT_PILLS = ('<rect x="150" y="110" width="100" height="36" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="2"/><text x="200" y="134" font-size="16" text-anchor="middle">Request</text>'
               '<rect x="150" y="180" width="100" height="36" rx="8" fill="#dcfce7" stroke="#22c55e" stroke-width="2"/><text x="200" y="204" font-size="16" text-anchor="middle">Response</text>')
FIXED_ARROWS = [  # the same boxes, every connector starts and ends on a box edge in the gaps (9 connectors, forward above, response below)
    [(280, 150), (320, 150)], [(540, 150), (580, 150)], [(800, 150), (820, 150)], [(660, 200), (660, 220)], [(800, 240), (810, 240), (810, 190), (820, 190)], [(900, 200), (900, 220)],
    [(960, 220), (960, 200)], [(820, 170), (800, 170)], [(580, 170), (540, 170)], [(320, 170), (280, 170)]]
FIXED_PILLS = ('<rect x="60" y="310" width="100" height="36" fill="#dbeafe" stroke="#2563eb" stroke-width="2"/><text x="110" y="334" font-size="16" text-anchor="middle">Request</text>'
               '<rect x="180" y="310" width="100" height="36" fill="#dcfce7" stroke="#22c55e" stroke-width="2"/><text x="230" y="334" font-size="16" text-anchor="middle">Response</text>')


def arrows_svg(arrows, sw=3):
    return "".join(line(a, sw=sw, marker="arrow") for a in arrows)


def groupings(arrows, pills):
    """The same shapes in the same paint order, split into calls in the four ways of the experiment."""
    boxes = re.findall(r"<rect\b[^>]*/>\s*<text\b.*?</text>", BOXES, flags=re.S)
    A = [g("all", BOXES + arrows_svg(arrows) + pills)]
    B = [g("boxes", BOXES), g("rest", arrows_svg(arrows) + pills)]
    C = [g("boxes", BOXES)] + [g(f"c{i}", line(a, marker="arrow")) for i, a in enumerate(arrows)] + [g("pills", pills)]
    D = [g(f"b{i}", b) for i, b in enumerate(boxes)] + [g(f"c{i}", line(a, marker="arrow")) for i, a in enumerate(arrows)] + [g("pills", pills)]
    return {"A": A, "B": B, "C": C, "D": D}


def final_keys(calls):
    return sorted(c.key() for c in collisions_for_page("".join(calls)))


def test_the_agents_geometry_is_rejected_for_the_real_reasons_in_every_grouping_and_the_final_collisions_do_not_depend_on_the_grouping():
    sets = groupings(AGENT_ARROWS, AGENT_PILLS)
    keys = {name: final_keys(calls) for name, calls in sets.items()}
    assert keys["A"] == keys["B"] == keys["C"] == keys["D"] and keys["A"], "grouping does not change the collisions"
    found = {k[0] for k in keys["A"]}
    assert {"connector_through_node", "connector_through_label", "arrowhead_in_node", "region_overlap_hides"} <= found
    assert {c.kind for c in collisions_for_page("".join(sets["A"])) if c.severity == "reject"} == {"connector_through_node", "arrowhead_in_node", "region_overlap_hides"}
    rejected = [c for c in collisions_for_page("".join(sets["A"])) if c.kind == "connector_through_node"]
    assert len(rejected) >= 7, "7 or more of the 11 connectors cross a box (8 by the geometry count of the experiment; the model counts a hit per box and connector)"


def test_each_call_of_the_agents_variants_has_the_same_reasons_as_the_final_page():
    """Sequentially, every call is judged against the page so far: the union of what the calls are charged with equals the final page's collisions."""
    for name, calls in groupings(AGENT_ARROWS, AGENT_PILLS).items():
        page, charged = "", set()
        for frag in calls:
            res = shadow_check(page, frag)
            charged |= {c.key() for c in res.reasons}
            page += frag                                   # every call is added, as if accepted, to compare with the final page
        final = {c.key() for c in collisions_for_page(page) if c.severity == "reject"}
        assert charged == final, name


def test_the_same_boxes_with_edge_attached_connectors_are_accepted_in_every_grouping():
    for name, calls in groupings(FIXED_ARROWS, FIXED_PILLS).items():
        page = ""
        for frag in calls:
            res = shadow_check(page, frag)
            assert res.verdict == "accept", (name, [c.message() for c in res.reasons])
            page += frag
        assert final_keys(calls) == [] or all(k[0] in ("label_overflow", "connectors_overlap") for k in final_keys(calls)), name


def test_the_connector_call_alone_is_not_blamed_for_the_gap_between_boxes():
    boxes = g("boxes", BOXES)
    res = shadow_check(boxes, g("conns", arrows_svg(FIXED_ARROWS)))
    assert res.verdict == "accept", "the existing validator rejects exactly this call (the gaps count as occupied); here the gaps are free"


def test_pills_over_the_user_box_are_a_real_overlap_in_one_call_or_two():
    assert "region_overlap_hides" in kinds(g("a", BOXES + AGENT_PILLS))
    assert shadow_check(g("b", BOXES), g("p", AGENT_PILLS)).verdict == "reject"


# ---- property tests ------------------------------------------------------------------------------------------------------------------------------
def random_page(rng, n=6):
    """A grid of labelled boxes with connectors that go from one edge to the next in the gap: clean by construction."""
    cols = rng.randrange(2, 4)
    w, h, gx, gy = rng.randrange(140, 200, 10), rng.randrange(60, 90, 10), rng.randrange(50, 90, 10), rng.randrange(50, 90, 10)
    cells = []
    body = ""
    for i in range(n):
        x, y = 60 + (i % cols) * (w + gx), 100 + (i // cols) * (h + gy)
        cells.append((x, y))
        body += box(x, y, w, h, f"N{i}")
    arrows = []
    for i, (x, y) in enumerate(cells):
        if i % cols != cols - 1 and i + 1 < n:
            arrows.append([(x + w, y + h // 2), (x + w + gx, y + h // 2)])
        if i + cols < n:
            arrows.append([(x + w // 2, y + h), (x + w // 2, y + h + gy)])
    return body, arrows, cells, (w, h, gx, gy)


def test_clean_random_layouts_give_no_rejection_in_any_grouping():
    rng = random.Random(5)
    for _ in range(25):
        body, arrows, *_ = random_page(rng)
        full = body + arrows_svg(arrows, sw=2)
        assert kinds(g("a", full)) == [], full
        calls = [g("boxes", body)] + [g(f"c{i}", line(a, sw=2, marker="arrow")) for i, a in enumerate(arrows)]
        page = ""
        for frag in calls:
            assert shadow_check(page, frag).verdict == "accept"
            page += frag


def test_injected_faults_are_found_in_random_layouts():
    rng = random.Random(9)
    for _ in range(25):
        body, arrows, cells, (w, h, gx, gy) = random_page(rng)
        x, y = cells[0]
        through = line([(x + 20, y + h // 2 + 14), (x + w + gx + 40, y + h // 2 + 14)], sw=3)      # starts inside box 0 and ends inside box 1
        assert {"connector_through_node"} & set(kinds(g("a", body + through)))
        stacked = box(x + 3, y + 3, w, h)
        assert "region_duplicate" in kinds(g("a", body + stacked))
        under_label = f'<text x="{x + w / 2}" y="{y + h / 2 + 5}" font-size="16" text-anchor="middle">N0 again</text>'
        assert "label_label" in kinds(g("a", body + under_label))


def test_the_verdict_for_a_page_does_not_depend_on_how_it_was_split_into_calls_for_random_splits():
    rng = random.Random(3)
    for _ in range(20):
        body, arrows, *_ = random_page(rng)
        shapes = re.findall(r"<rect\b[^>]*/>\s*<text\b.*?</text>", body, flags=re.S) + [line(a, marker="arrow") for a in arrows]
        bad = line([(100, 130), (500, 130)])
        shapes.insert(rng.randrange(len(shapes) + 1), bad)
        whole = final_keys([g("all", "".join(shapes))])
        cut = sorted(rng.sample(range(1, len(shapes)), 3))
        parts = [g(f"p{i}", "".join(shapes[a:b])) for i, (a, b) in enumerate(zip([0] + cut, cut + [len(shapes)]))]
        assert final_keys(parts) == whole
