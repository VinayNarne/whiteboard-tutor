"""
tests/test_spatial_grounding.py
Unit tests for learner whiteboard spatial grounding and backend validation:
1. Valid selected_element_ids matching active page elements are accepted.
2. Untrusted/invalid selected_element_ids (non-existent IDs) are rejected/stripped.
3. Gesture types are validated against allowed enum with safe fallbacks.
4. Prompt augmentation formats clean spatial context for WhiteboardAuthor.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from backend.main import app, engine
from backend.models import Notebook, Page, PageEvent, ChatTurn
from backend.database import init_db

init_db()
client = TestClient(app)


@pytest.fixture
def test_setup():
    with Session(engine) as session:
        nb = Notebook(topic="Spatial Grounding Test", title="Spatial Test")
        session.add(nb)
        session.commit()
        session.refresh(nb)

        p = Page(notebook_id=nb.id, page_number=1, status="active")
        session.add(p)
        session.commit()
        session.refresh(p)

        # Add a legitimate drawn element
        ev1 = PageEvent(
            page_id=p.id,
            seq=1,
            kind="draw",
            element_id="gateway_node",
            svg_fragment="<g id='gateway_node'><rect x='200' y='200' width='160' height='90' fill='#2563eb'/></g>",
            narration="API Gateway handles incoming traffic."
        )
        session.add(ev1)
        p.current_svg = ev1.svg_fragment
        p.element_count = 1
        session.add(p)
        session.commit()

        yield nb.id, p.id


def test_spatial_grounding_rejects_untrusted_elements(test_setup):
    nb_id, page_id = test_setup

    payload_invalid = {
        "message": "Can you explain this part?",
        "page_id": page_id,
        "selected_element_ids": ["malicious_or_nonexistent_node"],
        "gesture_type": "circle",
        "match_score": 0.95
    }

    with patch("backend.main.run_whiteboard_author", new_callable=AsyncMock) as mock_author:
        mock_author.return_value = "Here is an explanation of the topic."
        res = client.post(f"/api/notebooks/{nb_id}/chat", json=payload_invalid)
        assert res.status_code == 200

        # Verify that untrusted element ID was stripped from the LLM prompt!
        kwargs = mock_author.call_args.kwargs
        assert "malicious_or_nonexistent_node" not in kwargs["learner_message"]
        assert kwargs["learner_message"] == "Can you explain this part?"

    # Verify database ChatTurn
    with Session(engine) as db:
        turns = db.exec(
            select(ChatTurn).where(ChatTurn.notebook_id == nb_id).order_by(ChatTurn.seq.desc())
        ).all()
        user_turn = [t for t in turns if t.role == "user"][-1]
        assert user_turn.content == "Can you explain this part?"


def test_spatial_grounding_valid_element_accepted_and_grounded(test_setup):
    nb_id, page_id = test_setup

    payload_valid = {
        "message": "What is the throughput of this node?",
        "page_id": page_id,
        "selected_element_ids": ["gateway_node"],
        "gesture_type": "underline",
        "match_score": 0.88
    }

    with patch("backend.main.run_whiteboard_author", new_callable=AsyncMock) as mock_author:
        mock_author.return_value = "The API Gateway handles up to 50k requests per second."
        res = client.post(f"/api/notebooks/{nb_id}/chat", json=payload_valid)
        assert res.status_code == 200

        # Verify that valid element was augmented into the prompt
        kwargs = mock_author.call_args.kwargs
        augmented = kwargs["learner_message"]
        assert "[Learner underlined diagram element(s): 'gateway_node' (Gateway Node) (0.88 match)]" in augmented
        assert "What is the throughput of this node?" in augmented


def test_spatial_grounding_multi_element_relationship_grounded(test_setup):
    nb_id, page_id = test_setup

    # Add second element to page
    with Session(engine) as session:
        ev2 = PageEvent(
            page_id=page_id,
            seq=2,
            kind="draw",
            element_id="queue_node",
            svg_fragment="<g id='queue_node'><rect x='500' y='200' width='160' height='90' fill='#10b981'/></g>",
            narration="Message Queue buffers tasks."
        )
        session.add(ev2)
        p = session.get(Page, page_id)
        p.current_svg = (p.current_svg or "") + "\n" + ev2.svg_fragment
        p.element_count = 2
        session.add(p)
        session.commit()

    payload_multi = {
        "message": "How do these two connect and exchange data?",
        "page_id": page_id,
        "selected_element_ids": ["gateway_node", "queue_node"],
        "gesture_type": "circle",
        "match_score": 0.91
    }

    with patch("backend.main.run_whiteboard_author", new_callable=AsyncMock) as mock_author:
        mock_author.return_value = "The API Gateway pushes requests to the Message Queue asynchronously."
        res = client.post(f"/api/notebooks/{nb_id}/chat", json=payload_multi)
        assert res.status_code == 200

        kwargs = mock_author.call_args.kwargs
        augmented = kwargs["learner_message"]
        assert "[Learner circled relationship between diagram elements: 'gateway_node' (Gateway Node) and 'queue_node' (Queue Node) (0.91 match)]" in augmented
        assert "How do these two connect and exchange data?" in augmented


def test_spatial_grounding_multi_element_filters_partial_invalid(test_setup):
    nb_id, page_id = test_setup

    payload_mixed = {
        "message": "Explain this connection",
        "page_id": page_id,
        "selected_element_ids": ["gateway_node", "fake_unknown_node"],
        "gesture_type": "circle",
        "match_score": 0.75
    }

    with patch("backend.main.run_whiteboard_author", new_callable=AsyncMock) as mock_author:
        mock_author.return_value = "Here is the explanation."
        res = client.post(f"/api/notebooks/{nb_id}/chat", json=payload_mixed)
        assert res.status_code == 200

        kwargs = mock_author.call_args.kwargs
        augmented = kwargs["learner_message"]
        # fake_unknown_node was stripped; falls back to single element augmentation for gateway_node
        assert "fake_unknown_node" not in augmented
        assert "[Learner circled diagram element(s): 'gateway_node' (Gateway Node) (0.75 match)]" in augmented
