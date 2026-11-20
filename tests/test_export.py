"""Notebook export: drawings + narration + conversation, escaping, download header, print mode."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.database import engine, init_db
from backend.main import app
from backend.models import ChatTurn

init_db()
client = TestClient(app)


def _seed():
    nb = client.post("/api/notebooks", json={"topic": "Export <b>demo</b>"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
    client.patch(f"/api/notebooks/{nb}/pages/{pg}", json={"title": "Packets & headers"})
    frag = ('<g id="pkt_box"><rect x="100" y="150" width="320" height="140"/>'
            '<text x="260" y="225" text-anchor="middle" font-size="16">Header</text></g>')
    with patch("engine.author.generate_narration_audio", return_value=(1.0, 5, {"is_synthetic": False})):
        r = client.post(f"/api/notebooks/{nb}/pages/{pg}/draw", json={
            "element_id": "pkt_box", "svg_fragment": frag,
            "narration": "[[MARK:pkt_box]] A packet has a <script>alert(1)</script> header."})
        assert r.status_code == 200, r.text
    with Session(engine) as db:
        db.add(ChatTurn(notebook_id=nb, seq=1, role="user", content="What is a packet?"))
        db.add(ChatTurn(notebook_id=nb, seq=2, role="assistant", content="A small unit of data."))
        db.commit()
    return nb


def test_export_contains_drawing_narration_and_conversation_and_escapes_html():
    nb = _seed()
    try:
        r = client.get(f"/api/notebooks/{nb}/export")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        html = r.text
        assert "1. Packets &amp; headers" in html                  # page title, escaped
        assert "Export &lt;b&gt;demo&lt;/b&gt;" in html            # notebook topic, escaped
        assert 'id="pkt_box"' in html and "Header" in html           # the drawing is inline
        assert "A packet has a &lt;script&gt;alert(1)&lt;/script&gt; header." in html
        assert "[[MARK" not in html                                  # internal tokens never leak
        assert "<script>alert" not in html
        assert "What is a packet?" in html and "A small unit of data." in html
        assert "Content-Disposition" not in r.headers and "window.print" not in html
    finally:
        client.delete(f"/api/notebooks/{nb}")


def test_export_download_and_print_modes_and_missing_notebook():
    nb = _seed()
    try:
        d = client.get(f"/api/notebooks/{nb}/export?download=true")
        assert d.headers["content-disposition"].startswith('attachment; filename="Export_b_demo_b')
        assert "window.print" in client.get(f"/api/notebooks/{nb}/export?print=1").text
    finally:
        client.delete(f"/api/notebooks/{nb}")
    assert client.get("/api/notebooks/does-not-exist/export").status_code == 404


def test_unrenderable_drawing_degrades_to_a_note_not_an_error():
    from backend import export
    with patch.object(export, "sanitize_svg", side_effect=ValueError("bad svg")):
        assert "could not be rendered" in export._board_svg("<g id='x'/>")
    assert "Nothing was drawn" in export._board_svg("")
    assert "<svg" in export._board_svg("<svg><<<not xml")  # sanitiser recovery: renders, never raises
