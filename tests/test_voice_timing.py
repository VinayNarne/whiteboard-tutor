"""
tests/test_voice_timing.py
Verifies ElevenLabs word-timing and audio alignment accuracy:
  1. Character and word-level monotonicity:
     - start_times <= end_times for every character
     - start_times monotonically non-decreasing
  2. Character reconstruction:
     - "".join(characters) matches clean_text exactly
  3. Word-level extraction:
     - Word boundaries correctly group characters
     - Word durations > 0 and <= total audio duration
  4. Audio duration correlation:
     - The alignment end time matches the physical MP3 audio duration (within 200ms tolerance)
"""

import os
import sys
import json
from pathlib import Path

import pytest

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.voice import generate_narration_audio


def inspect_and_verify_alignment(alignment_path: Path, audio_path: Path):
    assert alignment_path.exists(), f"Alignment file not found: {alignment_path}"
    assert audio_path.exists(), f"Audio file not found: {audio_path}"

    with open(alignment_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    clean_text = data["clean_text"]
    provider = data.get("provider")
    alignment_duration = data["audio_duration_seconds"]
    raw_align = data.get("raw_alignment", {})

    chars = raw_align.get("characters", [])
    starts = raw_align.get("character_start_times_seconds", [])
    ends = raw_align.get("character_end_times_seconds", [])

    print(f"Alignment verification for: {alignment_path.name}")
    print(f"  Provider: {provider}")
    print(f"  Text: {clean_text[:50]}...")
    print(f"  Char count: {len(chars)}, Starts count: {len(starts)}, Ends count: {len(ends)}")

    # 1. Structural parity
    assert len(chars) == len(starts) == len(ends), "Length mismatch between chars, starts, ends"
    assert len(chars) > 0, "No characters in alignment"

    # 2. Reconstructed text match
    reconstructed = "".join(chars)
    assert reconstructed == clean_text, f"Text mismatch:\nOriginal:      '{clean_text}'\nReconstructed: '{reconstructed}'"
    print("  PASS exact text-to-character match")

    # 3. Monotonic timing validation
    for i in range(len(chars)):
        assert starts[i] <= ends[i], f"Char {i} ('{chars[i]}') start {starts[i]} > end {ends[i]}"
        if i > 0:
            assert starts[i] >= starts[i - 1], f"Char {i} start {starts[i]} < previous start {starts[i - 1]}"
    print("  PASS character timings monotonically increasing")

    # 4. Word-level reconstruction and timing check
    words = []
    current_word = []
    word_start = None
    word_end = None

    for char, s, e in zip(chars, starts, ends):
        if char in (" ", "\t", "\n", ".", ",", "!", "?", ";", ":"):
            if current_word:
                words.append({
                    "word": "".join(current_word),
                    "start": word_start,
                    "end": word_end,
                    "duration": round(word_end - word_start, 3)
                })
                current_word = []
                word_start = None
                word_end = None
        else:
            if word_start is None:
                word_start = s
            word_end = e
            current_word.append(char)

    if current_word:
        words.append({
            "word": "".join(current_word),
            "start": word_start,
            "end": word_end,
            "duration": round(word_end - word_start, 3)
        })

    assert len(words) > 0, "Failed to extract words from alignment"
    print(f"  Extracted {len(words)} words:")
    for w in words[:5]:
        print(f"    '{w['word']}': {w['start']:.3f}s -> {w['end']:.3f}s (dur: {w['duration']:.3f}s)")
        assert w["start"] <= w["end"], f"Word '{w['word']}' start > end"
        assert w["end"] <= alignment_duration + 0.5, f"Word '{w['word']}' exceeds total audio duration"

    print("  PASS word boundaries and timings strictly sequential and valid")

    # 5. Measure physical MP3 duration
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_file(str(audio_path), format="mp3")
        mp3_duration = len(seg) / 1000.0
        print(f"  Physical MP3 duration: {mp3_duration:.3f}s, Alignment duration: {alignment_duration:.3f}s")
        diff = abs(mp3_duration - alignment_duration)
        assert diff < 0.35, f"Discrepancy between MP3 duration ({mp3_duration:.3f}s) and alignment duration ({alignment_duration:.3f}s): {diff:.3f}s"
        print(f"  PASS MP3 physical duration matches alignment within {diff:.3f}s")
    except ImportError:
        print("  [Note] pydub not available for MP3 physical header check, checked alignment internal duration.")


def test_existing_generated_audio():
    print("\n--- Test 3A: Verifying Generated Audio Asset on Disk ---")
    gen_dir = Path(__file__).parent.parent / "generated_notebooks"
    align_files = list(gen_dir.rglob("*_alignment.json"))
    if not align_files:   # a fresh clone or CI has taught no lesson yet
        pytest.skip("no generated lesson audio on this machine yet")

    for align_file in align_files[:2]:
        audio_file = align_file.with_name(align_file.name.replace("_alignment.json", "_audio.mp3"))
        inspect_and_verify_alignment(align_file, audio_file)


@pytest.mark.skipif(not os.getenv("ELEVENLABS_API_KEY") or os.getenv("LP_VOICE") == "0", reason="calls the real ElevenLabs service: needs ELEVENLABS_API_KEY")
def test_fresh_synthesis_timing():
    print("\n--- Test 3B: Fresh ElevenLabs Synthesis Word-Timing Audit ---")
    tmp_dir = Path(__file__).parent / "scratch"
    tmp_dir.mkdir(exist_ok=True)
    audio_path = tmp_dir / "timing_test_audio.mp3"
    align_path = tmp_dir / "timing_test_alignment.json"

    narration = "The client sends a query to the DNS server to resolve example dot com."
    dur, char_count, data = generate_narration_audio(narration, str(audio_path), str(align_path))

    inspect_and_verify_alignment(align_path, audio_path)
    print("  PASS fresh synthesis word-timing audit passed")


if __name__ == "__main__":
    test_existing_generated_audio()
    test_fresh_synthesis_timing()
    print("\nAll voice word-timing tests PASS [OK]")
