"""
engine/scene.py
The lesson board: the tutor says WHAT to show, the code decides WHERE. The page is a lesson board
that grows like a notebook, and the frontend camera follows the block being explained.

Blocks: write_notes (handwritten lines with **bold** and ==highlight==; style recap = a card of takeaways) and draw_scene (a diagram:
nodes, edges, groups, teaching steps; no coordinates). This module measures every text (embedded Inter, Caveat from
engine/scene_layout/), lays diagrams out with ELK.js (Node, engine/scene_layout/), a ring for loops or a zigzag for long chains,
places each block on the board (notes on the left, diagrams on the right or full width), and turns each teaching step into one
ordinary board element <g id="b{n}_s{k}"> plus its narration. The author publishes those through the same audio/persist/emit path as
draw_new_element, so replay, annotations, export and learner pointing keep working. Every step carries its block's box in an empty
<desc class="cam cam-x-y-w-h"> (no geometry, so element boxes are unchanged): the camera reads it, and so does the next placement.
Evidence: docs/benchmark_runs/2026-11-05-scene-poc/README.md (same 13 prompts: gpt-4.1 0/13 usable -> 12/13).
"""

import base64
import html
import io
import json
import os
import math
import re
import shutil
import subprocess
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape

from fontTools.ttLib import TTFont

from engine._font_data import INTER_BOLD_WOFF2_B64, INTER_REGULAR_WOFF2_B64

LAYOUT_DIR = Path(__file__).parent / "scene_layout"


def _load_icons() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Lucide (ISC): name -> inner SVG markup, and tag -> name, from the pinned lucide-static package (npm install in scene_layout);
    without it, the small committed icons.json (95 icons, names only)."""
    pkg = LAYOUT_DIR / "node_modules" / "lucide-static"
    if not (pkg / "icon-nodes.json").exists():
        return json.loads((LAYOUT_DIR / "icons.json").read_text(encoding="utf-8")), {}
    nodes = json.loads((pkg / "icon-nodes.json").read_text(encoding="utf-8"))
    tags = json.loads((pkg / "tags.json").read_text(encoding="utf-8"))
    icons = {k: "".join("<%s %s/>" % (t, " ".join('%s="%s"' % a for a in at.items())) for t, at in v) for k, v in nodes.items()}
    by_tag: Dict[str, str] = {}
    for name in sorted(tags):
        for t in tags[name]:
            by_tag.setdefault(t.lower(), name)
    return icons, by_tag


ICONS, ICON_TAGS = _load_icons()
ICON_ALIASES = {"person": "user", "people": "users", "learner": "user", "student": "user", "customer": "user", "client": "monitor",
                "computer": "monitor", "internet": "globe", "web": "globe", "website": "globe", "money": "banknote",
                "plant": "sprout", "data": "database", "storage": "hard-drive", "memory": "memory-stick",
                "cache": "zap", "email": "mail", "message": "message-square", "document": "file-text", "file": "file-text",
                "idea": "lightbulb", "energy": "zap", "water": "droplet", "time": "clock", "security": "shield",
                # teaching words with a clear Lucide picture under another name (checked by hand 2026-11-22; a wrong icon misleads more than
                # none, so metaphors like volcano->mountain are left out). Grow from: python scripts/logs_query.py --all --icon-misses
                "ice": "snowflake", "snow": "snowflake", "farm": "tractor", "teacher": "graduation-cap", "electron": "atom",
                "packet": "package", "parcel": "package", "neuron": "brain", "tax": "receipt", "invoice": "receipt", "loan": "hand-coins",
                "debt": "hand-coins", "supplier": "truck", "delivery": "truck"}


def match_icon(word) -> str | None:
    """A Lucide icon name for a plain word: exact name, a short alias, then Lucide's own tags. No guessing beyond that."""
    w = re.sub(r"[\s_]+", "-", str(word or "").strip().lower())
    cands = list(dict.fromkeys([w, w[:-1] if w.endswith("s") else w]))
    for look in (lambda c: c, ICON_ALIASES.get, ICON_TAGS.get):   # exact name, then alias, then tag, for the word and its singular
        for c in cands:
            if look(c) in ICONS:
                return look(c)
    return None

W, H = 1200, 800   # the board width and the camera view shape
MAX_NODES = 16          # more than this is two ideas: the tutor is asked to split it
MAX_LINES = 8           # notes per block
MAX_EDGES, MAX_STEPS = 40, 12   # every step is a paid voice clip, and a runaway or prompt-injected tutor must not be able to order hundreds
MAX_BLOCKS_PER_TURN = 6     # x up to 12 clips each: the most voice one learner message can buy (security review)
MAX_TEXT, MAX_SAY = 160, 600    # characters in one label/line, and in what is said for one step (longer is cut)
LAYOUT_TIMEOUT_S = 15

# the board: notes on the left, diagrams on the right, wide diagrams across both; blocks stack downwards
NOTE_LANE, DIAGRAM_LANE, WIDE_LANE = (40, 500), (580, 580), (40, 1120)
TOP, GAP, MAX_BLOCK_H = 32, 48, 640
HAND, INTER = "Caveat, 'Caveat Board', Kalam, cursive", "Inter, 'Inter Board', sans-serif"   # 'Caveat Board' / 'Inter Board' are the faces embedded for exports (board_font_css)
CAVEAT = LAYOUT_DIR / "node_modules" / "@fontsource" / "caveat" / "files"
HAND_LINE, HAND_TITLE = (30, 400, 37), (36, 700, 44)   # Caveat's small x-height: 30 px reads like ~20 px of Inter
HIGHLIGHT = "#FDE68A"

# (size, weight, line height); the embedded font has 400 and 700 only
LABEL, DETAIL, EDGE, SEC_H = (18, 700, 23), (14, 400, 19), (13, 400, 17), (12, 700, 17)
# category colours (soft fill, strong stroke) from the app's tokens (frontend/src/index.css), assigned by first appearance
PALETTE = [("#E3F1EF", "#0F766E"), ("#E8EEFB", "#1D4ED8"), ("#EFEAFB", "#5B21B6"), ("#FEF3C7", "#B45309"), ("#FCE8F0", "#9D174D"), ("#E7F4EA", "#166534")]
MUTED = ("#F0EDE4", "#5B6472")
INK, INK2, LINE = "#1F2A37", "#5B6472", "#4B5563"
SHAPES = ["box", "diamond", "cylinder", "circle", "pill"]


class SceneError(Exception):
    """The scene cannot be drawn; the message goes back to the tutor."""


# ---------------------------------------------------------------------------------------------------------------------------------
# What the tutor sees
# ---------------------------------------------------------------------------------------------------------------------------------

SCENE_SYSTEM_PROMPT = """You are a one-on-one tutor teaching any topic on a live whiteboard. You explain by speaking and writing together.
The board works like a notebook: everything you add is a block that the app places, sizes and keeps readable, and the camera follows what you are explaining. Never think about coordinates, sizes or spacing.

BLOCKS
- write_notes: short handwritten lines, revealed one at a time while you say each one. For definitions, key terms, numbered steps and comparisons in words. Wrap a line's key term in **double stars**. A whole line in $...$ is a formula in TeX, typeset properly (give it a say). Use ==double equals== sparingly, at most once per block: for the single phrase the learner must remember. Highlighting everything highlights nothing.
- draw_scene: one diagram of boxes and arrows, built up in steps. For structure, flow, cause and effect, a process or a loop. Show what the explanation needs and nothing decorative; one idea per diagram.
- write_notes with style "recap": a card of two to four takeaways, to close an idea.
- draw_graph: an exact chart, when a number changes with another (a curve, growth over time, supply and demand, a measured trend). Give the formula or the data; the app computes every value, so never work out coordinates yourself. Mark the points you will talk about.
- calculate: before you say or write any number you worked out (money, growth, a total, a worked example), get it from calculate and quote that value. Never do arithmetic in your head.
- draw_table: a small table, to compare a few things across a few properties. draw_bar_chart: amounts across categories, to scale. draw_venn: what 2 or 3 groups share and do not share. Give the content; the app lays it out.
- replace_block: change a block already on the board (id "b3" as in blocks_on_board): fix a mistake, or add to it after a follow-up, instead of drawing it again.
- write_notes with style "code": real code the learner can type, a chunk per step while you explain what it does. When the learner asks for code or an example program, show code, not a diagram of it.
- A clear explanation usually goes: a few notes that name the idea, the diagram that shows it, then a recap. The blocks split the work and never repeat each other: notes give definitions, key terms and why it matters; the diagram shows how the parts connect; do not list in the notes the same steps the diagram is about to show. Not every answer needs all three; a short follow-up may need one block or none (answer in text when words alone are clearer).
- When the learner moves on to a different topic, call start_new_page first. A follow-up on the same topic stays on this board.
- When the learner signals to continue, move the lesson forward.

TEACHING
- Teach one idea at a time and build it up: each line or step is what you say aloud while it appears (one to three sentences, plain text).
- Your first answer to a new question answers all of it in short (every part of it), then builds the first idea; the details come in later turns.
- After you finish explaining an idea, check understanding: end your reply with one short question that makes the learner think, not one whose answer you just said: ask them to apply or explain it ("why…", "what would happen if…", "which would…"), not to repeat a fact you just gave ("what is…", "what does it make…").
- Start your next reply with their answer. When it is right, say why and move on. No flattery: open with "Right" or "Exactly" only when it is fully right; a vague, guessed or partly right answer is not right.
- When it is wrong or vague, do not give the answer the first time: say plainly that it is not right yet, then ask one smaller, easier question that leads them to see the flaw in their own reasoning (for example, ask what their idea would predict in a simple case). Teach nothing new in that turn. After a second miss on the same idea, explain it directly in a sentence or two, then check the same idea again from a different angle.
- If they skip it ("ok", "continue"), give the answer in a sentence and move on. Never ask the same question twice word for word.

POINTING
- When your answer is about something already on the board, point at it with annotate_element while you say it.
- annotate_element marks up anything already on the board (a node id, a group id or a step id), like a marker on a whiteboard: circle, underline, tick, cross, highlight, or an arrow between two ids. Put [[MARK:annotation_id]] at the start of its narration. remove_annotation clears a mark.
- When the learner circles or highlights parts of the board, their message begins with a prefix such as `[Learner circled diagram element(s): 'id' (Label) (0.92 match)]`. They are asking about those parts: answer about them. With two, they are asking how the two relate.

FINAL REPLY
- After adding blocks, your chat reply is one or two sentences: the learner has already heard every line and step, so do not repeat them. Ask your check question or offer the next thing to explore.
- Never put [[MARK:...]] in it."""

NOTES_TOOL = {"type": "function", "function": {
    "name": "write_notes",
    "description": "Adds a block of short handwritten lines to the board and reads them out one by one. Placement is automatic.",
    "parameters": {"type": "object", "required": ["lines"], "properties": {
        "title": {"type": "string", "description": "Optional short heading for the block."},
        "style": {"type": "string", "enum": ["notes", "recap", "code"], "description": "notes (default): handwritten lines; recap: a card of two to four takeaways; code: a code card, each line item a chunk of real code."},
        "lines": {"type": "array", "description": f"One to {MAX_LINES} lines, in teaching order.", "items": {"type": "object", "required": ["text"], "properties": {
            "text": {"type": "string", "description": "What is written: short (about 12 words). **term** for the key term; ==phrase== at most once per block, for the one thing to remember. Start with '1.' to number steps. A whole line in $...$ is a formula in TeX (for example $E = mc^2$ or $\\frac{1}{\\lambda^4}$), typeset properly; give it a `say`. For style code: a chunk of code, one to six lines separated by \\n, indented as it should be."},
            "say": {"type": "string", "description": "What you say aloud while this line appears (one to three sentences). Defaults to the line itself. For style code it is required: explain what the chunk does, never read the code out."}}}},
    }}}}

REPLACE_TOOL = {"type": "function", "function": {
    "name": "replace_block",
    "description": ("Change a block already on this page: correct it (a wrong label, a mistake) or add to it after a follow-up question (new nodes, lines, rows or steps). "
                    "Give its id (e.g. \"b3\"), the same tool and the complete new content. It is redrawn in the same place, and only what changed is shown and narrated; "
                    "use it instead of drawing the block again."),
    "parameters": {"type": "object", "required": ["block", "tool", "args", "say"], "properties": {
        "block": {"type": "string", "description": "The block's id, e.g. \"b3\"."},
        "tool": {"type": "string", "description": "The tool that drew it (write_notes, draw_scene, draw_graph, draw_table, draw_bar_chart or draw_venn)."},
        "args": {"type": "object", "description": "Exactly the fields that tool takes, with the complete new content."},
        "say": {"type": "string", "description": "One sentence about the change (e.g. what was corrected, or what you are adding)."}}}}}

SCENE_TOOL = {"type": "function", "function": {
    "name": "draw_scene",
    "description": "Adds one teaching diagram to the board and narrates it step by step. Layout and placement are automatic.",
    "parameters": {"type": "object", "required": ["title", "layout", "nodes", "edges", "steps"], "properties": {
        "title": {"type": "string", "description": "Short title shown above the diagram."},
        "layout": {"type": "string", "enum": ["flow", "cycle"], "description": "cycle when the main idea is a loop that returns to its start; otherwise flow."},
        "direction": {"type": "string", "enum": ["right", "down"], "description": "Preferred reading direction; the app may switch it to fit the board."},
        "groups": {"type": "array", "description": "Only when a real boundary helps (for example, 'Web tier').",
                   "items": {"type": "object", "required": ["id", "label"], "properties": {"id": {"type": "string"}, "label": {"type": "string"}}}},
        "nodes": {"type": "array", "items": {"type": "object", "required": ["id", "label", "shape"], "properties": {
            "id": {"type": "string"},
            "label": {"type": "string", "description": "The name of the thing, short. When the learner asks for specific wording, use it exactly."},
            "detail": {"type": "string", "description": "Optional: one short supporting line under the label."},
            "shape": {"type": "string", "enum": SHAPES, "description": "box: step or component; diamond: yes/no decision; cylinder: stored data; circle: natural thing or state; pill: start, end or person."},
            "category": {"type": "string", "description": "One short word for what kind of thing it is (for example input, process, output). Nodes of the same kind share a colour: use two to five categories."},
            "icon": {"type": "string", "description": "A plain word for a small picture above the label: give one to each node that is a concrete thing (e.g. \"server\", \"database\", \"user\", \"cell\", \"sun\", \"money\"); leave it out for abstract ideas (a process step, a rule, a number)."},
            "tone": {"type": "string", "enum": ["default", "accent", "muted"], "description": "accent on the one or two things to emphasise; muted for background things."},
            "group": {"type": "string", "description": "Id of the group this node sits in."},
            "sections": {"type": "array", "description": "For a card that summarises or compares: a few headed lines (for example Pros and Cons). Use sections instead of cramming several facts into the label.",
                         "items": {"type": "object", "required": ["heading", "text"], "properties": {"heading": {"type": "string"}, "text": {"type": "string"}}}},
        }}},
        "edges": {"type": "array", "description": "One per relationship, pointing in the direction of the flow.", "items": {"type": "object", "required": ["id", "from", "to"], "properties": {
            "id": {"type": "string"}, "from": {"type": "string"}, "to": {"type": "string"},
            "label": {"type": "string", "description": "Short; only when it adds meaning or the learner asked for it."},
            "dashed": {"type": "boolean"}}}},
        "steps": {"type": "array", "items": {"type": "object", "required": ["say", "show"], "properties": {
            "say": {"type": "string", "description": "What you say aloud in this step. Plain text."},
            "show": {"type": "array", "items": {"type": "string"}, "description": "Ids of the nodes, edges and groups that appear in this step."}}}},
    }}}}


# ---------------------------------------------------------------------------------------------------------------------------------
# Checking the scene (problems the code cannot repair go back to the tutor)
# ---------------------------------------------------------------------------------------------------------------------------------

def _slug(s) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", _raw(s))[:40]


def _raw(v) -> str:
    """An id as the model wrote it, whatever JSON it used: "a", 3, or {"id": "a"} (an unhashable dict crashed normalise: code review)."""
    return _txt(v.get("id") if isinstance(v, dict) else v).strip()


def _lst(v) -> list:
    return v if isinstance(v, list) else []


CUTS: ContextVar = ContextVar("cuts", default=None)   # the list one block build records its trimmed texts into (author.build_block sets it)


def _cut(s: str, limit: int, what: str) -> str:
    """s cut to `limit` characters; what was lost is recorded for cut_note, so the tutor can be told."""
    if len(s) > limit and (c := CUTS.get()) is not None:
        c.append(f'{what} "{s[:30]}..." ({len(s)} -> {limit} chars)')
    return s[:limit]


def _txt(v) -> str:
    """A text field as the tutor meant it; a list, object, true/false or null is no text (each crashed the build: security fuzz)."""
    return str(v) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def normalise(scene: dict) -> dict:
    """Repairable slips are repaired (ids made safe; unknown shapes/icons dropped; parts never shown go to the last step; an arrow
    waits until both its ends are on the board; a group appears with its first member). Unrepairable ones raise SceneError."""
    if not isinstance(scene, dict):
        raise SceneError("draw_scene needs an object with title, layout, nodes, edges and steps.")
    # every field coerced to the type the schema asks for, once, here: the model's tool arguments are not schema-checked
    nodes = [{**n, **{k: _txt(n.get(k)) for k in ("shape", "icon", "category", "tone")}, **{k: demath(_txt(n.get(k))) for k in ("label", "detail")},
              "sections": _lst(n.get("sections"))}
             for n in _lst(scene.get("nodes")) if isinstance(n, dict)]
    edges = [{**e, "label": demath(_txt(e.get("label"))), "dashed": e.get("dashed") is True} for e in _lst(scene.get("edges")) if isinstance(e, dict)]
    groups = [{**g, "label": _txt(g.get("label"))} for g in _lst(scene.get("groups")) if isinstance(g, dict)]
    steps = [{"say": _txt(st.get("say")), "show": _lst(st.get("show"))} for st in _lst(scene.get("steps")) if isinstance(st, dict)]
    problems, misses = [], []
    if not nodes:
        problems.append("The scene has no nodes.")
    if len(nodes) > MAX_NODES:
        problems.append(f"The scene has {len(nodes)} nodes; at most {MAX_NODES} fit one readable diagram. Teach it as two scenes.")
    if len(edges) > MAX_EDGES or len(steps) > MAX_STEPS:
        problems.append(f"A diagram holds at most {MAX_EDGES} edges and {MAX_STEPS} steps. Teach it as two scenes.")
    if not steps or not all(str(s.get("say") or "").strip() for s in steps):
        problems.append("Every step needs 'say': what you say aloud while its parts appear.")

    rename = {}
    for item in nodes + edges + groups:
        old = _raw(item.get("id"))
        new = _slug(old) or f"n{len(rename)}"
        if new.startswith("step_"):
            new = "x_" + new
        item["id"] = rename[old] = new
    ids = [i["id"] for i in nodes + edges + groups]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        problems.append(f"Ids must be unique across nodes, edges and groups; repeated: {dups}.")
    node_ids, group_ids = {n["id"] for n in nodes}, {g["id"] for g in groups}
    for e in edges:
        e["from"], e["to"] = rename.get(_raw(e.get("from")), _slug(e.get("from"))), rename.get(_raw(e.get("to")), _slug(e.get("to")))
        if e["from"] not in node_ids or e["to"] not in node_ids:
            problems.append(f"Edge '{e['id']}' connects '{e['from']}' to '{e['to']}', but both ends must be node ids.")
    for item in nodes + edges + groups:   # every text the board will show, cut to a readable length
        for k in ("label", "detail"):
            if isinstance(item.get(k), str):
                item[k] = _cut(item[k], MAX_TEXT, k)
    for n in nodes:
        if not str(n.get("label") or "").strip():
            problems.append(f"Node '{n['id']}' needs a label.")
        if n.get("group"):
            n["group"] = rename.get(_raw(n["group"]), _slug(n["group"]))
            if n["group"] not in group_ids:
                problems.append(f"Node '{n['id']}' is in group '{n['group']}', which is not in groups.")
        if n.get("shape") not in SHAPES:
            n["shape"] = "box"
        word = n.pop("icon", "")
        if word and (name := match_icon(word)):
            n["icon"] = name
        elif word:
            misses.append(word)
        n["sections"] = [{"heading": _cut(_txt(s.get("heading")), MAX_TEXT, "heading"), "text": _cut(_txt(s.get("text")), MAX_TEXT, "text")}
                         for s in n["sections"][:6] if isinstance(s, dict) and _txt(s.get("text")).strip()]
    if problems:
        raise SceneError(" ".join(problems))

    # when each part appears (step index)
    last = len(steps) - 1
    when: Dict[str, int] = {}
    for k, st in enumerate(steps):
        for raw in st.get("show") or []:
            when.setdefault(rename.get(_raw(raw), _slug(raw)), k)
    for n in nodes:
        when.setdefault(n["id"], last)
    for g in groups:
        members = [when[n["id"]] for n in nodes if n.get("group") == g["id"]]
        when[g["id"]] = min(members) if members else when.get(g["id"], last)
    for e in edges:
        when[e["id"]] = max(when.get(e["id"], 0), when[e["from"]], when[e["to"]])
    groups = [g for g in groups if any(n.get("group") == g["id"] for n in nodes)]
    return {"title": _cut(demath(_txt(scene.get("title"))).strip(), MAX_TEXT, "title"), "layout": _txt(scene.get("layout")), "direction": _txt(scene.get("direction")),
            "nodes": nodes, "edges": edges, "groups": groups, "steps": [{"say": _cut(str(s["say"]).strip(), MAX_SAY, f"narration of step {k + 1}")} for k, s in enumerate(steps)], "when": when, "icon_misses": misses}


# ---------------------------------------------------------------------------------------------------------------------------------
# Text measurement (the same Inter the board renders with)
# ---------------------------------------------------------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _metrics(hand: bool, bold: bool):
    """cmap, advance widths and units per em: the embedded Inter, or Caveat from engine/scene_layout (npm)."""
    if hand:
        path = CAVEAT / f"caveat-latin-{700 if bold else 400}-normal.woff2"
        if not path.exists():
            raise SceneError("The handwriting font is not installed on the server (needs `npm install` in engine/scene_layout).")
        f = TTFont(str(path))
    else:
        f = TTFont(io.BytesIO(base64.b64decode(INTER_BOLD_WOFF2_B64 if bold else INTER_REGULAR_WOFF2_B64)))
    return f.getBestCmap(), f["hmtx"].metrics, f["head"].unitsPerEm


@lru_cache(maxsize=8192)
def measure(text: str, size: float, weight: int, hand: bool = False) -> float:
    cmap, hmtx, upm = _metrics(hand, weight >= 600)
    return size * sum(hmtx[cmap[ord(c)]][0] / upm if ord(c) in cmap else 0.6 for c in text)   # a glyph outside the subset: 0.6 em


def measure_hand(text: str, size: float, bold: bool) -> float:
    return measure(text, size, 700 if bold else 400, hand=True)


def rich_words(text: str) -> List[Tuple[str, bool, bool]]:
    """'a **term** and ==this phrase==' -> [(word, bold, highlight)]. Unclosed markers are kept as written."""
    out, glue = [], False
    for part in re.split(r"(\*\*[^*]+\*\*|==[^=]+==)", str(text)):
        bold, hl = part.startswith("**") and part.endswith("**") and len(part) > 4, part.startswith("==") and part.endswith("==") and len(part) > 4
        words = (part[2:-2] if bold or hl else part).split()
        if glue and words and part[:1].strip():   # "**Supply**: ..." -> "Supply:" (not "Supply :", seen live)
            out[-1] = (out[-1][0] + words.pop(0), out[-1][1], out[-1][2])
        out += [(w, bold, hl) for w in words]
        glue = (bold or hl) and bool(words)
    return out


def wrap_rich(words, size: float, max_w: float, width=None) -> List[list]:
    """Words (word, bold, highlight) into lines no wider than max_w (a single longer word keeps its own line); handwriting by default."""
    width = width or (lambda t, bold: measure_hand(t, size, bold))
    space = width(" ", False)
    lines, cur, cur_w = [], [], 0.0
    for w in words:
        ww = width(w[0], w[1])
        if cur and cur_w + space + ww > max_w:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur_w += (space if cur else 0) + ww
        cur.append(w)
    return lines + [cur] if cur else lines


def wrap(text: str, f, max_w: float) -> List[str]:
    """Plain text in Inter, by the same greedy wrapping."""
    lines = wrap_rich([(w, False, False) for w in str(text).split()], f[0], max_w, lambda t, _: measure(t, f[0], f[1]))
    return [" ".join(w for w, _, _ in line) for line in lines] or [""]


def _row_h(r) -> float:
    return 34 if "icon" in r else r.get("gap") or r["f"][2]


def size_node(n: dict) -> dict:
    """Content rows (icon, label, detail, card sections) and the box that holds them."""
    card = bool(n["sections"])
    if card:
        max_w = 250
    else:
        max_w = 230 if n.get("detail") else 190
    rows = [{"icon": n["icon"]}] if n.get("icon") else []
    rows += [{"text": t, "f": LABEL, "color": INK} for t in wrap(n["label"], LABEL, max_w)]
    if n.get("detail"):
        rows += [{"gap": 5}] + [{"text": t, "f": DETAIL, "color": INK2} for t in wrap(n["detail"], DETAIL, max_w)]
    head_h = sum(_row_h(r) for r in rows)
    for i, sec in enumerate(n["sections"]):
        rows.append({"gap": 12 if i else 22, "body": True})
        rows += [{"text": t, "f": SEC_H, "color": "cat", "body": True} for t in wrap(str(sec.get("heading") or "").upper(), SEC_H, max_w)]
        rows += [{"text": t, "f": DETAIL, "color": INK, "body": True} for t in wrap(sec["text"], DETAIL, max_w)]
    tw = max([measure(r["text"], r["f"][0], r["f"][1]) for r in rows if "text" in r] + [28 if n.get("icon") else 0])
    th = sum(_row_h(r) for r in rows)
    w, h = max(tw + 32, 200 if card else 120), max(th + (34 if card else 24), 52)
    shape = "card" if card else n["shape"]
    if shape == "diamond":
        w, h = (tw / 2 + 8) / 0.55 * 2, (th / 2 + 6) / 0.45 * 2
    elif shape == "circle":
        w = h = max(math.hypot(tw, th) + 24, 90)
    elif shape == "cylinder":
        h += 18
    return {**n, "shape": shape, "rows": rows, "head_h": head_h, "th": th, "width": math.ceil(w), "height": math.ceil(h)}


def edge_label(e: dict):
    if not e.get("label"):
        return None
    lines = wrap(e["label"], EDGE, 150)
    return {"lines": lines, "width": math.ceil(max(measure(t, EDGE[0], EDGE[1]) for t in lines) + 14), "height": len(lines) * EDGE[2] + 8}


# ---------------------------------------------------------------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------------------------------------------------------------

def _elk_graph(scene, nodes, direction):
    by_group: Dict[str, list] = {}
    for n in nodes:
        by_group.setdefault(n.get("group") or "", []).append({"id": n["id"], "width": n["width"], "height": n["height"]})
    children = by_group.get("", []) + [{"id": g["id"], "layoutOptions": {"elk.padding": "[top=44,left=20,bottom=20,right=20]"}, "children": by_group[g["id"]]}
                                      for g in scene["groups"] if g["id"] in by_group]
    edges = []
    for e in scene["edges"]:
        lab = edge_label(e)
        edges.append({"id": e["id"], "sources": [e["from"]], "targets": [e["to"]],
                      "labels": [{"text": e["label"], "width": lab["width"], "height": lab["height"], "layoutOptions": {"elk.edgeLabels.inline": "true"}}] if lab else []})
    return {"id": "root", "children": children, "edges": edges, "layoutOptions": {
        "elk.algorithm": "layered", "elk.direction": direction, "elk.edgeRouting": "ORTHOGONAL", "elk.hierarchyHandling": "INCLUDE_CHILDREN",
        "elk.spacing.nodeNode": "45", "elk.layered.spacing.nodeNodeBetweenLayers": "70", "elk.spacing.edgeNode": "24", "elk.spacing.edgeEdge": "16",
        "elk.layered.spacing.edgeNodeBetweenLayers": "24", "elk.spacing.edgeLabel": "6", "elk.edgeLabels.placement": "CENTER",
        "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX", "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
        "elk.padding": "[top=0,left=0,bottom=0,right=0]",
        # break a loop where the tutor's order says it goes back (the fail -> retry edge), but only when there is a loop: on a graph
        # without one, MODEL_ORDER also reverses ordinary converging arrows (supply -> price), which stretched it into one long line
        **({"elk.layered.cycleBreaking.strategy": "MODEL_ORDER"} if _has_cycle(scene) else {})}}


def _has_cycle(scene) -> bool:
    nxt: Dict[str, list] = {}
    for e in scene["edges"]:
        nxt.setdefault(e["from"], []).append(e["to"])
    state: Dict[str, int] = {}   # 1 on the current path, 2 done

    def visit(v) -> bool:
        state[v] = 1
        for w in nxt.get(v, []):
            if state.get(w) == 1 or (w not in state and visit(w)):
                return True
        state[v] = 2
        return False
    return any(v not in state and visit(v) for v in nxt)


def missing_parts() -> List[str]:
    """What scene mode needs on this server and does not have (checked at startup; empty when ready)."""
    out = [] if shutil.which("node") else ["Node is not on PATH"]
    out += [f"{name} is not installed (run `npm install` in engine/scene_layout)" for name, path in
            (("elkjs", LAYOUT_DIR / "node_modules" / "elkjs"), ("@fontsource/caveat", CAVEAT),
             ("mathjax-full", LAYOUT_DIR / "node_modules" / "mathjax-full")) if not path.exists()]
    return out


MATH_RE = re.compile(r"^\s*\$+(.+?)\$+\s*$", re.S)   # a note line that is a formula: $...$ (or $$...$$)
EX_PX = 11                                            # one MathJax ex on the board: formulas about the size of the handwriting


def render_math(texs: List[str]) -> List[dict]:
    """TeX formulas as SVG (MathJax in Node, scene_layout/math.mjs): [{svg, w, h} in ex, or {error}]."""
    node = shutil.which("node")
    if not node or not (LAYOUT_DIR / "node_modules" / "mathjax-full").exists():
        raise SceneError("Formulas are not available on this server (needs `npm install` in engine/scene_layout); write it in words.")
    try:
        out = subprocess.run([node, "math.mjs"], input=json.dumps(texs), capture_output=True, text=True, cwd=LAYOUT_DIR,
                             timeout=LAYOUT_TIMEOUT_S, encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        raise SceneError("The formula took too long to typeset; write a shorter one.") from e
    if out.returncode != 0:
        raise SceneError(f"The formula engine failed: {out.stderr.strip()[:300]}")
    res = json.loads(out.stdout)
    for r in res:   # an unknown command is typeset in red (merror) instead of failing: the tutor should fix it
        if "svg" in r and ('data-mml-node="merror"' in r["svg"] or 'fill="red"' in r["svg"]):
            r.clear()
            r["error"] = "unknown command"
    return res


def math_svg(r: dict, x: float, y: float, max_w: float, colour: str = INK) -> Tuple[str, float, float]:
    """A typeset formula placed with its top-left at (x, y), at most max_w wide: (svg, width, height)."""
    w, h = r["w"] * EX_PX, r["h"] * EX_PX
    k = min(1.0, max_w / w)
    w, h = w * k, h * k
    body = re.sub(r'^<svg[^>]*?(viewBox="[^"]*")[^>]*>', lambda m: f'<svg x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" {m.group(1)}>', r["svg"], count=1)
    body = body.replace('stroke="currentColor" fill="currentColor"', f'stroke="{colour}" fill="{colour}" class="ink"', 1)
    return body, w, h


def _run_elk(graphs: list) -> list:
    node = shutil.which("node")
    if not node or not (LAYOUT_DIR / "node_modules" / "elkjs").exists():
        raise SceneError("The layout engine is not installed on the server (needs Node and `npm install` in engine/scene_layout).")
    try:
        out = subprocess.run([node, "layout.mjs"], input=json.dumps(graphs), capture_output=True, text=True, cwd=LAYOUT_DIR,
                             timeout=LAYOUT_TIMEOUT_S, encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        raise SceneError("The layout engine took too long; draw a smaller diagram.") from e
    if out.returncode != 0:
        raise SceneError(f"The layout engine failed: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def _flatten(g: dict) -> dict:
    """ELK result -> absolute boxes for nodes and groups, edge routes, edge-label boxes."""
    pos, gbox = {}, {}

    def walk(node, ox, oy):
        for c in node.get("children") or []:
            x, y = ox + c["x"], oy + c["y"]
            if c.get("children"):
                gbox[c["id"]] = {"x": x, "y": y, "w": c["width"], "h": c["height"]}
                walk(c, x, y)
            else:
                pos[c["id"]] = {"x": x, "y": y, "w": c["width"], "h": c["height"]}
    walk(g, 0, 0)
    routes, chips = {}, {}
    for e in (g.get("edges") or []) + [e for c in g.get("children") or [] for e in c.get("edges") or []]:
        ox, oy = (gbox[e["container"]]["x"], gbox[e["container"]]["y"]) if e.get("container") in gbox else (0, 0)
        if not e.get("sections"):
            continue
        s = e["sections"][0]
        routes[e["id"]] = [{"x": p["x"] + ox, "y": p["y"] + oy} for p in [s["startPoint"], *(s.get("bendPoints") or []), s["endPoint"]]]
        if e.get("labels"):
            lb = e["labels"][0]
            chips[e["id"]] = {"x": lb["x"] + ox, "y": lb["y"] + oy, "w": lb["width"], "h": lb["height"]}
    return {"pos": pos, "gbox": gbox, "routes": routes, "chips": chips, "w": g["width"], "h": g["height"]}


def _overlaps(a, b, m=0.0) -> bool:
    return a["x"] < b["x"] + b["w"] - m and b["x"] < a["x"] + a["w"] - m and a["y"] < b["y"] + b["h"] - m and b["y"] < a["y"] + a["h"] - m


def _clip(c, t, b, shape):
    """Where the ray from the centre c towards t leaves the shape b."""
    dx, dy = t["x"] - c["x"], t["y"] - c["y"]
    if shape == "circle":
        d = math.hypot(dx, dy) or 1
        return {"x": c["x"] + dx / d * b["w"] / 2, "y": c["y"] + dy / d * b["w"] / 2}
    if shape == "diamond":
        k = 1 / ((abs(dx) / (b["w"] / 2) + abs(dy) / (b["h"] / 2)) or 1)
    else:
        k = min(abs(b["w"] / 2 / (dx or 1e-9)), abs(b["h"] / 2 / (dy or 1e-9)))
    return {"x": c["x"] + dx * k, "y": c["y"] + dy * k}


def _ring(scene, nodes, f):
    n, max_w, max_h = len(nodes), max(v["width"] for v in nodes), max(v["height"] for v in nodes)
    rx, ry = f * max(120, n * 45 + max_w * 0.4), f * max(90, n * 25 + max_h * 0.4)   # start tight; _ring_layout grows it until nothing overlaps
    pos, centers, shape = {}, {}, {v["id"]: v["shape"] for v in nodes}
    for i, v in enumerate(nodes):
        a = -math.pi / 2 + i * 2 * math.pi / n
        centers[v["id"]] = {"x": rx * math.cos(a), "y": ry * math.sin(a)}
        pos[v["id"]] = {"x": centers[v["id"]]["x"] - v["width"] / 2, "y": centers[v["id"]]["y"] - v["height"] / 2, "w": v["width"], "h": v["height"]}
    routes, chips = {}, {}
    for e in scene["edges"]:
        a, b = centers[e["from"]], centers[e["to"]]
        p1, p2 = _clip(a, b, pos[e["from"]], shape[e["from"]]), _clip(b, a, pos[e["to"]], shape[e["to"]])
        d = math.hypot(p2["x"] - p1["x"], p2["y"] - p1["y"]) or 1
        ux, uy = (p2["x"] - p1["x"]) / d, (p2["y"] - p1["y"]) / d
        routes[e["id"]] = [{"x": p1["x"] + ux * 8, "y": p1["y"] + uy * 8}, {"x": p2["x"] - ux * 8, "y": p2["y"] - uy * 8}]
        lab = edge_label(e)
        if lab:
            mx, my = (p1["x"] + p2["x"]) / 2, (p1["y"] + p2["y"]) / 2
            r = math.hypot(mx, my) or 1
            push = abs(mx / r) * lab["width"] / 2 + abs(my / r) * lab["height"] / 2 + 18
            chips[e["id"]] = {"x": mx + mx / r * push - lab["width"] / 2, "y": my + my / r * push - lab["height"] / 2, "w": lab["width"], "h": lab["height"]}
    boxes = list(pos.values()) + list(chips.values())
    x0, y0 = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
    x1, y1 = max(b["x"] + b["w"] for b in boxes), max(b["y"] + b["h"] for b in boxes)
    sh = lambda p: {**p, "x": p["x"] - x0, "y": p["y"] - y0}
    return {"pos": {k: sh(v) for k, v in pos.items()}, "gbox": {}, "routes": {k: [sh(p) for p in v] for k, v in routes.items()},
            "chips": {k: sh(v) for k, v in chips.items()}, "w": x1 - x0, "h": y1 - y0}


def _ring_layout(scene, nodes):
    """Grow the ring until no two nodes and no label/node overlap."""
    f = 1.0
    while True:
        lay = _ring(scene, nodes, f)
        boxes, chips = list(lay["pos"].values()), list(lay["chips"].values())
        hit = any(_overlaps(a, b, -24) for i, a in enumerate(boxes) for b in boxes[i + 1:]) or any(_overlaps(c, b, -8) for c in chips for b in boxes)
        if not hit or f >= 4:
            return lay
        f += 0.1


def _chain(scene, nodes):
    """The nodes in order when the diagram is one simple chain (a->b->c..., no branches, no groups), else None."""
    if scene["groups"] or len(nodes) < 4 or len(scene["edges"]) != len(nodes) - 1:
        return None
    nxt = {e["from"]: e for e in scene["edges"]}
    targets = {e["to"] for e in scene["edges"]}
    if len(nxt) != len(scene["edges"]) or len(targets) != len(scene["edges"]):
        return None
    start = [n for n in nodes if n["id"] not in targets]
    by_id, order = {n["id"]: n for n in nodes}, []
    cur = start[0]["id"] if len(start) == 1 else None
    while cur and cur not in {n["id"] for n in order}:
        order.append(by_id[cur])
        cur = nxt[cur]["to"] if cur in nxt else None
    return order if len(order) == len(nodes) else None


def _snake(scene, order, rows):
    """A chain in `rows` rows that turn back on themselves (left to right, then right to left): short links only, no wrap-around lines."""
    per = math.ceil(len(order) / rows)
    rows = math.ceil(len(order) / per)   # 4 nodes asked in 3 rows fill only 2 (an empty row crashed the layout: code review)
    labs = {e["id"]: edge_label(e) for e in scene["edges"]}
    col_w = max(n["width"] for n in order)
    gap_x = max([70] + [l["width"] + 40 for l in labs.values() if l])
    gap_y = max([70] + [l["height"] + 40 for l in labs.values() if l])
    row_h = [max(n["height"] for n in order[r * per:(r + 1) * per]) for r in range(rows)]
    pos, centers = {}, {}
    for i, n in enumerate(order):
        r, c = divmod(i, per)
        col = c if r % 2 == 0 else per - 1 - c
        cx = col * (col_w + gap_x) + col_w / 2
        cy = sum(row_h[:r]) + r * gap_y + row_h[r] / 2
        centers[n["id"]] = {"x": cx, "y": cy}
        pos[n["id"]] = {"x": cx - n["width"] / 2, "y": cy - n["height"] / 2, "w": n["width"], "h": n["height"]}
    shape = {n["id"]: n["shape"] for n in order}
    routes, chips = {}, {}
    for e in scene["edges"]:
        a, b = centers[e["from"]], centers[e["to"]]
        p1, p2 = _clip(a, b, pos[e["from"]], shape[e["from"]]), _clip(b, a, pos[e["to"]], shape[e["to"]])
        routes[e["id"]] = [p1, p2]
        lab = labs[e["id"]]
        if lab:   # on the line, like ELK's inline labels
            chips[e["id"]] = {"x": (p1["x"] + p2["x"]) / 2 - lab["width"] / 2, "y": (p1["y"] + p2["y"]) / 2 - lab["height"] / 2, "w": lab["width"], "h": lab["height"]}
    w = per * col_w + (per - 1) * gap_x
    h = sum(row_h) + (rows - 1) * gap_y
    return {"pos": pos, "gbox": {}, "routes": routes, "chips": chips, "w": w, "h": h}


def arrange(scene: dict) -> Tuple[list, List[dict]]:
    """Sized nodes and the candidate layouts (unscaled, origin at (0, 0)), preferred first: a ring for a loop; otherwise ELK in the
    tutor's reading direction, ELK in the other one, and for a long simple chain the zigzag in two and three rows."""
    nodes = [size_node(n) for n in scene["nodes"]]
    if scene["layout"] == "cycle" and len(nodes) >= 3 and not scene["groups"]:
        return nodes, [_ring_layout(scene, nodes)]
    pref = "DOWN" if scene.get("direction") == "down" else "RIGHT"
    cands = [_flatten(g) for g in _run_elk([_elk_graph(scene, nodes, d) for d in (pref, "RIGHT" if pref == "DOWN" else "DOWN")])]
    order = _chain(scene, nodes)
    return nodes, cands + ([_snake(scene, order, r) for r in (2, 3)] if order else [])


def place(scene: dict, nodes: list, lay: dict, ox: float, oy: float, s: float) -> dict:
    """The layout scaled by s with its origin at (ox, oy): board coordinates for nodes, groups, labels and routes."""
    T = lambda b: {"x": ox + b["x"] * s, "y": oy + b["y"] * s, "w": b["w"] * s, "h": b["h"] * s}
    board = {"pos": {k: T(v) for k, v in lay["pos"].items()}, "gbox": {k: T(v) for k, v in lay["gbox"].items()},
             "chips": {k: T(v) for k, v in lay["chips"].items()},
             "routes": {k: [{"x": ox + p["x"] * s, "y": oy + p["y"] * s} for p in v] for k, v in lay["routes"].items()}}
    shape = {n["id"]: n["shape"] for n in nodes}
    if scene["layout"] != "cycle" or scene["groups"] or len(nodes) < 3:   # ELK ends on the bounding box: move them onto diamond/circle outlines
        for e in scene["edges"]:
            r = board["routes"].get(e["id"])
            if r and len(r) >= 2:
                _snap(r[0], r[1], board["pos"][e["from"]], shape[e["from"]])
                _snap(r[-1], r[-2], board["pos"][e["to"]], shape[e["to"]])
    return board


def _snap(pt, nb, b, shape):
    if shape not in ("diamond", "circle"):
        return
    cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    if abs(pt["x"] - nb["x"]) < 0.5 and abs(pt["x"] - cx) < b["w"] / 2:
        u = (pt["x"] - cx) / (b["w"] / 2)
        dy = b["h"] / 2 * (1 - abs(u)) if shape == "diamond" else b["h"] / 2 * math.sqrt(1 - u * u)
        pt["y"] = cy - dy if pt["y"] < cy else cy + dy
    elif abs(pt["y"] - nb["y"]) < 0.5 and abs(pt["y"] - cy) < b["h"] / 2:
        u = (pt["y"] - cy) / (b["h"] / 2)
        dx = b["w"] / 2 * (1 - abs(u)) if shape == "diamond" else b["w"] / 2 * math.sqrt(1 - u * u)
        pt["x"] = cx - dx if pt["x"] < cx else cx + dx


def geometry_issues(scene: dict, board: dict) -> List[list]:
    """Objective check of the laid-out board: overlaps, lines through nodes or labels, line crossings, off-canvas (logged, never blocking)."""
    P, C, R = board["pos"], board["chips"], board["routes"]
    issues = []
    ids = list(P)
    issues += [["node_overlap", a, b] for i, a in enumerate(ids) for b in ids[i + 1:] if _overlaps(P[a], P[b], 1)]
    issues += [["label_on_node", e, n] for e, c in C.items() for n in ids if _overlaps(c, P[n], 1)]

    def seg_hits(p, q, b, m=2):
        x0, y0, x1, y1 = b["x"] + m, b["y"] + m, b["x"] + b["w"] - m, b["y"] + b["h"] - m
        if x1 <= x0 or y1 <= y0:
            return False
        t0, t1, dx, dy = 0.0, 1.0, q["x"] - p["x"], q["y"] - p["y"]
        for pp, qq in ((-dx, p["x"] - x0), (dx, x1 - p["x"]), (-dy, p["y"] - y0), (dy, y1 - p["y"])):
            if pp == 0:
                if qq < 0:
                    return False
            else:
                r = qq / pp
                if pp < 0:
                    t0 = max(t0, r)
                else:
                    t1 = min(t1, r)
                if t0 > t1:
                    return False
        return t1 - t0 > 1e-6

    def cross(a, b, c, d):
        o = lambda p, q, r: (q["x"] - p["x"]) * (r["y"] - p["y"]) - (q["y"] - p["y"]) * (r["x"] - p["x"])
        return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0

    segs = {e["id"]: list(zip(R[e["id"]], R[e["id"]][1:])) for e in scene["edges"] if e["id"] in R}
    for e in scene["edges"]:
        for p, q in segs.get(e["id"], []):
            issues += [["line_through_node", e["id"], n] for n in ids if n not in (e["from"], e["to"]) and seg_hits(p, q, P[n])]
            issues += [["line_through_label", e["id"], o] for o, c in C.items() if o != e["id"] and seg_hits(p, q, c)]
    E = [e for e in scene["edges"] if e["id"] in segs]
    for i, a in enumerate(E):
        for b in E[i + 1:]:
            if {a["from"], a["to"]} & {b["from"], b["to"]}:
                continue
            if any(cross(p, q, r, t) for p, q in segs[a["id"]] for r, t in segs[b["id"]]):
                issues.append(["line_crosses_line", a["id"], b["id"]])
    boxes = list(P.values()) + list(C.values()) + list(board["gbox"].values())
    if any(b["x"] < 0 or b["y"] < 0 or b["x"] + b["w"] > W for b in boxes):   # the board grows downwards: only its sides are edges
        issues.append(["off_canvas"])
    return [list(i) for i in dict.fromkeys(tuple(i) for i in issues)]


# ---------------------------------------------------------------------------------------------------------------------------------
# SVG, one fragment per teaching step
# ---------------------------------------------------------------------------------------------------------------------------------

def _n(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _text(x, y, txt, f, s, color, anchor="middle") -> str:
    return (f'<text x="{_n(x)}" y="{_n(y + f[0] * 0.8 * s)}" text-anchor="{anchor}" font-family="{INTER}" font-size="{_n(f[0] * s)}" '
            f'font-weight="{f[1]}" fill="{color}">{escape(txt)}</text>')


def texture_on() -> bool:
    """LP_PAINT=svg: textures in the SVG itself (proof, off by default): shapes marked `wash` get the watercolour filter defined in
    WhiteboardCanvas, chart shading marked `hatch` is drawn as Rough.js hatching. No canvas, no WebGL, no recipes."""
    return os.getenv("LP_PAINT") == "svg"


def _node_svg(n, b, s, fill, stroke) -> str:
    sw = "3.6" if n.get("tone") == "accent" else "2"
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    st = f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"'
    if texture_on() and n["shape"] in ("box", "diamond", "circle", "pill"):   # the palette's pale fill as it is: any darker and the grey
        st += ' class="wash"'                                                    # detail text drops under 4.5:1 (checked per colour)
    if n["shape"] == "diamond":
        shape = f'<polygon points="{_n(x + w / 2)},{_n(y)} {_n(x + w)},{_n(y + h / 2)} {_n(x + w / 2)},{_n(y + h)} {_n(x)},{_n(y + h / 2)}" {st}/>'
    elif n["shape"] == "circle":
        shape = f'<ellipse cx="{_n(x + w / 2)}" cy="{_n(y + h / 2)}" rx="{_n(w / 2)}" ry="{_n(h / 2)}" {st}/>'
    elif n["shape"] == "pill":
        r = min(h / 2, 26)
        shape = (f'<path d="M{_n(x + r)},{_n(y)} H{_n(x + w - r)} A{_n(r)},{_n(r)} 0 0 1 {_n(x + w)},{_n(y + r)} V{_n(y + h - r)} A{_n(r)},{_n(r)} 0 0 1 {_n(x + w - r)},{_n(y + h)} '
                 f'H{_n(x + r)} A{_n(r)},{_n(r)} 0 0 1 {_n(x)},{_n(y + h - r)} V{_n(y + r)} A{_n(r)},{_n(r)} 0 0 1 {_n(x + r)},{_n(y)} Z" {st}/>')
    elif n["shape"] == "cylinder":
        ry = 9 * s
        shape = (f'<path d="M{_n(x)},{_n(y + ry)} A{_n(w / 2)},{_n(ry)} 0 0 1 {_n(x + w)},{_n(y + ry)} V{_n(y + h - ry)} A{_n(w / 2)},{_n(ry)} 0 0 1 {_n(x)},{_n(y + h - ry)} Z '
                 f'M{_n(x)},{_n(y + ry)} A{_n(w / 2)},{_n(ry)} 0 0 0 {_n(x + w)},{_n(y + ry)}" {st}/>')
    elif n["shape"] == "card":   # white card with a coloured header band
        shape = (f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" fill="#FFFFFF" stroke="{stroke}" stroke-width="{sw}"/>'
                 f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n((n["head_h"] + 18) * s)}" {st}/>')
    else:
        shape = f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" {st}/>'
    parts = [shape]
    if n["shape"] == "card":
        cy = y + 9 * s
    else:
        cy = y + (h - n["th"] * s) / 2 + (9 * s if n["shape"] == "cylinder" else 0)
    for r in n["rows"]:
        if "icon" in r:   # a nested <svg> scales the 24x24 icon without a transform attribute (the board forbids those)
            k = 28 * s
            parts.append(f'<svg x="{_n(x + w / 2 - k / 2)}" y="{_n(cy)}" width="{_n(k)}" height="{_n(k)}" viewBox="0 0 24 24" fill="none" stroke="{stroke}" '
                         f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{ICONS[r["icon"]]}</svg>')
        elif "text" in r:
            left = r.get("body")
            parts.append(_text(x + 16 * s if left else x + w / 2, cy, r["text"], r["f"], s, stroke if r["color"] == "cat" else r["color"], "start" if left else "middle"))
        cy += _row_h(r) * s
    return f'<g id="{n["id"]}">{"".join(parts)}</g>'


def _edge_svg(e, route, chip, s) -> str:
    d = "M" + " L".join(f"{_n(p['x'])},{_n(p['y'])}" for p in route)
    dash = ' stroke-dasharray="8 6"' if e.get("dashed") else ""
    parts = [f'<path class="edge" d="{d}" fill="none" stroke="{LINE}" stroke-width="2" marker-end="url(#arrow-dark)"{dash}/>']
    if chip:
        lab = edge_label(e)
        parts.append(f'<rect x="{_n(chip["x"])}" y="{_n(chip["y"])}" width="{_n(chip["w"])}" height="{_n(chip["h"])}" fill="#FFFFFF" stroke="#E2DDD2" stroke-width="1"/>')
        parts += [_text(chip["x"] + chip["w"] / 2, chip["y"] + 4 * s + i * EDGE[2] * s, t, EDGE, s, INK2) for i, t in enumerate(lab["lines"])]
    return f'<g id="{e["id"]}">{"".join(parts)}</g>'


# ---------------------------------------------------------------------------------------------------------------------------------
# The board: where the next block goes
# ---------------------------------------------------------------------------------------------------------------------------------

CAM_RE = re.compile(r'class="cam cam-(\d+)-(\d+)-(\d+)-(\d+)"')
ID_RE = re.compile(r'\sid="([^"]+)"')


def board_blocks(current_svg) -> List[dict]:
    """The boxes of the blocks already on the page, in the order they were added (every step of a block repeats its box)."""
    boxes = dict.fromkeys(CAM_RE.findall(current_svg or ""))
    return [{"x": int(x), "y": int(y), "w": int(w), "h": int(h)} for x, y, w, h in boxes]


FIXED_Y: ContextVar = ContextVar("fixed_y", default=None)   # replace_block: the block is rebuilt where it already is (code still decides; the lane gives x)


def place_block(lane, h: float, blocks: List[dict]) -> Tuple[float, float]:
    """Top-left of a new block in `lane`: below what is already in that lane, and never above the latest block, so the board reads
    top to bottom in teaching order and a diagram sits beside the notes it follows. A wide block goes below everything."""
    x, w = lane
    if FIXED_Y.get() is not None:
        return x, FIXED_Y.get()
    if lane == WIDE_LANE:
        return x, max([TOP] + [b["y"] + b["h"] + GAP for b in blocks])
    in_lane = [b for b in blocks if b["x"] < x + w and x < b["x"] + b["w"]]
    return x, max([TOP] + [b["y"] + b["h"] + GAP for b in in_lane] + [blocks[-1]["y"]] if blocks else [TOP])


def _cam(x, y, w, h) -> str:
    return f'<desc class="cam cam-{int(x)}-{int(y)}-{math.ceil(w)}-{math.ceil(h)}"/>'


def prefix_ids(scene: dict, p: str) -> dict:
    """Every id of a block gets the block's prefix, so two diagrams on one board can both have a node called 'db'."""
    pre = lambda i: f"{p}{i}"
    return {**scene,
            "nodes": [{**n, "id": pre(n["id"]), **({"group": pre(n["group"])} if n.get("group") else {})} for n in scene["nodes"]],
            "edges": [{**e, "id": pre(e["id"]), "from": pre(e["from"]), "to": pre(e["to"])} for e in scene["edges"]],
            "groups": [{**g, "id": pre(g["id"])} for g in scene["groups"]],
            "when": {pre(k): v for k, v in scene["when"].items()}}


_STEP_RE = re.compile(r'<g id="b(\d+)_s(\d+)"')
_TEXT_RE = re.compile(r"<text[^>]*>([^<]*)</text>|<desc class=\"tex\">([^<]*)</desc>")   # a formula has no <text>: its TeX is in a desc
_STOP = set("the a an and or of to in on for is are be it its this that with by as at from you your can we our lets let using use uses "
             "will what how why when then into so".split())


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", html.unescape(s).lower()))


def _stems(s: str) -> set:
    return {w[:5] for w in _norm(s).split() if w not in _STOP and len(w) > 1}


def board_texts(current_svg) -> Dict[Tuple[int, int], str]:
    """The written text of every step on the board, by (block, step)."""
    svg, out = current_svg or "", {}
    marks = list(_STEP_RE.finditer(svg))
    for i, m in enumerate(marks):
        chunk = svg[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(svg)]
        out[(int(m.group(1)), int(m.group(2)))] = " ".join(a or b for a, b in _TEXT_RE.findall(chunk))
    return out


def repeats(tool: str, args: dict, current_svg) -> str:
    """Why a new block repeats the board ("" when it does not). The prompt asks for no repeats, and live lessons still drew one
    diagram three times under three titles and wrote the same note twice (Selenium, 2026-11-05). Recaps repeat by design."""
    steps = board_texts(current_svg)
    if not steps:
        return ""
    if args.get("style") == "recap":   # a recap restates the notes by design, but not an earlier recap (live: two near-identical cards at the end)
        recaps = {int(b) for b in re.findall(r'<g id="b(\d+)_s\d+">(?:(?!<g id=).)*?class="recap-card"', current_svg, re.S)}
        steps = {k: t for k, t in steps.items() if k[0] in recaps}
        if not steps:
            return ""
    if args.get("style") == "code":   # live: asked "yes", the tutor drew the same script again; a new script reusing its imports is fine
        board = " " + _norm(" ".join(steps.values())) + " "
        chunks = [c for c in (_norm(_txt(l.get("text"))) for l in _lst(args.get("lines")) if isinstance(l, dict)) if len(c) >= 8]
        same = [c for c in chunks if f" {c} " in board]
        if not (chunks and len(same) >= 0.6 * len(chunks)):
            return ""
        at = next((b for (b, _), t in steps.items() if f" {same[0]} " in " " + _norm(t) + " "), None)
        fix = f'replace_block with block "b{at}"' if at else "replace_block with its id"
        return (f"This code is already on the board{f' (block {at})' if at else ''}. Point at it with annotate_element and explain, or show only the new lines. "
                f"To correct or extend it, use {fix}.")
    if tool == "draw_scene":
        labels = [_norm(_txt(n.get("label"))) for n in _lst(args.get("nodes")) if isinstance(n, dict)]
        labels = [l for l in labels if len(l) >= 4]
        diagrams = {int(b) for b in re.findall(r'<g id="b(\d+)_(?!s\d+")', current_svg)}   # node and group ids; notes have step ids only
        for b in sorted(diagrams & {b for b, _ in steps}):   # notes that listed these parts first do not block the diagram (it shows them better)
            text =" " + _norm(" ".join(t for (bb, _), t in steps.items() if bb == b)) + " "
            same = [l for l in labels if f" {l} " in text]
            if len(same) >= 3 and len(same) >= 0.6 * len(labels):
                return (f"This diagram repeats block {b}, already on the board ({len(same)} of its {len(labels)} parts: {', '.join(same[:4])}). "
                        f'To correct it or add to it, call replace_block with block "b{b}", tool "draw_scene" and the complete new content; to point at it, use annotate_element.')
        return ""
    old = [(f"b{b}_s{k}", _stems(t)) for (b, k), t in steps.items()]
    dup = [(plain(_txt(l.get("text"))), hit) for l in _lst(args.get("lines")) if isinstance(l, dict)
           if (s := _stems(plain(_txt(l.get("text"))))) and len(s) >= 2
           and (hit := next((sid for sid, o in old if len(s & o) >= (len(s) * 2 / 3 if len(s) >= 3 else len(s))), None))]   # two thirds of it is already there (a two-word line: all of it); live: 2 of 3 slipped past 70%
    # where it is: the tutor sees only the newest blocks' words, and the board may hold older ones (architecture review, 2026-11-16)
    return (f"These lines repeat what is already on the board: {'; '.join(f'{t} (already in {sid})' for t, sid in dup[:4])}. Leave them out "
            "and write only what is new (point at the old line with annotate_element and that id if you need it). "
            "To correct or extend that block, use replace_block with its id." if dup else "")


def page_view(current_svg) -> dict:
    """What the tutor is told about the board (instead of its SVG, which grows long): how many blocks, what they say, and the ids it can
    point at. Without the words it rewrote points it could not see: 62 of 74 refused blocks in the first lesson check were repeats."""
    said: Dict[int, str] = {}
    for (b, _), t in board_texts(current_svg).items():
        said[b] = f"{said.get(b, '')} {html.unescape(t)}".strip()
    return {"blocks_on_board": len(board_blocks(current_svg)),
            "already_written": {f"b{b}": t[:160] + ("..." if len(t) > 160 else "") for b, t in list(said.items())[-12:]},   # ponytail: last 12 blocks
            "annotatable_ids": list(dict.fromkeys(ID_RE.findall(current_svg or "")))[-120:]}   # the newest: the lesson is about them


def _hand_text(x, y, words, size, color=INK, on_board=True) -> str:
    """One run of words in the handwriting font, baseline at y. Written straight on the board (not on a card), it is class "ink",
    so a dark board theme can recolour it (frontend/src/index.css)."""
    bold = words[0][1]
    cls = ' class="ink"' if on_board else ""
    return (f'<text{cls} x="{_n(x)}" y="{_n(y)}" font-family="{HAND}" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">'
            f'{escape(" ".join(w[0] for w in words))}</text>')


def _rich_line(x, base, words, size, on_board=True) -> str:
    """A wrapped line of (word, bold, highlight): a highlighter band behind each highlighted run, then the text in runs of one weight."""
    space = measure_hand(" ", size, False)
    xs, cx = [], x
    for w in words:
        xs.append(cx)
        cx += measure_hand(w[0], size, w[1]) + space
    parts, i = [], 0
    while i < len(words):   # highlighter bands first, so the text sits on top
        if words[i][2]:
            j = i
            while j + 1 < len(words) and words[j + 1][2]:
                j += 1
            end = xs[j] + measure_hand(words[j][0], size, words[j][1])
            parts.append(f'<rect x="{_n(xs[i] - 4)}" y="{_n(base - size * 0.78)}" width="{_n(end - xs[i] + 8)}" height="{_n(size * 0.98)}" fill="{HIGHLIGHT}" stroke="none"{' class="hl"' if on_board else ""}/>')
            i = j + 1
        else:
            i += 1
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words) and words[j + 1][1] == words[i][1]:
            j += 1
        parts.append(_hand_text(xs[i], base, words[i:j + 1], size, on_board=on_board))
        i = j + 1
    return "".join(parts)


def _export_subset(path: Path) -> bytes:
    """Caveat for exports only (the screen uses the app's full font): Latin, Latin-1 and common punctuation and arrows, kerning kept,
    contextual alternates dropped. Same advance widths, so measured runs and highlighter bands still line up; half the bytes."""
    from fontTools import subset
    f = TTFont(str(path))
    opts = subset.Options()
    opts.flavor, opts.layout_features = "woff2", ["kern"]
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + [0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026, 0x2190, 0x2192])
    sub.subset(f)
    out = io.BytesIO()
    f.save(out)
    return out.getvalue()


@lru_cache(maxsize=1)
def board_font_css() -> str:
    """@font-face for Inter and Caveat, put once in a board's first step so an exported SVG/PNG keeps its fonts. Faces only: the trusted
    font CSS of the raw-SVG path also sets `text { font-family: Inter }`, which beat the handwriting named on the notes (seen live)."""
    # Own family names, named after the app's fonts in font-family: an inline SVG <style> is document-wide, and faces called "Inter"
    # (a subset, no unicode-range) would replace the app's Inter everywhere while a board is open (code review)
    face = lambda fam, w, b64: f"@font-face {{ font-family: '{fam}'; font-weight: {w}; src: url(data:font/woff2;base64,{b64}) format('woff2'); }}"
    if not all((CAVEAT / f"caveat-latin-{w}-normal.woff2").exists() for w in (400, 700)):
        raise SceneError("The handwriting font is not installed on the server (needs `npm install` in engine/scene_layout).")
    caveat = lambda w: base64.b64encode(_export_subset(CAVEAT / f"caveat-latin-{w}-normal.woff2")).decode()
    return " ".join([face("Inter Board", 400, INTER_REGULAR_WOFF2_B64), face("Inter Board", 700, INTER_BOLD_WOFF2_B64),
                     face("Caveat Board", 400, caveat(400)), face("Caveat Board", 700, caveat(700))])


_TEX_SYMBOLS = {r"\cdot": "·", r"\times": "×", r"\pm": "±", r"\sqrt": "√", r"\leq": "≤", r"\geq": "≥", r"\neq": "≠",
                r"\approx": "≈", r"\pi": "π", r"\lambda": "λ", r"\to": "→", r"\infty": "∞", r"\Delta": "Δ", r"\theta": "θ",
                r"\alpha": "α", r"\beta": "β", r"\mu": "μ", r"\sigma": "σ", r"\propto": "∝", r"\le": "≤", r"\ge": "≥"}


def demath(text: str) -> str:
    """Inline $...$ maths in a handwritten line, a label, speech or the chat reply, as readable text: only a whole $...$ line is typeset,
    and live the tutor also wrote "$x-2=0$" inside lines and replies (shown with its dollar signs, and spoken as 'dollar')."""
    def one(m):
        t = m.group(1)
        t = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", t)
        for k in sorted(_TEX_SYMBOLS, key=len, reverse=True):
            t = t.replace(k, _TEX_SYMBOLS[k])
        t = re.sub(r"\^\{?(-?\d+)\}?", lambda p: p.group(1).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")), t)   # x^2 → x², λ^4 → λ⁴
        return re.sub(r"\\(?:left|right|,|;|!|\s)|[{}\\]", "", t)
    # a closing $ followed by a digit is money ("$5 and $10"), and maths has no space just inside its $ signs
    return re.sub(r"\$\$?(?=\S)([^$\n]*?\S)\$\$?(?!\d)", one, str(text))


def plain(text: str) -> str:
    """A note line without its markers, for the voice."""
    return demath(re.sub(r"\*\*([^*]+)\*\*|==([^=]+)==", lambda m: m.group(1) or m.group(2), str(text))).strip()


MONO, CODE_SIZE, CODE_LH, CODE_PAD = "Consolas, 'Cascadia Mono', Menlo, 'DejaVu Sans Mono', monospace", 15, 22, 18
CODE_CHAR = 0.6 * CODE_SIZE     # the advance of one character in these fonts is 0.55-0.6 em: measured at the wide end, a line never overflows
CODE_BG, CODE_INK, CODE_DIM = "#1F2A37", "#E7EAEE", "#94A3B8"


def build_code(args: dict, n: int, blocks: List[dict]) -> Tuple[List[Tuple[str, str, str]], dict, dict]:
    """A code card: the learner asked for code (Selenium lesson: 'give me codes' got a diagram, the board had no way to show code).
    Each line item is a chunk of code (it may hold several lines), revealed while the tutor explains it; the code is never read aloud.
    Spaces are kept (non-breaking), long lines wrap with an indent, and a card too wide for the notes lane goes full width."""
    chunks = []
    for l in _lst(args.get("lines")):
        if not isinstance(l, dict):
            continue
        code = _txt(l.get("text")).replace("\r", "").replace("\t", "    ").rstrip()
        code, say = _cut(code, MAX_SAY, "code"), _cut(plain(_txt(l.get("say"))), MAX_SAY, "narration")
        if code.strip():
            if not say:
                raise SceneError("Each code step needs `say`: explain what that code does (the code itself is not read aloud).")
            chunks.append(([r.rstrip() for r in code.strip("\n").split("\n")], say))   # trailing spaces sent a short script to the wide lane
    if not chunks:
        raise SceneError("write_notes with style code needs at least one line of code.")
    if len(chunks) > MAX_LINES:
        raise SceneError(f"A code block holds at most {MAX_LINES} steps; split it into two blocks.")
    title = _cut(_txt(args.get("title")).strip(), MAX_TEXT, "title")
    longest = max(len(r) for c, _ in chunks for r in c)
    lane = NOTE_LANE if longest * CODE_CHAR + 2 * CODE_PAD <= NOTE_LANE[1] else WIDE_LANE
    per_row = int((lane[1] - 2 * CODE_PAD) / CODE_CHAR)
    laid, y = [], CODE_PAD + (CODE_LH + 8 if title else 0)
    for code, say in chunks:
        rows = []
        for r in code:   # a wrapped line continues under itself, four spaces in
            rows.append(r[:per_row])
            rows += ["    " + r[i:i + per_row - 4] for i in range(per_row, len(r), per_row - 4)]
        laid.append((y, rows, say))
        y += len(rows) * CODE_LH + 6
    h = y + CODE_PAD - 6
    if h > MAX_BLOCK_H * 1.5:
        raise SceneError("This code is too long for one block; show the important part, or split it into two code blocks.")
    x0, y0 = place_block(lane, h, blocks)
    cam, out = _cam(x0, y0, lane[1], h), []
    mono = lambda x, yy, t, c, w=400: (f'<text x="{_n(x)}" y="{_n(yy)}" font-family="{MONO}" font-size="{CODE_SIZE}" font-weight="{w}" fill="{c}">'
                                       f'{escape(t.replace(" ", chr(0xA0)))}</text>')
    for k, (ly, rows, say) in enumerate(laid):
        sid = f"b{n}_s{k + 1}"
        head = ""
        if k == 0:
            head = f'<rect x="{_n(x0)}" y="{_n(y0)}" width="{lane[1]}" height="{_n(h)}" rx="8" fill="{CODE_BG}" stroke="none"/>'
            if title:
                head += mono(x0 + CODE_PAD, y0 + CODE_PAD + CODE_SIZE * 0.85, title, CODE_DIM, 700)
        body = "".join(mono(x0 + CODE_PAD, y0 + ly + CODE_SIZE * 0.85 + i * CODE_LH, r, CODE_INK) for i, r in enumerate(rows))
        out.append((sid, f'<g id="{sid}">{cam}{head}{body}</g>', f"[[MARK:{sid}]] {say}"))
    return out, {"x": x0, "y": y0, "w": lane[1], "h": h}, {"kind": "code", "lines": sum(len(r) for _, r, _ in laid)}


def build_notes(args: dict, n: int, blocks: List[dict]) -> Tuple[List[Tuple[str, str, str]], dict, dict]:
    """A notes block (handwritten lines with a bullet, or numbered) or a recap card (lines with a check), one step per line."""
    if args.get("style") == "code":
        return build_code(args, n, blocks)
    lines = [{"text": _txt(l.get("text")), "say": _txt(l.get("say"))} for l in _lst(args.get("lines")) if isinstance(l, dict)]
    lines = [l for l in lines if rich_words(l["text"])]
    if not lines:
        raise SceneError("write_notes needs at least one line with text.")
    if len(lines) > MAX_LINES:
        raise SceneError(f"A notes block holds at most {MAX_LINES} lines; split it into two blocks.")
    recap = args.get("style") == "recap"
    title = _cut(demath(_txt(args.get("title")) or ("Recap" if recap else "")).strip(), MAX_TEXT, "title")
    size, lh = HAND_LINE[0], HAND_LINE[2]
    _, lane_w = NOTE_LANE
    pad, indent = (22 if recap else 0), 34
    y = pad + (HAND_TITLE[2] + 6 if title else 0)
    laid = []
    # A line written as $...$ is a formula, typeset by MathJax (written as text it read as "1/lambda^4"): checked before anything is laid out
    texs = [m.group(1)[:MAX_TEXT] for l in lines if (m := MATH_RE.match(l["text"]))]
    typeset = iter(render_math(texs) if texs else [])
    for l in lines:
        if MATH_RE.match(l["text"]):
            r, tex = next(typeset), MATH_RE.match(l["text"]).group(1)
            if "error" in r:
                raise SceneError(f"This formula cannot be typeset ({r['error']}): {tex[:80]}. Fix the TeX, or write it in words.")
            if not plain(l["say"]):
                raise SceneError(f"A formula line needs `say`: what you say about {tex[:60]} (the TeX is not read aloud).")
            fh = min(r["h"] * EX_PX, r["h"] * EX_PX * (lane_w - 2 * pad - indent) / (r["w"] * EX_PX))
            laid.append((y, None, indent, {**r, "tex": tex}, _cut(plain(l["say"]), MAX_SAY, "narration")))
            y += fh + 14
            continue
        words = rich_words(_cut(demath(l["text"]), MAX_TEXT, "line"))
        # "1." is the line's marker, and wrapped lines hang after it (they started under the number: live order lesson)
        num = words.pop(0) if not recap and re.match(r"^\d+[.)]$", words[0][0]) else None
        lead = measure_hand(num[0] + " ", size, num[1]) if num else indent
        rows = wrap_rich(words, size, lane_w - 2 * pad - lead) or [[]]
        laid.append((y, num, lead, rows, _cut(plain(l.get("say") or "") or plain(l["text"]), MAX_SAY, "narration")))
        y += len(rows) * lh + 10
    h = y + pad - 10
    x0, y0 = place_block(NOTE_LANE, h, blocks)
    cam = _cam(x0, y0, lane_w, h)
    out = []
    for k, (ly, num, lead, rows, say) in enumerate(laid):
        sid = f"b{n}_s{k + 1}"
        head = ""
        if k == 0:
            if recap:
                head += f'<rect x="{_n(x0)}" y="{_n(y0)}" width="{lane_w}" height="{_n(h)}" fill="#FFFFFF" stroke="#0F766E" stroke-width="2" class="recap-card"/>'
            if title:
                head += _hand_text(x0 + pad, y0 + pad + HAND_TITLE[0] * 0.85, [(title, True, False)], HAND_TITLE[0], "#0F766E" if recap else INK, on_board=not recap)
        tx = x0 + pad + lead
        base = y0 + ly + size * 0.85
        if isinstance(rows, dict):   # a formula: no bullet, typeset in the line's place
            body = math_svg(rows, tx, y0 + ly + 4, lane_w - 2 * pad - lead, "#0F766E" if recap else INK)[0]
            body += f'<desc class="tex">{html.escape(rows["tex"])}</desc>'   # drawn as shapes, so the board's text (page_view, repeats) reads this
            out.append((sid, f'<g id="{sid}">{cam}{head}{body}</g>', f"[[MARK:{sid}]] {say}"))
            continue
        if recap:
            mark = (f'<svg x="{_n(x0 + pad)}" y="{_n(base - size * 0.72)}" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0F766E" '
                    f'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">{ICONS["circle-check"]}</svg>')
        else:
            mark = _hand_text(x0 + pad, base, [num], size) if num else _hand_text(x0 + pad + 8, base, [("•", True, False)], size)
        body = "".join(_rich_line(tx, base + i * lh, row, size, on_board=not recap) for i, row in enumerate(rows))
        out.append((sid, f'<g id="{sid}">{cam}{head}{mark}{body}</g>', f"[[MARK:{sid}]] {say}"))
    return out, {"x": x0, "y": y0, "w": lane_w, "h": h}, {"kind": "recap" if recap else "notes", "lines": len(laid)}


def icon_note(report: dict) -> str:
    words = ", ".join(f'"{w}"' for w in report.get("icon_misses", [])[:3])
    return f" No icon matched: {words} (the label is shown without it)." if words else ""


def cut_note(report: dict) -> str:
    cut = report.get("cut", [])[:3]
    return f" Note: some text was cut to fit: {'; '.join(cut)}. Shorter text will show in full." if cut else ""


# A "screen" is the camera's default view, H board units tall; a page longer than this many screens reads better as two pages.
LONG_PAGE_H = 3 * H


def long_page_note(blocks: List[dict], box: dict) -> str:
    """Said once per page: only when the new block's bottom crosses LONG_PAGE_H (`blocks`: the board before it)."""
    before = max([b["y"] + b["h"] for b in blocks] or [0])
    bottom = box["y"] + box["h"]
    if before < LONG_PAGE_H <= bottom:
        return f" Note: this page is getting long (about {bottom / H:.1f} screens); if the next idea is a new topic or step, start_new_page would read better."
    return ""


def layout_note(report: dict) -> str:
    """One factual sentence when a drawn diagram came out worse than intended (labels shrunk small, or things overlapping); else ''.
    Only said to the tutor, never a refusal."""
    if report.get("kind") != "diagram":
        return ""
    bad = [i for i in report.get("issues", []) if i[0] in ("node_overlap", "label_on_node", "line_through_node", "off_canvas")]
    if report.get("long_labels"):
        return " Note: some node labels in this diagram were long and wrapped over many lines; shorter labels (3-4 words, details in the detail field) would read better next time."
    if report.get("label_px_framed", 99) < 11:   # ponytail: 11 of 18 px; tune from lesson-eval reports
        return " Note: this diagram had to be shrunk to fit, so its labels read small; fewer nodes or shorter labels (3-4 words) would read better next time."
    if bad:
        return " Note: some items in this diagram overlap or sit on each other; fewer nodes or shorter labels would lay out cleaner next time."
    return ""


def build_diagram(scene: dict, n: int, blocks: List[dict]) -> Tuple[List[Tuple[str, str, str]], dict, dict]:
    """A diagram block (ids already prefixed), one step per teaching step: in the diagram lane, or full width when that reads clearly
    bigger. Natural size at most; the camera zooms in on it, so a small scale here is not small on screen."""
    nodes, cands = arrange(scene)
    title_h = HAND_TITLE[2] + 14 if scene["title"] else 0

    def on_screen(lay, lane):   # label scale once the camera frames the block (frame(): lane + margin, board's shape, at most 2x)
        s = min(1.0, lane[1] / lay["w"], MAX_BLOCK_H / lay["h"])
        view_w = max(lane[1] + 80, (title_h + lay["h"] * s + 80) * W / H, W / 2)
        return s * W / view_w, s
    # the layout and lane that show the labels biggest; an earlier (preferred) choice keeps its place unless clearly beaten
    best = None
    for lay in cands:
        for lane in (DIAGRAM_LANE, WIDE_LANE):
            eff, s = on_screen(lay, lane)
            if best is None or eff > best[0] * 1.08:
                best = (eff, s, lay, lane)
    eff, s, lay, lane = best
    h = title_h + lay["h"] * s
    x0, y0 = place_block(lane, h, blocks)
    board = place(scene, nodes, lay, x0 + (lane[1] - lay["w"] * s) / 2, y0 + title_h, s)
    box = {"x": x0, "y": y0, "w": lane[1], "h": h}
    cam, when, sid_prefix = _cam(**box), scene["when"], f"b{n}_s"   # before the loops below reuse `n` for nodes
    cat: Dict[str, int] = {}
    for n in nodes:
        cat.setdefault(n.get("category") or "", len(cat))
    colour = lambda n: MUTED if n.get("tone") == "muted" else PALETTE[cat[n.get("category") or ""] % len(PALETTE)]

    layers = [{"groups": [], "edges": [], "nodes": []} for _ in scene["steps"]]
    for g in scene["groups"]:
        b = board["gbox"].get(g["id"])
        if b:
            layers[when[g["id"]]]["groups"].append(
                f'<g id="{g["id"]}">'
                f'<rect x="{_n(b["x"])}" y="{_n(b["y"])}" width="{_n(b["w"])}" height="{_n(b["h"])}" fill="#F7F4EC"{' class="wash"' if texture_on() else ""} stroke="#CFC8B8" '
                f'stroke-width="1.5" stroke-dasharray="7 6"/>{_text(b["x"] + 14, b["y"] + 10 * min(1, s), g["label"], (15, 700, 19), s, INK2, "start")}</g>')
    for e in scene["edges"]:
        if e["id"] in board["routes"]:
            layers[when[e["id"]]]["edges"].append(_edge_svg(e, board["routes"][e["id"]], board["chips"].get(e["id"]), s))
    for n in nodes:
        layers[when[n["id"]]]["nodes"].append(_node_svg(n, board["pos"][n["id"]], s, *colour(n)))

    out = []
    for k, (st, lay) in enumerate(zip(scene["steps"], layers)):
        sid = f"{sid_prefix}{k + 1}"
        head = ""
        if k == 0 and scene["title"]:
            head = _hand_text(x0, y0 + title_h - 14, [(scene["title"], True, False)], HAND_TITLE[0])
        body = "".join(lay["groups"] + lay["edges"] + lay["nodes"])
        out.append((sid, f'<g id="{sid}">{cam}{head}{body}</g>', f"[[MARK:{sid}]] {demath(st['say'])}"))
    return out, box, {"kind": "diagram", "lane": "wide" if lane == WIDE_LANE else "diagram", "scale": round(s, 3), "label_px": round(LABEL[0] * s, 1),
                      "label_px_framed": round(LABEL[0] * eff, 1), "nodes": len(nodes), "edges": len(scene["edges"]), "steps": len(out),
                      "icons": sum("icon" in n for n in nodes), "icon_misses": scene.get("icon_misses", []),
                      "long_labels": sum(sum(r.get("f") == LABEL for r in n["rows"]) > 3 for n in nodes),
                      "issues": geometry_issues(scene, board)}
