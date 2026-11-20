"""
engine/shape_model.py  --  PURE shape model for a proposed shape-level validator (design: docs/VALIDATOR_DESIGN.md).

SHADOW PHASE: nothing in the application imports this module and nothing here changes what is accepted or rejected. The existing validator
(engine/validator.py) stays authoritative; `shadow_check` only says what this proposal WOULD have decided, with reasons.

What it does
  1. `extract_shapes`  : the drawn SVG -> a flat list of Shape (rect, circle/ellipse, polygon, connector, text label), in document order.
                         Curves are flattened to short straight pieces, arrow heads of the board's markers become small polygons.
  2. role classification: label / connector / node / container / decoration (by geometry and style only, NEVER by which call or element a shape came from).
  3. `find_collisions` : the rules, over every pair of shapes on a page. A verdict depends on the final set of shapes, not on how they were grouped into calls.

Severity: 'reject' collisions are the ones a future enforcement could act on; 'advisory' ones (label overflow, a connector or arrow head over a label, connectors on top of each
each other) are only ever recorded (owner decision, shadow phase).

Founding rule kept: this only measures and reports. It never moves or repairs anything for the model.
All thresholds are HYPOTHESES (see the constants) to be tuned from shadow runs.
"""
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

CANVAS_W, CANVAS_H = 1200, 800

# ---- thresholds (hypotheses, tuned in shadow runs) ---------------------------------------------------------------------------------------------
THIN = 20.0                  # px: a region thinner than this is a 'decoration' (the existing validator ignores such shapes too)
REGION_OVERLAP = 0.20        # share of the smaller region another region may cover (same value as validator.OVERLAP_REJECT)
LABEL_OVERLAP = 0.30         # share of the smaller label box another label may cover (as validator.TEXT_OVERLAP_REJECT)
NEST_RATIO = 0.80            # a region fully inside another one is 'nested' when it is at most this share of the outer area
DUPLICATE_COVER = 0.90       # two regions covering this share of the smaller one, of similar size, are a stacked duplicate
DUPLICATE_SIZE = 0.80        # ... similar size = the smaller is at least this share of the larger
MARKER_RATIO = 0.15          # a shape at most this share of the area of a (non-container) shape it overlaps is a marker on it (a dot on a circle's edge): legal
LABEL_INSIDE = 0.90          # share of a label box inside a region for the label to belong to it
ATTACH_BAND = 4.0            # px: a connector may run in the band along a node's edge (attach tolerance)
INTERIOR_TOL = 8.0           # px of connector centre line allowed inside a node's shrunk interior
LABEL_CROSS_TOL = 6.0        # px of connector centre line allowed inside a label box
HEAD_AREA_TOL = 12.0         # px2 of arrow head allowed inside a node interior or label box
SEE_THROUGH = 0.6            # effective opacity at or below which a shape does not hide what is under it
TEXT_WIDTH_FACTOR = 0.50     # width of a label = chars x font size x this. MEASURED in Chromium with Inter on 177 stored labels: median 0.49 regular, 0.52 bold, 5th to 95th percentile 0.45 to 0.55
BOLD_WIDTH_FACTOR = 0.52     # (the existing validator uses 0.55 for its advisory estimate: an upper bound, which over-reports)
SAMPLE_STEP = 2.0            # px: spacing of the samples along a connector
# The board's Rough.js renderer (frontend/src/services/roughRenderer.ts) copies only stroke, stroke-width and fill colour of a rect/circle/ellipse:
# `fill-opacity` and `opacity` on the SHAPE are dropped, only an `opacity` on a parent <g> survives (shown in docs/SHADOW_VALIDATOR.md, rendered check).
RENDERER_DROPS_SHAPE_OPACITY = True

# The board's own markers (WhiteboardCanvas.tsx): viewBox 0 0 10 10, ref 8,5, 8 x 8 in stroke-width units, head path M 0 1.5 L 8 5 L 0 8.5 z
BOARD_MARKERS = {"arrow", "arrow-dark", "arrow-green"}
_HEAD_UNIT = [(-8.0, -3.5), (0.0, 0.0), (-8.0, 3.5)]       # head vertices relative to the tip, in marker units; one unit = 0.8 x stroke width
_HEAD_SCALE = 0.8

_PRESENTATION = ("fill", "fill-opacity", "opacity", "stroke", "stroke-width", "font-size", "text-anchor", "font-weight")


@dataclass
class Shape:
    index: int                       # document order = paint order (later is on top)
    element: str                     # the <g id> it came from: REPORTING ONLY, never used by a rule
    tag: str
    kind: str                        # 'text' | 'connector' | 'rect' | 'ellipse' | 'polygon'
    role: str = ""                   # 'label' | 'connector' | 'node' | 'container' | 'decoration'
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    pts: List[Tuple[float, float]] = field(default_factory=list)   # connector centre line, or polygon vertices
    params: Tuple[float, ...] = ()   # rect: x, y, w, h   ellipse: cx, cy, rx, ry
    stroke_w: float = 1.0
    has_fill: bool = False
    opacity: float = 1.0             # effective opacity that the board really draws (see RENDERER_DROPS_SHAPE_OPACITY)
    marker: List[str] = field(default_factory=list)                # ids from marker-start / marker-end
    heads: List[List[Tuple[float, float]]] = field(default_factory=list)
    text: str = ""
    size: float = 16.0
    anchor: str = "start"            # text-anchor of a label (read by engine/connector_text.py only)
    marker_ends: List[Tuple[str, str]] = field(default_factory=list)   # ('marker-start'|'marker-end', marker id) of a connector (read by engine/connector_text.py only)

    @property
    def w(self): return self.bbox[2] - self.bbox[0]

    @property
    def h(self): return self.bbox[3] - self.bbox[1]

    @property
    def area(self):
        if self.kind == "rect":
            return self.params[2] * self.params[3]
        if self.kind == "ellipse":
            return math.pi * self.params[2] * self.params[3]
        if self.kind == "polygon":
            return abs(_shoelace(self.pts))
        return self.w * self.h

    @property
    def see_through(self):
        return (not self.has_fill) or self.opacity <= SEE_THROUGH

    def descriptor(self) -> str:
        x0, y0, x1, y1 = self.bbox
        what = f"'{self.text[:24]}'" if self.kind == "text" else self.kind
        return f"{what}@{x0:.0f},{y0:.0f}-{x1:.0f},{y1:.0f}" + (f" in '{self.element}'" if self.element else "")

    def key(self) -> str:                                        # call-independent identity (no element id, no index)
        x0, y0, x1, y1 = self.bbox
        return f"{self.kind}@{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}" + (f":{self.text[:24]}" if self.kind == "text" else "")


@dataclass
class Collision:
    kind: str
    severity: str                    # 'reject' | 'advisory'
    a: Shape
    b: Optional[Shape]
    detail: str = ""
    data: Dict = field(default_factory=dict)

    def key(self):
        return (self.kind, tuple(sorted([self.a.key()] + ([self.b.key()] if self.b else []))))

    def message(self) -> str:
        who = self.a.descriptor() + (f" and {self.b.descriptor()}" if self.b else "")
        return f"{self.kind}: {who}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class ShadowResult:
    verdict: str                     # 'accept' | 'reject'   (what the PROPOSAL would decide)
    reasons: List[Collision]         # severity 'reject'
    advisories: List[Collision]
    shapes_new: int = 0


# ---- small geometry helpers ------------------------------------------------------------------------------------------------------------------
def _shoelace(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) if len(pts) >= 3 else 0.0


def _bbox_of(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_inter(a, b):
    return max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])


def _bbox_hit(a, b, pad=0.0):
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def _in_polygon(x, y, pts):
    inside, n = False, len(pts)
    for i in range(n):
        x1, y1, x2, y2 = pts[i][0], pts[i][1], pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def _dist_to_polygon_edge(x, y, pts):
    best = 1e9
    for i in range(len(pts)):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = x2 - x1, y2 - y1
        t = 0 if dx == dy == 0 else max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


def inside_region(s: Shape, x: float, y: float, shrink: float = 0.0) -> bool:
    """Is the point inside the region, at least `shrink` px away from its edge (shrink 0 = the region itself)."""
    if s.kind == "rect":
        rx, ry, rw, rh = s.params
        return rx + shrink <= x <= rx + rw - shrink and ry + shrink <= y <= ry + rh - shrink
    if s.kind == "ellipse":
        cx, cy, a, b = s.params
        a, b = a - shrink, b - shrink
        return a > 0 and b > 0 and ((x - cx) / a) ** 2 + ((y - cy) / b) ** 2 <= 1.0
    if s.kind == "polygon":
        return _in_polygon(x, y, s.pts) and (shrink <= 0 or _dist_to_polygon_edge(x, y, s.pts) >= shrink)
    return False


def region_overlap_area(a: Shape, b: Shape) -> float:
    """Area covered by both regions: exact for two rectangles, otherwise counted on a grid capped at about 6000 points."""
    ib = _bbox_inter(a.bbox, b.bbox)
    if ib[2] <= ib[0] or ib[3] <= ib[1]:
        return 0.0
    if a.kind == "rect" and b.kind == "rect":
        return (ib[2] - ib[0]) * (ib[3] - ib[1])
    box = (ib[2] - ib[0]) * (ib[3] - ib[1])
    step = max(1.5, math.sqrt(box / 6000.0))
    n, x = 0, ib[0] + step / 2
    while x < ib[2]:
        y = ib[1] + step / 2
        while y < ib[3]:
            if inside_region(a, x, y) and inside_region(b, x, y):
                n += 1
            y += step
        x += step
    return n * step * step


# ---- text boxes --------------------------------------------------------------------------------------------------------------------------------
def text_box(x, y, text, size, anchor, bold=False):
    w = len(text) * size * (BOLD_WIDTH_FACTOR if bold else TEXT_WIDTH_FACTOR)
    x0 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
    return (x0, y - size * 0.85, x0 + w, y + size * 0.25)


# ---- path flattening ---------------------------------------------------------------------------------------------------------------------------
_CMD = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)")
_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}


def _bezier(p0, c1, c2, p1, step=4.0):
    length = math.dist(p0, c1) + math.dist(c1, c2) + math.dist(c2, p1)
    n = max(4, int(length / step))
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0],
                    u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1]))
    return out


def _arc(p0, rx, ry, phi, large, sweep, p1):
    """SVG elliptical arc (endpoint form) flattened to points (standard endpoint-to-centre conversion)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry, phi_r = abs(rx), abs(ry), math.radians(phi)
    cp, sp = math.cos(phi_r), math.sin(phi_r)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    co = (0 if den == 0 else math.sqrt(max(0, num / den))) * (-1 if large == sweep else 1)
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx, cy = cp * cxp - sp * cyp + (p0[0] + p1[0]) / 2, sp * cxp + cp * cyp + (p0[1] + p1[1]) / 2
    ang = lambda ux, uy, vx, vy: math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(6, int(abs(dt) * max(rx, ry) / 4))
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
    return out


def flatten_path(d: str):
    """(list of subpaths as point lists, closed flags). Curves and arcs become short straight pieces (about 4 px). A path must start with M."""
    subs, closed = [], []
    cur, start, last_c, last_q = (0.0, 0.0), (0.0, 0.0), None, None
    pts = None
    for cmd, args in _CMD.findall(d or ""):
        c, rel = cmd.lower(), cmd.islower()
        nums = [float(n) for n in _NUM.findall(args)]
        if c == "z":
            if pts is not None:
                closed[-1] = True
                cur = start
            continue
        k = _ARGS[c]
        i, first = 0, True
        while i + k <= len(nums):
            a = nums[i:i + k]
            i += k
            ox, oy = cur
            op = "l" if (c == "m" and not first) else c
            first = False
            if op == "m":
                cur = (ox + a[0], oy + a[1]) if rel else (a[0], a[1])
                start, pts = cur, [cur]
                subs.append(pts)
                closed.append(False)
                last_c = last_q = None
                continue
            if pts is None:
                break                                                     # drawing before any M: not a path we can read
            if op == "l":
                cur = (ox + a[0], oy + a[1]) if rel else (a[0], a[1])
                pts.append(cur)
                last_c = last_q = None
            elif op == "h":
                cur = (ox + a[0], oy) if rel else (a[0], oy)
                pts.append(cur)
                last_c = last_q = None
            elif op == "v":
                cur = (ox, oy + a[0]) if rel else (ox, a[0])
                pts.append(cur)
                last_c = last_q = None
            elif op in ("c", "s"):
                if op == "c":
                    c1, c2, p1 = [(ox + a[j], oy + a[j + 1]) if rel else (a[j], a[j + 1]) for j in (0, 2, 4)]
                else:
                    c1 = (2 * ox - last_c[0], 2 * oy - last_c[1]) if last_c else cur
                    c2, p1 = [(ox + a[j], oy + a[j + 1]) if rel else (a[j], a[j + 1]) for j in (0, 2)]
                pts.extend(_bezier(cur, c1, c2, p1))
                cur, last_c, last_q = p1, c2, None
            elif op in ("q", "t"):
                if op == "q":
                    q1, p1 = [(ox + a[j], oy + a[j + 1]) if rel else (a[j], a[j + 1]) for j in (0, 2)]
                else:
                    q1 = (2 * ox - last_q[0], 2 * oy - last_q[1]) if last_q else cur
                    p1 = (ox + a[0], oy + a[1]) if rel else (a[0], a[1])
                c1 = (cur[0] + 2 / 3 * (q1[0] - cur[0]), cur[1] + 2 / 3 * (q1[1] - cur[1]))
                c2 = (p1[0] + 2 / 3 * (q1[0] - p1[0]), p1[1] + 2 / 3 * (q1[1] - p1[1]))
                pts.extend(_bezier(cur, c1, c2, p1))
                cur, last_q, last_c = p1, q1, None
            elif op == "a":
                p1 = (ox + a[5], oy + a[6]) if rel else (a[5], a[6])
                pts.extend(_arc(cur, a[0], a[1], a[2], bool(a[3]), bool(a[4]), p1))
                cur, last_c, last_q = p1, None, None
    return [s for s in subs if len(s) >= 2], [c for s, c in zip(subs, closed) if len(s) >= 2]


# ---- extraction --------------------------------------------------------------------------------------------------------------------------------
def _local(tag):
    return tag.split("}")[-1]


def _f(el, name, default=0.0):
    try:
        return float(re.sub(r"[a-z%]+$", "", (el.get(name) or "").strip()) or default)
    except ValueError:
        return default


def _num(v, default=0.0):
    try:
        return float(re.sub(r"[^\d.\-]", "", str(v)) or default) if v is not None else default
    except ValueError:
        return default


def _marker_ids(el):
    ids = []
    for name in ("marker-start", "marker-end"):
        m = re.search(r"url\(#([\w\-.:]+)\)", el.get(name) or "")
        if m:
            ids.append((name, m.group(1)))
    return ids


def _head(tip, back, sw, board):
    """Arrow head polygon at `tip`, pointing away from `back`. The board's markers have a known shape; any other marker gets a generic triangle."""
    dx, dy = tip[0] - back[0], tip[1] - back[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    scale = _HEAD_SCALE * sw if board else 0.6 * sw
    pts = _HEAD_UNIT if board else [(-10.0, -5.0), (0.0, 0.0), (-10.0, 5.0)]
    return [(tip[0] + (px * ux - py * uy) * scale, tip[1] + (px * uy + py * ux) * scale) for px, py in pts]


def _point_back(pts, dist, from_end=True):
    seq = list(reversed(pts)) if from_end else list(pts)
    acc = 0.0
    for i in range(1, len(seq)):
        acc += math.dist(seq[i - 1], seq[i])
        if acc >= dist:
            return seq[i]
    return seq[-1]


def extract_shapes(svg: str, start_index: int = 0) -> List[Shape]:
    """Every drawn shape of an SVG fragment (or of a whole page: the stored page is a run of <g> elements), in document order."""
    text = svg.strip() if svg else ""
    if not text:
        return []
    root = ET.fromstring(text) if text.startswith("<svg") else ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg">' + text + "</svg>")
    out: List[Shape] = []

    def style_of(el, parent):
        st = dict(parent)
        for k in ("fill", "fill-opacity", "stroke", "stroke-width", "font-size", "text-anchor", "font-weight"):
            if el.get(k) is not None:
                st[k] = el.get(k)
        if _local(el.tag) == "g" and el.get("opacity") is not None:
            st["gop"] = st.get("gop", 1.0) * _num(el.get("opacity"), 1.0)
        return st

    def eff_opacity(st, el):
        gop = st.get("gop", 1.0)
        if RENDERER_DROPS_SHAPE_OPACITY:
            return gop
        return gop * _num(el.get("opacity"), 1.0) * _num(st.get("fill-opacity"), 1.0)

    def add(s: Shape):
        s.index = start_index + len(out)
        out.append(s)

    def walk(el, parent_style, element_id):
        tag = _local(el.tag)
        if tag in ("defs", "marker", "style", "title", "desc", "linearGradient", "radialGradient", "filter"):
            return
        st = style_of(el, parent_style)
        if tag == "g":
            eid = element_id or el.get("id") or ""
            for child in el:
                walk(child, st, eid)
            return
        sw = _num(st.get("stroke-width"), 1.0) if st.get("stroke", "none") != "none" else 0.0
        fill = st.get("fill", "")
        has_fill = bool(fill) and fill not in ("none", "transparent")      # no fill attribute = unfilled (what the board's renderer draws)
        opac = eff_opacity(st, el)
        if tag == "rect":
            x, y, w, h = _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
            if w > 0 and h > 0:
                add(Shape(0, element_id or "", tag, "rect", bbox=(x, y, x + w, y + h), params=(x, y, w, h), stroke_w=sw, has_fill=has_fill, opacity=opac))
        elif tag in ("circle", "ellipse"):
            cx, cy = _f(el, "cx"), _f(el, "cy")
            rx, ry = (_f(el, "r"),) * 2 if tag == "circle" else (_f(el, "rx"), _f(el, "ry"))
            if rx > 0 and ry > 0:
                add(Shape(0, element_id or "", tag, "ellipse", bbox=(cx - rx, cy - ry, cx + rx, cy + ry), params=(cx, cy, rx, ry), stroke_w=sw, has_fill=has_fill, opacity=opac))
        elif tag == "polygon":
            nums = [float(n) for n in _NUM.findall(el.get("points") or "")]
            pts = list(zip(nums[0::2], nums[1::2]))
            if len(pts) >= 3:
                add(Shape(0, element_id or "", tag, "polygon", bbox=_bbox_of(pts), pts=pts, stroke_w=sw, has_fill=has_fill, opacity=opac))
        elif tag in ("line", "polyline", "path"):
            if tag == "line":
                subs, closed = [[(_f(el, "x1"), _f(el, "y1")), (_f(el, "x2"), _f(el, "y2"))]], [False]
            elif tag == "polyline":
                nums = [float(n) for n in _NUM.findall(el.get("points") or "")]
                subs, closed = [list(zip(nums[0::2], nums[1::2]))], [False]
            else:
                subs, closed = flatten_path(el.get("d") or "")
            markers = _marker_ids(el)
            for pts, is_closed in zip(subs, closed):
                if len(pts) < 2:
                    continue
                if tag == "path" and not markers and len(pts) >= 3 and (is_closed or has_fill):
                    add(Shape(0, element_id or "", tag, "polygon", bbox=_bbox_of(pts), pts=pts, stroke_w=sw, has_fill=has_fill, opacity=opac))
                    continue
                sh = Shape(0, element_id or "", tag, "connector", role="connector", bbox=_bbox_of(pts), pts=pts, stroke_w=max(sw, 1.0), opacity=opac,
                           marker=[m for _, m in markers], marker_ends=list(markers))
                for name, mid in markers:
                    board = mid in BOARD_MARKERS
                    if name == "marker-end":
                        sh.heads.append(_head(pts[-1], _point_back(pts, 6.0), sh.stroke_w, board))
                    else:
                        sh.heads.append(_head(pts[0], _point_back(pts, 6.0, from_end=False), sh.stroke_w, board))
                add(sh)
        elif tag == "text":
            size = _num(st.get("font-size"), 16.0) or 16.0
            anchor = el.get("text-anchor") or st.get("text-anchor") or "start"
            tspans = [t for t in el if _local(t.tag) == "tspan"]
            x, y = _f(el, "x"), _f(el, "y")
            lines = []
            if tspans:
                for t in tspans:
                    x = _f(t, "x", x) if t.get("x") is not None else x
                    y = y + _f(t, "dy") if t.get("dy") is not None else (_f(t, "y", y) if t.get("y") is not None else y)
                    body = re.sub(r"\s+", " ", "".join(t.itertext())).strip()
                    if body:
                        lines.append((x, y, body))
            else:
                body = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
                if body:
                    lines.append((x, y, body))
            for lx, ly, body in lines:
                bold = bool(re.search(r"bold|[6-9]00", str(st.get("font-weight", ""))))
                bx = text_box(lx, ly, body, size, anchor, bold)
                add(Shape(0, element_id or "", "text", "text", role="label", bbox=bx, text=body, size=size, opacity=opac, anchor=anchor))

    for child in root:
        walk(child, {}, None)
    return out


# ---- roles -------------------------------------------------------------------------------------------------------------------------------------
def classify(shapes: List[Shape]) -> None:
    """Roles from geometry only. A region is a 'container' when it fully holds two or more other regions, or one that is at least MARKER_RATIO of its own area
    (a frame or panel with content); a ring with a single small dot inside is still a 'node'. Thin regions are 'decoration', the rest are 'node'."""
    regions = [s for s in shapes if s.kind in ("rect", "ellipse", "polygon")]
    for r in regions:
        if min(r.w, r.h) < THIN:
            r.role = "decoration"
    big = [r for r in regions if r.role != "decoration"]
    for r in big:
        r.role = "node"
        held = []
        for s in big:
            if s is r or s.area * 1.25 > r.area or not (r.bbox[0] - 1 <= s.bbox[0] and r.bbox[1] - 1 <= s.bbox[1] and s.bbox[2] <= r.bbox[2] + 1 and s.bbox[3] <= r.bbox[3] + 1):
                continue
            if region_overlap_area(r, s) >= 0.98 * s.area:
                held.append(s)
        if len(held) >= 2 or any(s.area >= MARKER_RATIO * r.area for s in held):
            r.role = "container"


# ---- rules -------------------------------------------------------------------------------------------------------------------------------------
def _connector_samples(c: Shape):
    pts = c.pts
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        L = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(L / SAMPLE_STEP))
        for i in range(n):
            t = (i + 0.5) / n
            yield x1 + (x2 - x1) * t, y1 + (y2 - y1) * t


def _length_inside(c: Shape, test) -> float:
    return sum(SAMPLE_STEP for x, y in _connector_samples(c) if test(x, y))


def _nearest_edge_point(r: Shape, x, y):
    if r.kind == "rect":
        rx, ry, rw, rh = r.params
        cx, cy = min(max(x, rx), rx + rw), min(max(y, ry), ry + rh)
        if rx < x < rx + rw and ry < y < ry + rh:
            d = {"l": x - rx, "r": rx + rw - x, "t": y - ry, "b": ry + rh - y}
            k = min(d, key=d.get)
            return {"l": (rx, y), "r": (rx + rw, y), "t": (x, ry), "b": (x, ry + rh)}[k]
        return cx, cy
    cx, cy, a, b = r.params if r.kind == "ellipse" else ((r.bbox[0] + r.bbox[2]) / 2, (r.bbox[1] + r.bbox[3]) / 2, r.w / 2, r.h / 2)
    ang = math.atan2((y - cy) / (b or 1), (x - cx) / (a or 1))
    return cx + a * math.cos(ang), cy + b * math.sin(ang)


def _crossing_point(c: Shape, r: Shape):
    """Where the connector first crosses the edge of the region (so a message can say 'start it here'); the nearest edge point if it never crosses."""
    prev = None
    for x, y in _connector_samples(c):
        now = inside_region(r, x, y)
        if prev is not None and now != prev:
            return round(x, 1), round(y, 1)
        prev = now
    return _nearest_edge_point(r, *c.pts[0])


def _poly_area_inside(poly, test, step=1.5) -> float:
    x0, y0, x1, y1 = _bbox_of(poly)
    n, x = 0, x0 + step / 2
    while x < x1:
        y = y0 + step / 2
        while y < y1:
            if _in_polygon(x, y, poly) and test(x, y):
                n += 1
            y += step
        x += step
    return n * step * step


def find_collisions(shapes: List[Shape]) -> List[Collision]:
    """All collisions on a page, by the rules of docs/VALIDATOR_DESIGN.md. Depends only on the shapes (their geometry, style and paint order)."""
    classify(shapes)
    labels = [s for s in shapes if s.role == "label"]
    regions = [s for s in shapes if s.role in ("node", "container", "decoration")]
    solid = [s for s in regions if s.role != "decoration"]
    nodes = [s for s in regions if s.role in ("node", "decoration")]
    conns = [s for s in shapes if s.role == "connector"]
    out: List[Collision] = []

    # label against label
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            ib = _bbox_inter(a.bbox, b.bbox)
            if ib[2] > ib[0] and ib[3] > ib[1]:
                frac = (ib[2] - ib[0]) * (ib[3] - ib[1]) / max(1e-9, min(a.w * a.h, b.w * b.h))
                if frac > LABEL_OVERLAP:
                    out.append(Collision("label_label", "reject", a, b, f"{frac:.0%} of the smaller label", {"fraction": frac}))

    # label against region
    for l in labels:
        lb = l.bbox
        for r in solid:
            if not _bbox_hit(lb, r.bbox):
                continue
            n, tot, step = 0, 0, max(1.0, min(l.w, l.h) / 6)
            x = lb[0] + step / 2
            while x < lb[2]:
                y = lb[1] + step / 2
                while y < lb[3]:
                    tot += 1
                    n += inside_region(r, x, y)
                    y += step
                x += step
            f_in = n / max(1, tot)
            if f_in <= 0.02:
                continue
            centre_in = inside_region(r, (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2)
            if f_in >= LABEL_INSIDE:
                if r.index > l.index and not r.see_through:
                    out.append(Collision("label_covered", "reject", l, r, "the box is drawn after the label and hides it", {"fraction": f_in}))
            elif centre_in:
                out.append(Collision("label_overflow", "advisory", l, r, f"{f_in:.0%} of the label is inside, the rest sticks out", {"fraction": f_in}))
            else:
                out.append(Collision("label_straddles_region", "reject", l, r, f"{f_in:.0%} of the label is inside the {r.role}", {"fraction": f_in}))

    # region against region
    for i, a in enumerate(solid):
        for b in solid[i + 1:]:
            if not _bbox_hit(a.bbox, b.bbox):
                continue
            inter = region_overlap_area(a, b)
            small, large = (a, b) if a.area <= b.area else (b, a)
            if inter <= 0 or small.area <= 0:
                continue
            f = inter / small.area
            if f <= REGION_OVERLAP:
                continue
            if f >= 0.98 and small.area <= NEST_RATIO * large.area:
                continue                                                        # nesting: a box inside a frame
            top = a if a.index > b.index else b
            if small.area <= MARKER_RATIO * large.area and large.role != "container" and f < DUPLICATE_COVER:
                continue                                                        # a small marker on the edge of a node (the phone on the GPS circle)
            if f >= DUPLICATE_COVER and small.area >= DUPLICATE_SIZE * large.area:
                out.append(Collision("region_duplicate", "reject", a, b, f"stacked: {f:.0%} of the smaller is covered", {"fraction": f}))
            elif not top.see_through:
                out.append(Collision("region_overlap_hides", "reject", a, b, f"{f:.0%} of the smaller is covered by an opaque shape drawn later", {"fraction": f}))
            # else: the shape on top lets the one below show through (outline or translucent group): an intentional overlap such as a Venn diagram

    # connectors
    for c in conns:
        for r in nodes:
            if not _bbox_hit(c.bbox, r.bbox, pad=c.stroke_w):
                continue
            tol = max(ATTACH_BAND, c.stroke_w)
            inside = _length_inside(c, lambda x, y, r=r, tol=tol: inside_region(r, x, y, tol))
            if inside > INTERIOR_TOL:
                whole_inside = all(inside_region(r, x, y) for x, y in (c.pts[0], c.pts[-1]))
                if whole_inside and _length_inside(c, lambda x, y, r=r: not inside_region(r, x, y)) == 0:
                    continue                                                    # a short connector wholly inside one box (a glyph or axis inside a card)
                ex, ey = _crossing_point(c, r)
                out.append(Collision("connector_through_node", "reject", c, r, f"{inside:.0f} px of the line inside the box; it meets the box edge at ({ex:.0f},{ey:.0f})",
                                     {"length": inside, "edge_point": (ex, ey)}))
            for head in c.heads:
                area = _poly_area_inside(head, lambda x, y, r=r, tol=tol: inside_region(r, x, y, tol))
                if area > HEAD_AREA_TOL and not (all(inside_region(r, x, y) for x, y in (c.pts[0], c.pts[-1])) and inside > 0):
                    out.append(Collision("arrowhead_in_node", "reject", c, r, f"{area:.0f} px2 of the arrow head inside the box", {"area": area}))
        for l in labels:
            if not _bbox_hit(c.bbox, l.bbox, pad=c.stroke_w):
                continue
            box = (l.bbox[0] - 2, l.bbox[1] - 2, l.bbox[2] + 2, l.bbox[3] + 2)
            inside = _length_inside(c, lambda x, y, box=box: box[0] <= x <= box[2] and box[1] <= y <= box[3])
            if inside > LABEL_CROSS_TOL:
                out.append(Collision("connector_through_label", "advisory", c, l, f"{inside:.0f} px of the line inside the label", {"length": inside}))
            for head in c.heads:
                area = _poly_area_inside(head, lambda x, y, box=box: box[0] <= x <= box[2] and box[1] <= y <= box[3])
                if area > HEAD_AREA_TOL:
                    out.append(Collision("arrowhead_on_label", "advisory", c, l, f"{area:.0f} px2 of the arrow head on the label", {"area": area}))
    for i, a in enumerate(conns):
        for b in conns[i + 1:]:
            if not _bbox_hit(a.bbox, b.bbox, pad=max(a.stroke_w, b.stroke_w)):
                continue
            tol = max(a.stroke_w, b.stroke_w)
            near = _length_inside(a, lambda x, y, b=b: any(_dist_seg(x, y, p, q) <= tol for p, q in zip(b.pts, b.pts[1:])))
            if near > 20:
                out.append(Collision("connectors_overlap", "advisory", a, b, f"{near:.0f} px run on top of each other", {"length": near}))
    return out


def _dist_seg(x, y, p, q):
    dx, dy = q[0] - p[0], q[1] - p[1]
    t = 0 if dx == dy == 0 else max(0, min(1, ((x - p[0]) * dx + (y - p[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (p[0] + t * dx), y - (p[1] + t * dy))


# ---- shadow entry points -----------------------------------------------------------------------------------------------------------------------
def collisions_for_page(svg: str) -> List[Collision]:
    return find_collisions(extract_shapes(svg))


def shadow_check(existing_svg: Optional[str], new_fragment: str) -> ShadowResult:
    """What the PROPOSED validator would decide for a new fragment on a page. Collisions among shapes that were already on the page are not charged to the new call."""
    old = extract_shapes(existing_svg or "")
    new = extract_shapes(new_fragment, start_index=len(old))
    allc = find_collisions(old + new)
    n_old = len(old)
    mine = [c for c in allc if c.a.index >= n_old or (c.b is not None and c.b.index >= n_old)]
    reasons = [c for c in mine if c.severity == "reject"]
    return ShadowResult("reject" if reasons else "accept", reasons, [c for c in mine if c.severity != "reject"], len(new))
