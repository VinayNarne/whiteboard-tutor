"""
engine/voice.py
ElevenLabs TTS + word-alignment pipeline for Learning Platform.

Extracted from the webinar project's engine/author.py.
Each draw_new_element call that has narration goes through:
  generate_narration_audio(narration, audio_path, alignment_path)
  -> (audio_duration_seconds, char_count, alignment_dict)

The alignment.json produced here is the same format as the webinar project,
and the frontend useAnnotationOverlay hook reads it the same way.

INVARIANT: the text sent to ElevenLabs must be EXACTLY the text used for alignment,
with no modification in between. (Proven on both standard and streaming endpoints
with numbers, percentages, and years — webinar SAD §7.5.)
"""

import os
import re
import io
import json
import wave
import base64
import time
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

try:
    from pydub import AudioSegment
    _PYDUB_AVAILABLE = True
except ImportError:
    _PYDUB_AVAILABLE = False

from engine.markers import MARKER_LIKE, _token_id

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel default


# ---------------------------------------------------------------------------
# Marker extraction (no [[MARK:...]] syntax in LP narrations — narration is
# plain text per element; kept for forward compat if markers are added later)
# ---------------------------------------------------------------------------

def extract_markers_and_clean_text(narration: str):
    """
    Strips [[MARK:id]] markers from narration for TTS, returning:
      (clean_text, [(marker_id, char_index_in_clean_text), ...])
    If no markers, returns (narration, []).
    """
    markers = []
    clean_parts = []
    last_idx = 0
    clean_len = 0
    for match in MARKER_LIKE.finditer(narration):
        prefix = narration[last_idx:match.start()]
        clean_parts.append(prefix)
        clean_len += len(prefix)
        markers.append((_token_id(match.group(0)), clean_len))
        last_idx = match.end()
    clean_parts.append(narration[last_idx:])
    return "".join(clean_parts), markers


# ---------------------------------------------------------------------------
# Fallback: silent MP3 with synthetic character timings (when EL is offline)
# ---------------------------------------------------------------------------
FALLBACK_TAIL_SECONDS = 0.5   # silence after the last word, so the clip does not end on the final character's timing

def _generate_fallback_speech_alignment(clean_text: str):
    """
    Generates a silent MP3 + synthetic character timings at ~150 wpm.
    Used when ElevenLabs is offline or quota exceeded.
    """
    words = clean_text.split()
    duration = max(3.0, len(words) / 2.5)
    chars = list(clean_text)
    total_chars = max(1, len(chars))
    char_duration = duration / total_chars

    alignment = {
        "characters": chars,
        "character_start_times_seconds": [round(i * char_duration, 3) for i in range(total_chars)],
        "character_end_times_seconds": [round((i + 1) * char_duration, 3) for i in range(total_chars)]
    }

    buf = io.BytesIO()
    sample_rate = 16000
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b'\x00\x00' * int((duration + FALLBACK_TAIL_SECONDS) * sample_rate))
    buf.seek(0)

    if _PYDUB_AVAILABLE:
        try:
            mp3_buf = io.BytesIO()
            AudioSegment.from_wav(buf).export(mp3_buf, format="mp3")
            audio_bytes = mp3_buf.getvalue()
        except Exception:
            audio_bytes = buf.getvalue()
    else:
        audio_bytes = buf.getvalue()

    return audio_bytes, alignment, duration, True


# ---------------------------------------------------------------------------
# ElevenLabs call
# ---------------------------------------------------------------------------

def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        pass


def _call_elevenlabs_tts(clean_text: str):
    """
    Calls ElevenLabs /with-timestamps endpoint.
    Returns (audio_bytes, raw_alignment, duration_secs, is_fallback).
    Falls back to synthetic on any error.
    """
    if os.getenv("LP_VOICE") == "0":                 # voice off (lesson evals): an empty key is not enough, it is reloaded below
        return _generate_fallback_speech_alignment(clean_text)
    api_key = os.getenv("ELEVENLABS_API_KEY") or ELEVENLABS_API_KEY
    if not api_key:
        load_dotenv(override=True)
        api_key = os.getenv("ELEVENLABS_API_KEY")

    if not api_key:
        return _generate_fallback_speech_alignment(clean_text)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {"text": clean_text, "model_id": "eleven_turbo_v2_5"}

    t0 = time.time()
    try:
        import requests
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 429:  # rate limited: one short retry before falling back to silence
            time.sleep(1.5)
            res = requests.post(url, headers=headers, json=payload, timeout=25)
        dur = time.time() - t0
        if res.status_code == 200:
            data = res.json()
            audio_bytes = base64.b64decode(data["audio_base64"])
            raw_align = data.get("alignment") or {}
            return audio_bytes, raw_align, dur, False
        else:
            _safe_print(f"[Voice] ElevenLabs TTS failed ({res.status_code}): {res.text} - using fallback")
    except Exception as exc:
        _safe_print(f"[Voice] ElevenLabs request error: {exc} - using fallback")

    return _generate_fallback_speech_alignment(clean_text)


# ---------------------------------------------------------------------------
# Marker timing calculation
# ---------------------------------------------------------------------------

def _calculate_marker_timings(
    markers: list,
    alignment: dict,
    clean_text: str = "",
    default_marker_id: Optional[str] = None
):
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    if not chars or not starts:
        return [{"id": m[0], "time": 0.5 * (i + 1)} for i, m in enumerate(markers)], 5.0

    audio_duration = ends[-1] if ends else 0.0
    effective_markers = list(markers)

    if not effective_markers and default_marker_id:
        # Search for words from default_marker_id in clean_text
        keywords = [k for k in re.split(r'[^a-zA-Z0-9]+', default_marker_id) if len(k) >= 3]
        target_idx = None
        lower_text = clean_text.lower()
        for kw in keywords:
            pos = lower_text.find(kw.lower())
            if pos != -1:
                target_idx = pos
                break
        if target_idx is None:
            target_idx = 0
        effective_markers.append((default_marker_id, target_idx))

    timings = []
    for marker_id, clean_idx in effective_markers:
        idx = min(clean_idx, len(chars) - 1)
        while idx < len(chars) - 1 and chars[idx] in (' ', '\n', '\t', ',', '.', ';'):
            idx += 1
        word_start = idx
        while word_start > 0 and chars[word_start - 1] not in (' ', '\n', '\t'):
            word_start -= 1
        t_marker = starts[word_start] if word_start < len(starts) else starts[-1]
        t_marker = float(t_marker)

        # Safety net: if the marker falls beyond the first 40% of the audio, the model
        # placed [[MARK:...]] too late in the narration (e.g. at the end of a 60s narration).
        # Override to 0.0 so the element appears at the START of speech, not the end.
        # The correct authoring pattern is [[MARK:id]] in sentence 1 — this is a fallback only.
        if audio_duration > 0 and t_marker > audio_duration * 0.40:
            _safe_print(f"[Voice] Marker '{marker_id}' at {t_marker:.2f}s > 40% of {audio_duration:.2f}s "
                        f"- overriding revealTime to 0.0 (mark placed too late; use [[MARK]] in sentence 1)")
            t_marker = 0.0


        timings.append({
            "id": marker_id,
            "time": round(t_marker, 3),
            "char_index": clean_idx,
            "word_start_char": word_start
        })
    return timings, audio_duration


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_narration_audio(
    narration: str,
    audio_output_path: str,
    alignment_output_path: str,
    default_marker_id: Optional[str] = None
) -> tuple:
    """
    Synthesizes narration for a single draw event.
    Saves: MP3 audio + alignment JSON.
    Returns: (audio_duration_seconds, char_count, alignment_dict)

    The narration text sent to ElevenLabs is EXACTLY the text used for
    alignment — no modification between the two calls.
    """
    try:
        clean_text, markers = extract_markers_and_clean_text(narration)

        _safe_print(f"[Voice] Synthesizing narration for '{default_marker_id}': "
                    f"{len(clean_text)} chars, {len(markers)} marker(s)")

        audio_bytes, raw_align, _, is_fallback = _call_elevenlabs_tts(clean_text)
        marker_timings, audio_duration = _calculate_marker_timings(
            markers, raw_align, clean_text=clean_text, default_marker_id=default_marker_id
        )

        if marker_timings:
            reveal = marker_timings[0]['time']
            _safe_print(f"[Voice] '{default_marker_id}' - duration={audio_duration:.2f}s "
                        f"revealTime={reveal:.3f}s fallback={is_fallback}")

        alignment_data = {
            "provider": "synthetic_fallback" if is_fallback else "elevenlabs",
            "is_synthetic": bool(is_fallback),
            "audio_duration_seconds": audio_duration,
            "clean_text": clean_text,
            "marker_timings": marker_timings,
            "raw_alignment": raw_align
        }

        p_audio = Path(audio_output_path)
        p_audio.parent.mkdir(parents=True, exist_ok=True)
        p_audio.write_bytes(audio_bytes)

        p_align = Path(alignment_output_path)
        p_align.parent.mkdir(parents=True, exist_ok=True)
        p_align.write_text(json.dumps(alignment_data, indent=2), encoding="utf-8")

        return audio_duration, len(clean_text), alignment_data
    except Exception as exc:
        try:
            import traceback as _tb
            log_dir = Path("logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "voice_error.txt", "a", encoding="utf-8") as _f:
                _f.write(f"ERROR: {exc}\n{_tb.format_exc()}\n")
        except Exception:
            pass
        raise
