"""
tests/eval_layout.py
Layout measurements from stored boards that do NOT depend on ids or groups.

The tutor's guards read `<g id>` groups and shapes that carry an id (`validator.extract_element_bboxes`). Since baseline C most
drawn elements are bare tags, which that function cannot see (docs/BASELINE.md, "The unit is not formed"), so layout numbers built on
it were measured on 0-25% of the elements from D on. Here every shape and every text label counts, wherever it sits.

    shape_boxes(fragment)       one box per shape or text label in a drawn element
    element_box(fragment)       the union of those (one box per drawn element)
    layout_mask(fragments)      20x20 px canvas cells covered by any shape or label
    layout_clusters(by_topic)   how many topics have clearly different layouts (Jaccard of the masks, same rule as before)
    overlap_pairs(fragments)    pairs of different elements the overlap guard would reject (same rule as `check_overlap`)
"""
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.validator import OVERLAP_REJECT, _text_boxes, extract_element_bboxes  # noqa: E402

COLS, ROWS, W, H = 60, 40, 1200, 800
SAME_LAYOUT_JACCARD = 0.5     # two topics count as "the same layout" when their drawn areas overlap this much
_SHAPE = re.compile(r"<(?:rect|circle|ellipse|line|polyline|polygon|path)\b[^>]*>", re.IGNORECASE)
_DEFS = re.compile(r"<(defs|marker|symbol|pattern|clipPath|mask)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


def shape_boxes(fragment):
    """[(x0, y0, x1, y1)] for every shape (the validator's own bounds rules) and every text label (its estimated box)."""
    body = _DEFS.sub("", fragment or "")
    boxes = []
    for tag in _SHAPE.findall(body):
        found = extract_element_bboxes(f'<g id="s">{tag}</g>')      # the validator measures one shape at a time this way
        boxes += [(b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]) for b in (f["bbox"] for f in found)]
    boxes += [b[:4] for b in _text_boxes(body)]
    return boxes


def element_box(fragment):
    boxes = shape_boxes(fragment)
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def layout_mask(fragments):
    """Set of 20x20 px canvas cells covered by any shape or text label."""
    cells = set()
    cw, ch = W / COLS, H / ROWS
    for frag in fragments:
        for x0, y0, x1, y1 in shape_boxes(frag):
            cx0, cx1 = int(max(x0, 0) // cw), int(min(x1, W - 1) // cw)
            cy0, cy1 = int(max(y0, 0) // ch), int(min(y1, H - 1) // ch)
            cells.update((i, j) for i in range(cx0, cx1 + 1) for j in range(cy0, cy1 + 1))
    return cells


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def layout_clusters(first_page_fragments):
    """({topic: [fragments of its first page]}) -> (number of distinct layouts, mean pairwise Jaccard)."""
    masks = {d: layout_mask(f) for d, f in first_page_fragments.items() if f}
    pairs = {(a, b): jaccard(masks[a], masks[b]) for a, b in combinations(sorted(masks), 2)}
    parent = {n: n for n in masks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for (a, b), j in pairs.items():
        if j >= SAME_LAYOUT_JACCARD:
            parent[find(a)] = find(b)
    return len({find(n) for n in masks}), (round(sum(pairs.values()) / len(pairs), 3) if pairs else None)


def overlap_pairs(fragments):
    """Pairs of different drawn elements (in one page) that `validator.check_overlap` would have rejected: the intersection covers more
    than OVERLAP_REJECT of the smaller box, thin boxes (under 20 px) ignored."""
    boxes = [b for b in (element_box(f) for f in fragments) if b]
    count = 0
    for a, b in combinations(boxes, 2):
        wa, ha, wb, hb = a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]
        if min(wa, ha, wb, hb) < 20:
            continue
        iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
        if iw > 0 and ih > 0 and iw * ih / min(wa * ha, wb * hb) > OVERLAP_REJECT:
            count += 1
    return count


def board_layout(topics):
    """From a stored run's `topics`: (layout clusters, mean pairwise Jaccard, overlapping pairs summed over all pages)."""
    first = {d: [e["svg_fragment"] for e in t["pages"][0]["events"] if e["kind"] == "draw"] for d, t in topics.items() if t.get("pages")}
    clusters, mean_j = layout_clusters(first)
    pairs = sum(overlap_pairs([e["svg_fragment"] for e in pg["events"] if e["kind"] == "draw"])
                for t in topics.values() for pg in t.get("pages", []))
    return clusters, mean_j, pairs
