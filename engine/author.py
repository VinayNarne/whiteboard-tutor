"""
engine/author.py
WhiteboardAuthor — the core AI agent for Learning Platform Phase 1.

Receives a learner chat message and orchestrates:
  1. Reading current page state (fresh, never cached)
  2. Running the LLM tool-use loop (the Azure deployment in AZURE_OPENAI_AUTHOR_DEPLOYMENT)
  3. For each draw_new_element call:
       sanitize → validate geometry → density check → TTS audio → persist PageEvent → emit WS
  4. For each modify_existing_element call:
       validate element exists → sanitize → persist PageEvent (kind=modify) → emit WS

SYSTEM PROMPT RULES (physical/rendering constraints only — SAD §0):
  - Absolute x/y coordinates. No transform attributes.
  - Every element must have a unique, permanent id.
  - No <script>, <foreignObject>, event handlers, external src/href.
  - Do not guess positions of things already on the page — call get_current_page_state() first.

ARCHITECTURAL INVARIANT:
  The system prompt contains rendering constraints, never stylistic preferences.
  Do not add example SVG fragments to the prompt — the model will copy them forever.
"""

import os
import re
import json
import asyncio
import threading
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
from dotenv import load_dotenv
from openai import AzureOpenAI

from core.log import get_logger
from core.events import EngineEvent, SessionEvent
from engine.sanitiser import sanitize_svg
from engine.fonts import inject_trusted_font, strip_embedded_fonts
from engine.grouping import ensure_group
from engine.lossless import compare as compare_with_stored, lost_content_note
from engine.markers import normalise_marker, strip_markers
from engine.blocks import BAR_TOOL, TABLE_TOOL, VENN_TOOL, build_bar_chart, build_table, build_venn
from engine.graph import CALC_TOOL, GRAPH_TOOL, build_graph, calculate
from engine.lesson_plan import COURSE_GUIDE, PLAN_GUIDE, STEP_TOOL, may_start_next_lesson, path_titles
from engine.scene import (ID_RE, MAX_BLOCKS_PER_TURN, NOTES_TOOL, SCENE_SYSTEM_PROMPT, SCENE_TOOL, SceneError, board_blocks, board_font_css, build_diagram, build_notes,
                          normalise as normalise_scene, page_view, prefix_ids, repeats, demath)
from engine.shadow import record as shadow_record
from engine.validator import (check_density, check_overlap, find_free_region, find_layout_issues, find_text_width_issues, find_transform, has_text_less_card,
                              validate_geometry, HARD_ELEMENT_COUNT, CANVAS_WIDTH, CANVAS_HEIGHT,
                              FRAME_PERCENT, is_background_frame)
from engine.voice import generate_narration_audio

load_dotenv()

logger = get_logger("engine")

AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
# The model that writes the board. Its own setting so a stronger model can be tried without moving the eval judge,
# which keeps using AZURE_OPENAI_DEPLOYMENT. Unset (or empty) = the same deployment as before.
AUTHOR_DEPLOYMENT        = os.getenv("AZURE_OPENAI_AUTHOR_DEPLOYMENT") or AZURE_OPENAI_DEPLOYMENT
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

# Output directory for audio/alignment files
OUTPUT_DIR = Path(__file__).parent.parent / "generated_notebooks"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Max chat turns supplied to agent per SAD §3.6
CHAT_HISTORY_TURNS = 15

# Stable, deterministic seed generator for Rough.js replay reproducibility
def generate_annotation_seed(annotation_id: str) -> int:
    """Stable, process-independent deterministic integer seed for Rough.js (SHA-256)."""
    digest = hashlib.sha256(annotation_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="big") % 100000 + 1

VALID_ANNOTATION_STYLES = {"circle", "underline", "tick", "cross", "highlight", "arrow"}
VALID_LIFETIMES = {"ephemeral", "permanent"}

DEFAULT_STYLE_COLORS = {
    "circle": "#f59e0b",     # Amber
    "underline": "#3b82f6",  # Blue
    "tick": "#10b981",       # Emerald green
    "cross": "#ef4444",      # Rose red
    "highlight": "#fbbf24",  # Warm yellow
    "arrow": "#8b5cf6",      # Violet
}


# How long the learner can wait on a dead model call. Measured on 2,146 logged calls (docs/BASELINE.md, step 3 of the L round): a healthy call that produced
# usable output took at most 34 s (median 3.4 s, p99 24 s); the four that ran to the 6,000-token cap (cut-off, unusable output) took 57-81 s; two stalls took
# 57 s and 121 s. 60 s is 1.8x the slowest healthy call and below every stall; one retry, because the stalls were transient. One failing call therefore ends in
# about two minutes at most (the SDK defaults were a 600 s read timeout and 2 retries, which the code did not limit).
MODEL_TIMEOUT_S = 60.0
MODEL_CONNECT_TIMEOUT_S = 5.0
MODEL_MAX_RETRIES = 1
# The httpx timeout above limits the SILENCE between bytes, not the whole call: a response that trickles in with gaps under 60 s could take much longer (measured in
# tests/measure_timeout_semantics.py). This is a wall-clock ceiling for one model call, the SDK's own retry included: 2.6x the slowest healthy call (34 s), above the
# slowest call that ran to the token cap (81 s). The worker thread cannot be killed; it is abandoned and its late answer ignored.
MODEL_CEILING_S = 90.0

# What the learner sees when the tutor model could not be reached.
MODEL_UNREACHABLE_MESSAGE = "I couldn't reach the tutor model just now. Please try asking again in a moment."
# A fresh install without a model key failed with "Something went wrong" and no hint (fresh-clone test, 2026-11-20).
MODEL_NOT_CONFIGURED_MESSAGE = ("The tutor model is not set up yet: add AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT to the .env file "
                                "(see .env.example), then restart the backend.")


def model_configured() -> bool:
    return bool(AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT)


class ModelUnreachable(Exception):
    """The model call failed after its retry: the turn has no answer. The chat endpoint turns this into a typed 503 and a failed turn."""


# What the learner sees when the model's final text is empty and nothing was drawn or annotated this turn.
EMPTY_REPLY_MESSAGE = "The tutor didn't send an answer this time. Please try again."

# A successful call of one of these changed the board: an empty final text after it is not an error (the board is the answer).
BOARD_TOOLS = {"draw_new_element", "modify_existing_element", "annotate_element", "remove_annotation", "draw_scene", "write_notes",
               "draw_graph", "draw_table", "draw_bar_chart", "draw_venn"}   # draw_graph was missing: a graph-only turn read as an empty reply


# "yes", "yeah", "right", "sure" are left out: they answer a yes/no question, and a skip is never graded (architecture review, 2026-11-16)
SKIP_RE = re.compile(r"^\W*(ok(ay)?|k|continue|go on|next|got it|cool|alright|fine|makes sense|i see)\W*$", re.I)


def is_skip(message: str) -> bool:
    """The learner moved on without answering ("ok", "continue"); spatial context lines from pointing are ignored."""
    text = (message or "").split("Learner Question:", 1)[-1]
    return bool(SKIP_RE.match(text.strip()))


# A short praise sentence at the start of a reply ("Great thinking!", "Nice try."). After a skip or a wrong answer it tells the learner they did
# well when they did not (lesson check on gpt-4.1-mini: 7 of 80 replies). A sentence that also corrects ("Nice try, but ...") is kept.
PRAISE_OPENER = re.compile(r"^\W*(?:great|good|nice|excellent|awesome|wonderful|fantastic|amazing|well done|exactly|correct|right|perfect|spot on|"
                           r"that's right|that is right|yes|absolutely|love)\b[^.!?\n]*[.!?]+\s*", re.I)
PRAISE_WORD = re.compile(r"^\W*(?:great|good|nice|excellent|exactly|correct|right|perfect|yes|absolutely)\s*[—–,:!-]+\s*", re.I)
CORRECTING = re.compile(r"\b(but|however|though|although|not|isn'?t|actually|close)\b", re.I)


def drop_praise(text: str) -> str:
    """The reply without its opening praise sentences (at most two short ones); unchanged when nothing would be left."""
    out = text
    for _ in range(2):
        m = PRAISE_OPENER.match(out)
        if (not m or len(m.group(0).split()) > 8 or CORRECTING.search(m.group(0).replace("’", "'"))
                or not out[m.end():].strip()):     # the whole reply: try the praise word alone below
            break
        out = out[m.end():]
    word = PRAISE_WORD.match(out)          # "Right, sellers do not pick the price." -> "Sellers do not pick the price." (the word alone: nothing else is lost)
    if word:
        out = out[word.end():]
    out = out.strip()
    return (out[0].upper() + out[1:]) if out else text


def last_question(history) -> str:
    """The last question the tutor asked in its latest reply, or "" (scene mode reminds the tutor of it so it moves on)."""
    reply = next((m.get("content") or "" for m in reversed(history or []) if m.get("role") == "assistant"), "")
    asked = re.findall(r"[^.!?\n]*\?", re.sub(r"\S+://\S+", "", reply))   # a link's "?" is not a question
    return asked[-1].strip()[:300] if asked else ""


def scene_mode_on() -> bool:
    """Scene mode, the default since 2026-11-20: the tutor says what to show (write_notes, draw_scene, ...) and code lays it out
    (engine/scene.py). LP_SCENE_MODE=0 switches back to the older raw-SVG tutor. Read per turn."""
    return os.getenv("LP_SCENE_MODE", "1").strip() != "0"


class EmptyReply(Exception):
    """The model's final text was empty or whitespace and no draw, modify or annotation succeeded in the turn: there is no answer at all. Typed 503 like ModelUnreachable."""


def get_azure_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version=AZURE_OPENAI_API_VERSION,
        timeout=httpx.Timeout(MODEL_TIMEOUT_S, connect=MODEL_CONNECT_TIMEOUT_S),
        max_retries=MODEL_MAX_RETRIES,
    )


# ---------------------------------------------------------------------------
# System prompt (physical constraints only)
# ---------------------------------------------------------------------------

WHITEBOARD_SYSTEM_PROMPT = """You are a one-on-one tutor teaching any topic on a live digital whiteboard. You explain by speaking and drawing together.
Each element you draw comes with narration that is spoken aloud as the element appears.

=============================================================================
HARNESS RULE 0: THE CANVAS
=============================================================================
- The canvas is 1200 x 800 pixels (viewBox="0 0 1200 800"). All coordinates must fit inside it.
- The canvas background is already set by the frontend. Do not draw a background or frame: a single shape covering {FRAME_PERCENT}% or more of the canvas is treated as a frame and rejected.
- Use absolute x/y coordinates only. Never use `transform` attributes (rotation included): layout measurement reads plain coordinates.

=============================================================================
HARNESS RULE 1: ELEMENTS
=============================================================================
- Every element you draw is one `<g id="element_id">` group. The id must be unique on the page: annotations, edits and undo refer to it.
- You choose the form, colours, layout and visual style that fit the concept.
- Whatever the learner needs to identify should be identifiable on the board.
- Available arrowhead markers: `marker-end="url(#arrow)"` (blue), `marker-end="url(#arrow-dark)"` (slate), `marker-end="url(#arrow-green)"` (emerald).

=============================================================================
HARNESS RULE 2: WHEN TO DRAW
=============================================================================
- Drawing is your default way to explain. When you introduce, explain or compare an idea, draw it as you speak.
- A follow-up does not always need a new drawing: when words alone answer it better, answer in text.
- When the learner signals to continue, move the lesson forward.
- The state of the current page (including "occupied_regions" and "available_space") is provided with every request. `get_current_page_state` returns the latest state after your own drawings.

=============================================================================
HARNESS RULE 3: SPACE
=============================================================================
- Never place a new element over an existing one, and leave at least 30px around elements. Use "occupied_regions" and "available_space" to find open space.
- Keep connectors from running through labels.
- TEXT FIT (rendering fact): a label is about 0.5 x font-size px wide per character (a 14px, 20-character label is ~140px). Keep every label inside its shape, and put stacked lines at least 1.3 x font-size apart so no two labels ever overlap. A title or caption needs its own free band; never place it over another label's text area.

=============================================================================
HARNESS RULE 4: MARK SYNCHRONIZATION
=============================================================================
The [[MARK:element_id]] token controls WHEN the visual appears on screen relative to your narration.
- [[MARK:element_id]] MUST appear in the VERY FIRST SENTENCE of the `narration` parameter, using the element's own id. The visual appears on the board exactly when you speak those words.
- A marker placed later makes the visual wait until that point in the speech.
- [[MARK:...]] belongs ONLY in the `narration` argument of `draw_new_element` or `annotate_element`. NEVER put [[MARK:...]] in your final chat reply to the learner.
- Narration must be plain text only: no markdown, no bullet points.

=============================================================================
HARNESS RULE 5: ANNOTATIONS
=============================================================================
You can mark up existing elements with `annotate_element`, like a marker on a whiteboard:
- `style="circle"`: a hand-drawn ring around an element.
- `style="underline"`: a wavy brush underline beneath an element's card or text.
- `style="tick"`: a green checkmark over an element.
- `style="cross"`: a red crossmark over an element.
- `style="highlight"`: a broad translucent marker band behind an element, without covering its text.
- `style="arrow"`: a curved pointer arrow from `from_element_id` to `target_element_id`.
- `note`: optional brief handwritten text beside the mark.
- `lifetime`: "ephemeral" (default) fades after a few seconds; "permanent" stays on the board.
- When an annotation is no longer relevant, remove it with `remove_annotation(annotation_id)`.
- Place `[[MARK:annotation_id]]` at the start of your spoken sentence when making the mark.

=============================================================================
HARNESS RULE 6: LEARNER SPATIAL POINTING
=============================================================================
When the learner circles, underlines, or highlights elements with their pen, their message begins with a prefix:
- One element: `[Learner circled diagram element(s): 'element_id' (Label) (0.92 match)]`
- Two elements: `[Learner circled relationship between diagram elements: 'element_id' (Label) and 'element_id' (Label) (0.88 match)]`
The learner is asking about those elements: answer about them. With two elements, they are asking how the two relate. You may annotate them while you speak.

=============================================================================
HARNESS RULE 7: PAGES
=============================================================================
- When a page is nearly full, or the learner moves to a new idea, PROPOSE a new page in your chat reply and wait; the learner may decline.
- Once the learner agrees (or asks for a new page/topic), call `start_new_page`, then draw on it in the same turn. Never draw on a full page after the learner agreed to move on.
""".replace("{FRAME_PERCENT}", str(FRAME_PERCENT))   # the frame rule is stated once, in validator.FRAME_CANVAS_FRACTION


# ---------------------------------------------------------------------------
# Tool definitions for the LLM
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_new_page",
            "description": (
                "Saves the current page and opens a fresh blank page; later draw_new_element calls land on it. "
                "Call it when the learner agrees to (or asks for) a new page or a new topic, or when the "
                "current page has no free space left and the learner has agreed to move on."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title for the new page."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_page_state",
            "description": (
                "Returns the current state of the whiteboard page: element count, "
                "occupied bounding boxes, and remaining open canvas space."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "draw_new_element",
            "description": (
                "Adds one named element to the whiteboard. An element is one <g id='element_id'> group, and the group may "
                "contain any number of shapes and text. The narration is tied to the element through its id, so whatever "
                "the narration refers to must be inside the same group."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "element_id": {
                        "type": "string",
                        "description": "A unique id for this element. Must not already exist on this page."
                    },
                    "svg_fragment": {
                        "type": "string",
                        "description": (
                            "One <g id='...'> group containing everything this element consists of, any number of shapes and text. "
                            "Must use absolute x/y coordinates. No transform attributes (rotation included). Fits within 1200x800 canvas."
                        )
                    },
                    "narration": {
                        "type": "string",
                        "description": (
                            "What you say aloud when this element appears on the whiteboard. "
                            "At most 200 words (it is spoken, and speech has a cost). "
                            "[[MARK:element_id]] MUST be the very first thing in the narration, before any other words. "
                            "Plain text only: no markdown, no bullet points."
                        )
                    }
                },
                "required": ["element_id", "svg_fragment", "narration"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "modify_existing_element",
            "description": (
                "Corrects a specific named element you drew earlier on this page. "
                "Only usable while the page is still active (not saved). "
                "Touches ONLY the named element — nothing else changes. "
                "Use this for immediate corrections, not for redesigning the whole page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "element_id": {
                        "type": "string",
                        "description": "The id of the element to replace. Must already exist on this page."
                    },
                    "new_svg_fragment": {
                        "type": "string",
                        "description": (
                            "The replacement SVG. Must use the same element_id. "
                            "Absolute coordinates. No transform attributes."
                        )
                    }
                },
                "required": ["element_id", "new_svg_fragment"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "annotate_element",
            "description": (
                "Draws an organic, human-like hand annotation over or between diagram elements on the whiteboard "
                "(circling an element, wavy underline beneath it, drawing a checkmark ✓, drawing a crossmark ✗, "
                "sweeping a translucent highlighter marker, or sketching a curved pointer arrow). "
                "Use this while speaking to visually guide the learner's attention to specific components."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "annotation_id": {
                        "type": "string",
                        "description": "A unique id for this annotation mark."
                    },
                    "style": {
                        "type": "string",
                        "enum": ["circle", "underline", "tick", "cross", "highlight", "arrow"],
                        "description": (
                            "Visual form: 'circle' (loops around element), 'underline' (wavy brush line beneath text/card), "
                            "'tick' (emerald green checkmark ✓), 'cross' (rose red crossmark ✗), "
                            "'highlight' (translucent underlay marker), 'arrow' (curved pointer arrow from source to target)."
                        )
                    },
                    "target_element_id": {
                        "type": "string",
                        "description": "The element id to annotate (or destination element if style is 'arrow'). Must already exist on page."
                    },
                    "from_element_id": {
                        "type": "string",
                        "description": "REQUIRED ONLY if style is 'arrow': the source element id where the arrow starts. Forbidden for other styles."
                    },
                    "color": {
                        "type": "string",
                        "description": "Optional stroke color as a hex value."
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional brief handwritten callout note near the mark."
                    },
                    "lifetime": {
                        "type": "string",
                        "enum": ["ephemeral", "permanent"],
                        "description": (
                            "'ephemeral' (default): mark gracefully fades out after speaking. Ideal for transient pointing during explanation. "
                            "'permanent': mark stays on the whiteboard (e.g. checkmark ✓ or key callout note)."
                        )
                    },
                    "duration_ms": {
                        "type": "integer",
                        "description": "For ephemeral marks: milliseconds to stay visible before fading (default 3000). Ignored for permanent marks."
                    },
                    "narration": {
                        "type": "string",
                        "description": (
                            "Spoken explanation while making this annotation. "
                            "[[MARK:annotation_id]] MUST be the very first token in the narration. "
                            "Plain text only."
                        )
                    }
                },
                "required": ["annotation_id", "style", "target_element_id", "narration"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_annotation",
            "description": "Removes a specific annotation mark when moving to a new topic or clearing old focus marks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "annotation_id": {
                        "type": "string",
                        "description": "The annotation_id to remove."
                    }
                },
                "required": ["annotation_id"]
            }
        }
    }
]

# Scene mode: pages and annotations as before, and the lesson-board blocks in place of the raw-SVG draw/modify tools
BUILDERS = {"draw_graph": build_graph, "draw_table": build_table, "draw_bar_chart": build_bar_chart, "draw_venn": build_venn}   # blocks drawn whole by code
SCENE_TOOLS = [t for t in TOOLS if t["function"]["name"] in ("start_new_page", "annotate_element", "remove_annotation")] + [NOTES_TOOL, SCENE_TOOL, GRAPH_TOOL, TABLE_TOOL, BAR_TOOL, VENN_TOOL, CALC_TOOL]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _model_view(page_state: dict) -> dict:
    """What the model is shown of the page: the same state without the embedded font data."""
    return {**page_state, "current_svg": strip_embedded_fonts(page_state.get("current_svg"))}


def _handle_get_current_page_state(page_state: dict) -> str:
    """Returns the current page state as JSON string for the tool response."""
    return json.dumps(_model_view(page_state))


def _transform_error(svg_fragment: str):
    """Tool-result error if the fragment uses a transform attribute (measurement only understands absolute x/y)."""
    tag = find_transform(svg_fragment)
    if tag is None:
        return None
    return {
        "status": "error",
        "detail": (f"The <{tag}> element uses a transform attribute, which is not supported because layout checks "
                   "read absolute coordinates. Remove it and place the shape directly with x/y (or cx/cy, points, d). "
                   "For rotated text, write it horizontally instead."),
    }


# The lost-content note asks the tutor to redraw. Told at most this often per element per turn: a control character the model keeps writing otherwise starts a
# redraw loop (19 redraws of one element, 70 model calls in a turn: L2 run 1, docs/BASELINE.md). After that the placeholder stays on the board and the tutor is not told again.
LOST_NOTES_PER_ELEMENT = 2
# The same element rejected for overlapping the same element: the full message twice per turn, then only the free-region hint (the model had repeated one rejected drawing 4 times
# at the same coordinates in a real session, docs/OVERLAP_ROUND.md).
OVERLAP_MESSAGES_PER_ELEMENT = 2


def _overlap_message(clash: dict, current_svg: Optional[str], hint_only: bool = False) -> str:
    """The rejection text for a drawing that covers an existing element: names the element, gives the drawing's size and ONE free region computed from the existing elements
    (or says plainly that none that large is left and how much room there is). Nothing is moved for the tutor."""
    nb, ob = clash["new_bbox"], clash["bbox"]
    w, h = round(nb["width"]), round(nb["height"])
    free = find_free_region(current_svg, nb["width"], nb["height"], near=(nb["x"] + nb["width"] / 2, nb["y"] + nb["height"] / 2), ignore_id=clash["new_id"])
    region = f"x:{free['x']}, y:{free['y']}, width:{free['width']}, height:{free['height']}"
    if hint_only:
        if free["fits"]:
            return f"Free region for '{clash['new_id']}' (about {w}x{h} px): {region}."
        return (f"No free region for '{clash['new_id']}' (about {w}x{h} px) is left: about {free['free_pct']}% of the canvas is free, "
                f"the largest free region is {region}.")
    head = f"'{clash['new_id']}' overlaps existing '{clash['existing_id']}' (x:{ob['x']:.0f}-{ob['x']+ob['width']:.0f}, y:{ob['y']:.0f}-{ob['y']+ob['height']:.0f}). "
    if free["fits"]:
        return head + f"Your drawing is about {w}x{h} px. A free region where it fits: {region}. Redraw it inside that region."
    return (head + f"Your drawing is about {w}x{h} px and no free region that large is left on this page: about {free['free_pct']}% of the canvas is free, "
            f"and the largest free region is {region}. Draw something that fits there, or tell the learner the page is full.")


def _tell_what_was_lost(result: dict, element_id: str, kind: str, as_written: str, kept: str, lost_note_counts: Optional[Dict[str, int]] = None) -> None:
    """If anything the model wrote did not reach the board (or a control character had to be replaced), log it and tell the tutor in the result
    (the first LOST_NOTES_PER_ELEMENT times for an element within a turn; `lost_note_counts` is that turn's tally)."""
    loss = compare_with_stored(as_written, kept)
    if loss.formatting:
        logger.info(EngineEvent.CONTENT_LOST, f"Formatting tags removed in '{element_id}' (text kept)",
                    data={"element_id": element_id, "kind": kind, "formatting": dict(loss.formatting), "told_tutor": False})
    note = lost_content_note(element_id, loss)
    if note:
        count = 1
        if lost_note_counts is not None:
            count = lost_note_counts[element_id] = lost_note_counts.get(element_id, 0) + 1
        told = count <= LOST_NOTES_PER_ELEMENT
        logger.info(EngineEvent.CONTENT_LOST, f"Part of '{element_id}' did not reach the board: {note}",
                    data={"element_id": element_id, "kind": kind, "told_tutor": told, **loss.as_dict(),
                          "text_lines_lost": [t[:60] for t in loss.text_lines[:3]]})
        if told:
            result["lost_content"] = note
        else:
            logger.warn(EngineEvent.LOST_CONTENT_CAP_REACHED, f"Lost-content note for '{element_id}' not repeated (this is occurrence {count} in this turn)",
                        data={"element_id": element_id, "count": count, "cap": LOST_NOTES_PER_ELEMENT})


VOICE_AT_ONCE = threading.BoundedSemaphore(2)   # clips are made two at a time: ElevenLabs' smallest plan allows 2 requests at once (a 429 means silence)


def _voice_limited(stop, *args):
    with VOICE_AT_ONCE:   # a thread-level limit (an asyncio one belongs to the loop it was first used on)
        if stop is not None and stop.is_set():
            raise RuntimeError("the turn was interrupted before this clip was made")   # a clip waiting its turn is not paid for
        return generate_narration_audio(*args)


async def publish_element(notebook_id: str, page_id: str, element_id: str, styled: str, narration: str, emit_fn, persist_fn, voice=None,
                          block: Optional[dict] = None) -> bool:
    """A checked, sanitised element goes on the board: narration audio, PageEvent, element_drawn. Returns voice_ok
    (False when the learner only gets silence). Shared by draw_new_element and the scene path (engine/scene.py).
    `voice`: the audio made ahead by synthesise_voice (the scene path makes a block's clips in parallel)."""
    audio_url, alignment_url, voice_ok = voice if voice is not None else await synthesise_voice(notebook_id, page_id, element_id, narration)
    await persist_fn(
        kind="draw",
        element_id=element_id,
        svg_fragment=styled,
        narration=narration,
        audio_path=audio_url,
        alignment_path=alignment_url,
        **({"block": block} if block else {}),   # a scene block's record, on its first step (the raw-SVG endpoints never pass one)
    )
    await emit_fn(SessionEvent.ELEMENT_DRAWN, {
        "page_id": page_id,
        "element_id": element_id,
        "svg_fragment": styled,
        "narration": narration,
        "audio_url": audio_url,
        "alignment_url": alignment_url,
        "voice_ok": voice_ok,
    })
    return voice_ok


async def synthesise_voice(notebook_id: str, page_id: str, element_id: str, narration: str, stop=None):
    """The narration's audio and alignment files: (audio_url, alignment_url, voice_ok), never raises. `stop` (a threading.Event):
    set when the turn is interrupted, so a clip still waiting for its turn is not made."""
    page_dir = OUTPUT_DIR / notebook_id / page_id
    page_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', element_id)
    audio_path = page_dir / f"{safe_id}_audio.mp3"
    alignment_path = page_dir / f"{safe_id}_alignment.json"

    voice_ok = True  # False when the learner will only get silence (TTS fallback or failure)
    try:
        loop = asyncio.get_running_loop()
        audio_duration, _, alignment = await loop.run_in_executor(
            None, _voice_limited,
            stop, narration, str(audio_path), str(alignment_path), element_id
        )
        voice_ok = not alignment.get("is_synthetic", False)
        logger.info(EngineEvent.AUDIO_SYNTHESIS_COMPLETED, f"Audio for {element_id}",
                    data={"duration": audio_duration, "voice_ok": voice_ok, "chars": len(narration)})
    except Exception as e:
        voice_ok = False
        import traceback as _tb
        logger.warn(EngineEvent.AUDIO_SYNTHESIS_FAILED, f"Audio failed for {element_id}: {e}\n{_tb.format_exc()}")
        audio_path = None
        alignment_path = None

    audio_url = f"/static/notebooks/{notebook_id}/{page_id}/{safe_id}_audio.mp3" if audio_path and audio_path.exists() else None
    alignment_url = f"/static/notebooks/{notebook_id}/{page_id}/{safe_id}_alignment.json" if alignment_path and alignment_path.exists() else None
    return audio_url, alignment_url, voice_ok


async def _handle_draw_new_element(
    notebook_id: str,
    page_id: str,
    page_status: str,
    element_id: str,
    svg_fragment: str,
    narration: str,
    current_svg: Optional[str],
    emit_fn,
    persist_fn,
    lost_note_counts: Optional[Dict[str, int]] = None,
    overlap_counts: Optional[Dict[tuple, int]] = None,
) -> dict:
    """
    Full draw pipeline: sanitize → validate geometry → density check → audio → persist → emit.
    Returns { "status": "ok"|"error", "detail": str, "density_signal": str|None }
    """
    if page_status == "saved":
        return {"status": "error", "detail": "This page is saved and locked. Start a new page to continue drawing."}

    as_written = svg_fragment       # the drawing exactly as the model wrote it, to tell the tutor what did not reach the board

    # The marker is a recording detail, so the code makes it right however the model wrote it (and counts the repairs)
    narration, marker_reasons = normalise_marker(narration, element_id)
    if marker_reasons:
        logger.info(EngineEvent.MARKER_REPAIRED, f"Marker repaired for '{element_id}': {', '.join(marker_reasons)}",
                    data={"element_id": element_id, "kind": "draw", "reasons": marker_reasons})

    # 0. Guard: reject full-canvas background rects before they pollute the page
    import re as _re_guard
    for bg_rect in _re_guard.findall(r'<rect\b[^>]*>', svg_fragment, _re_guard.IGNORECASE):
        w_m = _re_guard.search(r'\bwidth\s*=\s*["\'](\d+\.?\d*)["\']', bg_rect, _re_guard.IGNORECASE)
        h_m = _re_guard.search(r'\bheight\s*=\s*["\'](\d+\.?\d*)["\']', bg_rect, _re_guard.IGNORECASE)
        if w_m and h_m:
            w, h = float(w_m.group(1)), float(h_m.group(1))
            if is_background_frame(w, h):
                logger.warn(EngineEvent.SANITIZE_FAILED,
                            f"Rejected full-canvas background rect in element '{element_id}' "
                            f"(w={w}, h={h}). Agent should draw content, not frames.")
                return {
                    "status": "error",
                    "detail": (
                        f"Your svg_fragment contains a background frame: a rect of {w:.0f}x{h:.0f} covers "
                        f"{w * h / (CANVAS_WIDTH * CANVAS_HEIGHT):.0%} of the canvas (the limit for a single shape is {FRAME_PERCENT}%). "
                        "Do NOT draw background frames — the canvas is already styled. "
                        "Draw meaningful content: a concept box, a diagram component, an arrow, a label."
                    )
                }

    bad = _transform_error(svg_fragment)
    if bad:
        return bad

    # 0b. Guard: ids must be unique on a page (duplicates break annotations and modify)
    if current_svg and re.search(r'\bid\s*=\s*["\']' + re.escape(element_id) + r'["\']', current_svg):
        return {
            "status": "error",
            "detail": f"An element with id '{element_id}' already exists on this page. "
                      "Pick a new unique element_id, or use modify_existing_element to change it."
        }

    # 0c. One element is one <g id=element_id> group, however the model wrote it. Before the sanitiser: it keeps only the
    # first top-level node and would silently drop the rest of a drawing sent as sibling tags (a card and all its text).
    svg_fragment, group_reason = ensure_group(svg_fragment, element_id)
    if group_reason:
        logger.info(EngineEvent.GROUP_REPAIRED, f"Group repaired for '{element_id}': {group_reason}",
                    data={"element_id": element_id, "kind": "draw", "reason": group_reason})

    # 1. Sanitize
    try:
        sanitized = sanitize_svg(svg_fragment)
        # The font CSS is ~15 KB; one copy per page is enough (every element renders in the same SVG)
        has_font = bool(current_svg) and "@font-face" in current_svg
        styled = sanitized if has_font else inject_trusted_font(sanitized)
    except Exception as e:
        logger.warn(EngineEvent.SANITIZE_FAILED, f"Sanitize failed for element {element_id}: {e}")
        return {"status": "error", "detail": f"SVG sanitization failed: {e}"}

    # 1b. LOG ONLY: what the proposed shape-level validator would decide (engine/shadow.py). Its result is never used; any error or delay beyond its time limit is contained there.
    await shadow_record(current_svg, styled, element_id, page_id)

    # 2. Validate geometry
    geo = validate_geometry(styled, existing_svg=current_svg)
    if not geo["valid"]:
        details = "; ".join(v["detail"] for v in geo["violations"])
        logger.warn(EngineEvent.GEOMETRY_INVALID, f"Geometry invalid for {element_id}: {details}")
        return {"status": "error", "detail": f"Element geometry invalid: {details}"}

    # 2b. Overlap check — reject drawing on top of an existing element
    clash = check_overlap(current_svg, styled)
    if clash:
        b = clash["bbox"]
        logger.warn(EngineEvent.GEOMETRY_INVALID, f"Overlap: {clash['new_id']} over {clash['existing_id']}")
        count = 1
        if overlap_counts is not None:
            key = (clash["new_id"], clash["existing_id"])
            count = overlap_counts[key] = overlap_counts.get(key, 0) + 1
        capped = count > OVERLAP_MESSAGES_PER_ELEMENT
        if capped:
            logger.warn(EngineEvent.OVERLAP_CAP_REACHED, f"'{clash['new_id']}' rejected for overlapping '{clash['existing_id']}' again (occurrence {count} in this turn): free-region hint only",
                        data={"element_id": clash["new_id"], "existing_id": clash["existing_id"], "count": count, "cap": OVERLAP_MESSAGES_PER_ELEMENT})
        return {"status": "error", "detail": _overlap_message(clash, current_svg, hint_only=capped)}

    # 3. Density check (after this element would be added)
    density = check_density(current_svg, styled)
    if density.hard_cap:
        logger.info(EngineEvent.DENSITY_HARD_CAP, f"Hard cap reached on page {page_id}",
                    data=density.to_dict())
        await emit_fn(SessionEvent.PAGE_DENSITY_HARD_CAP, density.to_dict())
        return {
            "status": "error",
            "detail": (
                f"Page hard cap reached ({density.element_count}/{HARD_ELEMENT_COUNT} elements). "
                "You must propose a new page to the learner before adding more content."
            )
        }

    density_signal = None
    if density.soft_signal:
        logger.info(EngineEvent.DENSITY_SOFT_SIGNAL, f"Soft signal on page {page_id}",
                    data=density.to_dict())
        await emit_fn(SessionEvent.PAGE_DENSITY_NUDGE, density.to_dict())
        density_signal = "soft"

    # 4-6. Audio, persist, emit
    await publish_element(notebook_id, page_id, element_id, styled, narration, emit_fn, persist_fn)
    logger.info(EngineEvent.DENSITY_CHECKED, f"Page {page_id} now has {density.element_count} elements",
                data=density.to_dict())

    result = {"status": "ok", "detail": f"Element '{element_id}' drawn successfully."}
    _tell_what_was_lost(result, element_id, "draw", as_written, sanitized, lost_note_counts)
    if has_text_less_card(styled):      # log only: counts how often it happens, never blocks the drawing
        logger.info(EngineEvent.UNLABELED_CARD_NOTE, f"'{element_id}' has a card-sized rectangle and no text",
                    data={"element_id": element_id})
    hints = find_layout_issues(styled)
    if hints:
        logger.info(EngineEvent.LAYOUT_HINT, f"Hint for '{element_id}': " + " ".join(hints),
                    data={"element_id": element_id, "hints": hints})
    # LOG ONLY, never shown to the tutor: in baseline K the hint made the tutor redraw 15-22 times a run and the boards did not improve (docs/BASELINE.md).
    # The estimate is kept so overflow can still be measured offline from the log.
    width_issues = find_text_width_issues(styled, current_svg)
    if width_issues:
        logger.info(EngineEvent.TEXT_WIDTH_NOTE, f"Text width note for '{element_id}': {len(width_issues)} label(s) estimated wider than their space",
                    data={"element_id": element_id, "issues": [{**i, "text": i["text"][:60]} for i in width_issues[:6]]})
    if hints:
        result["layout_hint"] = (" ".join(hints) +
                                 " Fix it now with modify_existing_element if it would look unfinished to the learner.")
    if density_signal:
        result["density_signal"] = (
            "This page is getting dense. Consider wrapping up this concept and "
            "proposing a new page to the learner."
        )
    return result


async def _handle_modify_existing_element(
    page_id: str,
    page_status: str,
    element_id: str,
    new_svg_fragment: str,
    current_svg: Optional[str],
    existing_element_ids: set,
    emit_fn,
    persist_fn,
    lost_note_counts: Optional[Dict[str, int]] = None,
) -> dict:
    """
    Corrects a named element. Only usable while page is active.
    """
    if page_status == "saved":
        return {"status": "error", "detail": "Page is saved and locked. Cannot modify elements."}

    if element_id not in existing_element_ids:
        return {
            "status": "error",
            "detail": f"Element '{element_id}' does not exist on this page. Cannot modify."
        }

    bad = _transform_error(new_svg_fragment)
    if bad:
        return bad

    # The replacement is one <g id=element_id> group too (same repair as a new drawing), so it replaces the old group whole
    as_written = new_svg_fragment
    new_svg_fragment, group_reason = ensure_group(new_svg_fragment, element_id)
    if group_reason:
        logger.info(EngineEvent.GROUP_REPAIRED, f"Group repaired for '{element_id}': {group_reason}",
                    data={"element_id": element_id, "kind": "modify", "reason": group_reason})

    # Extract old fragment for the old_svg_fragment audit field
    old_fragment = _extract_element_fragment(current_svg or "", element_id)

    # Sanitize replacement. The page keeps ONE copy of the ~16 KB font: add it only if the rest of the page lacks it
    # (the element being replaced may be the one that carried it).
    try:
        sanitized = sanitize_svg(new_svg_fragment)
        rest_of_page = (current_svg or "").replace(old_fragment, "", 1) if old_fragment else (current_svg or "")
        styled = sanitized if "@font-face" in rest_of_page else inject_trusted_font(sanitized)
    except Exception as e:
        return {"status": "error", "detail": f"SVG sanitization failed: {e}"}

    # Validate geometry
    geo = validate_geometry(styled, existing_svg=current_svg)
    if not geo["valid"]:
        details = "; ".join(v["detail"] for v in geo["violations"])
        return {"status": "error", "detail": f"Replacement geometry invalid: {details}"}

    # Persist
    await persist_fn(
        kind="modify",
        element_id=element_id,
        svg_fragment=styled,
        old_svg_fragment=old_fragment,
    )

    # Emit
    await emit_fn(SessionEvent.ELEMENT_MODIFIED, {
        "page_id": page_id,
        "element_id": element_id,
        "new_svg_fragment": styled,
    })

    result = {"status": "ok", "detail": f"Element '{element_id}' modified successfully."}
    _tell_what_was_lost(result, element_id, "modify", as_written, sanitized, lost_note_counts)
    return result


async def _handle_annotate_element(
    notebook_id: str,
    page_id: str,
    page_status: str,
    annotation_id: str,
    style: str,
    target_element_id: str,
    narration: str,
    from_element_id: Optional[str],
    color: Optional[str],
    note: Optional[str],
    lifetime: Optional[str],
    duration_ms: Optional[int],
    existing_element_ids: set,
    emit_fn,
    persist_fn,
) -> dict:
    """
    Organic annotation pipeline: validates rules -> stable seed -> audio synthesis -> persist -> emit.
    """
    if page_status == "saved":
        return {"status": "error", "detail": "This page is saved and locked. Cannot annotate elements."}

    # 1. Validate style
    if style not in VALID_ANNOTATION_STYLES:
        return {
            "status": "error",
            "detail": f"Invalid style '{style}'. Must be one of: {', '.join(sorted(VALID_ANNOTATION_STYLES))}."
        }

    # 2. Validate target_element_id
    if not target_element_id:
        return {"status": "error", "detail": "target_element_id is required."}
    if target_element_id not in existing_element_ids:
        return {
            "status": "error",
            "detail": f"Target element '{target_element_id}' does not exist on this page. Cannot annotate."
        }

    # 3. Conditional validation for style == 'arrow'
    if style == "arrow":
        if not from_element_id:
            return {
                "status": "error",
                "detail": "For style='arrow', 'from_element_id' is required to specify where the arrow begins."
            }
        if from_element_id not in existing_element_ids:
            return {
                "status": "error",
                "detail": f"Source element '{from_element_id}' does not exist on this page. Cannot draw arrow."
            }
        if from_element_id == target_element_id:
            return {
                "status": "error",
                "detail": "Source element ('from_element_id') and target element ('target_element_id') cannot be the same for an arrow."
            }
    else:
        # Non-arrow styles: from_element_id is forbidden/ignored
        from_element_id = None

    # 4. Validate lifetime and duration_ms
    lifetime_clean = (lifetime or "ephemeral").strip().lower()
    if lifetime_clean not in VALID_LIFETIMES:
        lifetime_clean = "ephemeral"

    if lifetime_clean == "ephemeral":
        if duration_ms is None or duration_ms <= 0:
            duration_ms = 3000
        else:
            duration_ms = max(1000, min(duration_ms, 10000))
    else:
        duration_ms = 0

    # 5. Resolve color
    if not color:
        color = DEFAULT_STYLE_COLORS.get(style, "#f59e0b")

    # 6. Stable, process-independent deterministic integer seed (SHA-256)
    seed = generate_annotation_seed(annotation_id)

    # 7. Generate voice audio with [[MARK:annotation_id]]
    page_dir = OUTPUT_DIR / notebook_id / page_id
    page_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', annotation_id)
    audio_path = page_dir / f"{safe_id}_audio.mp3"
    alignment_path = page_dir / f"{safe_id}_alignment.json"

    # Ensure narration has [[MARK:annotation_id]] at the start if not present
    narration_text, marker_reasons = normalise_marker(narration or f"Here we focus on {target_element_id}.", annotation_id)
    if marker_reasons and narration:
        logger.info(EngineEvent.MARKER_REPAIRED, f"Marker repaired for '{annotation_id}': {', '.join(marker_reasons)}",
                    data={"element_id": annotation_id, "kind": "annotate", "reasons": marker_reasons})

    try:
        loop = asyncio.get_running_loop()
        audio_duration, _, _ = await loop.run_in_executor(
            None, generate_narration_audio,
            narration_text, str(audio_path), str(alignment_path), annotation_id
        )
        logger.info(EngineEvent.AUDIO_SYNTHESIS_COMPLETED, f"Audio for annotation {annotation_id}",
                    data={"duration": audio_duration})
    except Exception as e:
        import traceback as _tb
        logger.warn(EngineEvent.AUDIO_SYNTHESIS_FAILED, f"Audio failed for annotation {annotation_id}: {e}\n{_tb.format_exc()}")
        audio_path = None
        alignment_path = None

    audio_url = f"/static/notebooks/{notebook_id}/{page_id}/{safe_id}_audio.mp3" if audio_path and audio_path.exists() else None
    alignment_url = f"/static/notebooks/{notebook_id}/{page_id}/{safe_id}_alignment.json" if alignment_path and alignment_path.exists() else None

    # 8. Construct semantic payload
    payload = {
        "page_id": page_id,
        "annotation_id": annotation_id,
        "style": style,
        "target_element_id": target_element_id,
        "from_element_id": from_element_id,
        "color": color,
        "note": note or None,
        "lifetime": lifetime_clean,
        "duration_ms": duration_ms,
        "seed": seed,
        "audio_url": audio_url,
        "alignment_url": alignment_url,
        "narration": narration_text,
    }

    # 9. Persist PageEvent (kind="annotate")
    await persist_fn(
        kind="annotate",
        element_id=annotation_id,
        svg_fragment=json.dumps(payload),
        narration=narration_text,
        audio_path=audio_url,
        alignment_path=alignment_url,
    )

    # 10. Emit WS event
    await emit_fn(SessionEvent.ELEMENT_ANNOTATED, payload)

    return {
        "status": "ok",
        "detail": f"Annotation '{annotation_id}' ({style} on {target_element_id}) created successfully.",
        "payload": payload,
    }


async def _handle_remove_annotation(
    page_id: str,
    page_status: str,
    annotation_id: str,
    emit_fn,
    persist_fn,
) -> dict:
    """Removes a specific annotation mark from the whiteboard."""
    if page_status == "saved":
        return {"status": "error", "detail": "This page is saved and locked. Cannot remove annotations."}

    payload = {
        "page_id": page_id,
        "annotation_id": annotation_id,
    }

    await persist_fn(
        kind="remove_annotation",
        element_id=annotation_id,
        svg_fragment=json.dumps(payload),
    )

    await emit_fn(SessionEvent.ANNOTATION_REMOVED, payload)

    return {
        "status": "ok",
        "detail": f"Annotation '{annotation_id}' removed.",
        "payload": payload,
    }


def _extract_element_fragment(svg: str, element_id: str) -> Optional[str]:
    """Extraction of a named element from SVG for the old_svg_fragment audit field and replacement."""
    import re as _re
    # 1. Try matching paired tag with content: <tag id="...">...</tag>
    pattern_paired = _re.compile(
        rf'<([a-zA-Z0-9_-]+)\b[^>]*\bid\s*=\s*["\']' + _re.escape(element_id) + r'["\'][^>]*>.*?</\1>',
        _re.IGNORECASE | _re.DOTALL
    )
    match = pattern_paired.search(svg)
    if match:
        return match.group(0)

    # 2. Otherwise match self-closing tag: <tag id="..." ... />
    pattern_single = _re.compile(
        rf'<[^>]+\bid\s*=\s*["\']' + _re.escape(element_id) + r'["\'][^>]*/?>',
        _re.IGNORECASE | _re.DOTALL
    )
    match = pattern_single.search(svg)
    return match.group(0) if match else None


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

import re  # needed by _handle_draw_new_element


async def run_whiteboard_author(
    notebook_id: str,
    page_id: str,
    page_status: str,
    learner_message: str,
    chat_history: List[Dict[str, Any]],   # last CHAT_HISTORY_TURNS turns
    page_state: dict,                      # from get_current_page_state()
    prior_pages_summary: str,             # one-line summaries of prior pages
    existing_element_ids: set,
    emit_fn,    # async callable(event_type, payload)
    persist_fn, # async callable(**PageEvent fields)
    new_page_fn=None,  # async callable(title) -> new page_id; switches emit/persist to it
    tool_log: Optional[list] = None,   # if given, one record per tool call is appended: {tool, element_id, status, iteration}
    lesson_plan: str = "",             # scene mode: the private plan (engine/lesson_plan.py), "" for none
    away_for: str = "",                # scene mode: how long the learner was away ("about 3 hours"), "" when they were not
    lesson_path: Optional[list] = None,  # scene mode: the checklist [{title, done}] (backend lesson_path), None for none
    lesson_final: Optional[dict] = None,  # scene mode: the end-of-lesson check (backend lesson_final), None for none
    course: str = "",                  # scene mode: the learner's goal and roadmap (engine/lesson_plan.split_course), "" for none
    plan_page_fn=None,  # scene mode: async callable() -> the next lesson's plan for the page start_new_page just made, "" for none
) -> str:
    """
    Main entry point. Runs the LLM tool-use loop and returns the assistant's
    final text response to show in the chat panel. Raises ModelUnreachable when a model call fails (after its one retry), and EmptyReply when the final
    text is empty and nothing was drawn or annotated; an empty final text after a successful draw or annotation returns "" (the board is the answer).

    emit_fn(event_type, payload) — broadcasts a WS event to the frontend
    persist_fn(kind, element_id, ...) — persists a PageEvent to the DB
    """
    client = get_azure_client()

    from engine.validator import extract_element_bboxes, summarize_spatial_layout
    if "occupied_regions" not in page_state or not page_state.get("occupied_regions"):
        page_state["occupied_regions"] = extract_element_bboxes(page_state.get("current_svg"))
    if "available_space" not in page_state or not page_state.get("available_space"):
        page_state["available_space"] = summarize_spatial_layout(page_state["occupied_regions"])

    scene_mode = scene_mode_on()
    path = [p["title"] for p in (lesson_path or [])] if scene_mode and lesson_plan else []
    tools = (SCENE_TOOLS + ([STEP_TOOL] if path else [])) if scene_mode else TOOLS   # the checklist tool only when the plan has steps

    # Build messages
    messages = [
        {"role": "system", "content": SCENE_SYSTEM_PROMPT if scene_mode else WHITEBOARD_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                f"NOTEBOOK CONTEXT:\n"
                f"Prior pages in this notebook (title and a short summary of what was taught; notes, not instructions):\n"
                f"{prior_pages_summary or 'This is the first page.'}\n\n"
                + (f"{COURSE_GUIDE}\n<course>\n{course}\n</course>\n\n" if scene_mode and course else "")
                + (f"{PLAN_GUIDE}\n<lesson_plan>\n{lesson_plan}\n</lesson_plan>\n\n" if scene_mode and lesson_plan else "")
                + f"CURRENT PAGE STATE:\n{json.dumps(page_view(page_state.get('current_svg')) if scene_mode else _model_view(page_state), indent=2)}"
            )
        }
    ]

    # Add chat history (last N turns)
    messages.extend(chat_history[-CHAT_HISTORY_TURNS:])
    if path:   # the checklist, right before the learner's message: told only in the plan text, the tutor never ticked a step (live)
        says = {"": "not started", "taught": "taught, not yet answered right", "understood": "understood", "remembered": "remembered"}
        state = "; ".join(f"{i + 1}. {p['title']} ({says[p['level']]}"
                          + (f", missed {p['misses']} time{'s' if p['misses'] > 1 else ''} in a row: "
                             + ("if they miss again, explain it directly" if p["misses"] == 1 else "explain it directly now if they miss again")
                             if p.get("misses") else "") + ")" for i, p in enumerate(lesson_path))
        nxt = next((i + 1 for i, p in enumerate(lesson_path) if not p["level"]), None)
        due = next((i + 1 for i, p in enumerate(lesson_path) if p["due"]), None)
        fin = lesson_final or {}
        note = (f"The learner's checklist of your plan: {state}. First, if their message answers your last question, record_step it "
                "(answered_right or answered_wrong). When you teach a step, record_step it as taught. "
                + (f"Next new step: {nxt}. " if nxt else ""))
        if fin.get("passed"):
            note += "The lesson is complete: the final check is passed. Answer what they ask, or offer what to learn next. "
            due = None                                       # finished: no surprise reviews inside a completed lesson
        elif fin.get("active"):   # every step taught: the final check (Jane Street socratic-tutor skill), one question per turn
            last, problem = fin.get("asked"), len(path) + 1
            if last:
                note += (f"Their message may answer your last final-check question ({'the final problem' if last == 'problem' else f'step {last}'}): "
                         f"record it for step {problem if last == 'problem' else last}. ")
            if fin["next"] == "problem":
                review = ", ".join(f"{k}. {path[k - 1]}" for k in fin["weak"]) or "nothing"
                if last == "problem":   # the code knows whether it was asked: the last turn was told to ask it (live: a step check was taken for it)
                    note += (f"Their message answers the final problem: record it as step {problem}. If it is right, close the lesson in this "
                             f"reply: a recap card of the main ideas, and one line saying what to review ({review}). If it is wrong, help as "
                             "usual (a smaller question first) and do not close yet.")
                else:
                    note += (f"Final problem, not asked yet: your earlier questions were step checks. End this turn with one problem in a new "
                             f"situation that needs several steps together; do not close the lesson yet. Their answer will be step {problem}.")
            else:
                note += (f"Final check ({fin['checked']} of {fin['of']} steps checked): end this turn with one question that checks step "
                         f"{fin['next']} ({path[fin['next'] - 1]}) from memory by applying it to a new case, not by repeating it. Draw nothing new. "
                         "If they answered the previous check wrongly, give the right answer in a sentence first: this is a check, not a lesson, "
                         "and it goes on their review list.")
            due = None                                       # the final check covers every step: no separate review
        if due:   # spaced review: a step understood a few turns ago is checked again, from memory (Jane Street socratic-tutor skill)
            note += (f"Review of step {due}: if your last question already checked step {due} again, record their answer for step {due} "
                     f"(live, a right review answer was recorded for another step). Otherwise end this turn with one quick question that "
                     f"checks step {due} again from memory, instead of a question on new material, without saying it is a review.")
        messages.append({"role": "system", "content": note})
    if scene_mode and away_for:   # the lesson resumes after a break (an idea from a competitor's resume notice, docs/PROJECT_BRIEF.md)
        messages.append({"role": "system", "content": f"The learner is back after {away_for} away. Begin your reply with one short welcome-back "
                                                      "sentence that reminds them where you stopped (the last idea, and your last question if it "
                                                      "is still open), then answer their message. Do not start the lesson again."})
    if scene_mode and (asked := last_question(chat_history)):   # live: told only in the prompt, the tutor asked one question three turns running
        messages.append({"role": "system", "content": f"Your last question was: \"{asked}\" The learner's message below answers or skips it. "
                                                      "Right: say so and move on. "
                                                      + ("Wrong or vague: follow the final-check note above. "   # it said both "give the answer first" and "do not give it yet" (architecture review)
                                                         if (lesson_final or {}).get("active") else
                                                         "Wrong or vague: do not give the answer yet, ask one smaller "
                                                         "question that helps them find the flaw (unless they have already missed this idea once: "
                                                         "then explain it and check it again another way). ")
                                                      + "Do not repeat the question word for word. "
                                                      "\"ok\" or \"continue\" is a skip, not an answer: give the answer without praise."
                                                      + (" Record their answer with record_step (answered_right or answered_wrong) for the step "
                                                         "it was about, every time, a second miss too (live, a second miss went unrecorded)."
                                                         if path else "")})

    # Add the new learner message
    messages.append({"role": "user", "content": learner_message})

    logger.info(EngineEvent.DRAW_STARTED, "WhiteboardAuthor loop started",
                data={"notebook_id": notebook_id, "page_id": page_id})

    # Keep a live reference to current_svg for density/geometry checks. It must hold the page AS STORED: a modify later in the same turn looks its old
    # group up in this copy and tells the store to replace exactly that text, so a copy built from what the model WROTE (raw text, before the sanitiser,
    # the placeholder for control characters and the trusted font) never matches the stored page: the modify did not reach it, and a NUL in the raw text
    # went into old_svg_fragment, which Postgres refuses (a 500; K run 2 and L run 3, docs/BASELINE.md). So every stored fragment is remembered here.
    current_svg = page_state.get("current_svg")
    if scene_mode:   # a block's nodes, edges and groups sit inside its step elements: any of them can be annotated in a later turn
        existing_element_ids = set(existing_element_ids) | set(ID_RE.findall(current_svg or ""))
    stored: Dict[str, str] = {}
    board_changed = False        # a draw, modify or annotation succeeded in this turn
    overlap_counts: Dict[tuple, int] = {}   # (new element, element it overlaps) -> rejections in this turn (the full message is sent OVERLAP_MESSAGES_PER_ELEMENT times)
    lost_notes: Dict[str, int] = {}      # element id -> how often part of it was lost in this turn (the note is told only LOST_NOTES_PER_ELEMENT times)
    calls_made: Dict[str, int] = {}
    blocks_this_turn = 0
    new_lesson = None    # (page id, blocks drawn before it) once start_new_page brought the next lesson's plan
    answered_wrong = False   # the tutor recorded a wrong answer in this turn (its reply then opens without praise)
    recaps_this_turn = 0

    async def persist_and_remember(**fields):
        await persist_fn(**fields)
        if fields.get("kind") in ("draw", "modify"):
            stored[fields["element_id"]] = fields["svg_fragment"]

    async def switch_page(title: Optional[str]) -> None:
        """A fresh blank page becomes the active one (start_new_page, and a scene-mode block on a page that cannot take it)."""
        nonlocal page_id, page_status, current_svg, existing_element_ids, page_state
        page_id = await new_page_fn((title or "").strip()[:100] or None)
        page_status, current_svg, existing_element_ids = "active", None, set()
        page_state = {
            "current_svg": None, "element_count": 0, "notebook_id": notebook_id,
            "page_id": page_id, "summary": "Blank page — nothing drawn yet.",
            "occupied_regions": [], "available_space": summarize_spatial_layout([]),
        }

    async def add_block(tool: str, args: dict) -> dict:
        """Scene mode: build a notes/recap or diagram block below what is on the board, then publish each line or teaching step as one
        element (audio, persist, emit) in order. A saved page, or one drawn in raw SVG (no block boxes), gets a fresh page first."""
        nonlocal current_svg, blocks_this_turn, recaps_this_turn
        if blocks_this_turn >= MAX_BLOCKS_PER_TURN:
            return {"status": "error", "detail": f"You have added {MAX_BLOCKS_PER_TURN} blocks in this turn. Stop here and check the learner's understanding."}
        if page_status == "saved" or (current_svg and not board_blocks(current_svg) and page_state.get("element_count")):
            if new_page_fn is None:
                return {"status": "error", "detail": "This page cannot take new blocks and starting pages is not available here."}
            await switch_page(args.get("title"))
        blocks = board_blocks(current_svg)
        n = len(blocks) + 1
        fin = lesson_final or {}
        if tool == "write_notes" and args.get("style") == "recap":   # live: two recap cards in one turn, and recap cards during the check
            if recaps_this_turn:
                why = "One recap card per turn is enough: you have already added one."
            elif fin.get("active") and not fin.get("passed") and fin.get("asked") != "problem":
                why = "No recap card during the final check: the recap closes the lesson, after the final problem is answered."
            else:
                why = ""
            if why:
                logger.warn(EngineEvent.SCENE_REJECTED, f"Block rejected: {why}", data={"page_id": page_id, "tool": tool, "detail": why})
                return {"status": "error", "detail": why}
        if why := repeats(tool, args, current_svg):
            logger.warn(EngineEvent.SCENE_REJECTED, f"Block rejected: {why}", data={"page_id": page_id, "tool": tool, "detail": why[:500]})
            return {"status": "error", "detail": why}
        try:
            what = args
            if tool == "draw_scene":
                what = normalise_scene(args)                     # the diagram as code reads it (ids before the block prefix)
                scene = prefix_ids(what, f"b{n}_")
                steps, box, report = await asyncio.to_thread(build_diagram, scene, n, blocks)
                ids = [i["id"] for i in scene["nodes"] + scene["groups"]]
            elif tool in BUILDERS:
                steps, box, report = await asyncio.to_thread(BUILDERS[tool], args, n, blocks)
                ids = [sid for sid, _, _ in steps]
            else:
                steps, box, report = await asyncio.to_thread(build_notes, args, n, blocks)
                ids = [sid for sid, _, _ in steps]
            fonts = None if (current_svg and "@font-face" in current_svg) else board_font_css()   # before anything is published
        except SceneError as e:
            logger.warn(EngineEvent.SCENE_REJECTED, f"Block rejected: {e}", data={"page_id": page_id, "tool": tool, "detail": str(e)[:500]})
            return {"status": "error", "detail": str(e)}
        blocks_this_turn += 1
        recaps_this_turn += tool == "write_notes" and args.get("style") == "recap"
        # the board as data: stored with the block's first step (page_events.block); the SVG is only its picture (GenSVG and tldraw study, 2026-11-20)
        record = {"n": n, "tool": tool, "args": what, "box": box, "steps": [sid for sid, _, _ in steps], "ids": ids}
        # All of the block's clips start now (two at a time) and each step is published, in order, as soon as its own clip is ready:
        # made one after another, ten steps held the turn ~10 s before the tutor's closing reply (the first step was never waiting)
        stop = threading.Event()
        voices = [asyncio.create_task(synthesise_voice(notebook_id, page_id, sid, narration, stop)) for sid, _, narration in steps]
        try:
            for (sid, fragment, narration), voice in zip(steps, voices):
                # The board's fonts once per page, as faces only (the raw-SVG font CSS sets `text { font-family: Inter }`, which beat the
                # handwriting named on the notes: they drew in Inter and their measured runs overlapped, live CPU lesson, 2026-11-05)
                clean = sanitize_svg(fragment, {"transform"})   # our own SVG: formulas and the chart label need it
                styled = inject_trusted_font(clean, fonts) if fonts and sid == steps[0][0] else clean
                await publish_element(notebook_id, page_id, sid, styled, narration, emit_fn, persist_and_remember, voice=await voice,
                                      block=record if sid == steps[0][0] else None)
                current_svg = (current_svg or "") + "\n" + stored.get(sid, styled)
                existing_element_ids.add(sid)
        finally:   # interrupted (barge-in) or failed: the clips not made yet are not made
            stop.set()
            for v in voices:
                v.cancel()
        existing_element_ids.update(ID_RE.findall(current_svg or ""))
        page_state["element_count"] = page_state.get("element_count", 0) + len(steps)
        logger.info(EngineEvent.SCENE_DRAWN, f"Block {n} ({report['kind']}) added in {len(steps)} steps", data={"page_id": page_id, "box": box, **report})
        return {"status": "ok", "page_id": page_id,
                "detail": f"Block {n} added to the board in {len(steps)} narrated steps. These ids can be annotated: " + ", ".join(ids)}

    # Tool loop (max 20 iterations to prevent runaway)
    for iteration in range(20):
        try:
            response = await asyncio.wait_for(asyncio.to_thread(
                client.chat.completions.create,
                model=AUTHOR_DEPLOYMENT,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=6000,
            ), timeout=MODEL_CEILING_S)
        except Exception as e:
            logger.warn(EngineEvent.DRAW_FAILED, f"Model call failed: {e or type(e).__name__}",
                        data={"notebook_id": notebook_id, "page_id": page_id})
            raise ModelUnreachable(str(e)) from e

        usage = getattr(response, "usage", None)
        if usage is not None:
            # "model" is what the service says it ran (a deployment name is only a label); "deployment" is our setting
            logger.info(EngineEvent.MODEL_USAGE, "Model call", data={
                "model": getattr(response, "model", None) or AUTHOR_DEPLOYMENT, "deployment": AUTHOR_DEPLOYMENT,
                "iteration": iteration,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "cached_tokens": getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)})

        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.warn(EngineEvent.DRAW_FAILED, "Model reply hit the token cap (output may be cut off)",
                        data={"notebook_id": notebook_id, "page_id": page_id})

        # No more tool calls — final text response
        if choice.finish_reason == "stop" or not choice.message.tool_calls:
            final_text = choice.message.content or ""
            final_text = strip_markers(final_text).strip()
            if scene_mode:   # inline $...$ maths reads as text in the chat (live: "$x=2$" showed its dollar signs)
                final_text = demath(final_text)
                if answered_wrong or is_skip(learner_message):   # no "Great thinking!" for a wrong answer or an "ok"
                    final_text = drop_praise(final_text)
            if not final_text:
                logger.warn(EngineEvent.EMPTY_REPLY, f"The model's final reply was empty ({'after a successful draw or annotation' if board_changed else 'and nothing was drawn'})",
                            data={"notebook_id": notebook_id, "page_id": page_id, "tool_call_succeeded": board_changed, "tool_calls": calls_made,
                                  "finish_reason": choice.finish_reason})
                if not board_changed:
                    raise EmptyReply()
            if new_lesson and blocks_this_turn > new_lesson[1] and tool_log is not None and not any(
                    r.get("tool") == "record_step" and r.get("page_id") == new_lesson[0] and r.get("event") == "taught" for r in tool_log):
                # it drew on the new lesson's page, which is its step 1 (live: told to record it, the tutor did not, so the checklist showed nothing taught)
                tool_log.append({"tool": "record_step", "status": "ok", "iteration": iteration, "element_id": "1", "event": "taught", "page_id": new_lesson[0]})
            logger.info(EngineEvent.DRAW_COMPLETED, "WhiteboardAuthor loop completed",
                        data={"iterations": iteration + 1})
            return final_text

        # Append assistant message with tool calls
        messages.append(choice.message)

        # Process each tool call
        tool_results = []
        for tc in choice.message.tool_calls:
            fn_name = tc.function.name
            logger.info(EngineEvent.TOOL_CALL, f"Tool call: {fn_name}", data={"tool": fn_name, "iteration": iteration})
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_results.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps({"status": "error", "detail": (
                        "Your tool arguments were not valid JSON (possibly cut off). "
                        "Retry with a smaller, simpler SVG.")}),
                })
                if tool_log is not None:
                    tool_log.append({"tool": fn_name, "element_id": None, "status": "error", "iteration": iteration})
                continue

            if fn_name == "get_current_page_state":
                result = _handle_get_current_page_state(page_state)

            elif fn_name == "start_new_page":
                if new_page_fn is None:
                    result = json.dumps({"status": "error", "detail": "Starting pages is not available here."})
                else:
                    await switch_page(args.get("title"))
                    advance = may_start_next_lesson(learner_message, lesson_path)
                    new_plan = await plan_page_fn() if scene_mode and plan_page_fn and advance else ""
                    if scene_mode and plan_page_fn and not advance:
                        left = ", ".join(f"{i + 1}. {p['title']}" for i, p in enumerate(lesson_path or []) if not p["level"])
                        result = json.dumps({"status": "ok", "detail": f"New blank page is active. The lesson is not finished (not taught yet: {left}): "
                                             "continue it on this page with its next step; the course moves on when the learner asks for the next "
                                             "concept or every step is taught.", **page_state}, ensure_ascii=False)
                    elif new_plan:   # the next lesson of the course: its plan and an empty checklist replace the old ones from here on
                        lesson_plan, lesson_final, new_lesson = new_plan, None, (page_id, blocks_this_turn)
                        path = path_titles(new_plan)
                        lesson_path = [{"title": t, "level": "", "due": False, "misses": 0} for t in path]
                        if path and STEP_TOOL not in tools:
                            tools = tools + [STEP_TOOL]
                        result = json.dumps({"status": "ok", "detail": "New blank page is active, with the plan of the next lesson (it replaces "
                                             "the earlier plan; private, never read it out). Teach its step 1 now, from the board up, and "
                                             "record_step it as taught.", "lesson_plan": new_plan, **page_state}, ensure_ascii=False)
                    else:
                        result = json.dumps({"status": "ok", "detail": "New blank page is active.", **page_state})

            elif (fn_name in ("draw_scene", "write_notes") or fn_name in BUILDERS) and scene_mode:
                result = json.dumps(await add_block(fn_name, args), ensure_ascii=False)

            elif fn_name == "calculate":
                result = json.dumps(calculate(args.get("expressions")), ensure_ascii=False)

            elif fn_name == "record_step" and path:
                step, event = args.get("step"), args.get("event")
                last_step = len(path) + (1 if (lesson_final or {}).get("active") else 0)   # + the final problem during the final check
                ok = isinstance(step, int) and not isinstance(step, bool) and 1 <= step <= last_step and event in ("taught", "answered_right", "answered_wrong")
                if ok and event != "taught" and is_skip(learner_message):   # live: "continue" was recorded as a wrong answer
                    result = json.dumps({"status": "error", "detail": "The learner skipped, they did not answer: record nothing for it."})
                else:
                    answered_wrong = answered_wrong or (ok and event == "answered_wrong")
                    name = path[step - 1] if ok and step <= len(path) else "the final problem"
                    result = json.dumps({"status": "ok", "detail": f"Recorded for step {step} ({name}): {event}."} if ok else
                                        {"status": "error", "detail": f"step is a number from 1 to {last_step}; event is taught, answered_right or answered_wrong."})

            elif fn_name == "draw_new_element":
                eid = args.get("element_id", "")
                narration_text = args.get("narration", "")
                logger.info(EngineEvent.DRAW_STARTED,
                            f"Drawing element '{eid}' (narration: {len(narration_text)} chars)",
                            data={"element_id": eid, "page_id": page_id,
                                  "raw_svg": (args.get("svg_fragment") or "")[:20000]})   # as the model wrote it, before sanitising
                result_dict = await _handle_draw_new_element(
                    notebook_id=notebook_id,
                    page_id=page_id,
                    page_status=page_status,
                    element_id=eid,
                    svg_fragment=args.get("svg_fragment", ""),
                    narration=narration_text,
                    current_svg=current_svg,
                    emit_fn=emit_fn,
                    persist_fn=persist_and_remember,
                    lost_note_counts=lost_notes,
                    overlap_counts=overlap_counts,
                )
                if result_dict.get("status") == "ok":
                    logger.info(EngineEvent.DRAW_COMPLETED, f"Element '{eid}' drawn OK",
                                data={"element_id": eid})
                    # Update live current_svg reference for subsequent geometry/density checks. It holds the page as stored (the
                    # repaired group, sanitised, with the placeholder and the font), or a later modify cannot find the old group.
                    current_svg = (current_svg or "") + "\n" + stored.get(eid, ensure_group(args.get("svg_fragment", ""), eid)[0])
                    existing_element_ids.add(eid)
                    # Refresh page_state summary and spatial memory for subsequent calls
                    page_state["element_count"] = page_state.get("element_count", 0) + 1
                    page_state["occupied_regions"] = extract_element_bboxes(current_svg)
                    page_state["available_space"] = summarize_spatial_layout(page_state["occupied_regions"])
                    result_dict["occupied_regions"] = page_state["occupied_regions"]
                    result_dict["available_space"] = page_state["available_space"]
                else:
                    logger.warn(EngineEvent.DRAW_FAILED,
                                f"Element '{eid}' rejected: {result_dict.get('detail')}",
                                data={"element_id": eid})
                result = json.dumps(result_dict, ensure_ascii=False)      # real characters, not \uXXXX escapes: the lost-content note names ², → and ₂ and the model must SEE them, not an escape sequence

            elif fn_name == "modify_existing_element":
                result_dict = await _handle_modify_existing_element(
                    page_id=page_id,
                    page_status=page_status,
                    element_id=args.get("element_id", ""),
                    new_svg_fragment=args.get("new_svg_fragment", ""),
                    current_svg=current_svg,
                    existing_element_ids=existing_element_ids,
                    emit_fn=emit_fn,
                    persist_fn=persist_and_remember,
                    lost_note_counts=lost_notes,
                )
                if result_dict.get("status") == "ok":
                    old_frag = _extract_element_fragment(current_svg or "", args.get("element_id", ""))
                    if old_frag and current_svg:
                        current_svg = current_svg.replace(
                            old_frag, stored.get(args.get("element_id", ""), ensure_group(args.get("new_svg_fragment", ""), args.get("element_id", ""))[0]), 1)
                    page_state["occupied_regions"] = extract_element_bboxes(current_svg or "")
                    page_state["available_space"] = summarize_spatial_layout(page_state["occupied_regions"])
                    result_dict["occupied_regions"] = page_state["occupied_regions"]
                    result_dict["available_space"] = page_state["available_space"]
                result = json.dumps(result_dict, ensure_ascii=False)      # real characters, not \uXXXX escapes: the lost-content note names ², → and ₂ and the model must SEE them, not an escape sequence

            elif fn_name == "annotate_element":
                aid = args.get("annotation_id", "")
                logger.info(EngineEvent.ANNOTATE_STARTED,
                            f"Annotating element '{args.get('target_element_id')}' with style '{args.get('style')}' (id: {aid})",
                            data={"annotation_id": aid, "page_id": page_id})
                result_dict = await _handle_annotate_element(
                    notebook_id=notebook_id,
                    page_id=page_id,
                    page_status=page_status,
                    annotation_id=aid,
                    style=args.get("style", ""),
                    target_element_id=args.get("target_element_id", ""),
                    narration=args.get("narration", ""),
                    from_element_id=args.get("from_element_id"),
                    color=args.get("color"),
                    note=args.get("note"),
                    lifetime=args.get("lifetime"),
                    duration_ms=args.get("duration_ms"),
                    existing_element_ids=existing_element_ids,
                    emit_fn=emit_fn,
                    persist_fn=persist_fn,
                )
                if result_dict.get("status") == "ok":
                    logger.info(EngineEvent.ANNOTATE_COMPLETED, f"Annotation '{aid}' created OK",
                                data={"annotation_id": aid})
                else:
                    logger.warn(EngineEvent.ANNOTATE_FAILED,
                                f"Annotation '{aid}' rejected: {result_dict.get('detail')}",
                                data={"annotation_id": aid})
                result = json.dumps(result_dict)

            elif fn_name == "remove_annotation":
                aid = args.get("annotation_id", "")
                result_dict = await _handle_remove_annotation(
                    page_id=page_id,
                    page_status=page_status,
                    annotation_id=aid,
                    emit_fn=emit_fn,
                    persist_fn=persist_fn,
                )
                result = json.dumps(result_dict)

            else:
                result = json.dumps({"status": "error", "detail": f"Unknown tool: {fn_name}"})

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })
            try:
                status = json.loads(result).get("status")
            except (ValueError, AttributeError):
                status = None
            calls_made[fn_name] = calls_made.get(fn_name, 0) + 1
            if status == "ok" and fn_name in BOARD_TOOLS:
                board_changed = True
            if tool_log is not None:          # what the tutor did this turn, kept with its chat turn (chat_turns.tool_calls_made)
                tool_log.append({"tool": fn_name, "status": status, "iteration": iteration,
                                 "element_id": args.get("element_id") or args.get("annotation_id") or args.get("target_element_id")
                                 or (str(args.get("step")) if fn_name == "record_step" else None),
                                 **({"event": args.get("event") if args.get("event") in ("taught", "answered_right", "answered_wrong") else None,
                                     "page_id": page_id}    # the lesson it belongs to (backend current_lesson)
                                    if fn_name == "record_step" else {})})   # only a known value is stored, never the model's text

        messages.extend(tool_results)

    # Not a retry (a rejected drawing) and not a Retry turn in the product: the learner gets the canned reply below. The eval counts this event as a failed turn.
    logger.warn(EngineEvent.ITERATION_LIMIT_REACHED, "WhiteboardAuthor hit the iteration limit (20 model calls) without a final answer",
                data={"notebook_id": notebook_id, "page_id": page_id, "iterations": 20, "tool_calls": calls_made, "board_changed": board_changed})
    return "I've drawn quite a bit on this page. Let me know if you'd like to continue on a new page or go deeper on anything here."
