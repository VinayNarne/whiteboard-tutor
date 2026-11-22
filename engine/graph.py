"""
engine/graph.py
Scene mode's graph block (draw_graph): the tutor gives formulas or data, the code computes and draws an exact chart, so the numbers are
right and the style matches the board (the idea came from a competitor's code-drawn coordinate planes, docs/PROJECT_BRIEF.md).

A formula is parsed with Python's ast and evaluated from a whitelist (numbers, x, + - * / ^, a few math functions, pi, e): it is never
executed as code. Steps: the axes (with the intro), then one step per series, then the marked points (their values computed here).
"""
import ast
import math
import operator
from typing import List, Tuple
from xml.sax.saxutils import escape

from engine.scene import (DIAGRAM_LANE, demath, texture_on, INK, INK2, INTER, MAX_SAY, MAX_TEXT, PALETTE, _cut, SceneError, _cam, _lst, _n, _txt, place_block)

MAX_SERIES, MAX_POINTS, MAX_MARKS, SAMPLES = 4, 60, 6, 240
PLOT_W, PLOT_H = 580, 420
LEFT, RIGHT, TOP, BOTTOM = 64, 24, 56, 52            # margins around the plot area, inside the block

GRAPH_TOOL = {"type": "function", "function": {
    "name": "draw_graph",
    "description": "Adds an exact chart: curves from formulas, or lines through data points. The app computes every value and draws it; "
                   "give formulas or data, never coordinates you worked out. Narrated in steps: axes, each series, then the marked points.",
    "parameters": {"type": "object", "required": ["title", "x", "series", "intro"], "properties": {
        "title": {"type": "string", "description": "Short title above the chart."},
        "intro": {"type": "string", "description": "What you say while the axes appear: what the chart shows and what each axis is."},
        "x": {"type": "object", "required": ["label", "min", "max"], "properties": {
            "label": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"}}},
        "y": {"type": "object", "description": "Optional: the y axis label and range (default: fitted to the data).", "properties": {
            "label": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"}}},
        "series": {"type": "array", "description": f"One to {MAX_SERIES} curves or data lines.", "items": {"type": "object", "required": ["label", "say"], "properties": {
            "label": {"type": "string", "description": "Short name shown in the legend."},
            "formula": {"type": "string", "description": "y as a function of x, for example '(700/x)^4', '2*x + 1', 'sin(x)', '1000*1.05^x'. Allowed: numbers, x, + - * / ^, parentheses, sin cos tan exp log ln sqrt abs, pi, e."},
            "points": {"type": "array", "description": "Instead of a formula: data points [x, y], in order of x.", "items": {"type": "array", "items": {"type": "number"}}},
            "say": {"type": "string", "description": "What you say while this series is drawn."}}}},
        "marks": {"type": "array", "description": "Optional: points to mark on the first series, at these x values; their y is computed and shown.",
                  "items": {"type": "object", "required": ["x"], "properties": {"x": {"type": "number"}, "label": {"type": "string"}}}},
        "marks_say": {"type": "string", "description": "What you say while the marked points appear (required with marks)."},
        "shade": {"type": "object", "description": "Optional: shade the area between the first series and the x axis from x = from to x = to "
                  "(an area under a curve, a range of values, a probability).", "properties": {"from": {"type": "number"}, "to": {"type": "number"}}},
    }}}}

_FUNCS = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "exp": math.exp, "log": math.log10, "ln": math.log, "sqrt": math.sqrt, "abs": abs}
_CONST = {"pi": math.pi, "e": math.e}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}


def compile_formula(text: str):
    """A function of x from a whitelisted formula, or SceneError. '^' is a power, as people write it."""
    src = _txt(text).strip().replace("^", "**")[:MAX_TEXT]
    if not src:
        raise SceneError("Each series needs a formula or points.")
    try:
        tree = ast.parse(src, mode="eval").body
    except SyntaxError:
        raise SceneError(f"This formula cannot be read: {src!r}. Write it like '2*x + 1' or '(700/x)^4'.")

    def check(n):
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            check(n.left), check(n.right)
            if isinstance(n.op, ast.Pow) and isinstance(n.right, ast.Constant) and abs(n.right.value) > 100:
                raise SceneError("A power in a formula is at most 100.")
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            check(n.operand)
        elif isinstance(n, ast.Constant) and type(n.value) in (int, float):
            pass   # a plain number is allowed
        elif isinstance(n, ast.Name) and (n.id == "x" or n.id in _CONST):
            pass   # the variable x or a named constant is allowed
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and len(n.args) == 1 and not n.keywords:
            check(n.args[0])
        else:
            raise SceneError(f"This formula uses something not allowed: {src!r}. Allowed: numbers, x, + - * / ^, sin cos tan exp log ln sqrt abs, pi, e.")
    check(tree)

    def ev(n, x):
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left, x), ev(n.right, x)
            if isinstance(n.op, ast.Pow) and abs(b) > 100:
                raise OverflowError
            return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp):
            return -ev(n.operand, x) if isinstance(n.op, ast.USub) else ev(n.operand, x)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            return x if n.id == "x" else _CONST[n.id]
        return _FUNCS[n.func.id](ev(n.args[0], x))

    def f(x: float):
        try:
            y = ev(tree, float(x))
            return y if isinstance(y, float) and math.isfinite(y) else None
        except (ArithmeticError, ValueError, TypeError):
            return None                                       # outside the formula's domain (1/0, log of a negative): a gap in the line
    return f


CALC_TOOL = {"type": "function", "function": {
    "name": "calculate",
    "description": "Work out numbers exactly before you say or write them (money, growth, totals, a worked example). "
                   "Returns each value. Never state a computed number you did not get from here.",
    "parameters": {"type": "object", "required": ["expressions"], "properties": {
        "expressions": {"type": "array", "maxItems": 12, "items": {"type": "string"},
                        "description": "Formulas like '1000*1.07^30' or '(1000*1.07^30) - (1000*1.07^20)'. Allowed: numbers, + - * / ^, "
                                       "brackets, sin cos tan exp log ln sqrt abs, pi, e."}}}}}


def _quote(v: float) -> str:
    """A value as the tutor should say it: 1,903,063.76, never 1.90306e+06."""
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) >= 1000 else f"{v:.6g}"


def calculate(expressions) -> dict:
    """The calculate tool: exact values for the tutor to quote. Live lessons invented them: '$1,000 at 30 grows to over $4,000 by 60,
    starting at 40 only about $1,600', which no interest rate gives (lesson check, 2026-11-15)."""
    if not isinstance(expressions, list) or not 1 <= len(expressions) <= 12:
        return {"status": "error", "detail": "expressions is a list of 1 to 12 formulas."}
    out = []
    for e in expressions:
        try:
            v = compile_formula(e)(0)
            out.append(f"{_txt(e)} = {_quote(v)}" if v is not None else f"{_txt(e)} = undefined")
        except SceneError as err:
            out.append(f"{_txt(e)}: {err}")
    return {"status": "ok", "detail": "; ".join(out)}


def nice_ticks(lo: float, hi: float, n: int = 5) -> List[float]:
    """About n round tick values (1, 2 or 5 times a power of ten) covering lo..hi."""
    span = hi - lo
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step - 1e-9) * step
    return [round(first + i * step, 10) for i in range(int((hi - first) / step + 1e-9) + 1)]


def fmt(v: float) -> str:
    """A value as people write it: 3 significant digits, no trailing zeros, thousands as 'k'/'M' only when long."""
    if v == 0:
        return "0"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.3g}M"
    if abs(v) >= 1e4:
        return f"{v / 1e3:.3g}k"
    if abs(v) >= 1e3:
        return str(round(v))          # 1629, not 1.63e+03
    return f"{v:.3g}"


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def build_graph(args: dict, n: int, blocks: List[dict]) -> Tuple[List[Tuple[str, str, str]], dict, dict]:
    title = _cut(demath(_txt(args.get("title"))).strip(), MAX_TEXT, "title")
    intro = _cut(_txt(args.get("intro")).strip(), MAX_SAY, "narration of the intro")
    xa = args.get("x") if isinstance(args.get("x"), dict) else {}
    ya = args.get("y") if isinstance(args.get("y"), dict) else {}
    x0, x1 = _num(xa.get("min")), _num(xa.get("max"))
    if x0 is None or x1 is None or not x1 > x0:
        raise SceneError("draw_graph needs x.min < x.max (numbers).")
    if not intro:
        raise SceneError("draw_graph needs `intro`: what you say while the axes appear.")
    series = [s for s in _lst(args.get("series")) if isinstance(s, dict)]
    if not series or len(series) > MAX_SERIES:
        raise SceneError(f"draw_graph needs one to {MAX_SERIES} series.")

    lines = []   # (label, say, [(x, y or None)], is_points)
    for s in series:
        say = _cut(_txt(s.get("say")).strip(), MAX_SAY, "narration")
        if not say:
            raise SceneError("Each series needs `say`: what you say while it is drawn.")
        pts = [p for p in _lst(s.get("points")) if isinstance(p, list) and len(p) == 2 and None not in (_num(p[0]), _num(p[1]))]
        if pts:
            data = sorted((float(a), float(b)) for a, b in pts[:MAX_POINTS])
            lines.append((_cut(demath(_txt(s.get("label"))).strip(), 40, "label"), say, data, True))
        else:
            f = compile_formula(s.get("formula"))
            data = [(x, f(x)) for x in (x0 + (x1 - x0) * i / SAMPLES for i in range(SAMPLES + 1))]
            if not any(y is not None for _, y in data):
                raise SceneError(f"The formula for '{_txt(s.get('label'))}' has no value between x = {fmt(x0)} and {fmt(x1)}.")
            lines.append((_cut(demath(_txt(s.get("label"))).strip(), 40, "label"), say, data, False))

    marks = []
    first = lines[0]
    for m in [m for m in _lst(args.get("marks")) if isinstance(m, dict)][:MAX_MARKS]:
        mx = _num(m.get("x"))
        if mx is None or not x0 <= mx <= x1:
            raise SceneError(f"A marked point must have x between {fmt(x0)} and {fmt(x1)}.")
        if first[3]:   # data: the nearest point
            my = min(first[2], key=lambda p: abs(p[0] - mx))[1]
        else:
            my = compile_formula(series[0].get("formula"))(mx)
        if my is not None:
            marks.append((mx, my, _cut(demath(_txt(m.get("label"))).strip(), 40, "label")))
    marks_say = _cut(_txt(args.get("marks_say")).strip(), MAX_SAY, "narration of the marks")
    sh = args.get("shade") if isinstance(args.get("shade"), dict) else {}
    a, z = _num(sh.get("from")), _num(sh.get("to"))
    shade = (max(a, x0), min(z, x1)) if a is not None and z is not None and min(z, x1) > max(a, x0) else None
    if marks and not marks_say:
        raise SceneError("Marked points need `marks_say`: what you say while they appear.")

    ys = [y for _, _, d, _ in lines for _, y in d if y is not None]
    y0, y1 = _num(ya.get("min")), _num(ya.get("max"))
    if y0 is None:
        y0 = min(ys + [0.0]) if min(ys) >= 0 else min(ys)
    if y1 is None:
        y1 = max(ys)
    if not y1 > y0:
        y1 = y0 + 1
    pad = (y1 - y0) * 0.05 if _num(ya.get("max")) is None else 0
    y1 += pad

    # the block: chart in the diagram lane
    title_h = 40 if title else 0
    legend_h = 26 if len(lines) > 1 else 0
    w, h = PLOT_W, PLOT_H + title_h + legend_h
    bx, by = place_block(DIAGRAM_LANE, h, blocks)
    px0, py0 = bx + LEFT, by + title_h + legend_h + TOP - 24      # plot area
    pw, ph = w - LEFT - RIGHT, PLOT_H - TOP - BOTTOM + 24
    sx = lambda x: px0 + (x - x0) / (x1 - x0) * pw
    sy = lambda y: py0 + ph - (y - y0) / (y1 - y0) * ph
    txt = lambda x, y, t, size=13, anchor="middle", color=INK2, weight=400: (
        f'<text x="{_n(x)}" y="{_n(y)}" font-family="{INTER}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(t)}</text>')
    cam = _cam(bx, by, w, h)
    colours = [PALETTE[i % len(PALETTE)][1] for i in range(len(lines))]

    axes = [f'<rect x="{_n(bx)}" y="{_n(by)}" width="{w}" height="{_n(h)}" rx="10" fill="#FFFFFF" stroke="#E5E1D6" stroke-width="1.5"/>']
    if title:
        axes.append(txt(bx + 20, by + 30, title, 18, "start", INK, 700))
    for i, (label, _, _, _) in enumerate(lines if legend_h else []):
        lx = bx + 20 + i * 140
        axes.append(f'<line x1="{_n(lx)}" y1="{_n(by + title_h + 14)}" x2="{_n(lx + 22)}" y2="{_n(by + title_h + 14)}" stroke="{colours[i]}" stroke-width="3"/>')
        axes.append(txt(lx + 28, by + title_h + 18, label, 13, "start", INK))
    for t in nice_ticks(x0, x1):
        X = sx(t)
        axes.append(f'<line x1="{_n(X)}" y1="{_n(py0)}" x2="{_n(X)}" y2="{_n(py0 + ph)}" stroke="#EEEAE0" stroke-width="1"/>')
        axes.append(txt(X, py0 + ph + 18, fmt(t)))
    for t in nice_ticks(y0, y1):
        Y = sy(t)
        axes.append(f'<line x1="{_n(px0)}" y1="{_n(Y)}" x2="{_n(px0 + pw)}" y2="{_n(Y)}" stroke="#EEEAE0" stroke-width="1"/>')
        axes.append(txt(px0 - 8, Y + 4, fmt(t), anchor="end"))
    axes.append(f'<path d="M{_n(px0)},{_n(py0)} V{_n(py0 + ph)} H{_n(px0 + pw)}" fill="none" stroke="{INK}" stroke-width="1.6"/>')
    axes.append(txt(px0 + pw / 2, py0 + ph + 40, _cut(demath(_txt(xa.get("label"))).strip(), MAX_TEXT, "axis label"), 14, color=INK, weight=700))
    yl = _cut(demath(_txt(ya.get("label"))).strip(), MAX_TEXT, "axis label")
    if yl:
        axes.append(f'<text x="{_n(bx + 18)}" y="{_n(py0 + ph / 2)}" font-family="{INTER}" font-size="14" font-weight="700" fill="{INK}" '
                    f'text-anchor="middle" transform="rotate(-90 {_n(bx + 18)} {_n(py0 + ph / 2)})">{escape(yl)}</text>')

    clip = lambda y: None if y is None or y < y0 - (y1 - y0) * 0.02 or y > y1 + (y1 - y0) * 0.02 else y
    steps = [("".join(axes), intro)]
    for i, (label, say, data, is_points) in enumerate(lines):
        runs, cur = [], []
        for x, y in data:
            if clip(y) is None:
                if cur:
                    runs.append(cur)
                cur = []
            else:
                cur.append(f"{_n(sx(x))},{_n(sy(y))}")
        if cur:
            runs.append(cur)
        body = "".join(f'<polyline points="{" ".join(r)}" fill="none" stroke="{colours[i]}" stroke-width="3" stroke-linejoin="round"/>' for r in runs)
        if is_points:
            body += "".join(f'<circle cx="{_n(sx(x))}" cy="{_n(sy(y))}" r="4" fill="{colours[i]}"/>' for x, y in data if clip(y) is not None)
        if i == 0 and shade:   # the area between the curve and the axis: a light fill, hatched as pencil lines with LP_PAINT=svg
            a, z = shade
            base = min(max(0.0, y0), y1)
            top = [(x, min(max(y, y0), y1)) for x, y in data if a <= x <= z and y is not None]
            if len(top) >= 2:
                pts = [(sx(x), sy(y)) for x, y in top] + [(sx(top[-1][0]), sy(base)), (sx(top[0][0]), sy(base))]
                body = (f'<polygon points="{" ".join(f"{_n(px)},{_n(py)}" for px, py in pts)}" fill="{colours[0]}" fill-opacity="0.18" stroke="none"'
                        + (' class="hatch"' if texture_on() else "") + "/>" + body)
        steps.append((body, say))
    if marks:
        parts, placed = [], []   # label boxes already placed: a label that would overlap one moves up (live: x = 2 and x = 3 collided)
        for mx, my, label in sorted(marks):
            if clip(my) is None:
                continue
            X, Y = sx(mx), sy(my)
            tag = f"{label} ({fmt(mx)}, {fmt(my)})" if label else f"({fmt(mx)}, {fmt(my)})"
            right = X < px0 + pw * 0.6
            tw = len(tag) * 7.4                                   # Inter bold 13 px: about 7.4 px a character, on the wide side
            lx = X + 10 if right else X - 10 - tw
            ly = Y - 10
            while any(lx < a + w and a < lx + tw and ly - 14 < b and b - 14 < ly for a, b, w in placed):
                ly -= 18
            placed.append((lx, ly, tw))
            parts.append(f'<line x1="{_n(X)}" y1="{_n(Y)}" x2="{_n(X)}" y2="{_n(py0 + ph)}" stroke="{INK2}" stroke-width="1.2" stroke-dasharray="4 4"/>'
                         f'<circle cx="{_n(X)}" cy="{_n(Y)}" r="6" fill="#FFFFFF" stroke="{INK}" stroke-width="2.4"/>'
                         + txt(lx, ly, tag, 13, "start", INK, 700))
        steps.append(("".join(parts), marks_say))

    out = [(f"b{n}_s{k + 1}", f'<g id="b{n}_s{k + 1}">{cam}{body}</g>', f"[[MARK:b{n}_s{k + 1}]] {demath(say)}") for k, (body, say) in enumerate(steps)]
    report = {"kind": "graph", "series": len(lines), "marks": [(fmt(a), fmt(b)) for a, b, _ in marks]}
    return out, {"x": bx, "y": by, "w": w, "h": h}, report
