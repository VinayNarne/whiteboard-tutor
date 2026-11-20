"""
Long sessions: what grows with the length of a notebook, and does each growth stay bounded?
Offline and free: the model is replaced by a recorder that captures exactly what would be sent, and the work runs
in-process on the isolated test database.

A learner who studies for hours ends up with dozens of pages and hundreds of chat turns. Every question must still
(1) send the model a prompt of bounded size, (2) answer quickly from the database, (3) load the notebook quickly.
"""
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.main as main
import engine.author as author
from backend.database import engine as db_engine
from backend.models import ChatTurn

PAGES, TURNS = 60, 400
SEED = {}   # timings gathered while building the notebook
LONG_SUMMARY = "Covered the idea in depth with several examples and a worked case. " * 30   # ~2,000 characters


@pytest.fixture(scope="module")
def long_notebook():
    # Drawing synthesises narration even when none is given: stub the speech call so this test is free and fast.
    mp = pytest.MonkeyPatch()
    mp.setattr(author, "generate_narration_audio", lambda text, audio, align, eid=None: (1.0, len(text), {"is_synthetic": False}))
    client = TestClient(main.app)
    draw_times = []
    nb = client.post("/api/notebooks", json={"topic": "Long session"}).json()["id"]
    page_ids = [client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]]
    for i in range(PAGES):
        if i:
            page_ids.append(client.post(f"/api/notebooks/{nb}/pages", json={"title": f"Concept {i + 1}"}).json()["id"])
        pid = page_ids[-1]
        for j in range(3):
            t0 = time.perf_counter()
            r = client.post(f"/api/notebooks/{nb}/pages/{pid}/draw", json={
                "element_id": f"p{i}_e{j}", "narration": "",
                "svg_fragment": f'<g id="p{i}_e{j}"><rect x="{80 + j * 300}" y="220" width="240" height="120"/>'
                                f'<text x="{110 + j * 300}" y="290" font-size="18">box {j}</text></g>'})
            draw_times.append(time.perf_counter() - t0)
            assert r.status_code == 200, r.text
        client.patch(f"/api/notebooks/{nb}/pages/{pid}", json={"title": f"Concept {i + 1}", "summary": LONG_SUMMARY[:2000]})
        if i < PAGES - 1:
            client.post(f"/api/notebooks/{nb}/pages/{pid}/save", json={})
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    with Session(db_engine) as db:
        for n in range(1, TURNS + 1):
            user = n % 2 == 1
            db.add(ChatTurn(notebook_id=nb, page_id=page_ids[n * PAGES // (TURNS + 1)], seq=n,
                            role="user" if user else "assistant",
                            content=("Can you go over this part again, with an example?" if user else
                                     "Here is the idea in plain words. " * 25),
                            timestamp=base + timedelta(minutes=n)))
        db.commit()
    SEED["draw_ms"] = [round(t * 1000) for t in draw_times]
    yield client, nb, page_ids
    client.delete(f"/api/notebooks/{nb}")
    mp.undo()


class _Recorder:
    """Stands in for the Azure client: records every prompt, answers with plain text (no drawing)."""

    def __init__(self):
        self.prompts = []
        msg = SimpleNamespace(content="Okay.", tool_calls=None)
        self.reply = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=msg)])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.prompts.append(kw["messages"])
        return self.reply


def _chars(messages):
    return sum(len(m["content"] if isinstance(m, dict) else (m.content or "")) for m in messages)


def test_a_question_deep_into_a_long_notebook_sends_a_bounded_prompt_quickly(long_notebook, monkeypatch):
    client, nb, page_ids = long_notebook
    rec = _Recorder()
    monkeypatch.setattr(author, "get_azure_client", lambda: rec)

    t0 = time.perf_counter()
    r = client.post(f"/api/notebooks/{nb}/chat", json={"message": "Next, what about the last idea?", "page_id": page_ids[-1]})
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200, r.text

    prompt = rec.prompts[0]
    size = _chars(prompt)
    context = next(m["content"] for m in prompt if m["role"] == "system" and m["content"].startswith("NOTEBOOK CONTEXT"))
    print(f"\n[long session] {PAGES} pages, {TURNS} turns -> prompt {size:,} chars "
          f"(notebook context {len(context):,}), chat answered in {elapsed:.2f}s")
    parts = context.split("CURRENT PAGE STATE:")
    print(f"[long session] context = prior-page lines {len(parts[0]):,} + current page state {len(parts[1]):,} chars")
    assert len(context) < 14_000, f"prior-page context grew with the notebook: {len(context):,} chars"
    assert size < 30_000, f"prompt grew with the notebook: {size:,} chars"
    assert "base64" not in "".join(m["content"] for m in prompt if isinstance(m, dict)),         "the embedded font reached the model (thousands of wasted tokens on every call)"
    assert sum(1 for m in prompt if m["role"] in ("user", "assistant")) <= 16        # 15 history turns + the new question
    assert elapsed < 3.0, f"a chat turn took {elapsed:.1f}s before the model was even called"


def test_the_prompt_stays_the_same_size_however_long_the_notebook_gets(long_notebook, monkeypatch):
    client, nb, page_ids = long_notebook
    rec = _Recorder()
    monkeypatch.setattr(author, "get_azure_client", lambda: rec)
    sizes = []
    for _ in range(3):
        client.post(f"/api/notebooks/{nb}/chat", json={"message": "And then?", "page_id": page_ids[-1]})
        sizes.append(_chars(rec.prompts[-1]))
    # each turn adds two chat turns to the notebook; history is capped, so the prompt must not climb
    assert max(sizes) - min(sizes) < 3_000, sizes


def test_loading_and_listing_a_long_notebook_is_fast(long_notebook):
    client, nb, page_ids = long_notebook

    def timed(url):
        t0 = time.perf_counter()
        r = client.get(url)
        assert r.status_code == 200, (url, r.text[:200])
        return time.perf_counter() - t0, len(r.content)

    for name, url, limit in [
        ("notebook (pages + all turns)", f"/api/notebooks/{nb}", 1.5),
        ("one page's events", f"/api/notebooks/{nb}/pages/{page_ids[30]}/events", 0.5),
        ("notebook list", "/api/notebooks", 0.5),
        ("export", f"/api/notebooks/{nb}/export", 3.0),
    ]:
        secs, size = timed(url)
        print(f"[long session] {name}: {secs * 1000:.0f} ms, {size / 1024:.0f} KB")
        assert secs < limit, f"{name} took {secs:.2f}s"


def test_drawing_stays_fast_as_the_notebook_grows(long_notebook):
    """Each page was built from the same three draws; the 60th page must not be slower than the 1st."""
    times = SEED["draw_ms"]
    first, last = sorted(times[:30])[15], sorted(times[-30:])[15]
    print(f"[long session] draw request, median: first pages {first} ms, last pages {last} ms")
    assert last < max(3 * first, 400), (first, last)


def test_the_model_never_sees_the_font_but_stored_drawings_keep_it(long_notebook):
    client, nb, page_ids = long_notebook
    stored = client.get(f"/api/notebooks/{nb}/pages/{page_ids[0]}/events").json()["events"][0]["svg_fragment"]
    assert "@font-face" in stored and len(stored) > 10_000       # exports and the board still render with the real font


def test_strip_embedded_fonts_removes_only_the_font():
    from engine.fonts import inject_trusted_font, strip_embedded_fonts
    drawing = '<g id="a"><rect x="10" y="10" width="50" height="30"/><text x="12" y="30">Hi</text></g>'
    with_font = inject_trusted_font(drawing)
    assert "base64" in with_font and len(with_font) > 10_000
    lean = strip_embedded_fonts(with_font)
    assert "base64" not in lean and "@font-face" not in lean
    assert '<rect x="10" y="10" width="50" height="30"' in lean and ">Hi</text>" in lean and 'id="a"' in lean
    assert strip_embedded_fonts(lean) == lean and strip_embedded_fonts(None) is None and strip_embedded_fonts("") == ""


def test_editing_drawings_does_not_pile_up_font_copies(monkeypatch):
    """Every edit used to add another ~16 KB copy of the font to the page: dozens of edits made pages megabytes big."""
    from backend.models import Page
    monkeypatch.setattr(author, "generate_narration_audio", lambda text, a, b, eid=None: (1.0, len(text), {"is_synthetic": False}))
    client = TestClient(main.app)
    nb = client.post("/api/notebooks", json={"topic": "Font copies"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]

    def box(eid, x, label):
        return (f'<g id="{eid}"><rect x="{x}" y="220" width="240" height="120"/>'
                f'<text x="{x + 30}" y="290" font-size="18">{label}</text></g>')

    def font_faces():
        with Session(db_engine) as db:
            return db.get(Page, pg).current_svg.count("base64,")

    try:
        for eid, x in (("a", 80), ("b", 400)):
            client.post(f"/api/notebooks/{nb}/pages/{pg}/draw", json={"element_id": eid, "svg_fragment": box(eid, x, eid), "narration": "x"})
        assert font_faces() == 2                                        # one copy = regular + bold
        for n, (eid, x) in enumerate((("b", 400), ("a", 80), ("b", 400), ("a", 80), ("b", 400))):
            r = client.post(f"/api/notebooks/{nb}/pages/{pg}/modify", json={"element_id": eid, "new_svg_fragment": box(eid, x, f"v{n}")})
            assert r.status_code == 200, r.text
            assert font_faces() == 2, f"font copies piled up after edit {n + 1}: {font_faces()} faces"
    finally:
        client.delete(f"/api/notebooks/{nb}")
