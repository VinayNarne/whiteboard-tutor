"""
engine/blocks.py
Three more lesson-board blocks (scene mode): draw_table, draw_bar_chart and draw_venn. As everywhere on the board, the tutor says WHAT
(columns and rows, categories and values, sets and what sits in each region) and the code decides WHERE: sizes, wrapping, layout,
colours. Each block is revealed step by step while the tutor speaks, like the other blocks.
"""
from typing import List, Tuple
from xml.sax.saxutils import escape

from engine.graph import _num, fmt, nice_ticks
from engine.scene import (DIAGRAM_LANE, INK, INK2, INTER, MAX_SAY, MAX_TEXT, PALETTE, WIDE_LANE, SceneError, _cam, _lst, _n, _txt,
                          demath, measure, place_block, plain, wrap)

CELL, HEAD = (15, 400, 20), (15, 700, 20)
MAX_COLS, MAX_ROWS, MAX_CELL = 6, 8, 80
MAX_CATS, MAX_BAR_SERIES = 10, 3
MAX_ITEMS = 6

Steps = List[Tuple[str, str, str]]


def _t(x, y, text, size=14, weight=400, color=INK, anchor="middle") -> str:
    return (f'<text x="{_n(x)}" y="{_n(y)}" font-family="{INTER}" font-size="{size}" font-weight="{weight}" fill="{color}" '
            f'text-anchor="{anchor}">{escape(text)}</text>')


def _lines(x, y, lines, f, color=INK, anchor="middle") -> str:
    return "".join(_t(x, y + f[0] * 0.8 + i * f[2], ln, f[0], f[1], color, anchor) for i, ln in enumerate(lines))


def _say(text, fallback) -> str:
    return (plain(_txt(text)) or plain(fallback))[:MAX_SAY]


def _steps(n: int, parts: List[Tuple[str, str]], cam: str) -> Steps:
    return [(f"b{n}_s{k + 1}", f'<g id="b{n}_s{k + 1}">{cam}{body}</g>', f"[[MARK:b{n}_s{k + 1}]] {say}") for k, (body, say) in enumerate(parts)]


# --------------------------------------------------------------------------------------------------------------------------------
# Table
# --------------------------------------------------------------------------------------------------------------------------------

TABLE_TOOL = {"type": "function", "function": {
    "name": "draw_table",
    "description": "Adds a table for comparing a few things across a few properties (planets by size and moons, three economies, the "
                   "parts of a cell and their jobs). The header appears first, then one row per step while you speak.",
    "parameters": {"type": "object", "required": ["title", "intro", "columns", "rows"], "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string", "description": "What you say while the header appears: what is being compared."},
        "columns": {"type": "array", "items": {"type": "string"}, "description": f"2 to {MAX_COLS} short column headings; the first names the rows."},
        "rows": {"type": "array", "description": f"1 to {MAX_ROWS} rows, in teaching order.", "items": {"type": "object", "required": ["cells"], "properties": {
            "cells": {"type": "array", "items": {"type": "string"}, "description": "One short value per column."},
            "say": {"type": "string", "description": "What you say while this row appears."}}}},
    }}}}


def build_table(args: dict, n: int, blocks: List[dict]) -> Tuple[Steps, dict, dict]:
    title = demath(_txt(args.get("title"))).strip()[:MAX_TEXT]
    cols = [demath(_txt(c)).strip()[:MAX_CELL] for c in _lst(args.get("columns"))]
    if not 2 <= len(cols) <= MAX_COLS or not all(cols):
        raise SceneError(f"draw_table needs 2 to {MAX_COLS} non-empty column headings.")
    rows = []
    for r in [r for r in _lst(args.get("rows")) if isinstance(r, dict)]:
        cells = [demath(_txt(c)).strip()[:MAX_CELL] for c in _lst(r.get("cells"))]
        if len(cells) != len(cols):
            raise SceneError(f"Each table row needs exactly {len(cols)} cells, one per column (a row had {len(cells)}).")
        rows.append((cells, _say(r.get("say"), f"{cells[0]}: " + ", ".join(f"{c} {v}" for c, v in zip(cols[1:], cells[1:])))))
    if not 1 <= len(rows) <= MAX_ROWS:
        raise SceneError(f"draw_table needs 1 to {MAX_ROWS} rows; split a longer table into two.")
    intro = _say(args.get("intro"), title or ", ".join(cols))

    pad = 12
    natural = [max(measure(t, HEAD[0] if i == 0 else CELL[0], 700 if i == 0 else 400) for i, t in enumerate([c] + [r[0][j] for r in rows])) + 2 * pad
               for j, c in enumerate(cols)]
    lane = DIAGRAM_LANE if sum(natural) <= DIAGRAM_LANE[1] else WIDE_LANE
    inner = lane[1]
    if sum(natural) <= inner:   # spare room shared out, so the table fills its lane
        widths = [w + (inner - sum(natural)) / len(cols) for w in natural]
    else:                       # too wide even full width: columns shrink in proportion and their text wraps
        widths = [max(90, w * inner / sum(natural)) for w in natural]
        widths = [w * inner / sum(widths) for w in widths]
    wrap_row = lambda cells, f: [wrap(c, f, w - 2 * pad) for c, w in zip(cells, widths)]
    head = wrap_row(cols, HEAD)
    body = [wrap_row(cells, CELL) for cells, _ in rows]
    row_h = lambda wrapped, f: max(len(c) for c in wrapped) * f[2] + 2 * pad
    title_h = 40 if title else 0
    hh, rhs = row_h(head, HEAD), [row_h(b, CELL) for b in body]
    h = title_h + hh + sum(rhs)
    bx, by = place_block(lane, h, blocks)
    xs = [bx + sum(widths[:j]) for j in range(len(cols))]

    parts = []
    first = [f'<rect x="{_n(bx)}" y="{_n(by + title_h)}" width="{_n(inner)}" height="{_n(h - title_h)}" rx="8" fill="#FFFFFF" stroke="#CFC8B8" stroke-width="1.5"/>',
             f'<rect x="{_n(bx)}" y="{_n(by + title_h)}" width="{_n(inner)}" height="{_n(hh)}" rx="8" fill="{PALETTE[0][0]}" stroke="none"/>']
    if title:
        first.append(_t(bx + 4, by + 26, title, 18, 700, INK, "start"))
    for j, lines in enumerate(head):
        first.append(_lines(xs[j] + pad, by + title_h + pad, lines, HEAD, PALETTE[0][1], "start"))
    parts.append(("".join(first), intro))
    y = by + title_h + hh
    for (cells, say), wrapped, rh in zip(rows, body, rhs):
        cell = [f'<line x1="{_n(bx)}" y1="{_n(y)}" x2="{_n(bx + inner)}" y2="{_n(y)}" stroke="#E5E1D6" stroke-width="1.2"/>']
        for j, lines in enumerate(wrapped):
            cell.append(_lines(xs[j] + pad, y + pad, lines, HEAD if j == 0 else CELL, INK, "start"))   # the first column names the row
        parts.append(("".join(cell), say))
        y += rh
    box = {"x": bx, "y": by, "w": inner, "h": h}
    return _steps(n, parts, _cam(**box)), box, {"kind": "table", "columns": len(cols), "rows": len(rows), "lane": "wide" if lane == WIDE_LANE else "diagram"}


# --------------------------------------------------------------------------------------------------------------------------------
# Bar chart
# --------------------------------------------------------------------------------------------------------------------------------

BAR_TOOL = {"type": "function", "function": {
    "name": "draw_bar_chart",
    "description": "Adds a bar chart that compares amounts across categories (votes by party, rainfall by month, energy by source). "
                   "Give the numbers; the app draws the bars to scale and writes each value. Axes first, then one series per step.",
    "parameters": {"type": "object", "required": ["title", "intro", "categories", "series"], "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string", "description": "What you say while the axes and categories appear."},
        "categories": {"type": "array", "items": {"type": "string"}, "description": f"2 to {MAX_CATS} short category names, in order."},
        "y_label": {"type": "string", "description": "What the bars measure, with the unit."},
        "series": {"type": "array", "description": f"1 to {MAX_BAR_SERIES} sets of bars (several = grouped side by side).",
                   "items": {"type": "object", "required": ["label", "values", "say"], "properties": {
                       "label": {"type": "string"}, "values": {"type": "array", "items": {"type": "number"}, "description": "One number per category."},
                       "say": {"type": "string", "description": "What you say while these bars appear."}}}},
    }}}}


def build_bar_chart(args: dict, n: int, blocks: List[dict]) -> Tuple[Steps, dict, dict]:
    title = demath(_txt(args.get("title"))).strip()[:MAX_TEXT]
    cats = [demath(_txt(c)).strip()[:40] for c in _lst(args.get("categories"))]
    if not 2 <= len(cats) <= MAX_CATS or not all(cats):
        raise SceneError(f"draw_bar_chart needs 2 to {MAX_CATS} named categories.")
    series = []
    for s in [s for s in _lst(args.get("series")) if isinstance(s, dict)]:
        values = [_num(v) for v in _lst(s.get("values"))]
        if len(values) != len(cats) or None in values:
            raise SceneError(f"Each series needs exactly {len(cats)} numbers, one per category.")
        say = _say(s.get("say"), "")
        if not say:
            raise SceneError("Each series needs `say`: what you say while its bars appear.")
        series.append((demath(_txt(s.get("label"))).strip()[:30], values, say))
    if not 1 <= len(series) <= MAX_BAR_SERIES:
        raise SceneError(f"draw_bar_chart needs 1 to {MAX_BAR_SERIES} series.")
    intro = _say(args.get("intro"), "")
    if not intro:
        raise SceneError("draw_bar_chart needs `intro`: what you say while the axes appear.")

    allv = [v for _, vs, _ in series for v in vs]
    lo, hi = min(0.0, min(allv)), max(0.0, max(allv))
    if hi == lo:
        hi = lo + 1
    ticks = nice_ticks(lo, hi)
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    while ticks[-1] < hi:                  # the axis reaches the next round tick above the tallest bar (39 stopped at a 30 tick)
        ticks.append(round(ticks[-1] + step, 10))
    while ticks[0] > lo:
        ticks.insert(0, round(ticks[0] - step, 10))
    lo, hi = ticks[0], ticks[-1]
    lane = WIDE_LANE if len(cats) * len(series) > 12 or len(cats) > 7 else DIAGRAM_LANE
    w = lane[1]
    legend = len(series) > 1
    title_h, legend_h = (40 if title else 0), (26 if legend else 0)
    left, right, top, bottom = 64, 20, 24, 48
    plot_h = 300
    h = title_h + legend_h + top + plot_h + bottom
    bx, by = place_block(lane, h, blocks)
    px0, py0, pw = bx + left, by + title_h + legend_h + top, w - left - right
    sy = lambda v: py0 + plot_h - (v - lo) / (hi - lo) * plot_h
    slot = pw / len(cats)
    group = slot * 0.72
    bw = group / len(series)
    colours = [PALETTE[i][1] for i in range(len(series))]

    axes = [f'<rect x="{_n(bx)}" y="{_n(by)}" width="{w}" height="{_n(h)}" rx="10" fill="#FFFFFF" stroke="#E5E1D6" stroke-width="1.5"/>']
    if title:
        axes.append(_t(bx + 20, by + 30, title, 18, 700, INK, "start"))
    for i, (label, _, _) in enumerate(series if legend else []):
        lx = bx + 20 + i * 150
        axes.append(f'<rect x="{_n(lx)}" y="{_n(by + title_h + 6)}" width="14" height="14" rx="2" fill="{colours[i]}"/>')
        axes.append(_t(lx + 20, by + title_h + 18, label, 13, 400, INK, "start"))
    for t in ticks:
        Y = sy(t)
        axes.append(f'<line x1="{_n(px0)}" y1="{_n(Y)}" x2="{_n(px0 + pw)}" y2="{_n(Y)}" stroke="#EEEAE0" stroke-width="1"/>')
        axes.append(_t(px0 - 8, Y + 4, fmt(t), 12, 400, INK2, "end"))
    axes.append(f'<path d="M{_n(px0)},{_n(py0)} V{_n(sy(lo) if lo == 0 else py0 + plot_h)} H{_n(px0 + pw)}" fill="none" stroke="{INK}" stroke-width="1.6"/>')
    if lo < 0:   # a zero line when bars go both ways
        axes.append(f'<line x1="{_n(px0)}" y1="{_n(sy(0))}" x2="{_n(px0 + pw)}" y2="{_n(sy(0))}" stroke="{INK}" stroke-width="1.6"/>')
    for i, c in enumerate(cats):
        lines = wrap(c, (12, 400, 15), slot - 6)[:2]
        axes.append(_lines(px0 + slot * (i + 0.5), py0 + plot_h + 8, lines, (12, 400, 15), INK))
    yl = demath(_txt(args.get("y_label"))).strip()[:MAX_TEXT]
    if yl:
        axes.append(f'<text x="{_n(bx + 18)}" y="{_n(py0 + plot_h / 2)}" font-family="{INTER}" font-size="13" font-weight="700" fill="{INK}" '
                    f'text-anchor="middle" transform="rotate(-90 {_n(bx + 18)} {_n(py0 + plot_h / 2)})">{escape(yl)}</text>')
    parts = [("".join(axes), intro)]
    for k, (_, values, say) in enumerate(series):
        bars = []
        for i, v in enumerate(values):
            x = px0 + slot * i + (slot - group) / 2 + k * bw
            y0, y1 = sy(max(v, 0)), sy(min(v, 0))
            bars.append(f'<rect x="{_n(x + 1)}" y="{_n(y0)}" width="{_n(bw - 2)}" height="{_n(max(1, y1 - y0))}" fill="{colours[k]}" stroke="none"/>')
            bars.append(_t(x + bw / 2, (y0 - 5) if v >= 0 else (y1 + 14), fmt(v), 11 if len(series) > 1 else 12, 700, INK))
        parts.append(("".join(bars), say))
    box = {"x": bx, "y": by, "w": w, "h": h}
    return _steps(n, parts, _cam(**box)), box, {"kind": "bars", "categories": len(cats), "series": len(series)}


# --------------------------------------------------------------------------------------------------------------------------------
# Venn diagram
# --------------------------------------------------------------------------------------------------------------------------------

VENN_TOOL = {"type": "function", "function": {
    "name": "draw_venn",
    "description": "Adds a Venn diagram of 2 or 3 overlapping sets (mammals and sea animals, what two religions share, prime and even "
                   "numbers). Circles appear one per step, then the items in each region. Place items by the sets they belong to.",
    "parameters": {"type": "object", "required": ["title", "sets", "regions"], "properties": {
        "title": {"type": "string"},
        "sets": {"type": "array", "description": "2 or 3 sets.", "items": {"type": "object", "required": ["label", "say"], "properties": {
            "label": {"type": "string"}, "say": {"type": "string", "description": "What you say while this circle appears."}}}},
        "regions": {"type": "array", "description": "Regions that have items in them.", "items": {"type": "object", "required": ["in", "items"], "properties": {
            "in": {"type": "array", "items": {"type": "integer"}, "description": "The numbers (1, 2, 3) of the sets this region is inside, "
                   "and only those: [1] = only in set 1, [1, 2] = in sets 1 and 2 but not 3."},
            "items": {"type": "array", "items": {"type": "string"}, "description": f"1 to {MAX_ITEMS} short items; a list of small things "
                      "can be one item ('12, 14, 16, 18, 20'), so a region shows all of its members."},
            "say": {"type": "string", "description": "What you say while these items appear."}}}},
    }}}}


def build_venn(args: dict, n: int, blocks: List[dict]) -> Tuple[Steps, dict, dict]:
    title = demath(_txt(args.get("title"))).strip()[:MAX_TEXT]
    sets = [(demath(_txt(s.get("label"))).strip()[:40], _say(s.get("say"), _txt(s.get("label"))))
            for s in _lst(args.get("sets")) if isinstance(s, dict)]
    if len(sets) not in (2, 3) or not all(label for label, _ in sets):
        raise SceneError("draw_venn needs 2 or 3 named sets.")
    k = len(sets)
    regions, seen = [], set()
    for r in [r for r in _lst(args.get("regions")) if isinstance(r, dict)]:
        idx = sorted({i for i in _lst(r.get("in")) if isinstance(i, int) and not isinstance(i, bool)})
        if not idx or not all(1 <= i <= k for i in idx):
            raise SceneError(f"Each region's `in` lists set numbers from 1 to {k} (the sets it is inside).")
        if tuple(idx) in seen:
            raise SceneError(f"Two regions are both inside sets {idx}: put all their items in one region.")
        seen.add(tuple(idx))
        items = [demath(_txt(i)).strip()[:40] for i in _lst(r.get("items")) if _txt(i).strip()]
        if not 1 <= len(items) <= MAX_ITEMS:
            raise SceneError(f"Each region holds 1 to {MAX_ITEMS} short items.")
        names = " and ".join(sets[i - 1][0] for i in idx)
        regions.append((tuple(idx), items, _say(r.get("say"), f"In {names}: " + ", ".join(items))))
    if not regions:
        raise SceneError("draw_venn needs at least one region with items.")

    w = DIAGRAM_LANE[1]
    title_h = 40 if title else 0
    if k == 2:
        r, h = 150.0, title_h + 380
    else:
        r, h = 130.0, title_h + 520                            # room for the bottom set's label
    bx, by = place_block(DIAGRAM_LANE, h, blocks)
    cx, cy = bx + w / 2, by + title_h + (h - title_h) / 2 + (0 if k == 2 else -15)   # three circles sit low: lift them
    centres = [(cx - 95, cy), (cx + 95, cy)] if k == 2 else [(cx - 75, cy - 45), (cx + 75, cy - 45), (cx, cy + 85)]
    gx, gy = sum(c[0] for c in centres) / k, sum(c[1] for c in centres) / k

    def anchor(idx):   # a point well inside the region that is in exactly these sets
        if len(idx) == k:
            return gx, gy
        if len(idx) == 1:
            x, y = centres[idx[0] - 1]
            return x + (x - gx) * (0.55 if k == 2 else 0.6), y + (y - gy) * (0.55 if k == 2 else 0.6)
        (ax, ay), (bx2, by2) = centres[idx[0] - 1], centres[idx[1] - 1]
        mx, my = (ax + bx2) / 2, (ay + by2) / 2
        return mx + (mx - gx) * 0.55, my + (my - gy) * 0.55   # away from the third circle (k = 3)

    parts = []
    frame = [f'<rect x="{_n(bx)}" y="{_n(by)}" width="{w}" height="{_n(h)}" rx="10" fill="#FFFFFF" stroke="#E5E1D6" stroke-width="1.5"/>']
    if title:
        frame.append(_t(bx + 20, by + 30, title, 18, 700, INK, "start"))
    for i, ((x, y), (label, say)) in enumerate(zip(centres, sets)):
        soft, strong = PALETTE[i]
        circle = f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" fill="{soft}" fill-opacity="0.55" stroke="{strong}" stroke-width="2.4"/>'
        lx = x + (x - gx) * 0.55
        ly = (y - r - 12) if y <= gy else (y + r + 24)
        parts.append(((("".join(frame)) if i == 0 else "") + circle + _t(lx, ly, label, 16, 700, strong), say))
    for idx, items, say in regions:
        x, y = anchor(idx)
        width = (120 if len(idx) == 1 else 96) if k == 2 else {1: 96, 2: 70, 3: 56}[len(idx)]   # how wide each region is, near its anchor
        lines = [ln for it in items for ln in wrap(it, (13, 400, 16), width)][:8]
        parts.append((_lines(x, y - len(lines) * 16 / 2, lines, (13, 400, 16), INK), say))
    box = {"x": bx, "y": by, "w": w, "h": h}
    return _steps(n, parts, _cam(**box)), box, {"kind": "venn", "sets": k, "regions": len(regions)}
