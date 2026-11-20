"""
tests/test_modify_and_savelock.py
Comprehensive test suite verifying:
  1. modify_existing_element lifecycle:
     - Draw an element on an active page
     - Modify the element with updated SVG attributes (preserving the exact same element_id)
     - Verify PageEvent row has kind="modify", correct old_svg_fragment, correct svg_fragment
     - Verify modifying a non-existent element is rejected
  2. Save-lock invariant (SAD hard rule):
     - Save the page (status="saved")
     - Attempt to draw on the saved page -> rejected with HTTP 400
     - Attempt to modify an element on the saved page -> rejected with HTTP 400
     - Attempt chat targeting the saved page -> rejected with HTTP 400
     - Confirm no new PageEvents are inserted after page is saved
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from backend.main import app
from backend.database import init_db, engine
from backend.models import PageEvent, Page

init_db()
client = TestClient(app)


def test_modify_existing_element_lifecycle():
    print("\n--- Test 1: modify_existing_element Lifecycle ---")
    # 1. Create a notebook and active page
    res = client.post("/api/notebooks", json={"topic": "Compiler Design", "title": "Lexical Analysis"})
    assert res.status_code == 201
    nb_id = res.json()["id"]

    res = client.post(f"/api/notebooks/{nb_id}/pages", json={"title": "Tokenization"})
    assert res.status_code == 201
    page_id = res.json()["id"]

    # 2. Draw initial element: id="token_box"
    initial_svg = '<g id="token_box"><rect x="100" y="100" width="120" height="60" fill="#3b82f6" /><text x="110" y="135">Token</text></g>'
    res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/draw",
        json={
            "element_id": "token_box",
            "svg_fragment": initial_svg,
            "narration": "Here is the token box representing an identified token."
        }
    )
    assert res.status_code == 200, f"Draw failed: {res.text}"
    print("  PASS element 'token_box' drawn")

    # Verify draw event in DB
    with Session(engine) as db:
        draw_event = db.exec(
            select(PageEvent).where(PageEvent.page_id == page_id, PageEvent.kind == "draw")
        ).first()
        assert draw_event is not None
        assert draw_event.element_id == "token_box"
        assert draw_event.seq == 1
        assert "token_box" in draw_event.svg_fragment

    # 3. Modify the existing element: correct fill to red, change width, preserve same id="token_box"
    modified_svg = '<g id="token_box"><rect x="100" y="100" width="180" height="60" fill="#ef4444" /><text x="110" y="135">Identifier Token</text></g>'
    res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/modify",
        json={
            "element_id": "token_box",
            "new_svg_fragment": modified_svg
        }
    )
    assert res.status_code == 200, f"Modify failed: {res.text}"
    print("  PASS element 'token_box' modified")

    # 4. Verify DB PageEvent row for modify
    with Session(engine) as db:
        events = db.exec(
            select(PageEvent).where(PageEvent.page_id == page_id).order_by(PageEvent.seq)
        ).all()
        assert len(events) == 2, f"Expected 2 events, got {len(events)}"

        # Event 1: draw
        ev1 = events[0]
        assert ev1.seq == 1
        assert ev1.kind == "draw"
        assert ev1.element_id == "token_box"

        # Event 2: modify
        ev2 = events[1]
        assert ev2.seq == 2
        assert ev2.kind == "modify"
        assert ev2.element_id == "token_box", "Element ID must be preserved exactly"
        assert ev2.old_svg_fragment is not None, "old_svg_fragment must be recorded for audit"
        assert 'id="token_box"' in ev2.old_svg_fragment
        assert '#3b82f6' in ev2.old_svg_fragment or 'fill' in ev2.old_svg_fragment
        assert 'id="token_box"' in ev2.svg_fragment
        assert '#ef4444' in ev2.svg_fragment or '180' in ev2.svg_fragment
        print(f"  PASS PageEvent kind='modify' verified (seq={ev2.seq}, element_id='{ev2.element_id}')")
        print(f"       old_svg_fragment: {ev2.old_svg_fragment.strip()}")
        print(f"       new_svg_fragment: {ev2.svg_fragment.strip()}")

    # 5. Verify modifying a non-existent element is rejected
    res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/modify",
        json={
            "element_id": "non_existent_element",
            "new_svg_fragment": '<rect id="non_existent_element" x="0" y="0" width="10" height="10" />'
        }
    )
    assert res.status_code == 400
    assert "does not exist on this page" in res.json()["detail"]
    print("  PASS non-existent element modification rejected with 400")


def test_savelock_invariant():
    print("\n--- Test 2: Save-Lock Invariant ---")
    # 1. Create a notebook and active page
    res = client.post("/api/notebooks", json={"topic": "Database Internals", "title": "B-Tree Indexes"})
    assert res.status_code == 201
    nb_id = res.json()["id"]

    res = client.post(f"/api/notebooks/{nb_id}/pages", json={"title": "Root Node"})
    assert res.status_code == 201
    page_id = res.json()["id"]

    # 2. Draw initial node
    res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/draw",
        json={
            "element_id": "b_root",
            "svg_fragment": '<circle id="b_root" cx="600" cy="200" r="50" fill="#10b981" />',
            "narration": "Here is the B-Tree root node."
        }
    )
    assert res.status_code == 200
    print("  PASS initial element drawn on active page")

    # 3. Save the page (locks the page)
    res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/save",
        json={"summary": "B-Tree root node completed."}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "saved"
    print("  PASS page successfully saved and locked")

    # Verify status in DB
    with Session(engine) as db:
        pg = db.get(Page, page_id)
        assert pg.status == "saved"

    # 4. Attempt to draw_new_element against saved page -> MUST REJECT
    res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/draw",
        json={
            "element_id": "child_node",
            "svg_fragment": '<circle id="child_node" cx="400" cy="400" r="40" fill="#6366f1" />',
            "narration": "Attempting to draw on a locked page."
        }
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    assert "saved and locked" in res.json()["detail"].lower()
    print("  PASS draw_new_element against saved page REJECTED (HTTP 400)")

    # 5. Attempt to modify_existing_element against saved page -> MUST REJECT
    res = client.post(
        f"/api/notebooks/{nb_id}/pages/{page_id}/modify",
        json={
            "element_id": "b_root",
            "new_svg_fragment": '<circle id="b_root" cx="600" cy="200" r="70" fill="#ef4444" />'
        }
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    assert "saved and locked" in res.json()["detail"].lower()
    print("  PASS modify_existing_element against saved page REJECTED (HTTP 400)")

    # 6. Attempt chat targeting saved page -> MUST REJECT
    res = client.post(
        f"/api/notebooks/{nb_id}/chat",
        json={
            "message": "Add another child node",
            "page_id": page_id
        }
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    assert "saved and locked" in res.json()["detail"].lower()
    print("  PASS chat targeting saved page REJECTED (HTTP 400)")

    # 7. Confirm no events were added after the save
    with Session(engine) as db:
        events = db.exec(
            select(PageEvent).where(PageEvent.page_id == page_id)
        ).all()
        assert len(events) == 1, f"Expected exactly 1 event (the initial draw), found {len(events)}"
        print("  PASS DB event count unchanged (no leak into locked page)")


if __name__ == "__main__":
    test_modify_existing_element_lifecycle()
    test_savelock_invariant()
    print("\nAll modify and save-lock invariant tests PASS [OK]")
