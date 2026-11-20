"""
The LOG-ONLY shadow hook (engine/shadow.py, docs/SHADOW_VALIDATOR.md).

What must hold: the hook never changes a drawing outcome (accepted or rejected, the message, what is stored, what is sent to the browser), whether it is on,
off, failing or too slow; it is easy to switch off; it writes compact records without drawing text; and its cost is bounded.
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import engine.author as au
import engine.shadow as shadow
from core.events import EngineEvent
from test_shape_model import AGENT_ARROWS, AGENT_PILLS, BOXES, FIXED_ARROWS, FIXED_PILLS, g, groupings, line


def fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def run_calls(calls, tmp_path, timings=None):
    """The real draw handler for a list of (element_id, fragment): outcomes, what was stored and what was sent to the browser."""
    state = {"svg": None}
    outcomes, stored, sent = [], [], []

    async def emit(event, payload=None):
        sent.append((str(event), sorted((payload or {}).keys())))

    async def persist(kind, element_id, svg_fragment, **k):
        stored.append((kind, element_id, svg_fragment, k.get("narration")))
        state["svg"] = (state["svg"] or "") + svg_fragment

    async def go():
        for eid, frag in calls:
            t0 = time.perf_counter()
            res = await au._handle_draw_new_element("nb", "pg", "active", eid, frag, f"[[MARK:{eid}]] Here.", state["svg"], emit, persist, {}, {})
            if timings is not None:
                timings.append(time.perf_counter() - t0)
            outcomes.append((eid, res["status"], res.get("detail", ""), res.get("layout_hint"), res.get("density_signal")))
    with patch.object(au, "generate_narration_audio", fake_tts), patch.object(au, "OUTPUT_DIR", tmp_path):
        asyncio.run(go())
    return outcomes, stored, sent


def scenarios():
    cases = {}
    for geometry, arrows, pills in (("drawn", AGENT_ARROWS, AGENT_PILLS), ("edge", FIXED_ARROWS, FIXED_PILLS)):
        for name, calls in groupings(arrows, pills).items():
            cases[f"six-box {name} {geometry}"] = [(f"e{i}", frag) for i, frag in enumerate(calls)]
    cases["plain card"] = [("card", g("card", '<rect x="100" y="100" width="200" height="80" fill="#eef" stroke="#00f"/><text x="200" y="145" font-size="18" text-anchor="middle">Hello</text>'))]
    cases["overlap rejected"] = [("a", g("a", '<rect x="100" y="100" width="300" height="200" fill="#eef"/>')), ("b", g("b", '<rect x="120" y="120" width="300" height="200" fill="#fee"/>'))]
    cases["bleeds the canvas"] = [("wide", g("wide", '<rect x="900" y="100" width="500" height="80" fill="#eef"/>'))]
    cases["transform"] = [("t", '<g id="t" transform="rotate(10)"><rect x="100" y="100" width="100" height="50"/></g>')]
    cases["labels overlap inside one call"] = [("l", g("l", '<text x="100" y="100" font-size="18">Alpha beta</text><text x="110" y="104" font-size="18">Alpha gamma</text>'))]
    cases["background frame"] = [("bg", g("bg", '<rect x="0" y="0" width="1200" height="800" fill="#fff"/>'))]
    cases["not even xml"] = [("junk", "<g id='junk'><rect x=")]
    return cases


def outcomes_with(monkeypatch, tmp_path, env):
    monkeypatch.setenv(shadow.ENV, env)
    return {name: run_calls(calls, tmp_path / env / name.replace(" ", "_")) for name, calls in scenarios().items()}


def test_switching_the_hook_on_or_off_changes_no_drawing_outcome_stored_content_or_browser_event(monkeypatch, tmp_path):
    on = outcomes_with(monkeypatch, tmp_path, "1")
    off = outcomes_with(monkeypatch, tmp_path, "0")
    assert on.keys() == off.keys() and len(on) >= 15
    for name in on:
        assert on[name] == off[name], name
    # the scenarios really exercise accepted and rejected drawings
    statuses = {s for out, _, _ in on.values() for _, s, *_ in out}
    assert statuses == {"ok", "error"}


def test_a_failing_shadow_check_changes_nothing_and_is_logged_once_per_drawing(monkeypatch, tmp_path):
    monkeypatch.setenv(shadow.ENV, "1")
    base = run_calls(scenarios()["six-box C drawn"], tmp_path / "base")
    events = []
    with patch.object(shadow, "compute", side_effect=RuntimeError("boom")), patch.object(shadow.logger, "warn", lambda ev, msg, **k: events.append(ev)):
        broken = run_calls(scenarios()["six-box C drawn"], tmp_path / "broken")
    assert broken == base
    assert events and set(events) == {EngineEvent.SHADOW_FAILED} and len(events) == len(base[0])


def test_a_slow_shadow_check_is_abandoned_after_its_time_limit_and_the_drawing_is_unaffected(monkeypatch, tmp_path):
    monkeypatch.setenv(shadow.ENV, "1")
    calls = scenarios()["plain card"]
    base = run_calls(calls, tmp_path / "base")
    seen = []
    with patch.object(shadow, "TIMEOUT_S", 0.05), patch.object(shadow, "compute", lambda *a: time.sleep(0.4)), patch.object(shadow.logger, "info", lambda ev, msg, **k: seen.append(ev)):
        timings = []
        slow = run_calls(calls, tmp_path / "slow", timings)
    assert slow == base and EngineEvent.SHADOW_SKIPPED in seen and EngineEvent.SHADOW_VALIDATED not in seen
    assert max(timings) < 0.3, ("the draw waited for the limit, not for the whole slow check", timings)


def test_the_switch_and_its_spellings(monkeypatch):
    monkeypatch.delenv(shadow.ENV, raising=False)
    assert shadow.enabled()
    for v in ("0", "off", "OFF", "false", "no"):
        monkeypatch.setenv(shadow.ENV, v)
        assert not shadow.enabled(), v
    for v in ("1", "on", "yes"):
        monkeypatch.setenv(shadow.ENV, v)
        assert shadow.enabled(), v


def capture(monkeypatch, tmp_path, calls, env="1"):
    monkeypatch.setenv(shadow.ENV, env)
    logged = []
    with patch.object(shadow.logger, "info", lambda ev, msg, data=None, **k: logged.append((ev, msg, data))):
        out = run_calls(calls, tmp_path)
    return logged, out


def test_one_compact_record_per_drawing_with_categories_verdicts_and_reasons_and_no_drawing_text(monkeypatch, tmp_path):
    calls = [(f"e{i}", f) for i, f in enumerate(groupings(AGENT_ARROWS, AGENT_PILLS)["A"])]
    logged, out = capture(monkeypatch, tmp_path, calls)
    recs = [d for ev, _, d in logged if ev == EngineEvent.SHADOW_VALIDATED]
    assert len(recs) == 1
    r = recs[0]
    assert r["existing"] == "accept" and r["proposed"] == "reject" and r["differs"] is True
    assert {"connector_through_node", "arrowhead_in_node", "region_overlap_hides"} <= set(r["reject_kinds"])
    assert "connector_through_label" in r["advisory_kinds"] and "connector_through_label" not in r["reject_kinds"], "label crossings are advisories"
    assert sum(r["roles"].values()) == r["shapes_new"] and r["roles"].get("connector", 0) == 11 and r["roles"].get("label", 0) >= 8, "the drawing is described by its shape roles"
    assert 0 < len(r["reasons"]) <= shadow.MAX_REASONS and r["reasons_total"] >= len(r["reasons"])
    assert r["ms"] >= 0 and r["wait_ms"] >= r["ms"] * 0 and r["shapes_new"] > 20 and r["page_id"] == "pg"
    blob = json.dumps(r)
    assert "User" not in blob and "Frontend" not in blob and "<rect" not in blob and "<polyline" not in blob, "no drawing text or source in the record"
    assert len(blob) < 3500


def test_the_record_pairs_the_existing_verdict_with_the_proposed_one_for_accepted_and_rejected_drawings(monkeypatch, tmp_path):
    boxes = g("boxes", BOXES)
    union_rejected = g("conn", "".join(line(a, sw=2, marker="arrow") for a in FIXED_ARROWS))
    logged, out = capture(monkeypatch, tmp_path, [("boxes", boxes), ("conn", union_rejected)])
    recs = {d["element_id"]: d for ev, _, d in logged if ev == EngineEvent.SHADOW_VALIDATED}
    assert recs["boxes"]["existing"] == "accept" and recs["boxes"]["proposed"] == "accept" and not recs["boxes"]["differs"]
    assert recs["conn"]["existing"] == "reject" and recs["conn"]["existing_reason"] == "overlap" and recs["conn"]["proposed"] == "accept" and recs["conn"]["differs"]
    assert [o[1] for o in out[0]] == ["ok", "error"], "the existing validator decided"


def test_no_records_when_off_and_none_for_drawings_rejected_before_the_sanitiser(monkeypatch, tmp_path):
    calls = scenarios()["plain card"]
    logged, _ = capture(monkeypatch, tmp_path, calls, env="0")
    assert not [1 for ev, *_ in logged if ev == EngineEvent.SHADOW_VALIDATED]
    logged, _ = capture(monkeypatch, tmp_path, scenarios()["transform"] + scenarios()["background frame"], env="1")
    assert not [1 for ev, *_ in logged if ev == EngineEvent.SHADOW_VALIDATED], "rejected by the transform and frame guards before the sanitiser: nothing to compare"


def test_pages_with_too_many_shapes_are_skipped_not_computed(monkeypatch, tmp_path):
    page = "".join(f'<g id="g{i}"><rect x="{(i % 40) * 28 + 10}" y="{(i // 40) * 28 + 10}" width="20" height="20" fill="#eee"/></g>' for i in range(610))
    rec = shadow.compute(page, g("new", '<rect x="1100" y="760" width="30" height="30" fill="#eee"/>'), "new")
    assert rec["proposed"] == "skipped" and rec["skipped"] == "too_many_shapes" and rec["existing"] in ("accept", "reject")


def test_the_cost_per_drawing_is_small_on_a_realistic_page():
    page = "".join(g(f"e{i}", BOXES) for i in range(1))
    t = []
    for _ in range(5):
        t0 = time.perf_counter()
        shadow.compute(page, g("c", "".join(line(a, sw=2, marker="arrow") for a in FIXED_ARROWS)), "c")
        t.append((time.perf_counter() - t0) * 1000)
    assert min(t) < 150, t


# ---- a full chat turn through the API: the same scripted model, hook on and off ---------------------------------------------------------------
def _tc(i, name, args):
    return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _model(rounds, final="Done."):
    out = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(content=None, tool_calls=[_tc(i, n, a) for i, (n, a) in enumerate(r)]))], usage=None, model="fake") for r in rounds]
    out.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=final, tool_calls=None))], usage=None, model="fake"))
    it, seen = iter(out), {"results": []}

    def create(**kw):
        seen["results"] = [json.loads(m["content"]) for m in kw["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
        return next(it)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), seen


def test_a_whole_chat_turn_gives_the_same_reply_results_and_stored_page_with_the_hook_on_or_off(api, monkeypatch):
    client, eng = api
    rounds = [[("draw_new_element", {"element_id": "boxes", "svg_fragment": g("boxes", BOXES), "narration": "[[MARK:boxes]] Six boxes."})],
              [("draw_new_element", {"element_id": "arrows", "svg_fragment": g("arrows", "".join(line(a, marker="arrow") for a in AGENT_ARROWS)), "narration": "[[MARK:arrows]] Arrows."})],
              [("draw_new_element", {"element_id": "ok", "svg_fragment": g("ok", '<rect x="100" y="500" width="200" height="60" fill="#eef"/>'), "narration": "[[MARK:ok]] A card."})]]
    result = {}
    for env in ("1", "0"):
        monkeypatch.setenv(shadow.ENV, env)
        nb = client.post("/api/notebooks", json={"topic": "Shadow"}).json()["id"]
        m, seen = _model(rounds)
        with patch("engine.author.get_azure_client", lambda: m), patch("engine.author.generate_narration_audio", side_effect=fake_tts):
            r = client.post(f"/api/notebooks/{nb}/chat", json={"message": "draw"})
        page = client.get(f"/api/notebooks/{nb}").json()["pages"][0]
        events = client.get(f"/api/notebooks/{nb}/pages/{page['id']}/events").json()
        events = events["events"] if isinstance(events, dict) and "events" in events else events
        stored = [(e["kind"], e["element_id"], e["svg_fragment"], e.get("narration")) for e in events]
        result[env] = (r.status_code, r.json().get("response"), [(x["status"], x.get("detail")) for x in seen["results"]], stored)
    assert result["1"] == result["0"]
    assert [e[1] for e in result["1"][3]] == ["boxes", "ok"], "the boxes and the card were drawn, the arrows were rejected (union box), with the hook on or off"
