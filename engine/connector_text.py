"""
engine/connector_text.py  --  LOG-ONLY, z-order-aware connector-versus-text diagnostic for the shadow validator (docs/SHADOW_VALIDATOR.md, section 9).

Question answered: where does a connector, or its arrow head, run over text that is VISIBLE on the board? A connector drawn first and an opaque label chip drawn after it
(the usual "label on the line" look) is not a collision: the board paints in document order, so the chip hides the line. The older advisories in shape_model
(`connector_through_label`, `arrowhead_on_label`) are geometry only and report those pairs too; this check does not.

  * Pure and synchronous. Nothing is rejected, moved or redrawn; the caller (engine/shadow.py) records the result next to the shadow verdict and ignores it otherwise.
  * Body and head are separate: the head is the real marker outline (the board's three markers, or the marker the drawing defines), not the line.
  * Ambiguous cases are kept apart from definite ones: text width is an estimate (plus or minus 10 percent), so an overlap that exists only under the wide estimate, or a
    graze of under BODY_MIN px, is 'ambiguous', never a defect.
  * A pair that is geometrically overlapping but invisible because a later opaque shape covers it is counted as `hidden`, not reported.
  * Unsupported geometry (an arrow head whose marker cannot be found, a connector with no direction) is counted, never guessed.
  * Content: reports hold shapes (bounding boxes, element ids, indexes) and fixed reason codes. The label text is never part of a report.
All thresholds are HYPOTHESES tuned on the 33 saved benchmark boards (IN-SAMPLE); see docs/SHADOW_VALIDATOR.md.
"""
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from engine import shape_model as sm

# ---- thresholds (hypotheses) -------------------------------------------------------------------------------------------------------------------
GLYPH_ABOVE = 0.78           # ink band of a line of text, in em above the baseline ... (measured in Chromium: 15 to 85 percent of the font box)
GLYPH_BELOW = 0.10           # ... and below it
WIDTH_LOW, WIDTH_HIGH = 0.90, 1.10   # label width relative to the estimate: the measured width per character is 0.45 to 0.55 around the 0.50 estimate
BODY_MIN = 3.0               # px of visible line inside the ink band for a definite body overlap
BODY_GRAZE = 1.0             # below this nothing is reported; between this and BODY_MIN it is a graze (ambiguous)
HEAD_MIN = 6.0               # px2 of visible arrow head on the ink band for a definite head overlap
HEAD_GRAZE = 1.0
HEAD_COVER = 0.5             # share of an arrow head hidden by a later opaque box that holds a label
STEP = 1.5                   # px between samples along a connector
HEAD_STEP = 1.0              # px grid for the head area
MAX_LENGTH = 4000.0          # a connector longer than this (the canvas is 1200 x 800) is not sampled: counted as unsupported
MAX_HEAD = 300.0             # an arrow head wider or longer than this is not measured: counted as unsupported
MAX_WORK = 600_000           # sample and grid points tested per page; past this the rest of the page is left unchecked and counted (the shadow worker thread cannot be cancelled)

KINDS = ("connector_body_over_text", "arrowhead_over_text", "arrowhead_covered_by_label")


@dataclass
class Marker:
    outline: List[Tuple[float, float]]
    width: float
    height: float
    viewbox: Tuple[float, float, float, float]
    ref: Tuple[float, float]
    orient: str = "0"
    user_space: bool = False


# The board's own markers (frontend WhiteboardCanvas.tsx): the app defines them before any drawing, so a drawing that re-defines the same id does not change them.
BOARD = Marker(outline=[(0.0, 1.5), (8.0, 5.0), (0.0, 8.5)], width=8.0, height=8.0, viewbox=(0.0, 0.0, 10.0, 10.0), ref=(8.0, 5.0), orient="auto-start-reverse")


@dataclass
class Head:
    which: str                               # 'start' | 'end'
    poly: List[Tuple[float, float]]
    length: float                            # how far the head reaches back along the line from its tip


@dataclass
class Finding:
    kind: str                                # one of KINDS
    certainty: str                           # 'definite' | 'ambiguous'
    connector: sm.Shape
    label: sm.Shape
    why: str                                 # fixed reason code
    amount: float                            # px of visible line, or px2 of visible head, or the share of the head that is covered
    detail: str = ""


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    hidden: List[Tuple[sm.Shape, sm.Shape]] = field(default_factory=list)    # geometric overlaps that are invisible: a later opaque shape covers them
    unsupported: Dict[str, int] = field(default_factory=dict)
    connectors: int = 0
    labels: int = 0


# ---- markers -----------------------------------------------------------------------------------------------------------------------------------
def _hull(pts):
    p = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(p) < 3:
        return p
    cr = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for q in p:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(p):
        while len(up) >= 2 and cr(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return lo[:-1] + up[:-1]


def _num(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default


def parse_markers(svg: str) -> Dict[str, Marker]:
    """The markers a drawing (or a page) defines, by id; the first definition of an id wins, as in a browser. Anything unreadable gives an empty dict."""
    text = (svg or "").strip()
    if not text:
        return {}
    try:
        root = ET.fromstring(text if text.startswith("<svg") else '<svg xmlns="http://www.w3.org/2000/svg">' + text + "</svg>")
    except ET.ParseError:
        return {}
    out: Dict[str, Marker] = {}
    for el in root.iter():
        if sm._local(el.tag) != "marker" or not el.get("id") or el.get("id") in out:
            continue
        pts: List[Tuple[float, float]] = []
        for c in el.iter():
            tag = sm._local(c.tag)
            if tag == "path":
                for sub in sm.flatten_path(c.get("d") or "")[0]:
                    pts.extend(sub)
            elif tag in ("polygon", "polyline"):
                nums = [float(n) for n in sm._NUM.findall(c.get("points") or "")]
                pts.extend(zip(nums[0::2], nums[1::2]))
            elif tag in ("circle", "ellipse"):
                cx, cy = _num(c.get("cx")), _num(c.get("cy"))
                rx, ry = (_num(c.get("r")),) * 2 if tag == "circle" else (_num(c.get("rx")), _num(c.get("ry")))
                pts.extend((cx + rx * math.cos(k * math.pi / 8), cy + ry * math.sin(k * math.pi / 8)) for k in range(16))
            elif tag == "rect":
                x, y, w, h = _num(c.get("x")), _num(c.get("y")), _num(c.get("width")), _num(c.get("height"))
                pts.extend([(x, y), (x + w, y), (x, y + h), (x + w, y + h)])
        mw, mh = _num(el.get("markerWidth"), 3.0), _num(el.get("markerHeight"), 3.0)
        vb = [float(n) for n in sm._NUM.findall(el.get("viewBox") or "")]
        if len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0:
            vb = [0.0, 0.0, mw, mh]
        if len(pts) >= 3 and mw > 0 and mh > 0:
            out[el.get("id")] = Marker(_hull(pts), mw, mh, tuple(vb), (_num(el.get("refX")), _num(el.get("refY"))), el.get("orient") or "0", el.get("markerUnits") == "userSpaceOnUse")
    return out


def heads_of(c: sm.Shape, markers: Dict[str, Marker], unsupported: Dict[str, int]) -> List[Head]:
    """The arrow heads of a connector as polygons: the marker outline scaled by the stroke width and turned along the line, tip on the line's end point."""
    out: List[Head] = []
    for name, mid in c.marker_ends:
        mk = BOARD if mid in sm.BOARD_MARKERS else markers.get(mid)
        if mk is None:
            unsupported["marker_unresolved"] = unsupported.get("marker_unresolved", 0) + 1
            continue
        end = name == "marker-end"
        tip = c.pts[-1] if end else c.pts[0]
        back = sm._point_back(c.pts, 2.0, from_end=end)
        dx, dy = tip[0] - back[0], tip[1] - back[1]
        n = math.hypot(dx, dy)
        if n < 1e-6:
            unsupported["no_direction"] = unsupported.get("no_direction", 0) + 1
            continue
        ux, uy = dx / n, dy / n                                   # pointing away from the line at this end
        ang = math.atan2(uy, ux)
        if mk.orient == "auto":
            ang += 0.0 if end else math.pi                        # 'auto' follows the line's own direction, which at the start points into the line
        elif mk.orient != "auto-start-reverse":
            ang = math.radians(_num(mk.orient))
        u = 1.0 if mk.user_space else c.stroke_w
        scale = min(mk.width * u / mk.viewbox[2], mk.height * u / mk.viewbox[3])
        co, si = math.cos(ang), math.sin(ang)
        poly = [(tip[0] + (scale * (x - mk.ref[0])) * co - (scale * (y - mk.ref[1])) * si, tip[1] + (scale * (x - mk.ref[0])) * si + (scale * (y - mk.ref[1])) * co) for x, y in mk.outline]
        x0, y0, x1, y1 = sm._bbox_of(poly)
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or max(x1 - x0, y1 - y0) > MAX_HEAD:
            unsupported["head_too_large"] = unsupported.get("head_too_large", 0) + 1
            continue
        out.append(Head("end" if end else "start", poly, max(0.0, max((tip[0] - px) * ux + (tip[1] - py) * uy for px, py in poly))))
    return out


# ---- text bands --------------------------------------------------------------------------------------------------------------------------------
def band(label: sm.Shape, scale: float) -> Tuple[float, float, float, float]:
    """Where the ink of one line of text is: its estimated width times `scale` around the anchor point, glyph height only (not the whole font box)."""
    x0, y0, x1, y1 = label.bbox
    w = (x1 - x0) * scale
    if label.anchor == "middle":
        cx = (x0 + x1) / 2
        bx0, bx1 = cx - w / 2, cx + w / 2
    elif label.anchor == "end":
        bx0, bx1 = x1 - w, x1
    else:
        bx0, bx1 = x0, x0 + w
    base = y0 + 0.85 * label.size                                # sm.text_box puts the top at baseline - 0.85 em
    return bx0, base - GLYPH_ABOVE * label.size, bx1, base + GLYPH_BELOW * label.size


def _inside(box, x, y, pad=0.0):
    return box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad


def _poly_hit(poly, a, b) -> bool:
    return not (max(p[0] for p in poly) < a[0] or min(p[0] for p in poly) > b[0] or max(p[1] for p in poly) < a[1] or min(p[1] for p in poly) > b[1])


# ---- the check ---------------------------------------------------------------------------------------------------------------------------------
def analyse(shapes: List[sm.Shape], markers: Optional[Dict[str, Marker]] = None, charged_from: int = 0) -> Report:
    """Every connector against every text line on a page, in paint order. A pair is charged only when its connector or its label has index >= `charged_from`
    (a call is not blamed for what was already on the page)."""
    markers = markers or {}
    rep = Report()
    labels = [s for s in shapes if s.kind == "text" and s.size > 0 and s.w > 0]
    conns = [s for s in shapes if s.kind == "connector" and len(s.pts) >= 2]
    rep.labels, rep.connectors = len(labels), len(conns)
    # opaque shapes that hide what is under them (the board drops shape-level opacity, so a fill is opaque unless a parent group is translucent: sm.Shape.see_through)
    opaque = [r for r in shapes if r.kind in ("rect", "ellipse", "polygon") and r.has_fill and not r.see_through]
    chip_labels = {}
    for r in opaque:
        for l in labels:
            if l.index > r.index and sm.inside_region(r, (l.bbox[0] + l.bbox[2]) / 2, (l.bbox[1] + l.bbox[3]) / 2) and _bbox_close(r, l):
                chip_labels.setdefault(r.index, l)
    work = 0
    for c in conns:
        total = sum(math.dist(p, q) for p, q in zip(c.pts, c.pts[1:]))
        if not math.isfinite(total) or total > MAX_LENGTH:
            rep.unsupported["too_long"] = rep.unsupported.get("too_long", 0) + 1
            continue
        if work > MAX_WORK:
            rep.unsupported["work_budget"] = rep.unsupported.get("work_budget", 0) + 1
            continue
        later = [r for r in opaque if r.index > c.index]
        covered = lambda x, y, later=later: any(r.bbox[0] <= x <= r.bbox[2] and r.bbox[1] <= y <= r.bbox[3] and sm.inside_region(r, x, y) for r in later)
        heads = heads_of(c, markers, rep.unsupported)
        cut_start = max([h.length for h in heads if h.which == "start"], default=0.0)
        cut_end = max([h.length for h in heads if h.which == "end"], default=0.0)
        samples = _samples(c.pts)
        half = c.stroke_w / 2
        for l in labels:
            if c.index < charged_from and l.index < charged_from:
                continue
            wide, tight = band(l, WIDTH_HIGH), band(l, WIDTH_LOW)
            reach = (wide[0] - half - 1, wide[1] - half - 1, wide[2] + half + 1, wide[3] + half + 1)
            if not sm._bbox_hit(c.bbox, reach) and not any(_poly_hit(h.poly, reach[:2], reach[2:]) for h in heads):
                continue
            vis_t = vis_w = hid_w = 0.0
            work += len(samples) + 40 * len(heads) + len(later)
            for s, x, y in samples:
                if s < cut_start or s > total - cut_end or not _inside(wide, x, y, half):
                    continue
                if covered(x, y):
                    hid_w += STEP
                else:
                    vis_w += STEP
                    if _inside(tight, x, y, half):
                        vis_t += STEP
            if vis_t >= BODY_MIN:
                rep.findings.append(Finding("connector_body_over_text", "definite", c, l, "visible_line", vis_t, f"{vis_t:.0f} px of the line over the text"))
            elif vis_w >= BODY_GRAZE:
                why = "width_estimate" if vis_w >= BODY_MIN else "graze"
                rep.findings.append(Finding("connector_body_over_text", "ambiguous", c, l, why, vis_w, f"{vis_w:.0f} px of the line, depends on the text width estimate" if why == "width_estimate" else f"{vis_w:.0f} px graze"))
            elif hid_w >= BODY_MIN:
                rep.hidden.append((c, l))
            for h in heads:
                a_t, a_w = _head_area(h, tight, covered), _head_area(h, wide, covered)
                if a_t >= HEAD_MIN:
                    rep.findings.append(Finding("arrowhead_over_text", "definite", c, l, "visible_head", a_t, f"{a_t:.0f} px2 of the arrow head over the text"))
                elif a_w >= HEAD_GRAZE:
                    why = "width_estimate" if a_w >= HEAD_MIN else "graze"
                    rep.findings.append(Finding("arrowhead_over_text", "ambiguous", c, l, why, a_w, f"{a_w:.0f} px2 of the arrow head, depends on the text width estimate" if why == "width_estimate" else f"{a_w:.0f} px2 graze"))
        # a later opaque box that holds a label hides the head: the label's box covers the end of the connector
        for h in heads:
            frac, chip = _head_covered(h, later, chip_labels)
            if chip is not None and frac >= HEAD_COVER and (c.index >= charged_from or chip.index >= charged_from):
                rep.findings.append(Finding("arrowhead_covered_by_label", "definite", c, chip, "head_hidden_by_label_box", frac, f"a later box with a label hides {frac:.0%} of the arrow head"))
    return rep


def _bbox_close(r: sm.Shape, l: sm.Shape) -> bool:
    """The region is a label's own box, not a big panel that happens to be under it: at least half of the label's box overlaps the region and the region is at most 8 times
    the label's area. (A label wider than its box still counts: that is the usual overflow.)"""
    ix = max(0.0, min(r.bbox[2], l.bbox[2]) - max(r.bbox[0], l.bbox[0]))
    iy = max(0.0, min(r.bbox[3], l.bbox[3]) - max(r.bbox[1], l.bbox[1]))
    return ix * iy >= 0.5 * max(1e-9, l.w * l.h) and r.w * r.h <= 8 * l.w * l.h


def _samples(pts):
    """(arc length, x, y) of points every STEP px along the polyline."""
    out, s = [], 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        L = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(L / STEP))
        for i in range(n):
            t = (i + 0.5) / n
            out.append((s + L * t, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
        s += L
    return out


def _grid(poly):
    x0, y0, x1, y1 = sm._bbox_of(poly)
    x = x0 + HEAD_STEP / 2
    while x < x1:
        y = y0 + HEAD_STEP / 2
        while y < y1:
            if sm._in_polygon(x, y, poly):
                yield x, y
            y += HEAD_STEP
        x += HEAD_STEP


def _head_area(h: Head, box, covered) -> float:
    """px2 of the arrow head that is inside the ink band and not hidden by a later opaque shape."""
    if not _poly_hit(h.poly, box[:2], box[2:]):
        return 0.0
    return sum(HEAD_STEP * HEAD_STEP for x, y in _grid(h.poly) if _inside(box, x, y) and not covered(x, y))


def _head_covered(h: Head, later, chip_labels) -> Tuple[float, Optional[sm.Shape]]:
    """(share of the head hidden by later opaque boxes that hold a label, one of those labels)."""
    total = hit = 0
    chip = None
    for x, y in _grid(h.poly):
        total += 1
        for r in later:
            if r.index in chip_labels and r.bbox[0] <= x <= r.bbox[2] and r.bbox[1] <= y <= r.bbox[3] and sm.inside_region(r, x, y):
                hit += 1
                chip = chip or chip_labels[r.index]
                break
    return (hit / total if total else 0.0), chip
