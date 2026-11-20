"""
Which model writes the board is a setting (AZURE_OPENAI_AUTHOR_DEPLOYMENT), the default is unchanged, the judge does not
move with it, and every model call is logged with the model the service says it ran, so no run can be confused with another.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from core.events import EngineEvent
from engine import author

ROOT = Path(__file__).parent.parent


def _deployments(**env):
    """AUTHOR_DEPLOYMENT and AZURE_OPENAI_DEPLOYMENT as a fresh process reads them with this environment."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("AZURE_OPENAI_")}
    base.update(env)
    code = "import engine.author as a; print(a.AUTHOR_DEPLOYMENT + '|' + a.AZURE_OPENAI_DEPLOYMENT)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=base, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1].split("|")


def test_with_nothing_set_the_author_uses_the_same_deployment_as_before():
    author_dep, cheap = _deployments()          # .env sets AZURE_OPENAI_DEPLOYMENT only, not the author setting
    assert author_dep == cheap


def test_the_author_deployment_is_its_own_setting_and_the_cheap_one_does_not_move():
    author_dep, cheap = _deployments(AZURE_OPENAI_DEPLOYMENT="cheap-one", AZURE_OPENAI_AUTHOR_DEPLOYMENT="strong-one")
    assert (author_dep, cheap) == ("strong-one", "cheap-one")


def test_an_empty_setting_means_the_same_deployment_as_before():
    author_dep, cheap = _deployments(AZURE_OPENAI_DEPLOYMENT="cheap-one", AZURE_OPENAI_AUTHOR_DEPLOYMENT="")
    assert author_dep == cheap == "cheap-one"


class _Capture:
    def __init__(self):
        self.rows = []

    def info(self, event, message=None, data=None, **kw):
        self.rows.append((event, data))

    warn = error = debug = info


def test_the_author_call_uses_the_author_deployment_and_logs_the_model_the_service_ran(monkeypatch):
    calls = []
    msg = SimpleNamespace(content="Okay.", tool_calls=None)
    reply = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=msg)], model="strong-model-2026-01-01",
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=7, prompt_tokens_details=SimpleNamespace(cached_tokens=64)))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: calls.append(kw) or reply)))
    cap = _Capture()
    monkeypatch.setattr(author, "get_azure_client", lambda: client)
    monkeypatch.setattr(author, "AUTHOR_DEPLOYMENT", "my-author")
    monkeypatch.setattr(author, "AZURE_OPENAI_DEPLOYMENT", "my-cheap")
    monkeypatch.setattr(author, "logger", cap)

    out = asyncio.run(author.run_whiteboard_author("nb", "pg", "active", "hi", [], {"current_svg": ""}, "", set(),
                                                   emit_fn=None, persist_fn=None))
    assert out == "Okay."
    assert calls[0]["model"] == "my-author"
    usage = [d for e, d in cap.rows if e == EngineEvent.MODEL_USAGE]
    assert usage == [{"model": "strong-model-2026-01-01", "deployment": "my-author", "iteration": 0,
                      "prompt_tokens": 100, "completion_tokens": 7, "cached_tokens": 64}]


def test_the_model_name_falls_back_to_the_deployment_if_the_service_does_not_say(monkeypatch):
    msg = SimpleNamespace(content="Okay.", tool_calls=None)
    reply = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=msg)],
                            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: reply)))
    cap = _Capture()
    monkeypatch.setattr(author, "get_azure_client", lambda: client)
    monkeypatch.setattr(author, "AUTHOR_DEPLOYMENT", "my-author")
    monkeypatch.setattr(author, "logger", cap)
    asyncio.run(author.run_whiteboard_author("nb", "pg", "active", "hi", [], {"current_svg": ""}, "", set(),
                                             emit_fn=None, persist_fn=None))
    [data] = [d for e, d in cap.rows if e == EngineEvent.MODEL_USAGE]
    assert data["model"] == data["deployment"] == "my-author" and data["cached_tokens"] is None


def test_the_eval_judge_keeps_the_cheap_deployment_whatever_the_author_uses(monkeypatch):
    import eval_judge
    seen = []
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: seen.append(kw["model"]) or resp)))
    monkeypatch.setattr(author, "get_azure_client", lambda: client)
    monkeypatch.setattr(author, "AUTHOR_DEPLOYMENT", "strong-one")
    monkeypatch.setattr(author, "AZURE_OPENAI_DEPLOYMENT", "cheap-one")
    eval_judge.call_azure([{"role": "user", "content": "x"}])
    assert seen == ["cheap-one"]
