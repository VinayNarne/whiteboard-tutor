"""Delete endpoints work end to end (incl. audio cleanup) and every event constant used in code exists."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import init_db
import backend.main as bm
from core import events

init_db()
client = TestClient(app)
ROOT = Path(__file__).parent.parent


def test_every_referenced_event_constant_exists():
    pat = re.compile(r"\b(BackendEvent|EngineEvent|SessionEvent)\.([A-Z_]+)")
    missing = []
    for f in [*ROOT.glob("backend/*.py"), *ROOT.glob("engine/*.py"), *ROOT.glob("core/*.py")]:
        for cls, name in pat.findall(f.read_text(encoding="utf-8")):
            if not hasattr(getattr(events, cls), name):
                missing.append(f"{f.name}: {cls}.{name}")
    assert not missing, missing


def test_delete_page_and_notebook_remove_rows_and_audio():
    nb = client.post("/api/notebooks", json={"topic": "Delete me"}).json()["id"]
    pid = client.post(f"/api/notebooks/{nb}/pages", json={"title": "p"}).json()["id"]
    audio_dir = bm.OUTPUT_DIR / nb
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "x.mp3").write_bytes(b"x")

    assert client.delete(f"/api/notebooks/{nb}/pages/{pid}").status_code == 200
    assert client.delete(f"/api/notebooks/{nb}").status_code == 200
    assert client.get(f"/api/notebooks/{nb}").status_code == 404
    assert not audio_dir.exists()


def test_engine_survives_stale_connections():
    from backend.database import engine
    assert engine.pool._pre_ping is True and engine.pool._recycle == 1800
