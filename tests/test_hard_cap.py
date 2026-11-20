"""
tests/test_hard_cap.py
End-to-end hard-cap check through the real /draw pipeline (audio mocked):
  24 small non-overlapping elements -> all accepted (soft signal fires from 15)
  25th element                       -> rejected, page stays at 24 and active
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import init_db
from engine.validator import HARD_ELEMENT_COUNT

init_db()
client = TestClient(app)


def _box(i: int) -> str:
    x, y = 40 + (i % 6) * 190, 40 + (i // 6) * 150
    return (f'<g id="box_{i}"><rect x="{x}" y="{y}" width="150" height="100"/>'
            f'<text x="{x + 75}" y="{y + 55}" text-anchor="middle" font-size="14">Item {i}</text></g>')


def test_hard_cap_rejects_25th_element_and_keeps_page_usable():
    nb = client.post("/api/notebooks", json={"topic": "Hard cap"}).json()["id"]
    pid = client.post(f"/api/notebooks/{nb}/pages", json={"title": "Cap"}).json()["id"]
    url = f"/api/notebooks/{nb}/pages/{pid}/draw"
    with patch("engine.author.generate_narration_audio", return_value=(1.0, b"", {})):
        for i in range(HARD_ELEMENT_COUNT - 1):
            r = client.post(url, json={"element_id": f"box_{i}", "svg_fragment": _box(i)})
            assert r.status_code == 200, f"element {i} rejected: {r.text}"
        r = client.post(url, json={"element_id": "box_24", "svg_fragment": _box(24)})
    assert r.status_code == 400 and "hard cap" in r.json()["detail"].lower()
    page = client.get(f"/api/notebooks/{nb}").json()["pages"][0]
    assert page["element_count"] == HARD_ELEMENT_COUNT - 1 and page["status"] == "active"


def test_duplicate_element_id_rejected():
    nb = client.post("/api/notebooks", json={"topic": "dup"}).json()["id"]
    pid = client.post(f"/api/notebooks/{nb}/pages", json={}).json()["id"]
    url = f"/api/notebooks/{nb}/pages/{pid}/draw"
    with patch("engine.author.generate_narration_audio", return_value=(1.0, b"", {})):
        assert client.post(url, json={"element_id": "box_0", "svg_fragment": _box(0)}).status_code == 200
        again = client.post(url, json={"element_id": "box_0", "svg_fragment": _box(3)})
    assert again.status_code == 400 and "already exists" in again.json()["detail"]
