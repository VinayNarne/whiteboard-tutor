"""Browser errors reach the structured log (POST /api/client-log), tied to the notebook, size-capped, rate-limited, and never an error themselves."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import backend.main as bm
from backend.limits import CLIENT_LOG_LIMITER
from core.events import BackendEvent

client = TestClient(bm.app)


def _post(events):
    with patch("backend.main.logger") as log:
        r = client.post("/api/client-log", json={"events": events})
    return r, [c for c in log.warn.call_args_list if c.args and c.args[0] == BackendEvent.CLIENT_ERROR]


def test_an_error_is_logged_with_its_details_and_the_notebook():
    CLIENT_LOG_LIMITER.hits.clear()
    r, calls = _post([{"kind": "error", "message": "x is undefined", "source": "App.tsx:10:5", "stack": "at foo", "notebook_id": "nb1", "page_url": "http://localhost:5173/"},
                      {"kind": "http_error", "message": "POST /api/notebooks/nb1/chat -> 503", "status": 503}])
    assert r.status_code == 204 and len(calls) == 2
    assert calls[0].kwargs["session_id"] == "nb1" and calls[0].kwargs["data"]["source"] == "App.tsx:10:5" and "x is undefined" in calls[0].args[1]
    assert calls[1].kwargs["data"]["status"] == 503


def test_control_characters_are_replaced_and_oversize_text_is_refused():
    CLIENT_LOG_LIMITER.hits.clear()
    _, calls = _post([{"kind": "console.error", "message": "a" + chr(0) + "b"}])
    assert chr(0) not in calls[0].args[1] and "\ufffd" in calls[0].args[1]
    assert client.post("/api/client-log", json={"events": [{"kind": "error", "message": "x" * 5000}]}).status_code == 422
    assert client.post("/api/client-log", json={"events": [{"kind": "error"}] * 21}).status_code == 422


def test_too_many_batches_are_dropped_quietly():
    CLIENT_LOG_LIMITER.hits.clear()
    for _ in range(60):
        assert client.post("/api/client-log", json={"events": [{"kind": "error", "message": "m"}]}).status_code == 204
    r, calls = _post([{"kind": "error", "message": "one too many"}])
    assert r.status_code == 204 and calls == []
    CLIENT_LOG_LIMITER.hits.clear()
