"""Unfinished-drawing hints and the voice_ok flag sent with every drawn element."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import SessionEvent
from engine.author import _handle_draw_new_element
from engine.validator import find_layout_issues


def _card(x, y, label=True):
    t = f'<text x="{x + 100}" y="{y + 40}" text-anchor="middle" font-size="14">Layer</text>' if label else ""
    return f'<rect x="{x}" y="{y}" width="200" height="60"/>{t}'


def test_unlabeled_card_is_flagged_and_labeled_card_is_not():
    bad = f'<g id="g">{_card(100, 100)}{_card(100, 200, label=False)}</g>'
    good = f'<g id="g">{_card(100, 100)}{_card(100, 200)}</g>'
    assert any("no label" in i for i in find_layout_issues(bad))
    assert find_layout_issues(good) == []


def test_container_sized_for_more_items_than_drawn_is_flagged():
    shell = '<rect x="60" y="100" width="400" height="500"/>'
    two = _card(100, 120) + _card(100, 200)           # content ends at y=260 of 600
    full = "".join(_card(100, 120 + i * 70) for i in range(6))  # content ends at y=540 of 600
    assert any("empty at the bottom" in i for i in find_layout_issues(f'<g id="g">{shell}{two}</g>'))
    assert find_layout_issues(f'<g id="g">{shell}{full}</g>') == []


def _draw(alignment=None, boom=False):
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    async def persist(**kw):
        pass

    def fake_tts(*a, **k):
        if boom:
            raise RuntimeError("tts down")
        return 1.0, 5, alignment

    frag = f'<g id="hint_el">{_card(100, 100)}{_card(100, 200, label=False)}</g>'
    with patch("engine.author.generate_narration_audio", side_effect=fake_tts):
        res = asyncio.run(_handle_draw_new_element(
            "nb", "pg", "active", "hint_el", frag, "Narration.", None, emit, persist))
    drawn = [p for k, p in events if k == SessionEvent.ELEMENT_DRAWN][0]
    return res, drawn


def test_voice_ok_false_on_synthetic_fallback_and_on_failure_true_otherwise():
    assert _draw({"is_synthetic": True})[1]["voice_ok"] is False
    assert _draw(boom=True)[1]["voice_ok"] is False
    res, drawn = _draw({"is_synthetic": False})
    assert drawn["voice_ok"] is True
    assert "no label" in res["layout_hint"]  # the hint reaches the tutor in the tool result
