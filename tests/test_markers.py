"""
The [[MARK:id]] marker is a recording detail: the code makes it right however the model wrote it, and no marker syntax
ever reaches the voice. Baseline D: 40-56% of narrations had no marker and 5 used single brackets (read aloud).
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EngineEvent
from engine import voice
from engine.author import _handle_annotate_element
from engine.markers import MARKER_LIKE, normalise_marker, strip_markers

CANON = "[[MARK:el]]"
ALIGN = {"characters": list("x"), "character_start_times_seconds": [0.0], "character_end_times_seconds": [1.0]}


# ---- a) every form ends up as ONE valid marker -----------------------------------------------------------------------

VARIANTS = [
    ("[[MARK:el]] Hello world.", []),                         # already right
    ("[MARK:el] Hello world.", ["format"]),                   # single bracket
    ("[[ MARK : el ]] Hello world.", ["format"]),             # spaces
    ("[  Mark:el  ] Hello world.", ["format"]),               # single bracket, spaces, mixed case
    ("[[mark:el]] Hello world.", ["format"]),                 # lowercase
    ("[[MARK:el] Hello world.", ["format"]),                  # unbalanced
    ("[MARK:el]] Hello world.", ["format"]),
    ("[MARK: el ]Hello world.", ["format"]),                  # no space before the text
    ("[[MARK:el Hello world.", ["format"]),                   # closing bracket missing
    ("Hello world.", ["missing"]),                             # no marker at all
    ("[[MARK:other]] Hello world.", ["wrong_id"]),            # names another element
    ("[[MARK:el]] Hello [[MARK:other]] world.", ["duplicate"]),
]


@pytest.mark.parametrize("raw,reasons", VARIANTS)
def test_every_form_ends_up_as_one_valid_marker(raw, reasons):
    out, why = normalise_marker(raw, "el")
    assert why == reasons
    assert len(MARKER_LIKE.findall(out)) == 1 and out.count(CANON) == 1
    assert strip_markers(out).split() == ["Hello", "world."]          # the words are untouched


@pytest.mark.parametrize("raw,reasons", VARIANTS)
def test_no_bracket_reaches_the_voice(raw, reasons, tmp_path):
    sent = []

    def fake_tts(clean_text):
        sent.append(clean_text)
        return b"MP3", ALIGN, 1.0, False
    out, _ = normalise_marker(raw, "el")
    with patch.object(voice, "_call_elevenlabs_tts", fake_tts):
        voice.generate_narration_audio(out, str(tmp_path / "a.mp3"), str(tmp_path / "a.json"), "el")
        voice.generate_narration_audio(raw, str(tmp_path / "b.mp3"), str(tmp_path / "b.json"), "el")   # even unrepaired text
    assert len(sent) == 2
    for text in sent:                                                   # the repaired text AND the raw, unrepaired text
        assert text.split() == ["Hello", "world."], text


def test_a_marker_the_model_placed_later_keeps_its_place():
    out, why = normalise_marker("Here we begin, [MARK:el] we highlight the node.", "el")
    assert out == "Here we begin, [[MARK:el]] we highlight the node." and why == ["format"]
    clean, markers = voice.extract_markers_and_clean_text(out)
    assert markers == [("el", len("Here we begin, "))] and clean == "Here we begin,  we highlight the node."


# ---- b) must survive: text with square brackets that is not a marker --------------------------------------------------

@pytest.mark.parametrize("text", [
    "arrays use a[0] and b[1].",
    "Index with [1] or [[2]] or m[[0]].",
    "[Mark Twain wrote it] in 1876.",
    "A [MARK] without a colon is not a marker.",
    "The list is [1, 2, 3].",
    "Use x[i] < y[j] to compare.",
])
def test_ordinary_brackets_are_left_alone(text, tmp_path):
    assert strip_markers(text) == text
    out, why = normalise_marker(text, "el")
    assert why == ["missing"] and out == f"{CANON} {text}"             # only a marker is added; the text is intact
    sent = []
    with patch.object(voice, "_call_elevenlabs_tts", lambda t: (sent.append(t), (b"MP3", ALIGN, 1.0, False))[1]):
        voice.generate_narration_audio(out, str(tmp_path / "a.mp3"), str(tmp_path / "a.json"), "el")
    assert sent[0].strip() == text                                      # and it is what the voice receives


# ---- strip_markers for everything that is read or shown --------------------------------------------------------------------

def test_strip_markers_for_replies_and_exports():
    assert strip_markers("[[MARK:a]] Here. [MARK: b ] There.") == "Here. There."
    assert strip_markers("No marker here, just a[0].") == "No marker here, just a[0]."
    assert strip_markers("") == "" and strip_markers(None) == ""


# ---- through the real annotation handler ----------------------------------------------------------------------------------

def test_the_annotation_handler_uses_the_same_repair():
    async def noop(*a, **k):
        pass
    saved = []

    async def persist(**k):
        saved.append(k)
    with patch.object(voice, "_call_elevenlabs_tts", lambda t: (b"MP3", ALIGN, 1.0, False)), patch("engine.author.logger") as log:
        r = asyncio.run(_handle_annotate_element(
            "nb", "pg", "active", "ann1", "circle", "el", "[MARK:ann1] Look here.", None, None, None, None, None, {"el"}, noop, persist))
    assert r["status"] == "ok"
    assert saved[0]["narration"] == "[[MARK:ann1]] Look here."
    assert any(c.args[0] == EngineEvent.MARKER_REPAIRED for c in log.info.call_args_list)
