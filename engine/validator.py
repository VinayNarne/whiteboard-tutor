"""
engine/validator.py
What is on the board, measured from its SVG: the union of element bounding boxes (the page's canvas coverage), each element's box, and a short
text summary of the occupied and free space.
"""

import re
from typing import Optional

_LEFT_COL, _CENTER_COL, _RIGHT_COL = "Left Column", "Center Column", "Right Column"


CANVAS_WIDTH  = 1200
CANVAS_HEIGHT = 800


# One definition of "background frame", used by the measurements below:
# a single shape covering this share of the board or more is a frame, whatever its proportions.
FRAME_CANVAS_FRACTION = 0.6


def is_background_frame(width: float, height: float) -> bool:
    return width * height >= FRAME_CANVAS_FRACTION * (CANVAS_WIDTH * CANVAS_HEIGHT)


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
        center_or_right = _CENTER_COL if cx < 800 else _RIGHT_COL
        col = _LEFT_COL if cx < 400 else center_or_right
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

    cols_used = {_LEFT_COL: [], _CENTER_COL: [], _RIGHT_COL: []}
    for item in occupied_elements:
        zone = item.get("zone", "")
        eid = item.get("element_id", "unnamed")
        if _LEFT_COL in zone:
            cols_used[_LEFT_COL].append(eid)
        elif _CENTER_COL in zone:
            cols_used[_CENTER_COL].append(eid)
        elif _RIGHT_COL in zone:
            cols_used[_RIGHT_COL].append(eid)

    recommendations = []
    if not cols_used[_LEFT_COL]:
        recommendations.append("Left Column (x: 60-380, y: 120-720) is OPEN")
    if not cols_used[_CENTER_COL]:
        recommendations.append("Center Column (x: 420-780, y: 120-720) is OPEN")
    if not cols_used[_RIGHT_COL]:
        recommendations.append("Right Column (x: 820-1140, y: 120-720) is OPEN")

    if not recommendations:
        recommendations.append("All main columns have content; check bounding boxes and place new elements in bottom row or vertical gaps.")

    return "; ".join(recommendations)
