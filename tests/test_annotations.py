"""
tests/test_annotations.py
Unit and integration tests for the Whiteboard Annotation System:
- Deterministic stable seed generation (SHA-256)
- Conditional validation rules (arrow source/target, non-arrow styles)
- Ephemeral vs Permanent lifetimes & duration clamping
- PageEvent persistence and SessionEvent emission
- REST endpoints /api/notebooks/{nb_id}/pages/{p_id}/annotate and remove-annotation
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import json
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import init_db
import seed
from engine.author import generate_annotation_seed, _handle_annotate_element, _handle_remove_annotation
from core.events import SessionEvent

init_db()
client = TestClient(app)


def test_deterministic_annotation_seed():
    """Verify that SHA-256 seed generation produces the exact same integer across multiple calls."""
    seed1 = generate_annotation_seed("ann_circle_cache")
    seed2 = generate_annotation_seed("ann_circle_cache")
    seed_other = generate_annotation_seed("ann_tick_step1")

    assert seed1 == seed2
    assert isinstance(seed1, int)
    assert 1 <= seed1 <= 100000
    assert seed1 != seed_other


@pytest.mark.asyncio
async def test_annotate_element_validation_rules():
    """Test conditional validation rules for target, source, and styles."""
    emitted = []
    persisted = []

    async def mock_emit(evt, payload):
        emitted.append((evt, payload))

    async def mock_persist(**kwargs):
        persisted.append(kwargs)

    existing_ids = {"box_client", "box_server", "box_db"}

    # 1. Reject invalid style
    res_bad_style = await _handle_annotate_element(
        notebook_id="nb_1",
        page_id="p_1",
        page_status="active",
        annotation_id="ann_bad",
        style="sparkle",
        target_element_id="box_client",
        narration="Look at this",
        from_element_id=None,
        color=None,
        note=None,
        lifetime="ephemeral",
        duration_ms=3000,
        existing_element_ids=existing_ids,
        emit_fn=mock_emit,
        persist_fn=mock_persist,
    )
    assert res_bad_style["status"] == "error"
    assert "Invalid style" in res_bad_style["detail"]

    # 2. Reject missing target
    res_missing_target = await _handle_annotate_element(
        notebook_id="nb_1",
        page_id="p_1",
        page_status="active",
        annotation_id="ann_bad_target",
        style="circle",
        target_element_id="non_existent_box",
        narration="Look at this",
        from_element_id=None,
        color=None,
        note=None,
        lifetime="ephemeral",
        duration_ms=3000,
        existing_element_ids=existing_ids,
        emit_fn=mock_emit,
        persist_fn=mock_persist,
    )
    assert res_missing_target["status"] == "error"
    assert "does not exist on this page" in res_missing_target["detail"]

    # 3. Arrow style requires from_element_id
    res_arrow_no_source = await _handle_annotate_element(
        notebook_id="nb_1",
        page_id="p_1",
        page_status="active",
        annotation_id="ann_arrow_no_src",
        style="arrow",
        target_element_id="box_server",
        narration="Data flows here",
        from_element_id=None,
        color=None,
        note=None,
        lifetime="permanent",
        duration_ms=None,
        existing_element_ids=existing_ids,
        emit_fn=mock_emit,
        persist_fn=mock_persist,
    )
    assert res_arrow_no_source["status"] == "error"
    assert "'from_element_id' is required" in res_arrow_no_source["detail"]

    # 4. Arrow source and target cannot be identical
    res_arrow_same = await _handle_annotate_element(
        notebook_id="nb_1",
        page_id="p_1",
        page_status="active",
        annotation_id="ann_arrow_loop",
        style="arrow",
        target_element_id="box_server",
        narration="Data flows to itself",
        from_element_id="box_server",
        color=None,
        note=None,
        lifetime="permanent",
        duration_ms=None,
        existing_element_ids=existing_ids,
        emit_fn=mock_emit,
        persist_fn=mock_persist,
    )
    assert res_arrow_same["status"] == "error"
    assert "cannot be the same" in res_arrow_same["detail"]


@pytest.mark.asyncio
async def test_annotate_element_success_and_payload():
    """Verify successful annotation creation, stable seed, and persistence."""
    emitted = []
    persisted = []

    async def mock_emit(evt, payload):
        emitted.append((evt, payload))

    async def mock_persist(**kwargs):
        persisted.append(kwargs)

    existing_ids = {"cache_layer", "db_layer"}

    with patch("engine.author.generate_narration_audio", return_value=(2.5, b"", {})):
        res = await _handle_annotate_element(
            notebook_id="nb_test",
            page_id="p_test",
            page_status="active",
            annotation_id="ann_circle_cache",
            style="circle",
            target_element_id="cache_layer",
            narration="Notice the cache layer intercepts all queries",
            from_element_id=None,
            color="#f59e0b",
            note="Fast in-memory lookup",
            lifetime="ephemeral",
            duration_ms=4500,
            existing_element_ids=existing_ids,
            emit_fn=mock_emit,
            persist_fn=mock_persist,
        )

    assert res["status"] == "ok"
    payload = res["payload"]
    assert payload["annotation_id"] == "ann_circle_cache"
    assert payload["style"] == "circle"
    assert payload["target_element_id"] == "cache_layer"
    assert payload["from_element_id"] is None
    assert payload["color"] == "#f59e0b"
    assert payload["note"] == "Fast in-memory lookup"
    assert payload["lifetime"] == "ephemeral"
    assert payload["duration_ms"] == 4500
    assert payload["seed"] == generate_annotation_seed("ann_circle_cache")
    assert payload["narration"].startswith("[[MARK:ann_circle_cache]]")

    # Check persistence and emission
    assert len(persisted) == 1
    assert persisted[0]["kind"] == "annotate"
    assert persisted[0]["element_id"] == "ann_circle_cache"

    assert len(emitted) == 1
    assert emitted[0][0] == SessionEvent.ELEMENT_ANNOTATED
    assert emitted[0][1]["annotation_id"] == "ann_circle_cache"


@pytest.mark.asyncio
async def test_remove_annotation_handler():
    """Verify remove_annotation persists removal event and emits SessionEvent.ANNOTATION_REMOVED."""
    emitted = []
    persisted = []

    async def mock_emit(evt, payload):
        emitted.append((evt, payload))

    async def mock_persist(**kwargs):
        persisted.append(kwargs)

    res = await _handle_remove_annotation(
        page_id="p_test",
        page_status="active",
        annotation_id="ann_circle_cache",
        emit_fn=mock_emit,
        persist_fn=mock_persist,
    )

    assert res["status"] == "ok"
    assert len(persisted) == 1
    assert persisted[0]["kind"] == "remove_annotation"
    assert persisted[0]["element_id"] == "ann_circle_cache"

    assert len(emitted) == 1
    assert emitted[0][0] == SessionEvent.ANNOTATION_REMOVED
    assert emitted[0][1]["annotation_id"] == "ann_circle_cache"


def test_rest_annotate_and_remove_endpoints():
    """Test REST API endpoints for annotating and removing annotations on a real page."""
    # 1. Create a notebook
    nb_res = client.post("/api/notebooks", json={"topic": "Annotation Test", "title": "Annotation Test"})
    assert nb_res.status_code == 201
    nb_id = nb_res.json()["id"]

    # 2. Get active page from notebook details
    nb_detail = client.get(f"/api/notebooks/{nb_id}")
    page_id = nb_detail.json()["pages"][0]["id"]

    # 3. Draw a base element first
    from backend.database import engine
    seed.draw(engine, page_id, "queue_node", '<g id="queue_node"><rect x="100" y="100" width="200" height="100" /><text x="150" y="150">Queue</text></g>',
              "[[MARK:queue_node]] Here is the queue node.")

    # 4. Annotate the element with circle
    with patch("engine.author.generate_narration_audio", return_value=(1.0, b"", {})):
        ann_res = client.post(
            f"/api/notebooks/{nb_id}/pages/{page_id}/annotate",
            json={
                "annotation_id": "ann_circle_q",
                "style": "circle",
                "target_element_id": "queue_node",
                "color": "#f59e0b",
                "note": "Buffer",
                "lifetime": "ephemeral",
                "duration_ms": 3000,
                "narration": "Let's circle the queue buffer.",
            }
        )
    assert ann_res.status_code == 200
    assert ann_res.json()["status"] == "ok"
    assert ann_res.json()["payload"]["style"] == "circle"

    # 5. Check page events sequence
    page_detail = client.get(f"/api/notebooks/{nb_id}/pages/{page_id}/events")
    assert page_detail.status_code == 200
    events = page_detail.json()["events"]
    assert len(events) >= 2
    annotate_event = [e for e in events if e["kind"] == "annotate"][0]
    assert annotate_event["element_id"] == "ann_circle_q"
    parsed_payload = json.loads(annotate_event["svg_fragment"])
    assert parsed_payload["target_element_id"] == "queue_node"

    # 6. Remove annotation
    rm_res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/remove-annotation",
        json={"annotation_id": "ann_circle_q"}
    )
    assert rm_res.status_code == 200
    assert rm_res.json()["status"] == "ok"

    # 7. Check page events again has remove_annotation
    page_detail2 = client.get(f"/api/notebooks/{nb_id}/pages/{page_id}/events")
    events2 = page_detail2.json()["events"]
    rm_events = [e for e in events2 if e["kind"] == "remove_annotation"]
    assert len(rm_events) == 1
    assert rm_events[0]["element_id"] == "ann_circle_q"
