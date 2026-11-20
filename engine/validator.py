"""
engine/validator.py
Page density check and SVG geometry validation for Learning Platform.

Two checks:
  1. check_density(current_svg, new_fragment)
     - Soft signal: >= SOFT_ELEMENT_COUNT named elements
     - Hard cap:    >= HARD_ELEMENT_COUNT (rejects the draw_new_element call)
     Coverage soft signal uses the union of element bboxes (compute_coverage);
     full-canvas background rects are excluded by extract_element_bboxes.

  2. validate_geometry(svg_fragment, existing_svg)
     - Parses x/y/width/height/cx/cy/r/x1/y1/x2/y2 attributes directly.
     - No Playwright browser launch per element — was adding ~10s per draw call.
     - Playwright is reserved for replay tests and visual verification tests only.

THRESHOLDS (SAD §3.5):
  SOFT_ELEMENT_COUNT  = 15
  HARD_ELEMENT_COUNT  = 25
"""

import html
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Thresholds (SAD §3.5)
# ---------------------------------------------------------------------------

SOFT_ELEMENT_COUNT  = 15
HARD_ELEMENT_COUNT  = 25
SOFT_COVERAGE       = 0.70   # fraction of canvas covered (union of element bboxes)
OVERLAP_REJECT      = 0.20   # new element may cover at most this share of the smaller bbox

CANVAS_WIDTH  = 1200
CANVAS_HEIGHT = 800

# One definition of "background frame", used by the draw guard, the measurements below and the tutor's prompt:
# a single shape covering this share of the board or more is a frame, whatever its proportions.
FRAME_CANVAS_FRACTION = 0.6
FRAME_PERCENT = round(FRAME_CANVAS_FRACTION * 100)


def is_background_frame(width: float, height: float) -> bool:
    return width * height >= FRAME_CANVAS_FRACTION * (CANVAS_WIDTH * CANVAS_HEIGHT)


# ---------------------------------------------------------------------------
# Element counting
# ---------------------------------------------------------------------------

_COUNTED_TAGS = {"rect", "circle", "ellipse", "line", "polyline", "polygon",
                 "path", "text", "image", "g"}


def count_named_elements(svg_content: str) -> int:
    """
    Counts SVG elements that have an id attribute and are in the counted-tag set.
    Raw wrapper <g> tags without ids are not counted.
    """
    pattern = re.compile(
        r'<(' + '|'.join(_COUNTED_TAGS) + r')\b[^>]*\bid\s*=\s*["\'][^"\']+["\'][^>]*>',
        re.IGNORECASE
    )
    return len(pattern.findall(svg_content))


# ---------------------------------------------------------------------------
# Density check
# ---------------------------------------------------------------------------

class DensityResult:
    def __init__(self, hard_cap: bool, soft_signal: bool, element_count: int, coverage: float = 0.0):
        self.hard_cap = hard_cap
        self.soft_signal = soft_signal
        self.element_count = element_count
        self.coverage = coverage

    def to_dict(self) -> dict:
        return {
            "hard_cap": self.hard_cap,
            "soft_signal": self.soft_signal,
            "element_count": self.element_count,
            "canvas_coverage": round(self.coverage, 3),
            "hard_cap_threshold": HARD_ELEMENT_COUNT,
            "soft_count_threshold": SOFT_ELEMENT_COUNT,
            "soft_coverage_threshold": SOFT_COVERAGE,
        }


def compute_coverage(svg: Optional[str]) -> float:
    """Fraction of the canvas covered by the union of named-element bboxes (grid-sampled)."""
    cols, rows = 60, 40
    cw, ch = CANVAS_WIDTH / cols, CANVAS_HEIGHT / rows
    filled = set()
    for el in extract_element_bboxes(svg):
        b = el["bbox"]
        x0, x1 = int(max(b["x"], 0) // cw), int(min(b["x"] + b["width"], CANVAS_WIDTH - 1) // cw)
        y0, y1 = int(max(b["y"], 0) // ch), int(min(b["y"] + b["height"], CANVAS_HEIGHT - 1) // ch)
        filled.update((i, j) for i in range(x0, x1 + 1) for j in range(y0, y1 + 1))
    return len(filled) / (cols * rows)


def check_overlap(existing_svg: Optional[str], fragment: str) -> Optional[dict]:
    """
    Returns {"new_id", "existing_id", "bbox"} for the first existing element the new
    fragment's top-level element mostly covers, else None. Thin shapes (connectors,
    underlines) are ignored; the agent may deliberately draw across boxes.
    """
    new_els = extract_element_bboxes(fragment)
    if not new_els:
        return None
    new = new_els[-1] if len(new_els) == 1 else max(new_els, key=lambda e: e["bbox"]["width"] * e["bbox"]["height"])
    nb = new["bbox"]
    for old in extract_element_bboxes(existing_svg):
        if old["element_id"] == new["element_id"]:
            continue
        ob = old["bbox"]
        if min(nb["width"], nb["height"], ob["width"], ob["height"]) < 20:
            continue
        iw = min(nb["x"] + nb["width"], ob["x"] + ob["width"]) - max(nb["x"], ob["x"])
        ih = min(nb["y"] + nb["height"], ob["y"] + ob["height"]) - max(nb["y"], ob["y"])
        if iw <= 0 or ih <= 0:
            continue
        smaller = min(nb["width"] * nb["height"], ob["width"] * ob["height"])
        if iw * ih / smaller > OVERLAP_REJECT:
            return {"new_id": new["element_id"], "existing_id": old["element_id"], "bbox": ob, "new_bbox": nb}
    return None


FREE_MARGIN, FREE_GAP, FREE_STEP = 20, 10, 10      # px: canvas margin kept free, gap kept around every existing element, grid size of the search


def find_free_region(existing_svg: Optional[str], width: float, height: float, near=None, ignore_id: Optional[str] = None) -> dict:
    """
    One free rectangle on the canvas for a drawing of width x height, computed from the existing elements (the same boxes check_overlap uses; shapes thinner than 20 px are
    ignored as there). A 10 px grid inside a 20 px margin, a 10 px gap around every element, then the free rectangles that are at least as large as the drawing; the LARGEST wins (a strip
    exactly as tall as the drawing leaves no margin for the model's coordinates), the one nearest `near` (the centre of where the model tried to draw) on a tie. Nothing is moved: this only describes room.
    Returns {"fits": bool, "x", "y", "width", "height" (px), "free_pct"}; when nothing fits, the region is the LARGEST free rectangle.
    """
    cols, rows = (CANVAS_WIDTH - 2 * FREE_MARGIN) // FREE_STEP, (CANVAS_HEIGHT - 2 * FREE_MARGIN) // FREE_STEP
    busy = [[False] * cols for _ in range(rows)]
    for el in extract_element_bboxes(existing_svg):
        if el["element_id"] == ignore_id:
            continue
        b = el["bbox"]
        if min(b["width"], b["height"]) < 20:
            continue
        x0, x1, y0, y1 = b["x"] - FREE_GAP, b["x"] + b["width"] + FREE_GAP, b["y"] - FREE_GAP, b["y"] + b["height"] + FREE_GAP
        for r in range(rows):
            cy = FREE_MARGIN + r * FREE_STEP
            if cy >= y1 or cy + FREE_STEP <= y0:
                continue
            for c in range(cols):
                cx = FREE_MARGIN + c * FREE_STEP
                if cx < x1 and cx + FREE_STEP > x0:
                    busy[r][c] = True
    free_pct = round(100 * sum(not v for row in busy for v in row) / (rows * cols))
    rects = []                                           # (left col, right col, top row, bottom row): the maximal free rectangles that end at each row
    heights = [0] * cols
    for r in range(rows):
        heights = [0 if busy[r][c] else heights[c] + 1 for c in range(cols)]
        stack = []                                       # (start col, height)
        for c in range(cols + 1):
            h = heights[c] if c < cols else 0
            start = c
            while stack and stack[-1][1] >= h:
                s, sh = stack.pop()
                if sh > 0:
                    rects.append((s, c - 1, r - sh + 1, r))
                start = s
            stack.append((start, h))

    def px(rc):
        l, rr, t, b = rc
        return FREE_MARGIN + l * FREE_STEP, FREE_MARGIN + t * FREE_STEP, (rr - l + 1) * FREE_STEP, (b - t + 1) * FREE_STEP
    fitting = [rc for rc in rects if px(rc)[2] >= width and px(rc)[3] >= height]
    if fitting:
        cx0, cy0 = near if near else (CANVAS_WIDTH / 2, CANVAS_HEIGHT / 2)
        best = min(fitting, key=lambda rc: (-px(rc)[2] * px(rc)[3], (px(rc)[0] + px(rc)[2] / 2 - cx0) ** 2 + (px(rc)[1] + px(rc)[3] / 2 - cy0) ** 2))
        x, y, w, h = px(best)
        return {"fits": True, "x": x, "y": y, "width": w, "height": h, "free_pct": free_pct}
    if rects:
        x, y, w, h = px(max(rects, key=lambda rc: px(rc)[2] * px(rc)[3]))
        return {"fits": False, "x": x, "y": y, "width": w, "height": h, "free_pct": free_pct}
    return {"fits": False, "x": 0, "y": 0, "width": 0, "height": 0, "free_pct": free_pct}


def check_density(current_svg: Optional[str], new_fragment: str) -> DensityResult:
    """
    Checks density AFTER the new fragment would be added.
    Soft signal: >= SOFT_ELEMENT_COUNT named elements OR >= SOFT_COVERAGE canvas coverage.
    Hard cap:    >= HARD_ELEMENT_COUNT named elements (draw call is rejected).
    Coverage is the union of group/shape bboxes (see compute_coverage), not a regex
    area estimate, so a composite element no longer inflates it.
    """
    total = count_named_elements(current_svg or "") + count_named_elements(new_fragment)
    coverage = compute_coverage((current_svg or "") + new_fragment)
    return DensityResult(
        hard_cap=total >= HARD_ELEMENT_COUNT,
        soft_signal=total >= SOFT_ELEMENT_COUNT or coverage >= SOFT_COVERAGE,
        element_count=total,
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Fast geometry validation — pure SVG attribute parsing (no Playwright)
# ---------------------------------------------------------------------------

def _attr(tag_str: str, name: str, default: float = 0.0) -> float:
    """Extract a numeric attribute from a tag string."""
    m = re.search(rf'\b{re.escape(name)}\s*=\s*["\']([0-9.\-]+)["\']', tag_str, re.IGNORECASE)
    return float(m.group(1)) if m else default


_PATH_ARGS = {"m": 2, "l": 2, "t": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "a": 7}
_PATH_D = re.compile(r'\bd\s*=\s*"([^"]*)"|\bd\s*=\s*\'([^\']*)\'', re.IGNORECASE)
_PATH_CMD = re.compile(r'([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)')
_NUM = re.compile(r'-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def _path_bounds(tag_str: str) -> Optional[tuple]:
    """(min_x, min_y, max_x, max_y) of a <path>'s d attribute; control points included."""
    m = _PATH_D.search(tag_str)
    if not m:
        return None
    xs, ys, cx, cy = [], [], 0.0, 0.0
    for cmd, args in _PATH_CMD.findall(m.group(1) or m.group(2)):
        k, rel, c = _PATH_ARGS.get(cmd.lower()), cmd.islower(), cmd.lower()
        if k is None:
            continue
        nums = [float(n) for n in _NUM.findall(args)]
        for i in range(0, len(nums) - k + 1, k):
            a = nums[i:i + k]
            if c == "h":
                cx = cx + a[0] if rel else a[0]
            elif c == "v":
                cy = cy + a[0] if rel else a[0]
            else:
                # arcs: only the endpoint (last pair); curves: every pair incl. control points
                pairs = [(a[-2], a[-1])] if c == "a" else list(zip(a[0::2], a[1::2]))
                bx, by = cx, cy
                for px, py in pairs:
                    xs.append(bx + px if rel else px)
                    ys.append(by + py if rel else py)
                cx, cy = xs[-1], ys[-1]
            xs.append(cx)
            ys.append(cy)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _check_bounds(eid: str, x: float, y: float, w: float, h: float) -> Optional[dict]:
    """Return a violation dict if the bounding box bleeds the canvas, else None."""
    if x < -10 or y < -10 or (x + w) > CANVAS_WIDTH + 10 or (y + h) > CANVAS_HEIGHT + 10:
        return {
            "element_id": eid,
            "detail": (
                f"Element bleeds canvas: x={x:.0f} y={y:.0f} "
                f"w={w:.0f} h={h:.0f} "
                f"(canvas {CANVAS_WIDTH}x{CANVAS_HEIGHT})"
            )
        }
    return None


_TEXT_RE = re.compile(r'<text\b([^>]*)>(.*?)</text>', re.IGNORECASE | re.DOTALL)
TEXT_OVERLAP_REJECT = 0.30


def _text_boxes(svg: str) -> list:
    """Estimated (id-less) boxes of <text> labels: width ~ 0.5em per char, height ~ 1.1em."""
    boxes = []
    for m in _TEXT_RE.finditer(svg):
        attrs, body = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if not body:
            continue
        size = _attr(attrs, "font-size", 14) or 14
        w, h = len(body) * size * 0.5, size * 1.1
        x, y = _attr(attrs, "x", 0), _attr(attrs, "y", 0)
        anchor = re.search(r'text-anchor\s*=\s*["\']([a-z]+)', attrs)
        anchor = anchor.group(1) if anchor else "start"
        x0 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
        boxes.append((x0, y - h * 0.8, x0 + w, y + h * 0.2, body))
    return boxes


def find_text_overlap(svg_fragment: str) -> Optional[tuple]:
    """First pair of labels in one fragment whose estimated boxes mostly cover each other."""
    boxes = _text_boxes(svg_fragment)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
            if iw <= 0 or ih <= 0:
                continue
            smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if iw * ih / smaller > TEXT_OVERLAP_REJECT:
                return a[4][:40], b[4][:40]
    return None


_RECT_RE = re.compile(r'<rect\b([^>]*)/?>', re.IGNORECASE)


def find_layout_issues(svg_fragment: str) -> list:
    """
    Non-blocking hints about drawings that look unfinished (generic geometry, no topic knowledge):
      - a card-sized rectangle with no label inside it
      - a large container whose bottom ~third is empty (sized for more items than were drawn)
    Returns at most 3 short sentences for the tutor to act on with modify_existing_element.
    """
    svg = re.sub(r'<(defs|marker|symbol|pattern|clipPath|mask)\b.*?</\1>', '', svg_fragment,
                 flags=re.IGNORECASE | re.DOTALL)
    rects = []
    for m in _RECT_RE.finditer(svg):
        a = m.group(1)
        x, y, w, h = _attr(a, "x"), _attr(a, "y"), _attr(a, "width"), _attr(a, "height")
        if is_background_frame(w, h):
            continue
        rects.append((x, y, w, h))
    texts = [(b[0], b[1], b[2], b[3]) for b in _text_boxes(svg)]

    def inside(px, py, r):
        return r[0] <= px <= r[0] + r[2] and r[1] <= py <= r[1] + r[3]

    def contains_rect(outer, inner):
        return (outer is not inner and inner[0] >= outer[0] and inner[1] >= outer[1]
                and inner[0] + inner[2] <= outer[0] + outer[2] and inner[1] + inner[3] <= outer[1] + outer[3])

    issues = []
    for r in rects:
        children = [c for c in rects if contains_rect(r, c)]
        label_inside = any(inside((t[0] + t[2]) / 2, (t[1] + t[3]) / 2, r) for t in texts)
        if r[2] >= 120 and r[3] >= 40 and not children and not label_inside:
            issues.append(f"The card at x={r[0]:.0f}, y={r[1]:.0f} ({r[2]:.0f}x{r[3]:.0f}) has no label inside it.")
        elif r[2] >= 200 and r[3] >= 200 and children:
            bottoms = [c[1] + c[3] for c in children] + [t[3] for t in texts if inside((t[0] + t[2]) / 2, (t[1] + t[3]) / 2, r)]
            empty = (r[1] + r[3] - max(bottoms)) / r[3]
            if empty > 0.30:
                issues.append(f"The container at x={r[0]:.0f}, y={r[1]:.0f} is {empty:.0%} empty at the bottom; "
                              "shrink it to fit its content or add the missing items.")
    return issues[:3]


# ---- text width: an ADVISORY estimate, never a rejection -------------------------------------------------------------------------
# The blocking checks measure a label with an older, cruder box (`_text_boxes`, and a fixed 80 px in `extract_element_bboxes`), so a long label
# that runs into the next element passes them. This estimate, characters x font size x 0.55, only produces a hint for the tutor.
TEXT_WIDTH_FACTOR = 0.55
DEFAULT_FONT_SIZE = 16
TEXT_FIT_TOLERANCE = 10          # px of slack before a label is said to run past its card
NEIGHBOUR_OVERLAP = 0.30         # share of the label's own box that must lie inside another element to say it runs into it


def estimate_text_width(text: str, font_size: float) -> float:
    return len(text) * font_size * TEXT_WIDTH_FACTOR


def find_text_width_issues(svg_fragment: str, existing_svg: Optional[str] = None) -> list:
    """
    Labels whose ESTIMATED width makes them run off the canvas, past the right edge of the card they start in, or into another element
    already on the page. [{"kind": "canvas"|"card"|"neighbour", "text", "width", "size", "over" (px, or the neighbour's id)}], in order.
    """
    svg = re.sub(r'<(defs|marker|symbol|pattern|clipPath|mask)\b.*?</\1>', '', svg_fragment or '', flags=re.IGNORECASE | re.DOTALL)
    rects = []
    for m in _RECT_RE.finditer(svg):
        a = m.group(1)
        x, y, w, h = _attr(a, "x"), _attr(a, "y"), _attr(a, "width"), _attr(a, "height")
        if w >= 40 and h >= 20 and not is_background_frame(w, h):
            rects.append((x, y, w, h))
    neighbours = extract_element_bboxes(existing_svg) if existing_svg else []
    issues = []
    for m in _TEXT_RE.finditer(svg):
        attrs, body = m.group(1), html.unescape(re.sub(r'<[^>]+>', '', m.group(2))).strip()
        if not body:
            continue
        size = _attr(attrs, "font-size", DEFAULT_FONT_SIZE) or DEFAULT_FONT_SIZE
        width, x, y = estimate_text_width(body, size), _attr(attrs, "x", 0), _attr(attrs, "y", 0)
        anchor = re.search(r'text-anchor\s*=\s*["\']([a-z]+)', attrs)
        anchor = anchor.group(1) if anchor else "start"
        x0 = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
        x1, top, bottom = x0 + width, y - size * 0.8, y + size * 0.2
        info = {"text": body, "width": round(width), "size": size}
        if x1 > CANVAS_WIDTH or x0 < 0:
            issues.append({**info, "kind": "canvas", "over": round(max(x1 - CANVAS_WIDTH, -x0))})
            continue
        px, py = min(x0 + 2, x1), (top + bottom) / 2
        cards = [r for r in rects if r[0] <= px <= r[0] + r[2] and r[1] <= py <= r[1] + r[3]]
        card = min(cards, key=lambda r: r[2] * r[3]) if cards else None
        if card and x1 > card[0] + card[2] + TEXT_FIT_TOLERANCE:
            issues.append({**info, "kind": "card", "over": round(x1 - (card[0] + card[2]))})
            continue
        area = max(1.0, width * (bottom - top))
        for e in neighbours:
            b = e["bbox"]
            iw = min(x1, b["x"] + b["width"]) - max(x0, b["x"])
            ih = min(bottom, b["y"] + b["height"]) - max(top, b["y"])
            if iw > 0 and ih > 0 and iw * ih / area > NEIGHBOUR_OVERLAP:
                issues.append({**info, "kind": "neighbour", "over": e["element_id"]})
                break
    return issues


def find_text_width_hints(svg_fragment: str, existing_svg: Optional[str] = None) -> list:
    """The width issues as short sentences for the tutor (advisory, at most 3)."""
    out = []
    for i in find_text_width_issues(svg_fragment, existing_svg)[:3]:
        label = i["text"] if len(i["text"]) <= 40 else i["text"][:37] + "..."
        head = f'The label "{label}" is about {i["width"]} px wide at font size {i["size"]:g} and'
        if i["kind"] == "canvas":
            out.append(f'{head} runs off the edge of the canvas by about {i["over"]} px.')
        elif i["kind"] == "card":
            out.append(f'{head} runs past the right edge of its card by about {i["over"]} px.')
        else:
            out.append(f"{head} runs into '{i['over']}'.")
    return out


_TAG_RE = re.compile(r"<([a-zA-Z][A-Za-z0-9:_-]*)(?:\s|/|>)([^>]*)>")
_TRANSFORM_RE = re.compile(r"(?<![A-Za-z0-9_-])transform\s*=")


def find_transform(svg_fragment: str) -> Optional[str]:
    """
    Name of the first tag carrying a `transform` attribute, else None. Every measurement in this module
    (bounds, overlap, coverage, text boxes) reads plain coordinates, so a transformed shape would be
    measured in the wrong place. Only attributes inside tags are checked, not text content.
    """
    for m in _TAG_RE.finditer(svg_fragment):
        if _TRANSFORM_RE.search(m.group(0)):
            return m.group(1)
    return None


def has_text_less_card(svg_fragment: str) -> bool:
    """
    True if the fragment has a card-sized rectangle (at least 120x60, not a background frame) and no <text> at all.
    This used to REJECT the drawing ("every card must include text labels"). It now only feeds a log note: the rule
    was a content rule, and legitimate drawings trip it (a label drawn as its own element, bars, cells, plot areas).
    """
    has_card = any(
        _attr(t, "width") >= 120 and _attr(t, "height") >= 60 and not is_background_frame(_attr(t, "width"), _attr(t, "height"))
        for t in re.findall(r'<rect\b[^>]*>', svg_fragment, re.IGNORECASE)
    )
    return has_card and not re.search(r'<text\b[^>]*>', svg_fragment, re.IGNORECASE)


def validate_geometry(svg_fragment: str, existing_svg: Optional[str] = None) -> dict:
    """
    Validates that all named elements in svg_fragment fit within the canvas.
    Uses direct SVG attribute parsing — no Playwright browser launch.

    Returns:
      { "valid": bool, "violations": [{ "element_id": str, "detail": str }] }

    Tolerates ±10px bleed for minor coordinate rounding from the LLM.
    Background frames (see is_background_frame) are skipped
    — they are cosmetic framing elements, not content.
    """
    violations = []

    # Tokenize the fragment into individual opening tags
    tag_pattern = re.compile(
        r'<(rect|circle|ellipse|line|polyline|polygon|path|text)\b[^>]*/?>',
        re.IGNORECASE | re.DOTALL
    )

    for m in tag_pattern.finditer(svg_fragment):
        tag_str = m.group(0)
        tag     = m.group(1).lower()

        # Children of composite <g id> elements carry no id of their own; check them all
        eid_m = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', tag_str, re.IGNORECASE)
        eid = eid_m.group(1) if eid_m else f"<{tag}> inside fragment"

        if tag == "text":
            v = _check_bounds(eid, _attr(tag_str, "x", 0), _attr(tag_str, "y", 0) - 14, 0, 14)
            if v:
                violations.append(v)
            continue

        if tag == "rect":
            x = _attr(tag_str, "x", 0)
            y = _attr(tag_str, "y", 0)
            w = _attr(tag_str, "width", 0)
            h = _attr(tag_str, "height", 0)
            # Skip cosmetic full-canvas frames
            if is_background_frame(w, h):
                continue
            v = _check_bounds(eid, x, y, w, h)
            if v:
                violations.append(v)

        elif tag == "circle":
            cx = _attr(tag_str, "cx", 0)
            cy = _attr(tag_str, "cy", 0)
            r  = _attr(tag_str, "r", 0)
            v  = _check_bounds(eid, cx - r, cy - r, r * 2, r * 2)
            if v:
                violations.append(v)

        elif tag == "ellipse":
            cx = _attr(tag_str, "cx", 0)
            cy = _attr(tag_str, "cy", 0)
            rx = _attr(tag_str, "rx", 0)
            ry = _attr(tag_str, "ry", 0)
            v  = _check_bounds(eid, cx - rx, cy - ry, rx * 2, ry * 2)
            if v:
                violations.append(v)

        elif tag == "line":
            x1 = _attr(tag_str, "x1", 0)
            y1 = _attr(tag_str, "y1", 0)
            x2 = _attr(tag_str, "x2", 0)
            y2 = _attr(tag_str, "y2", 0)
            x  = min(x1, x2)
            y  = min(y1, y2)
            w  = abs(x2 - x1)
            h  = abs(y2 - y1)
            v  = _check_bounds(eid, x, y, w, h)
            if v:
                violations.append(v)

        elif tag in ("polyline", "polygon"):
            pts_m = re.search(r'\bpoints\s*=\s*["\']([^"\']+)["\']', tag_str, re.IGNORECASE)
            if pts_m:
                coords = [float(c) for c in re.findall(r'[0-9.\-]+', pts_m.group(1))]
                if len(coords) >= 4:
                    xs = coords[0::2]
                    ys = coords[1::2]
                    v  = _check_bounds(eid, min(xs), min(ys),
                                       max(xs) - min(xs), max(ys) - min(ys))
                    if v:
                        violations.append(v)

        elif tag == "path":
            pb = _path_bounds(tag_str)
            if pb:
                v = _check_bounds(eid, pb[0], pb[1], pb[2] - pb[0], pb[3] - pb[1])
                if v:
                    violations.append(v)

    # (A card with no <text> in the same drawing used to be rejected here. That was a content rule, and it rejected
    #  legitimate drawings: see has_text_less_card, which only logs a note now.)

    clash = find_text_overlap(svg_fragment)
    if clash:
        violations.append({
            "element_id": "text_overlap",
            "detail": f'Labels "{clash[0]}" and "{clash[1]}" overlap each other. Give each label its own space (spacing, smaller font, or wider box).'
        })

    return {"valid": len(violations) == 0, "violations": violations}


# ---------------------------------------------------------------------------
# Spatial Memory & Layout Extraction (Phase B)
# ---------------------------------------------------------------------------

def extract_element_bboxes(svg_content: Optional[str]) -> list:
    """
    Extracts the bounding box and layout zone for each named element in the SVG.
    Handles both group elements <g id="...">...</g> and standalone elements with ids.
    Filters out background frames (see is_background_frame).
    """
    if not svg_content:
        return []
    # defs/markers/patterns/clips hold reusable parts, not rendered geometry
    svg_content = re.sub(r'<(defs|marker|symbol|pattern|clipPath|mask)\b.*?</\1>', '', svg_content,
                         flags=re.IGNORECASE | re.DOTALL)

    results = []
    seen_ids = set()

    group_pattern = re.compile(
        r'<g\b([^>]*\bid\s*=\s*["\']([^"\']+)["\'][^>]*)>(.*?)</g>',
        re.IGNORECASE | re.DOTALL
    )

    tag_pattern = re.compile(
        r'<(rect|circle|ellipse|line|polyline|polygon|path|text)\b([^>]*)/?>',
        re.IGNORECASE | re.DOTALL
    )

    def _get_shape_bounds(tag: str, tag_str: str) -> Optional[tuple]:
        if tag == "rect":
            w = _attr(tag_str, "width", 0)
            h = _attr(tag_str, "height", 0)
            if is_background_frame(w, h):
                return None
            x = _attr(tag_str, "x", 0)
            y = _attr(tag_str, "y", 0)
            return (x, y, x + w, y + h)
        elif tag == "circle":
            cx = _attr(tag_str, "cx", 0)
            cy = _attr(tag_str, "cy", 0)
            r = _attr(tag_str, "r", 0)
            return (cx - r, cy - r, cx + r, cy + r)
        elif tag == "ellipse":
            cx = _attr(tag_str, "cx", 0)
            cy = _attr(tag_str, "cy", 0)
            rx = _attr(tag_str, "rx", 0)
            ry = _attr(tag_str, "ry", 0)
            return (cx - rx, cy - ry, cx + rx, cy + ry)
        elif tag == "line":
            x1 = _attr(tag_str, "x1", 0)
            y1 = _attr(tag_str, "y1", 0)
            x2 = _attr(tag_str, "x2", 0)
            y2 = _attr(tag_str, "y2", 0)
            return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        elif tag in ("polyline", "polygon"):
            pts_m = re.search(r'\bpoints\s*=\s*["\']([^"\']+)["\']', tag_str, re.IGNORECASE)
            if pts_m:
                coords = [float(c) for c in re.findall(r'[0-9.\-]+', pts_m.group(1))]
                if len(coords) >= 4:
                    xs, ys = coords[0::2], coords[1::2]
                    return (min(xs), min(ys), max(xs), max(ys))
        elif tag == "path":
            return _path_bounds(tag_str)
        elif tag == "text":
            x = _attr(tag_str, "x", 0)
            y = _attr(tag_str, "y", 0)
            return (x, y - 16, x + 80, y + 4)
        return None

    def _determine_zone(x: float, y: float, w: float, h: float) -> str:
        cx = x + w / 2
        cy = y + h / 2
        if y < 100 and h < 80:
            return f"Header Zone (x:{x:.0f}-{x+w:.0f}, y:{y:.0f}-{y+h:.0f})"
        col = "Left Column" if cx < 400 else ("Center Column" if cx < 800 else "Right Column")
        row = "Top Row" if cy < 420 else "Bottom Row"
        return f"{col}, {row} (x:{x:.0f}-{x+w:.0f}, y:{y:.0f}-{y+h:.0f})"

    for gm in group_pattern.finditer(svg_content):
        eid = gm.group(2)
        inner = gm.group(3)
        seen_ids.add(eid)

        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        found_any = False
        for sm in tag_pattern.finditer(inner):
            stag = sm.group(1).lower()
            bounds = _get_shape_bounds(stag, sm.group(0))
            if bounds:
                b_min_x, b_min_y, b_max_x, b_max_y = bounds
                min_x = min(min_x, b_min_x)
                min_y = min(min_y, b_min_y)
                max_x = max(max_x, b_max_x)
                max_y = max(max_y, b_max_y)
                found_any = True

        if found_any and max_x > min_x and max_y > min_y:
            w = round(max_x - min_x, 1)
            h = round(max_y - min_y, 1)
            x = round(min_x, 1)
            y = round(min_y, 1)
            results.append({
                "element_id": eid,
                "bbox": {"x": x, "y": y, "width": w, "height": h},
                "zone": _determine_zone(x, y, w, h)
            })

    for sm in tag_pattern.finditer(svg_content):
        tag_str = sm.group(0)
        stag = sm.group(1).lower()
        id_m = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', tag_str, re.IGNORECASE)
        if not id_m:
            continue
        eid = id_m.group(1)
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        bounds = _get_shape_bounds(stag, tag_str)
        if bounds:
            b_min_x, b_min_y, b_max_x, b_max_y = bounds
            w = round(b_max_x - b_min_x, 1)
            h = round(b_max_y - b_min_y, 1)
            x = round(b_min_x, 1)
            y = round(b_min_y, 1)
            results.append({
                "element_id": eid,
                "bbox": {"x": x, "y": y, "width": w, "height": h},
                "zone": _determine_zone(x, y, w, h)
            })

    return results


def summarize_spatial_layout(occupied_elements: list) -> str:
    """
    Summarizes occupied zones and suggests open canvas space.
    """
    if not occupied_elements:
        return (
            "Canvas is completely empty. Free to use any zone:\n"
            "- Header Zone: x: 50-1150, y: 30-90\n"
            "- Left Column: x: 60-380, y: 120-720\n"
            "- Center Column: x: 420-780, y: 120-720\n"
            "- Right Column: x: 820-1140, y: 120-720"
        )

    cols_used = {"Left Column": [], "Center Column": [], "Right Column": []}
    for item in occupied_elements:
        zone = item.get("zone", "")
        eid = item.get("element_id", "unnamed")
        if "Left Column" in zone:
            cols_used["Left Column"].append(eid)
        elif "Center Column" in zone:
            cols_used["Center Column"].append(eid)
        elif "Right Column" in zone:
            cols_used["Right Column"].append(eid)

    recommendations = []
    if not cols_used["Left Column"]:
        recommendations.append("Left Column (x: 60-380, y: 120-720) is OPEN")
    if not cols_used["Center Column"]:
        recommendations.append("Center Column (x: 420-780, y: 120-720) is OPEN")
    if not cols_used["Right Column"]:
        recommendations.append("Right Column (x: 820-1140, y: 120-720) is OPEN")

    if not recommendations:
        recommendations.append("All main columns have content; check bounding boxes and place new elements in bottom row or vertical gaps.")

    return "; ".join(recommendations)

