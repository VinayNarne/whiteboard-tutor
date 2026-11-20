"""
The development-only Gemini launcher (scripts/dev_gemini.py). No network and no real key: every client is a stub.

What must hold:
  * drawing calls go to gemini-3.8-flash, page summaries and every other call keep the Azure deployment, an unknown model name is an error, and a failed Gemini call
    is an error (never a silent GPT-4.1);
  * the launcher refuses to start, naming the problem and never a secret, when the Gemini key or the Azure settings are missing, the shadow validator is off, the
    database is not on this machine, the port is taken, or the routing cannot be verified;
  * it starts the app in-process without reload, prints the mode and models, writes one `dev_gemini_active` record, and uses the log the report script reads;
  * through the REAL author loop, summary path and shadow hook: Gemini draws, Azure summarises, the shadow record carries `connector_text`, and a diagnostic exception changes
    neither the reply, nor the stored drawings, nor which model was called.
"""
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import engine.author as au
import engine.connector_text as ct
import engine.shadow as shadow
from core.events import EngineEvent
from test_shadow_hook import _tc, fake_tts
from test_shape_model import g

ROOT = Path(__file__).parent.parent
GEM_SECRET, AZ_SECRET, DB_SECRET = "gem-secret-1234", "az-secret-5678", "db-secret-9012"
GOOD_ENV = {"GEMINI_API_KEY": GEM_SECRET, "AZURE_OPENAI_API_KEY": AZ_SECRET, "AZURE_OPENAI_ENDPOINT": "https://example.invalid/",
            "DATABASE_URL": f"postgresql://postgres:{DB_SECRET}@127.0.0.1:5432/learning_platform"}


@pytest.fixture(scope="module")
def dg():
    spec = importlib.util.spec_from_file_location("dev_gemini", ROOT / "scripts" / "dev_gemini.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def restore_author(monkeypatch):
    """Whatever a test installs into engine.author is undone afterwards."""
    monkeypatch.setattr(au, "get_azure_client", au.get_azure_client)
    monkeypatch.setattr(au, "AUTHOR_DEPLOYMENT", au.AUTHOR_DEPLOYMENT)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stub:
    """A model client that records every call and answers with `reply` or raises `error`."""

    def __init__(self, name, reply="ok", error=None):
        self.name, self.calls, self.reply, self.error = name, [], reply, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))], model=self.name)


def router(dg, gem, az, azure="gpt-4.1"):
    return dg.RoutingClient(dg.DRAW_MODEL, {azure}, lambda: gem, lambda: az)


# ---- routing ------------------------------------------------------------------------------------------------------------------------------------
def test_the_drawing_model_goes_to_gemini_and_the_azure_deployment_to_azure_with_every_argument_passed_on(dg):
    gem, az = Stub("gemini-3.8-flash"), Stub("gpt-4.1")
    r = router(dg, gem, az)
    r.chat.completions.create(model="gemini-3.8-flash", messages=[{"role": "user", "content": "draw"}], tools=[{"x": 1}], tool_choice="auto", temperature=0.7, max_tokens=6000)
    r.chat.completions.create(model="gpt-4.1", messages=[{"role": "user", "content": "sum"}], temperature=0, max_tokens=120, timeout=12.0)
    assert [c["model"] for c in gem.calls] == ["gemini-3.8-flash"] and gem.calls[0]["tools"] == [{"x": 1}] and gem.calls[0]["max_tokens"] == 6000 and gem.calls[0]["tool_choice"] == "auto"
    assert [c["model"] for c in az.calls] == ["gpt-4.1"] and az.calls[0]["timeout"] == 12.0 and az.calls[0]["max_tokens"] == 120


def test_a_failed_gemini_call_is_an_error_and_never_retried_on_azure(dg):
    gem, az = Stub("g", error=RuntimeError("quota")), Stub("a")
    with pytest.raises(RuntimeError, match="quota"):
        router(dg, gem, az).chat.completions.create(model="gemini-3.8-flash", messages=[])
    assert az.calls == [] and len(gem.calls) == 1


@pytest.mark.parametrize("model", ["gpt-4o-mini", "gemini-4-argon", "", None, "GEMINI-3.8-FLASH"])
def test_an_unexpected_model_name_is_an_error_not_a_silent_choice(dg, model):
    gem, az = Stub("g"), Stub("a")
    with pytest.raises(dg.ConfigError):
        router(dg, gem, az).chat.completions.create(model=model, messages=[])
    assert gem.calls == [] and az.calls == []


def test_the_underlying_clients_are_created_only_when_first_used(dg):
    made = []
    r = dg.RoutingClient(dg.DRAW_MODEL, {"gpt-4.1"}, lambda: made.append("gemini") or Stub("g"), lambda: made.append("azure") or Stub("a"))
    assert made == []
    r.chat.completions.create(model="gpt-4.1", messages=[])
    r.chat.completions.create(model="gpt-4.1", messages=[])
    assert made == ["azure"], "one Azure client, no Gemini client unless a drawing call is made"


def test_install_overrides_only_the_two_names_in_engine_author_and_nothing_in_the_environment(dg, restore_author):
    before_env, before_deployment = dict(os.environ), au.AZURE_OPENAI_DEPLOYMENT
    s = dg.Settings(azure_deployment=au.AZURE_OPENAI_DEPLOYMENT)
    r = dg.install(au, s, gemini_factory=lambda: Stub("g"), azure_factory=lambda: Stub("a"))
    assert au.AUTHOR_DEPLOYMENT == "gemini-3.8-flash" and au.get_azure_client() is r
    assert au.AZURE_OPENAI_DEPLOYMENT == before_deployment, "the summary deployment is untouched"
    assert dict(os.environ) == before_env, "nothing is written to the environment"
    assert r.route_for(au.AZURE_OPENAI_DEPLOYMENT) == "azure" and r.route_for(au.AUTHOR_DEPLOYMENT) == "gemini"


def test_install_refuses_and_changes_nothing_when_the_routing_cannot_be_told_apart(dg):
    fake = SimpleNamespace(get_azure_client=lambda: "original", AUTHOR_DEPLOYMENT="original-deployment", AZURE_OPENAI_DEPLOYMENT="gemini-3.8-flash")
    with pytest.raises(dg.ConfigError):
        dg.install(fake, dg.Settings(azure_deployment="gemini-3.8-flash"))
    assert fake.get_azure_client() == "original" and fake.AUTHOR_DEPLOYMENT == "original-deployment"


# ---- start-up checks ----------------------------------------------------------------------------------------------------------------------------
def verified(dg, monkeypatch, env=None, port=None):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("LP_SHADOW_VALIDATOR", raising=False)
    return dg.verify(au, dict(GOOD_ENV if env is None else env), port=port or free_port())


def test_a_good_configuration_is_accepted_and_describes_itself_without_secrets(dg, monkeypatch):
    s = verified(dg, monkeypatch)
    assert s.draw_model == "gemini-3.8-flash" and s.azure_deployment == au.AZURE_OPENAI_DEPLOYMENT
    assert DB_SECRET not in s.database and "127.0.0.1:5432/learning_platform" in s.database
    assert Path(s.log_file).resolve() == (ROOT / "logs" / "learning_platform.jsonl").resolve()
    text = dg.banner(s)
    for must in ("DEVELOPMENT ONLY", "gemini-3.8-flash", au.AZURE_OPENAI_DEPLOYMENT, "Shadow validator:     ON", "Auto-reload:          OFF", "localhost:5173", "learning_platform.jsonl"):
        assert must in text, must
    assert GEM_SECRET not in text and AZ_SECRET not in text and DB_SECRET not in text


@pytest.mark.parametrize("drop, expect", [
    ("GEMINI_API_KEY", "GEMINI_API_KEY"), ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"), ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_ENDPOINT")])
def test_a_missing_key_or_endpoint_refuses_to_start(dg, monkeypatch, drop, expect):
    env = {k: v for k, v in GOOD_ENV.items() if k != drop}
    with pytest.raises(dg.ConfigError) as e:
        verified(dg, monkeypatch, env)
    assert any(expect in p for p in e.value.problems)


def test_a_blank_gemini_key_refuses_to_start_and_says_there_is_no_fallback(dg, monkeypatch):
    with pytest.raises(dg.ConfigError) as e:
        verified(dg, monkeypatch, {**GOOD_ENV, "GEMINI_API_KEY": "   "})
    assert "no fallback" in " ".join(e.value.problems)


def test_a_switched_off_shadow_validator_refuses_to_start(dg, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("LP_SHADOW_VALIDATOR", "0")
    with pytest.raises(dg.ConfigError) as e:
        dg.verify(au, dict(GOOD_ENV), port=free_port())
    assert any("shadow validator" in p for p in e.value.problems)


@pytest.mark.parametrize("url", ["postgresql://u:p@db.example.com:5432/learning_platform", "postgresql://u:p@10.0.0.7/x", "postgres://u:p@prod-db/x"])
def test_a_database_that_is_not_on_this_machine_refuses_to_start(dg, monkeypatch, url):
    with pytest.raises(dg.ConfigError) as e:
        verified(dg, monkeypatch, {**GOOD_ENV, "DATABASE_URL": url})
    assert any("not at this machine" in p for p in e.value.problems) and "p@" not in " ".join(e.value.problems)


@pytest.mark.parametrize("url", [None, "", "sqlite:///./learning_platform.db", "postgresql://postgres:x@localhost/learning_platform", "postgresql://postgres:x@127.0.0.1/learning_platform"])
def test_local_databases_are_accepted(dg, monkeypatch, url):
    env = {k: v for k, v in GOOD_ENV.items() if k != "DATABASE_URL"}
    if url is not None:
        env["DATABASE_URL"] = url
    assert verified(dg, monkeypatch, env).database


def test_a_port_that_is_in_use_refuses_to_start_instead_of_starting_a_second_server(dg, monkeypatch):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        with pytest.raises(dg.ConfigError) as e:
            verified(dg, monkeypatch, port=busy.getsockname()[1])
    assert any("already in use" in p and "stop the running backend" in p for p in e.value.problems)


def test_all_problems_are_listed_together_and_no_secret_is_in_any_of_them(dg, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("LP_SHADOW_VALIDATOR", "off")
    env = {"AZURE_OPENAI_API_KEY": AZ_SECRET, "DATABASE_URL": f"postgresql://postgres:{DB_SECRET}@db.example.com/x"}
    with pytest.raises(dg.ConfigError) as e:
        dg.verify(au, env, port=free_port())
    text = str(e.value) + " ".join(e.value.problems)
    assert len(e.value.problems) >= 4 and not any(s in text for s in (GEM_SECRET, AZ_SECRET, DB_SECRET))


def test_the_log_the_launcher_names_is_the_log_the_server_writes_and_the_report_reads(dg):
    import backend.main as bm
    import inspect
    assert 'logs/learning_platform.jsonl' in inspect.getsource(bm.on_startup), "the server opens this log at start-up (relative to the working directory, which the launcher fixes)"
    assert dg.report_log_path().resolve() == dg.LOG_FILE.resolve()


def test_a_working_directory_other_than_the_repository_root_refuses_to_start(dg, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LP_SHADOW_VALIDATOR", raising=False)
    with pytest.raises(dg.ConfigError) as e:
        dg.verify(au, dict(GOOD_ENV), port=free_port())
    assert any("working directory" in p for p in e.value.problems)


# ---- main() -------------------------------------------------------------------------------------------------------------------------------------
def run_main(dg, monkeypatch, env):
    import backend.main as bm
    import uvicorn
    monkeypatch.setattr(au, "get_azure_client", au.get_azure_client)
    monkeypatch.setattr(au, "AUTHOR_DEPLOYMENT", au.AUTHOR_DEPLOYMENT)
    monkeypatch.setattr(bm, "on_startup", lambda: None)
    monkeypatch.setattr(dg, "_load_env", lambda: None)
    monkeypatch.setattr(dg, "PORT", free_port())
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("LP_SHADOW_VALIDATOR", raising=False)
    for k in ("GEMINI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
        if k in env:
            monkeypatch.setenv(k, env[k])
    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update(app=app, **kw))
    return dg.main(), captured, bm


def test_main_starts_the_app_in_process_without_reload_after_installing_the_override(dg, monkeypatch, capsys):
    rc, captured, bm = run_main(dg, monkeypatch, GOOD_ENV)
    assert rc == 0 and captured["app"] is bm.app and captured["host"] == "127.0.0.1" and captured["reload"] is False and captured["port"] == dg.PORT
    assert au.AUTHOR_DEPLOYMENT == "gemini-3.8-flash"
    out = capsys.readouterr().out
    assert "DEVELOPMENT ONLY" in out and "gemini-3.8-flash" in out and GEM_SECRET not in out + capsys.readouterr().err


def test_main_writes_one_development_mode_record_after_the_apps_own_start_up(dg, monkeypatch):
    rc, _, bm = run_main(dg, monkeypatch, GOOD_ENV)
    logged = []
    fake = SimpleNamespace(info=lambda ev, msg, data=None, **k: logged.append((ev, msg, data)))
    with patch("core.log.get_logger", lambda service: fake):
        bm.on_startup()
    assert len(logged) == 1 and logged[0][0] == "dev_gemini_active"
    d = logged[0][2]
    assert d["mode"] == "development-only" and d["drawing_model"] == "gemini-3.8-flash" and d["reload"] is False and d["shadow_validator"] is True
    assert GEM_SECRET not in json.dumps(d) and DB_SECRET not in json.dumps(d)


def test_main_refuses_without_the_gemini_key_starts_nothing_and_changes_nothing(dg, monkeypatch, capsys):
    before = (au.get_azure_client, au.AUTHOR_DEPLOYMENT)
    rc, captured, _ = run_main(dg, monkeypatch, {k: v for k, v in GOOD_ENV.items() if k != "GEMINI_API_KEY"})
    err = capsys.readouterr().err
    assert rc == 2 and captured == {} and "NOT STARTED" in err and "GEMINI_API_KEY" in err and AZ_SECRET not in err
    assert (au.get_azure_client, au.AUTHOR_DEPLOYMENT) == before, "no override was installed"


# ---- the real author loop, summary path and shadow hook ---------------------------------------------------------------------------------------------
EDGE = g("edge", '<line x1="600" y1="420" x2="900" y2="420" stroke="#000" stroke-width="3"/><text x="750" y="425" font-size="16" text-anchor="middle">Fail</text>')
BOX = g("box", '<rect x="100" y="100" width="220" height="80" fill="#eef" stroke="#00f"/><text x="210" y="145" font-size="18" text-anchor="middle">Hello</text>')


class Scripted:
    """A scripted model: one tool-call round per draw, then a final answer; records every call."""

    def __init__(self, name):
        self.name, self.calls = name, []
        rounds = [[("draw_new_element", {"element_id": "box", "svg_fragment": BOX, "narration": "[[MARK:box]] A box."})],
                  [("draw_new_element", {"element_id": "edge", "svg_fragment": EDGE, "narration": "[[MARK:edge]] An arrow label."})]]
        msgs = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(content=None, tool_calls=[_tc(i, n, a) for i, (n, a) in enumerate(r)]))], usage=None, model=name)
                for r in rounds]
        msgs.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="Done.", tool_calls=None))], usage=None, model=name))
        self._it = iter(msgs)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return next(self._it)


def one_turn(api, dg, monkeypatch, raise_in_diagnostic):
    client, _ = api
    import backend.page_summary as page_summary
    gem, az = Scripted("gemini-3.8-flash"), Stub("gpt-4.1", reply="The learner saw a box and a labelled arrow.")
    monkeypatch.setattr(page_summary, "CLIENT_FACTORY", None)                  # the production default: the summary asks engine.author.get_azure_client()
    dg.install(au, dg.Settings(azure_deployment=au.AZURE_OPENAI_DEPLOYMENT), gemini_factory=lambda: gem, azure_factory=lambda: az)
    logged = []
    nb = client.post("/api/notebooks", json={"topic": "Routing"}).json()["id"]
    with patch.object(shadow.logger, "info", lambda ev, msg, data=None, **k: logged.append((ev, data))), patch("engine.author.generate_narration_audio", side_effect=fake_tts):
        if raise_in_diagnostic:
            with patch.object(ct, "analyse", side_effect=RuntimeError("boom")):
                r = client.post(f"/api/notebooks/{nb}/chat", json={"message": "draw"})
        else:
            r = client.post(f"/api/notebooks/{nb}/chat", json={"message": "draw"})
    page = client.get(f"/api/notebooks/{nb}").json()["pages"][0]
    events = client.get(f"/api/notebooks/{nb}/pages/{page['id']}/events").json()
    events = events["events"] if isinstance(events, dict) and "events" in events else events
    stored = [(e["kind"], e["element_id"], e["svg_fragment"]) for e in events]
    chat_gem, chat_az = len(gem.calls), len(az.calls)
    saved = client.post(f"/api/notebooks/{nb}/pages/{page['id']}/save", json={})
    summary = client.get(f"/api/notebooks/{nb}").json()["pages"][0].get("summary")
    return {"status": r.status_code, "reply": r.json().get("response"), "stored": stored, "gem_models": [c["model"] for c in gem.calls[:chat_gem]], "az_during_chat": chat_az,
            "az_models_after_save": [c["model"] for c in az.calls], "gem_calls_after_save": len(gem.calls) - chat_gem, "save": saved.status_code, "summary": summary,
            "records": [d for ev, d in logged if ev == EngineEvent.SHADOW_VALIDATED]}


def test_a_whole_turn_draws_with_gemini_flash_summarises_with_azure_and_records_the_diagnostic(api, dg, monkeypatch, restore_author):
    t = one_turn(api, dg, monkeypatch, raise_in_diagnostic=False)
    assert t["status"] == 200 and t["reply"] == "Done." and [s[1] for s in t["stored"]] == ["box", "edge"]
    assert t["gem_models"] == ["gemini-3.8-flash"] * 3, "every drawing-author call (two draws and the final answer) went to Gemini Flash"
    assert t["az_during_chat"] == 0, "no Azure call while the board was written"
    assert t["save"] == 200 and t["az_models_after_save"] == [au.AZURE_OPENAI_DEPLOYMENT] and t["gem_calls_after_save"] == 0, "the page summary used Azure, not Gemini"
    assert t["summary"] == "The learner saw a box and a labelled arrow."
    recs = {r["element_id"]: r for r in t["records"]}
    assert set(recs) == {"box", "edge"} and recs["edge"]["connector_text"]["body"] == 1 and recs["box"]["connector_text"]["body"] == 0
    assert "Fail" not in json.dumps(recs) and "<line" not in json.dumps(recs), "no label text or SVG in the records"


def test_a_diagnostic_exception_changes_neither_the_reply_nor_the_stored_drawings_nor_the_model_used(api, dg, monkeypatch, restore_author):
    ok = one_turn(api, dg, monkeypatch, raise_in_diagnostic=False)
    bad = one_turn(api, dg, monkeypatch, raise_in_diagnostic=True)
    for key in ("status", "reply", "gem_models", "az_during_chat", "az_models_after_save", "save", "summary"):
        assert ok[key] == bad[key], key
    assert [(k, e, s) for k, e, s in ok["stored"]] == [(k, e, s) for k, e, s in bad["stored"]], "the same drawings were stored"
    assert len(bad["records"]) == len(ok["records"]) == 2 and all(r.get("connector_text_error") == "RuntimeError" and "connector_text" not in r for r in bad["records"])
    assert [r["proposed"] for r in ok["records"]] == [r["proposed"] for r in bad["records"]]
