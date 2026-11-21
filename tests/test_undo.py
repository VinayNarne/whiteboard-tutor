"""Undo the last drawing: removes the element and everything that depends on it, and keeps all views consistent."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import backend.main as bm
import seed
from backend.database import engine, init_db
from backend.page_state import rebuild_page_svg

init_db()
client = TestClient(bm.app)


def _box(eid, x):
    return (f'<g id="{eid}"><rect x="{x}" y="200" width="250" height="120"/>'
            f'<text x="{x + 20}" y="260" font-size="16">{eid}</text></g>')


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


@pytest.fixture()
def board():
    """A notebook with a page holding three drawn elements (a, b, c); TTS writes real files."""
    nb = client.post("/api/notebooks", json={"topic": "Undo"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
    for i, eid in enumerate(["a", "b", "c"]):
        seed.draw(engine, pg, eid, _box(eid, 40 + i * 300), f"Draw {eid}.", nb=nb)
    yield nb, pg
    client.delete(f"/api/notebooks/{nb}")


def _page(nb):
    return client.get(f"/api/notebooks/{nb}").json()["pages"][0]


def _events(nb, pg):
    return client.get(f"/api/notebooks/{nb}/pages/{pg}/events").json()["events"]


def _files(nb, pg):
    d = bm.OUTPUT_DIR / nb / pg
    return {p.name for p in d.iterdir()} if d.exists() else set()


def test_rebuild_helper_reproduces_what_persistence_stores(board):
    """The helper must mirror how draws/modifies build current_svg, or undo would corrupt pages."""
    nb, pg = board
    seed.modify(engine, pg, "b", _box("b", 700))
    from sqlmodel import Session, select
    from backend.models import Page, PageEvent
    with Session(engine) as db:
        stored = db.get(Page, pg)
        events = db.exec(select(PageEvent).where(PageEvent.page_id == pg)).all()
        svg, count = rebuild_page_svg(events)
        assert svg == stored.current_svg and count == stored.element_count == 3


def test_undo_removes_only_the_last_element_its_audio_and_updates_every_view(board):
    nb, pg = board
    assert {"c_audio.mp3", "c_alignment.json"} <= _files(nb, pg)

    r = client.post(f"/api/notebooks/{nb}/pages/{pg}/undo")
    assert r.status_code == 200 and r.json()["removed_element_id"] == "c" and r.json()["element_count"] == 2

    page = _page(nb)
    assert page["element_count"] == 2
    assert [e["element_id"] for e in _events(nb, pg)] == ["a", "b"]
    assert 'id="c"' not in client.get(f"/api/notebooks/{nb}/pages/{pg}/events").json()["current_svg"]
    files = _files(nb, pg)
    assert "c_audio.mp3" not in files and "c_alignment.json" not in files          # its audio is gone
    assert {"a_audio.mp3", "b_audio.mp3"} <= files                                    # the others are untouched

    # the page keeps working: the undone id can be drawn again, and the export shows the final state
    seed.draw(engine, pg, "c", _box("c", 640), "Again.", nb=nb)
    assert _page(nb)["element_count"] == 3


def test_undo_walks_back_to_empty_then_reports_nothing_to_undo(board):
    nb, pg = board
    assert [client.post(f"/api/notebooks/{nb}/pages/{pg}/undo").json()["removed_element_id"] for _ in range(3)] == ["c", "b", "a"]
    again = client.post(f"/api/notebooks/{nb}/pages/{pg}/undo")
    assert again.status_code == 400 and "nothing to undo" in again.json()["detail"].lower()
    page = _page(nb)
    assert page["element_count"] == 0 and _events(nb, pg) == []


def test_undo_also_removes_edits_and_annotations_that_belong_to_the_element(board):
    nb, pg = board
    with patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        seed.modify(engine, pg, "c", _box("c", 700))
        for ann, target in (("ann_on_c", "c"), ("ann_on_a", "a")):
            r = client.post(f"/api/notebooks/{nb}/pages/{pg}/annotate", json={
                "annotation_id": ann, "style": "circle", "target_element_id": target, "narration": f"Look at {target}."})
            assert r.status_code == 200, r.text

    r = client.post(f"/api/notebooks/{nb}/pages/{pg}/undo")
    assert r.status_code == 200 and r.json()["removed_element_id"] == "c"

    remaining = {(e["kind"] if "kind" in e else "?", e["element_id"]) for e in _events(nb, pg)}
    ids = {e for _, e in remaining}
    assert "c" not in ids and "ann_on_c" not in ids          # the element, its edit and its annotation are gone
    assert "ann_on_a" in ids and {"a", "b"} <= ids           # an annotation on another element survives


def test_undo_announces_the_removal_over_the_websocket(board):
    nb, pg = board
    with client.websocket_connect(f"/api/ws/notebooks/{nb}") as ws:
        client.post(f"/api/notebooks/{nb}/pages/{pg}/undo")
        msg = ws.receive_json()
    assert msg["type"] == "element_removed"
    assert msg["payload"]["element_id"] == "c" and msg["payload"]["page_id"] == pg


def test_undo_refuses_saved_pages_busy_tutor_and_unknown_targets(board):
    nb, pg = board

    class Busy:
        def done(self):
            return False

    bm.ACTIVE_AGENT_TASKS[nb] = Busy()
    try:
        busy = client.post(f"/api/notebooks/{nb}/pages/{pg}/undo")
        assert busy.status_code == 409 and "still drawing" in busy.json()["detail"]
    finally:
        bm.ACTIVE_AGENT_TASKS.pop(nb, None)
    assert _page(nb)["element_count"] == 3                    # nothing was removed

    assert client.post(f"/api/notebooks/{nb}/pages/nope/undo").status_code == 404
    other = client.post("/api/notebooks", json={"topic": "Other"}).json()["id"]
    try:
        assert client.post(f"/api/notebooks/{other}/pages/{pg}/undo").status_code == 404   # page belongs elsewhere
    finally:
        client.delete(f"/api/notebooks/{other}")

    client.post(f"/api/notebooks/{nb}/pages/{pg}/save")
    locked = client.post(f"/api/notebooks/{nb}/pages/{pg}/undo")
    assert locked.status_code == 400 and "locked" in locked.json()["detail"]
    assert _page(nb)["element_count"] == 3


def test_undo_still_works_with_unique_seq_and_the_next_event_takes_the_next_number(board):
    """(page_id, seq) is unique (migration 0003): undo removes the last event, the next drawing is numbered after the last one that is left, and
    the seq numbers of the page stay unique and in order, however many times this is repeated."""
    nb, pg = board
    assert [e["seq"] for e in _events(nb, pg)] == [1, 2, 3]
    assert client.post(f"/api/notebooks/{nb}/pages/{pg}/undo").status_code == 200
    assert [e["seq"] for e in _events(nb, pg)] == [1, 2]
    with patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        for eid, x in (("d", 700), ("e", 40)):
            frag = f'<g id="{eid}"><rect x="{x}" y="450" width="250" height="120"/><text x="{x + 20}" y="510" font-size="16">{eid}</text></g>'
            seed.draw(engine, pg, eid, frag, f"Draw {eid}.", nb=nb)
    seqs = [e["seq"] for e in _events(nb, pg)]
    assert seqs == [1, 2, 3, 4] and len(set(seqs)) == len(seqs)
    assert client.post(f"/api/notebooks/{nb}/pages/{pg}/undo").status_code == 200
    assert client.post(f"/api/notebooks/{nb}/pages/{pg}/undo").status_code == 200
    assert [e["seq"] for e in _events(nb, pg)] == [1, 2]
