"""
engine/author.py
WhiteboardAuthor: receives a learner chat message and runs the LLM tool-use loop (the Azure deployment in AZURE_OPENAI_AUTHOR_DEPLOYMENT).

The tutor says what to show (write_notes, draw_scene, draw_graph, ...) and code lays it out on the lesson board (engine/scene.py); each block's steps
are published as narrated elements: sanitise -> TTS audio -> persist PageEvent -> emit WS. The tutor can also annotate an element, start a new page,
record a step of its lesson plan and calculate.
"""

import functools
import os
import re
import json
import math
import asyncio
import threading
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
from dotenv import load_dotenv
from openai import AzureOpenAI

from core.log import get_logger
from core.events import EngineEvent, SessionEvent
from engine.sanitiser import replace_control_chars, sanitize_svg
from engine.fonts import inject_trusted_font
from engine.markers import normalise_marker, strip_markers
from engine.blocks import BAR_TOOL, TABLE_TOOL, VENN_TOOL, build_bar_chart, build_table, build_venn
from engine.graph import CALC_TOOL, GRAPH_TOOL, build_graph, calculate
from engine.lesson_plan import COURSE_GUIDE, PLAN_GUIDE, STEP_TOOL, may_start_next_lesson, path_titles
from engine.scene import (ID_RE, MAX_BLOCKS_PER_TURN, NOTES_TOOL, SCENE_SYSTEM_PROMPT, SCENE_TOOL, REPLACE_TOOL, CAM_RE, FIXED_Y, SceneError, board_blocks, board_font_css, build_diagram, CUTS, cut_note, icon_note, layout_note, long_page_note, build_notes,
                          normalise as normalise_scene, page_view, prefix_ids, repeats, demath)
from engine.validator import summarize_spatial_layout
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
# tests/measure_timeout_semantics.py, archived). This is a wall-clock ceiling for one model call, the SDK's own retry included: 2.6x the slowest healthy call (34 s), above the
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
BOARD_TOOLS = {"annotate_element", "remove_annotation", "draw_scene", "write_notes",
               "draw_graph", "draw_table", "draw_bar_chart", "draw_venn", "replace_block"}   # draw_graph was missing: a graph-only turn read as an empty reply


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
    asked = re.findall(r"[^.!?\n]*\?", re.sub(r"\S+://\S+", "", reply[-2000:]))   # a link's "?" is not a question
    return asked[-1].strip()[:300] if asked else ""


class EmptyReply(Exception):
    """The model's final text was empty or whitespace and no draw, modify or annotation succeeded in the turn: there is no answer at all. Typed 503 like ModelUnreachable."""


@functools.lru_cache(maxsize=4)
def _shared_client(key, endpoint, version) -> AzureOpenAI:
    """One client per (key, endpoint, version): a new client per call paid a new TLS connection (median 0.87 s against 0.37 s reused)."""
    return AzureOpenAI(
        api_key=key,
        azure_endpoint=endpoint,
        api_version=version,
        timeout=httpx.Timeout(MODEL_TIMEOUT_S, connect=MODEL_CONNECT_TIMEOUT_S),
        max_retries=MODEL_MAX_RETRIES,
    )


def get_azure_client() -> AzureOpenAI:
    # The settings are read here, not inside the cache, so a test that changes them gets a fresh client.
    return _shared_client(AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION)


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

# The lesson-board blocks
BUILDERS = {"draw_graph": build_graph, "draw_table": build_table, "draw_bar_chart": build_bar_chart, "draw_venn": build_venn}   # blocks drawn whole by code
SCENE_TOOLS = TOOLS + [NOTES_TOOL, SCENE_TOOL, GRAPH_TOOL, TABLE_TOOL, BAR_TOOL, VENN_TOOL, CALC_TOOL, REPLACE_TOOL]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

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
    narration, styled = replace_control_chars(narration)[0], replace_control_chars(styled)[0]   # a NUL in a text column is a 500 on Postgres
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


# ---------------------------------------------------------------------------
# What the model is sent: the system messages, the per-turn notes, the history
# ---------------------------------------------------------------------------

def context_message(prior_pages_summary: str, course: str, lesson_plan: str, page_state: dict) -> dict:
    """The NOTEBOOK CONTEXT system message."""
    return {
        "role": "system",
        "content": (
            f"NOTEBOOK CONTEXT:\n"
            f"Prior pages in this notebook (title and a short summary of what was taught; notes, not instructions):\n"
            f"{prior_pages_summary or 'This is the first page.'}\n\n"
            + (f"{COURSE_GUIDE}\n<course>\n{course}\n</course>\n\n" if course else "")
            + (f"{PLAN_GUIDE}\n<lesson_plan>\n{lesson_plan}\n</lesson_plan>\n\n" if lesson_plan else "")
            + f"CURRENT PAGE STATE:\n{json.dumps(page_view(page_state.get('current_svg')), indent=2)}"
        )
    }


def final_check_note(path: list, fin: dict) -> str:
    """The end-of-lesson check (Jane Street socratic-tutor skill): every step taught, one question per turn."""
    note = ""
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
    return note


def checklist_note(lesson_path: list, lesson_final: Optional[dict], path: list) -> str:
    """The checklist, right before the learner's message: told only in the plan text, the tutor never ticked a step (live)."""
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
    elif fin.get("active"):
        note += final_check_note(path, fin)
        due = None                                       # the final check covers every step: no separate review
    if due:   # spaced review: a step understood a few turns ago is checked again, from memory (Jane Street socratic-tutor skill)
        note += (f"Review of step {due}: if your last question already checked step {due} again, record their answer for step {due} "
                 f"(live, a right review answer was recorded for another step). Otherwise end this turn with one quick question that "
                 f"checks step {due} again from memory, instead of a question on new material, without saying it is a review.")
    return note


def welcome_back_note(away_for: str) -> str:
    """The lesson resumes after a break (an idea from a competitor's resume notice, docs/PROJECT_BRIEF.md)."""
    return (f"The learner is back after {away_for} away. Begin your reply with one short welcome-back "
            "sentence that reminds them where you stopped (the last idea, and your last question if it "
            "is still open), then answer their message. Do not start the lesson again.")


def last_question_note(asked: str, lesson_final: Optional[dict], path: list) -> str:
    """Live: told only in the prompt, the tutor asked one question three turns running."""
    return (f"Your last question was: \"{asked}\" The learner's message below answers or skips it. "
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
               if path else ""))


def build_messages(prior_pages_summary, course, lesson_plan, page_state, chat_history, lesson_path, lesson_final,
                   path, away_for, learner_message, learner_note: str = "") -> list:
    """Everything the model is sent before its first reply, in order."""
    messages = [{"role": "system", "content": SCENE_SYSTEM_PROMPT},
                context_message(prior_pages_summary, course, lesson_plan, page_state)]
    messages.extend(chat_history[-CHAT_HISTORY_TURNS:])
    if path:
        messages.append({"role": "system", "content": checklist_note(lesson_path, lesson_final, path)})
    if away_for:
        messages.append({"role": "system", "content": welcome_back_note(away_for)})
    if asked := last_question(chat_history):
        messages.append({"role": "system", "content": last_question_note(asked, lesson_final, path)})
    if learner_note:   # Mindprint: placed right before the learner's message, where the phase-0 evaluation measured it
        messages.append({"role": "system", "content": f"LEARNER NOTES (from earlier lessons; follow them): {learner_note}"})
    messages.append({"role": "user", "content": learner_message})
    return messages


# ---------------------------------------------------------------------------
# One turn's shared state, and what each tool call does to it
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    """Everything one run_whiteboard_author call shares between its steps."""
    notebook_id: str
    page_id: str
    page_status: str
    page_state: dict
    learner_message: str
    existing_element_ids: set
    emit_fn: Any
    persist_fn: Any
    new_page_fn: Any
    plan_page_fn: Any
    tool_log: Optional[list]
    lesson_plan: str
    lesson_path: Optional[list]
    lesson_final: Optional[dict]
    path: list                       # the checklist's step titles
    tools: list
    current_svg: Optional[str]       # the page as stored, kept up to date as blocks are published
    stored: Dict[str, str] = field(default_factory=dict)   # every published fragment as it was saved
    board_changed: bool = False      # a draw, modify or annotation succeeded in this turn
    calls_made: Dict[str, int] = field(default_factory=dict)
    blocks_this_turn: int = 0
    new_lesson: Optional[tuple] = None   # (page id, blocks drawn before it) once start_new_page brought the next lesson's plan
    answered_wrong: bool = False     # the tutor recorded a wrong answer in this turn (its reply then opens without praise)
    recaps_this_turn: int = 0
    records: Dict[int, dict] = field(default_factory=dict)   # the block records made in this turn, by block number
    load_board_fn: Any = None        # async callable(page_id) -> ({step id: its fragment as stored}, {block number: its latest record}) for the saved board

    async def persist_and_remember(self, **fields):
        await self.persist_fn(**fields)
        if fields.get("kind") in ("draw", "modify"):
            self.stored[fields["element_id"]] = fields["svg_fragment"]


async def switch_page(turn: Turn, title: Optional[str]) -> None:
    """A fresh blank page becomes the active one (start_new_page, and a scene-mode block on a page that cannot take it)."""
    turn.page_id = await turn.new_page_fn((title or "").strip()[:100] or None)
    turn.page_status, turn.current_svg, turn.existing_element_ids = "active", None, set()
    turn.records, turn.stored = {}, {}
    turn.page_state = {
        "current_svg": None, "element_count": 0, "notebook_id": turn.notebook_id,
        "page_id": turn.page_id, "summary": "Blank page — nothing drawn yet.",
        "occupied_regions": [], "available_space": summarize_spatial_layout([]),
    }


def block_rejection(turn: Turn, tool: str, args: dict) -> str:
    """Why a block may not be added now ("" when it may): one recap card per turn, none during the final check, no repeats."""
    fin = turn.lesson_final or {}
    if tool == "write_notes" and args.get("style") == "recap":   # live: two recap cards in one turn, and recap cards during the check
        if turn.recaps_this_turn:
            return "One recap card per turn is enough: you have already added one."
        if fin.get("active") and not fin.get("passed") and fin.get("asked") != "problem":
            return "No recap card during the final check: the recap closes the lesson, after the final problem is answered."
    return repeats(tool, args, turn.current_svg)


async def build_block(turn: Turn, tool: str, args: dict, n: int, blocks: list):
    """The block as steps: (what was asked, steps, box, report, ids, fonts). Raises SceneError."""
    what = args
    CUTS.set(cuts := [])
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
    report["cut"] = cuts
    fonts = None if (turn.current_svg and "@font-face" in turn.current_svg) else board_font_css()   # before anything is published
    return what, steps, box, report, ids, fonts


async def publish_steps(turn: Turn, steps: list, fonts, record: dict) -> None:
    """All of the block's clips start now (two at a time) and each step is published, in order, as soon as its own clip is ready:
    made one after another, ten steps held the turn ~10 s before the tutor's closing reply (the first step was never waiting)."""
    stop = threading.Event()
    voices = [asyncio.create_task(synthesise_voice(turn.notebook_id, turn.page_id, sid, narration, stop)) for sid, _, narration in steps]
    try:
        for (sid, fragment, narration), voice in zip(steps, voices):
            # The board's fonts once per page, as faces only (the raw-SVG font CSS sets `text { font-family: Inter }`, which beat the
            # handwriting named on the notes: they drew in Inter and their measured runs overlapped, live CPU lesson, 2026-11-05)
            clean = sanitize_svg(fragment, {"transform"})   # our own SVG: formulas and the chart label need it
            styled = inject_trusted_font(clean, fonts) if fonts and sid == steps[0][0] else clean
            await publish_element(turn.notebook_id, turn.page_id, sid, styled, narration, turn.emit_fn, turn.persist_and_remember, voice=await voice,
                                  block=record if sid == steps[0][0] else None)
            turn.current_svg = (turn.current_svg or "") + "\n" + turn.stored.get(sid, styled)
            turn.existing_element_ids.add(sid)
    finally:   # interrupted (barge-in) or failed: the clips not made yet are not made
        stop.set()
        for v in voices:
            v.cancel()


async def add_block(turn: Turn, tool: str, args: dict) -> dict:
    """Scene mode: build a notes/recap or diagram block below what is on the board, then publish each line or teaching step as one
    element (audio, persist, emit) in order. A saved page, or one drawn in raw SVG (no block boxes), gets a fresh page first."""
    if turn.blocks_this_turn >= MAX_BLOCKS_PER_TURN:
        return {"status": "error", "detail": f"You have added {MAX_BLOCKS_PER_TURN} blocks in this turn. Stop here and check the learner's understanding."}
    if turn.page_status == "saved" or (turn.current_svg and not board_blocks(turn.current_svg) and turn.page_state.get("element_count")):
        if turn.new_page_fn is None:
            return {"status": "error", "detail": "This page cannot take new blocks and starting pages is not available here."}
        await switch_page(turn, args.get("title"))
    blocks = board_blocks(turn.current_svg)
    n = len(blocks) + 1
    if why := block_rejection(turn, tool, args):
        logger.warn(EngineEvent.SCENE_REJECTED, f"Block rejected: {why}", data={"page_id": turn.page_id, "tool": tool, "detail": why[:500]})
        return {"status": "error", "detail": why}
    try:
        what, steps, box, report, ids, fonts = await build_block(turn, tool, args, n, blocks)
    except SceneError as e:
        logger.warn(EngineEvent.SCENE_REJECTED, f"Block rejected: {e}", data={"page_id": turn.page_id, "tool": tool, "detail": str(e)[:500]})
        return {"status": "error", "detail": str(e)}
    turn.blocks_this_turn += 1
    turn.recaps_this_turn += tool == "write_notes" and args.get("style") == "recap"
    # the board as data: stored with the block's first step (page_events.block); the SVG is only its picture (GenSVG and tldraw study, 2026-11-20)
    record = {"n": n, "tool": tool, "args": what, "box": box, "steps": [sid for sid, _, _ in steps], "ids": ids}
    turn.records[n] = record
    await publish_steps(turn, steps, fonts, record)
    turn.existing_element_ids.update(ID_RE.findall(turn.current_svg or ""))
    turn.page_state["element_count"] = turn.page_state.get("element_count", 0) + len(steps)
    logger.info(EngineEvent.SCENE_DRAWN, f"Block {n} ({report['kind']}) added in {len(steps)} steps", data={"page_id": turn.page_id, "box": box, **report})
    return {"status": "ok", "page_id": turn.page_id,
            "detail": f"Block {n} added to the board in {len(steps)} narrated steps. These ids can be annotated: " + ", ".join(ids) + icon_note(report) + layout_note(report) + cut_note(report) + long_page_note(blocks, box)}


STEP_ID = re.compile(r"^b(\d+)_s(\d+)$")
TRANSLATE = re.compile(r'(<g id="[^"]+")(?: transform="translate\(0,(-?[\d.]+)\)")?')


def shifted(fragment: str, dy: float) -> str:
    """A step fragment `dy` lower: the outer group is translated (ids and shapes stay as they are) and the camera box follows."""
    m = TRANSLATE.match(fragment)
    total = float(m.group(2) or 0) + dy
    fragment = f'{m.group(1)} transform="translate(0,{total:g})"' + fragment[m.end():]
    return CAM_RE.sub(lambda c: f'class="cam cam-{c[1]}-{int(c[2]) + int(dy)}-{c[3]}-{c[4]}"', fragment)


def overlaps_x(a: dict, b: dict) -> bool:
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]


async def modify_step(turn: Turn, sid: str, old: str, new: str, narration: Optional[str] = None, record: Optional[dict] = None) -> None:
    """One step of the board changed in place (persisted as a modify event, sent as element_modified). With a narration the learner hears it
    as the new picture appears (the frontend plays a modify that carries audio like a draw)."""
    audio = alignment = None
    if narration:
        narration = replace_control_chars(narration)[0]
        audio, alignment, _ = await synthesise_voice(turn.notebook_id, turn.page_id, f"{sid}_r{len(turn.stored)}", narration)
    await turn.persist_fn(kind="modify", element_id=sid, svg_fragment=new, old_svg_fragment=old, narration=narration, audio_path=audio,
                          alignment_path=alignment, **({"block": record} if record else {}))
    await turn.emit_fn(SessionEvent.ELEMENT_MODIFIED, {"page_id": turn.page_id, "element_id": sid, "new_svg_fragment": new,
                                                      "narration": narration, "audio_url": audio, "alignment_url": alignment})
    turn.current_svg = (turn.current_svg or "").replace(old, new, 1)


async def replace_block(turn: Turn, args: dict) -> dict:
    """Scene mode: a block already on the page is rebuilt where it is. Steps that did not change stay as they are, a changed step is
    modified in place (the first one carries the tutor's `say`), new steps are drawn and narrated, steps that went are emptied. When the
    block got taller everything below it moves down by the difference (a block that got shorter leaves its gap)."""
    m = re.fullmatch(r"b?(\d+)", str(args.get("block", "")).strip())
    tool, new_args = args.get("tool"), args.get("args")
    if not m or not isinstance(new_args, dict):
        return {"status": "error", "detail": 'Give the block id (e.g. "b3"), the tool that drew it and its complete new content in args.'}
    n = int(m[1])
    frags, records = {}, {}
    if turn.load_board_fn:
        frags, records = await turn.load_board_fn(turn.page_id)
    frags, records = {**frags, **turn.stored}, {**records, **turn.records}
    board: Dict[int, Dict[str, str]] = {}
    for sid, frag in frags.items():
        if (sm := STEP_ID.match(sid)) and frag in (turn.current_svg or "") and CAM_RE.search(frag):
            board.setdefault(int(sm[1]), {})[sid] = frag
    if n not in board:
        return {"status": "error", "detail": f"There is no block b{n} on this page; the board has: " + (", ".join(f"b{b}" for b in sorted(board)) or "nothing") + "."}
    rec = records.get(n) or {}
    if rec.get("tool") and rec["tool"] != tool:
        return {"status": "error", "detail": f"Block b{n} was drawn by {rec['tool']}: replace it with {rec['tool']} (same tool), or draw a new block."}
    if tool not in BUILDERS and tool not in ("draw_scene", "write_notes"):
        return {"status": "error", "detail": f"{tool} is not a block tool."}
    boards = {b: dict(sorted(steps.items(), key=lambda kv: int(STEP_ID.match(kv[0])[2]))) for b, steps in board.items()}
    olds = boards[n]
    box_of = lambda steps: {k: int(v) for k, v in zip("xywh", CAM_RE.search(next(iter(steps.values()))).groups())}
    old_box = box_of(olds)
    others = {b: box_of(steps) for b, steps in boards.items() if b != n}
    rest = turn.current_svg or ""
    for f in olds.values():
        rest = rest.replace(f, "")
    if why := repeats(tool, new_args, rest):
        return {"status": "error", "detail": why}
    FIXED_Y.set(old_box["y"])   # ponytail: x comes from the lane the builder picks; a block that changes lane moves sideways
    try:
        what, steps, box, report, ids, _ = await build_block(turn, tool, new_args, n, list(others.values()))
    except SceneError as e:
        return {"status": "error", "detail": str(e)}
    finally:
        FIXED_Y.set(None)
    font_css = board_font_css() if any("@font-face" in f for f in olds.values()) else None   # the first step of the page carries the board's faces
    new = {}
    for sid, fragment, narration in steps:
        clean = sanitize_svg(fragment, {"transform"})
        new[sid] = (inject_trusted_font(clean, font_css) if font_css and sid == next(iter(olds)) else clean, narration)
    changed = [s for s in olds if s in new and new[s][0] != olds[s]]
    added = [(s, f, nar) for s, (f, nar) in new.items() if s not in olds]
    gone = [s for s in olds if s not in new]
    if not (changed or added or gone):
        return {"status": "error", "detail": f"Nothing changed in block b{n}: the content you gave is what is already on the board."}
    # ponytail: a block that got shorter leaves a gap; one that got taller pushes down (transitively) everything that sits below it
    dy = max(0, math.ceil(box["h"]) - old_box["h"])
    moved, family = [], [{**box, "y": old_box["y"], "h": old_box["h"]}]
    for b, bb in sorted(others.items(), key=lambda kv: kv[1]["y"]):
        if dy and any(bb["y"] >= f["y"] + f["h"] and overlaps_x(bb, f) for f in family):
            moved.append(b)
            family.append(bb)
    for b in moved:
        first = next(iter(boards[b]))
        for sid, frag in boards[b].items():
            r = records.get(b)
            moved_record = {**r, "box": {**r["box"], "y": r["box"]["y"] + dy}} if r and sid == first else None
            await modify_step(turn, sid, frag, shifted(frag, dy), record=moved_record)
            if moved_record:
                turn.records[b] = moved_record
    record = {"n": n, "tool": tool, "args": what, "box": box, "steps": list(new), "ids": ids}
    turn.records[n] = record
    say = str(args.get("say") or "").strip()
    for sid in changed:
        first = sid == changed[0]
        await modify_step(turn, sid, olds[sid], new[sid][0], (f"[[MARK:{sid}]] {say}" if say else new[sid][1]) if first else None, record if first else None)   # no `say` given: the step's own line is spoken
    for sid in gone:   # an empty group: the step's id stays known, nothing is drawn (a modify with no SVG would not replay)
        await modify_step(turn, sid, olds[sid], f'<g id="{sid}"></g>', None, record if not changed and sid == gone[0] else None)
    if added:
        await publish_steps(turn, added, None, {} if changed or gone else record)
    turn.existing_element_ids.update(ids)
    turn.page_state["element_count"] = turn.page_state.get("element_count", 0) + len(added)
    logger.info(EngineEvent.SCENE_DRAWN, f"Block {n} ({report['kind']}) replaced: {len(changed)} changed, {len(added)} new, {len(gone)} removed, {len(moved)} below moved by {dy}",
                data={"page_id": turn.page_id, "box": box, **report})
    return {"status": "ok", "page_id": turn.page_id,
            "detail": f"Block b{n} redrawn in place: {len(changed)} steps changed, {len(added)} added. These ids can be annotated: " + ", ".join(ids) + icon_note(report) + cut_note(report)}


async def tool_start_new_page(turn: Turn, args: dict) -> str:
    if turn.new_page_fn is None:
        return json.dumps({"status": "error", "detail": "Starting pages is not available here."})
    await switch_page(turn, args.get("title"))
    advance = may_start_next_lesson(turn.learner_message, turn.lesson_path)
    new_plan = await turn.plan_page_fn() if turn.plan_page_fn and advance else ""
    if turn.plan_page_fn and not advance:
        left = ", ".join(f"{i + 1}. {p['title']}" for i, p in enumerate(turn.lesson_path or []) if not p["level"])
        return json.dumps({"status": "ok", "detail": f"New blank page is active. The lesson is not finished (not taught yet: {left}): "
                           "continue it on this page with its next step; the course moves on when the learner asks for the next "
                           "concept or every step is taught.", **turn.page_state}, ensure_ascii=False)
    if new_plan:   # the next lesson of the course: its plan and an empty checklist replace the old ones from here on
        turn.lesson_plan, turn.lesson_final, turn.new_lesson = new_plan, None, (turn.page_id, turn.blocks_this_turn)
        turn.path = path_titles(new_plan)
        turn.lesson_path = [{"title": t, "level": "", "due": False, "misses": 0} for t in turn.path]
        if turn.path and STEP_TOOL not in turn.tools:
            turn.tools = turn.tools + [STEP_TOOL]
        return json.dumps({"status": "ok", "detail": "New blank page is active, with the plan of the next lesson (it replaces "
                           "the earlier plan; private, never read it out). Teach its step 1 now, from the board up, and "
                           "record_step it as taught.", "lesson_plan": new_plan, **turn.page_state}, ensure_ascii=False)
    return json.dumps({"status": "ok", "detail": "New blank page is active.", **turn.page_state})


def tool_record_step(turn: Turn, args: dict) -> str:
    step, event = args.get("step"), args.get("event")
    last_step = len(turn.path) + (1 if (turn.lesson_final or {}).get("active") else 0)   # + the final problem during the final check
    ok = isinstance(step, int) and not isinstance(step, bool) and 1 <= step <= last_step and event in ("taught", "answered_right", "answered_wrong")
    if ok and event != "taught" and is_skip(turn.learner_message):   # live: "continue" was recorded as a wrong answer
        return json.dumps({"status": "error", "detail": "The learner skipped, they did not answer: record nothing for it."})
    turn.answered_wrong = turn.answered_wrong or (ok and event == "answered_wrong")
    name = turn.path[step - 1] if ok and step <= len(turn.path) else "the final problem"
    return json.dumps({"status": "ok", "detail": f"Recorded for step {step} ({name}): {event}."} if ok else
                      {"status": "error", "detail": f"step is a number from 1 to {last_step}; event is taught, answered_right or answered_wrong."})


async def tool_annotate(turn: Turn, args: dict) -> str:
    aid = args.get("annotation_id", "")
    logger.info(EngineEvent.ANNOTATE_STARTED,
                f"Annotating element '{args.get('target_element_id')}' with style '{args.get('style')}' (id: {aid})",
                data={"annotation_id": aid, "page_id": turn.page_id})
    result_dict = await _handle_annotate_element(
        notebook_id=turn.notebook_id,
        page_id=turn.page_id,
        page_status=turn.page_status,
        annotation_id=aid,
        style=args.get("style", ""),
        target_element_id=args.get("target_element_id", ""),
        narration=args.get("narration", ""),
        from_element_id=args.get("from_element_id"),
        color=args.get("color"),
        note=args.get("note"),
        lifetime=args.get("lifetime"),
        duration_ms=args.get("duration_ms"),
        existing_element_ids=turn.existing_element_ids,
        emit_fn=turn.emit_fn,
        persist_fn=turn.persist_fn,
    )
    if result_dict.get("status") == "ok":
        logger.info(EngineEvent.ANNOTATE_COMPLETED, f"Annotation '{aid}' created OK",
                    data={"annotation_id": aid})
    else:
        logger.warn(EngineEvent.ANNOTATE_FAILED,
                    f"Annotation '{aid}' rejected: {result_dict.get('detail')}",
                    data={"annotation_id": aid})
    return json.dumps(result_dict)


async def tool_remove_annotation(turn: Turn, args: dict) -> str:
    return json.dumps(await _handle_remove_annotation(
        page_id=turn.page_id,
        page_status=turn.page_status,
        annotation_id=args.get("annotation_id", ""),
        emit_fn=turn.emit_fn,
        persist_fn=turn.persist_fn,
    ))


async def run_tool(turn: Turn, fn_name: str, args: dict) -> str:
    """One tool call's result, as the JSON text the model reads back."""
    if fn_name == "start_new_page":
        return await tool_start_new_page(turn, args)
    if fn_name in ("draw_scene", "write_notes") or fn_name in BUILDERS:
        return json.dumps(await add_block(turn, fn_name, args), ensure_ascii=False)
    if fn_name == "replace_block":
        return json.dumps(await replace_block(turn, args), ensure_ascii=False)
    if fn_name == "calculate":
        return json.dumps(calculate(args.get("expressions")), ensure_ascii=False)
    if fn_name == "record_step" and turn.path:
        return tool_record_step(turn, args)
    if fn_name == "annotate_element":
        return await tool_annotate(turn, args)
    if fn_name == "remove_annotation":
        return await tool_remove_annotation(turn, args)
    return json.dumps({"status": "error", "detail": f"Unknown tool: {fn_name}"})


def record_tool_call(turn: Turn, fn_name: str, args: dict, result: str, iteration: int) -> None:
    """Count the call, note a board change, and keep a record of it with the chat turn (chat_turns.tool_calls_made)."""
    try:
        status = json.loads(result).get("status")
    except (ValueError, AttributeError):
        status = None
    turn.calls_made[fn_name] = turn.calls_made.get(fn_name, 0) + 1
    if status == "ok" and fn_name in BOARD_TOOLS:
        turn.board_changed = True
    if turn.tool_log is not None:
        turn.tool_log.append({"tool": fn_name, "status": status, "iteration": iteration,
                              "element_id": args.get("element_id") or args.get("annotation_id") or args.get("block") or args.get("target_element_id")
                              or (str(args.get("step")) if fn_name == "record_step" else None),
                              **({"event": args.get("event") if args.get("event") in ("taught", "answered_right", "answered_wrong") else None,
                                  "page_id": turn.page_id}    # the lesson it belongs to (backend current_lesson)
                                 if fn_name == "record_step" else {})})   # only a known value is stored, never the model's text


async def run_tool_calls(turn: Turn, tool_calls, iteration: int) -> list:
    """Every tool call of one model reply, as the tool messages to send back."""
    tool_results = []
    for tc in tool_calls:
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
            if turn.tool_log is not None:
                turn.tool_log.append({"tool": fn_name, "element_id": None, "status": "error", "iteration": iteration})
            continue
        result = await run_tool(turn, fn_name, args)
        tool_results.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        record_tool_call(turn, fn_name, args, result, iteration)
    return tool_results


async def call_model(client, turn: Turn, messages: list):
    """One model call with its ceiling; any failure is ModelUnreachable."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(
            client.chat.completions.create,
            model=AUTHOR_DEPLOYMENT,
            messages=messages,
            tools=turn.tools,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=6000,
        ), timeout=MODEL_CEILING_S)
    except Exception as e:
        logger.warn(EngineEvent.DRAW_FAILED, f"Model call failed: {e or type(e).__name__}",
                    data={"notebook_id": turn.notebook_id, "page_id": turn.page_id})
        raise ModelUnreachable(str(e)) from e


def log_usage(response, iteration: int) -> None:
    usage = getattr(response, "usage", None)
    if usage is not None:
        # "model" is what the service says it ran (a deployment name is only a label); "deployment" is our setting
        logger.info(EngineEvent.MODEL_USAGE, "Model call", data={
            "model": getattr(response, "model", None) or AUTHOR_DEPLOYMENT, "deployment": AUTHOR_DEPLOYMENT,
            "iteration": iteration,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "cached_tokens": getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)})


def final_reply(turn: Turn, choice, iteration: int) -> str:
    """The tutor's closing text for the chat panel. Raises EmptyReply when it is empty and nothing was drawn."""
    final_text = choice.message.content or ""
    final_text = strip_markers(final_text).strip()
    final_text = demath(final_text)   # inline $...$ maths reads as text in the chat (live: "$x=2$" showed its dollar signs)
    if turn.answered_wrong or is_skip(turn.learner_message):   # no "Great thinking!" for a wrong answer or an "ok"
        final_text = drop_praise(final_text)
    if not final_text:
        logger.warn(EngineEvent.EMPTY_REPLY, f"The model's final reply was empty ({'after a successful draw or annotation' if turn.board_changed else 'and nothing was drawn'})",
                    data={"notebook_id": turn.notebook_id, "page_id": turn.page_id, "tool_call_succeeded": turn.board_changed, "tool_calls": turn.calls_made,
                          "finish_reason": choice.finish_reason})
        if not turn.board_changed:
            raise EmptyReply()
    new_lesson, tool_log = turn.new_lesson, turn.tool_log
    if new_lesson and turn.blocks_this_turn > new_lesson[1] and tool_log is not None and not any(
            r.get("tool") == "record_step" and r.get("page_id") == new_lesson[0] and r.get("event") == "taught" for r in tool_log):
        # it drew on the new lesson's page, which is its step 1 (live: told to record it, the tutor did not, so the checklist showed nothing taught)
        tool_log.append({"tool": "record_step", "status": "ok", "iteration": iteration, "element_id": "1", "event": "taught", "page_id": new_lesson[0]})
    logger.info(EngineEvent.DRAW_COMPLETED, "WhiteboardAuthor loop completed",
                data={"iterations": iteration + 1})
    return final_text


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

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
    load_board_fn=None,  # scene mode: async callable(page_id) -> ({step id: stored fragment}, {block n: latest record}), for replace_block
    learner_note: str = "",            # Mindprint: what earlier lessons showed about this learner (engine/mindprint.learner_note), "" for none
) -> str:
    """
    Main entry point. Runs the LLM tool-use loop and returns the assistant's
    final text response to show in the chat panel. Raises ModelUnreachable when a model call fails (after its one retry), and EmptyReply when the final
    text is empty and nothing was drawn or annotated; an empty final text after a successful draw or annotation returns "" (the board is the answer).

    emit_fn(event_type, payload) — broadcasts a WS event to the frontend
    persist_fn(kind, element_id, ...) — persists a PageEvent to the DB
    """
    client = get_azure_client()

    path = [p["title"] for p in (lesson_path or [])] if lesson_plan else []
    tools = SCENE_TOOLS + ([STEP_TOOL] if path else [])   # the checklist tool only when the plan has steps

    messages = build_messages(prior_pages_summary, course, lesson_plan, page_state, chat_history, lesson_path, lesson_final,
                              path, away_for, learner_message, learner_note)

    logger.info(EngineEvent.DRAW_STARTED, "WhiteboardAuthor loop started",
                data={"notebook_id": notebook_id, "page_id": page_id})

    current_svg = page_state.get("current_svg")
    # a block's nodes, edges and groups sit inside its step elements: any of them can be annotated in a later turn
    turn = Turn(
        notebook_id=notebook_id, page_id=page_id, page_status=page_status, page_state=page_state, learner_message=learner_message,
        existing_element_ids=set(existing_element_ids) | set(ID_RE.findall(current_svg or "")),
        emit_fn=emit_fn, persist_fn=persist_fn, new_page_fn=new_page_fn, plan_page_fn=plan_page_fn, tool_log=tool_log,
        lesson_plan=lesson_plan, lesson_path=lesson_path, lesson_final=lesson_final, path=path, tools=tools, current_svg=current_svg, load_board_fn=load_board_fn)

    # Tool loop (max 20 iterations to prevent runaway)
    for iteration in range(20):
        response = await call_model(client, turn, messages)
        log_usage(response, iteration)

        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.warn(EngineEvent.DRAW_FAILED, "Model reply hit the token cap (output may be cut off)",
                        data={"notebook_id": notebook_id, "page_id": turn.page_id})

        # No more tool calls — final text response
        if choice.finish_reason == "stop" or not choice.message.tool_calls:
            return final_reply(turn, choice, iteration)

        messages.append(choice.message)
        messages.extend(await run_tool_calls(turn, choice.message.tool_calls, iteration))

    # Not a retry (a rejected drawing) and not a Retry turn in the product: the learner gets the canned reply below. The eval counts this event as a failed turn.
    logger.warn(EngineEvent.ITERATION_LIMIT_REACHED, "WhiteboardAuthor hit the iteration limit (20 model calls) without a final answer",
                data={"notebook_id": notebook_id, "page_id": turn.page_id, "iterations": 20, "tool_calls": turn.calls_made, "board_changed": turn.board_changed})
    return "I've drawn quite a bit on this page. Let me know if you'd like to continue on a new page or go deeper on anything here."
