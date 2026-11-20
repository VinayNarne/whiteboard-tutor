"""Transform attributes are rejected: all layout measurement assumes absolute coordinates."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.author import _handle_draw_new_element, _handle_modify_existing_element
from engine.sanitiser import sanitize_svg
from engine.validator import find_transform


def test_find_transform_detects_attribute_only_where_it_matters():
    assert find_transform('<g id="a"><text x="10" y="20" transform="rotate(-90)">Y axis</text></g>') == "text"
    assert find_transform('<g id="a" transform="translate(50 50)"><rect x="0" y="0" width="9" height="9"/></g>') == "g"
    assert find_transform('<g id="a"><rect x="0" y="0" width="9" height="9"/></g>') is None
    # lookalikes and plain text content must not trigger it
    assert find_transform('<linearGradient id="g" gradientTransform="rotate(45)"/>') is None
    assert find_transform('<g id="a"><text x="1" y="2">set transform = 1 in CSS</text></g>') is None
    assert find_transform('<g id="a"><rect x="0" y="0" width="9" height="9" data-transform="x"/></g>') is None


def test_sanitiser_strips_transform_even_if_something_slips_past():
    out = sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect id="r" x="1" y="2" width="9" height="9" transform="rotate(30)"/></svg>')
    assert "transform" not in out and 'x="1"' in out


def _run(coro):
    return asyncio.run(coro)


def _noop():
    async def emit(*a, **k):
        pass

    async def persist(**k):
        pass
    return emit, persist


def test_draw_tool_rejects_transform_with_actionable_message_and_accepts_clean_version():
    emit, persist = _noop()
    bad = '<g id="axis"><rect x="100" y="100" width="300" height="80"/><text x="120" y="140" transform="rotate(-90)">Label</text></g>'
    good = '<g id="axis"><rect x="100" y="100" width="300" height="80"/><text x="120" y="140">Label</text></g>'
    with patch("engine.author.generate_narration_audio", return_value=(1.0, 5, {"is_synthetic": False})):
        r = _run(_handle_draw_new_element("nb", "pg", "active", "axis", bad, "Narration.", None, emit, persist))
        assert r["status"] == "error"
        assert "transform" in r["detail"] and "absolute" in r["detail"] and "<text>" in r["detail"]
        ok = _run(_handle_draw_new_element("nb", "pg", "active", "axis", good, "Narration.", None, emit, persist))
        assert ok["status"] == "ok"


def test_modify_tool_rejects_transform_too():
    emit, persist = _noop()
    current = '<g id="box"><rect x="100" y="100" width="300" height="80"/><text x="120" y="140">Hi</text></g>'
    bad = '<g id="box" transform="translate(900 700)"><rect x="100" y="100" width="300" height="80"/><text x="120" y="140">Hi</text></g>'
    r = _run(_handle_modify_existing_element("pg", "active", "box", bad, current, {"box"}, emit, persist))
    assert r["status"] == "error" and "transform" in r["detail"]


def test_http_draw_endpoint_returns_400_for_transform():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.database import init_db

    init_db()
    client = TestClient(app)
    nb = client.post("/api/notebooks", json={"topic": "Transform guard"}).json()["id"]
    try:
        pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
        frag = '<g id="t"><rect x="100" y="100" width="300" height="80" transform="rotate(10)"/><text x="120" y="140">Hi</text></g>'
        r = client.post(f"/api/notebooks/{nb}/pages/{pg}/draw", json={"element_id": "t", "svg_fragment": frag})
        assert r.status_code == 400 and "transform" in r.json()["detail"]
    finally:
        client.delete(f"/api/notebooks/{nb}")
