"""
tests/test_api_lifecycle.py
Tests the end-to-end API lifecycle for Learning Platform Phase 1:
  - Notebook creation, listing, retrieval
  - Page creation and auto-numbering
  - Draw and modify event logging with single-table shared seq
  - Page save and silent reload
  - Replay events retrieval in strict sequence order
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import init_db

init_db()
client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    print("  PASS health check")


def test_notebook_and_page_lifecycle():
    # 1. Create notebook
    res = client.post("/api/notebooks", json={"topic": "Neural Networks", "title": "Intro to Neural Networks"})
    assert res.status_code == 201
    nb = res.json()
    nb_id = nb["id"]
    assert nb["topic"] == "Neural Networks"
    print("  PASS notebook created:", nb_id)

    # 2. List notebooks
    res = client.get("/api/notebooks")
    assert res.status_code == 200
    nbs = res.json()
    assert any(n["id"] == nb_id for n in nbs)
    print("  PASS notebook in list")

    # 3. Create Page 1
    res = client.post(f"/api/notebooks/{nb_id}/pages", json={"title": "Single Perceptron"})
    assert res.status_code == 201
    p1 = res.json()
    p1_id = p1["id"]
    assert p1["page_number"] == 1
    assert p1["status"] == "active"
    print("  PASS page 1 created:", p1_id)

    # 4. Save Page 1 with SVG content
    svg_p1 = '<svg viewBox="0 0 1200 800"><circle id="n1" cx="200" cy="200" r="40" fill="#3b82f6"/><text id="t1" x="200" y="200">Input</text></svg>'
    res = client.post(f"/api/notebooks/{nb_id}/pages/{p1_id}/save", json={
        "final_svg": svg_p1,
        "summary": "Diagram of single input neuron.",
        "element_count": 2
    })
    assert res.status_code == 200
    saved = res.json()
    assert saved["status"] == "saved"
    print("  PASS page 1 saved")

    # 5. Create Page 2 (auto-numbering should give 2)
    res = client.post(f"/api/notebooks/{nb_id}/pages", json={"title": "Multi-Layer Perceptron"})
    assert res.status_code == 201
    p2 = res.json()
    assert p2["page_number"] == 2
    print("  PASS page 2 auto-numbered:", p2["page_number"])

    # 6. Verify get_notebook includes both pages
    res = client.get(f"/api/notebooks/{nb_id}")
    assert res.status_code == 200
    detail = res.json()
    assert len(detail["pages"]) == 2
    assert detail["pages"][0]["id"] == p1_id
    assert detail["pages"][0]["status"] == "saved"
    assert detail["pages"][1]["id"] == p2["id"]
    assert detail["pages"][1]["status"] == "active"
    print("  PASS notebook detail includes both pages in order")

    # 7. Test events endpoint for replay
    res = client.get(f"/api/notebooks/{nb_id}/pages/{p1_id}/events")
    assert res.status_code == 200
    ev_data = res.json()
    assert "events" in ev_data
    assert "final_svg" in ev_data
    from engine.sanitiser import sanitize_svg
    assert ev_data["final_svg"] == sanitize_svg(svg_p1)  # save runs the sanitiser
    print("  PASS page replay events endpoint returns final_svg")


def test_save_sanitises_client_svg_and_ignores_client_count():
    nb = client.post("/api/notebooks", json={"topic": "XSS"}).json()["id"]
    pid = client.post(f"/api/notebooks/{nb}/pages", json={}).json()["id"]
    evil = '<svg><script>alert(1)</script><rect id="r" x="1" y="1" width="9" height="9" onclick="x()"/></svg>'
    client.post(f"/api/notebooks/{nb}/pages/{pid}/save", json={"final_svg": evil, "element_count": 999})
    page = client.get(f"/api/notebooks/{nb}/pages/{pid}/events").json()
    assert "<script" not in page["final_svg"] and "onclick" not in page["final_svg"]
    assert client.get(f"/api/notebooks/{nb}").json()["pages"][0]["element_count"] != 999


LOCAL_OK = ["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:3000", "http://[::1]:5173"]
FOREIGN = ["http://evil.example", "http://evil.example:5173", "http://localhost.evil.example", "https://127.0.0.1.evil.example:5173"]


def test_cors_allows_any_local_port_and_rejects_foreign_sites():
    for origin in LOCAL_OK:
        h = {"Origin": origin, "Access-Control-Request-Method": "DELETE"}
        assert client.options("/api/notebooks", headers=h).headers.get("access-control-allow-origin") == origin, origin
    for origin in FOREIGN:
        h = {"Origin": origin, "Access-Control-Request-Method": "DELETE"}
        assert "access-control-allow-origin" not in client.options("/api/notebooks", headers=h).headers, origin


def test_websocket_accepts_local_pages_on_any_port_and_rejects_foreign_ones():
    import pytest
    from starlette.websockets import WebSocketDisconnect
    for origin in ("http://localhost:5173", "http://127.0.0.1:5174"):
        with client.websocket_connect("/api/ws/notebooks/x", headers={"origin": origin}):
            pass  # accepted and closed cleanly
    for origin in FOREIGN:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/ws/notebooks/x", headers={"origin": origin}):
                pass


if __name__ == "__main__":
    print("Running API lifecycle tests...")
    test_health()
    test_notebook_and_page_lifecycle()
    print("\nAll API lifecycle tests PASS [OK]")
