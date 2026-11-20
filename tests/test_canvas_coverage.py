"""
pages.canvas_coverage was a column nobody wrote (always 0.0). It is now written whenever the page's drawing changes (draw, modify, undo), with the same number the
density check logs, so the cached fill can be read from the page without recomputing it.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from sqlmodel import Session

import backend.main as bm
from backend.database import engine, init_db
from backend.models import Page
from core.events import EngineEvent
from engine.validator import compute_coverage

init_db()
client = TestClient(bm.app)


def _card(eid, x, y, w=300, h=150):
    return f'<g id="{eid}"><rect x="{x}" y="{y}" width="{w}" height="{h}"/><text x="{x + 20}" y="{y + 60}" font-size="16">{eid}</text></g>'


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


@pytest.fixture()
def page():
    nb = client.post("/api/notebooks", json={"topic": "Coverage"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
    yield nb, pg
    client.delete(f"/api/notebooks/{nb}")


def _coverage(pg):
    with Session(engine) as db:
        p = db.get(Page, pg)
        return p.canvas_coverage, p.current_svg


def _draw(nb, pg, eid, x, y, **kw):
    with patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        return client.post(f"/api/notebooks/{nb}/pages/{pg}/draw", json={"element_id": eid, "svg_fragment": _card(eid, x, y, **kw), "narration": f"[[MARK:{eid}]] Here."})


def test_a_new_page_has_no_coverage_and_every_drawing_raises_it_to_the_same_number_the_density_check_logs(page):
    nb, pg = page
    assert _coverage(pg)[0] == 0.0
    seen = []
    for eid, x, y in (("a", 60, 60), ("b", 450, 60), ("c", 60, 300)):
        with patch("engine.author.logger") as log:
            assert _draw(nb, pg, eid, x, y).status_code == 200
        logged = [c.kwargs["data"]["canvas_coverage"] for c in log.info.call_args_list if c.args[0] == EngineEvent.DENSITY_CHECKED]
        cov, svg = _coverage(pg)
        assert cov == logged[0] == round(compute_coverage(svg), 3)
        seen.append(cov)
    assert 0 < seen[0] < seen[1] < seen[2]


def test_a_modified_element_changes_the_coverage_and_an_annotation_does_not(page):
    nb, pg = page
    _draw(nb, pg, "a", 60, 60)
    before = _coverage(pg)[0]
    bigger = _card("a", 60, 60, w=600, h=400)
    assert client.post(f"/api/notebooks/{nb}/pages/{pg}/modify", json={"element_id": "a", "new_svg_fragment": bigger}).status_code == 200
    grown = _coverage(pg)[0]
    assert grown > before
    with patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        assert client.post(f"/api/notebooks/{nb}/pages/{pg}/annotate", json={"annotation_id": "r", "style": "circle", "target_element_id": "a",
                                                                          "narration": "[[MARK:r]] Look."}).status_code == 200
    assert _coverage(pg)[0] == grown


def test_undo_brings_the_coverage_back_down(page):
    nb, pg = page
    _draw(nb, pg, "a", 60, 60)
    one = _coverage(pg)[0]
    _draw(nb, pg, "b", 450, 60)
    two = _coverage(pg)[0]
    assert two > one
    assert client.post(f"/api/notebooks/{nb}/pages/{pg}/undo").status_code == 200
    assert _coverage(pg)[0] == one
    assert client.post(f"/api/notebooks/{nb}/pages/{pg}/undo").status_code == 200
    assert _coverage(pg)[0] == 0.0
