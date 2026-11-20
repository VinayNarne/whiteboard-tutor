"""
scripts/dev_gemini.py  --  DEVELOPMENT-ONLY launcher: the normal app, with Gemini 3.8 Flash writing the board.

    python scripts/dev_gemini.py        (from the repository root; serves http://127.0.0.1:8100, the port the frontend proxies to)

What it changes, in this one process only (nothing on disk, nothing in .env, no production default):
  * the drawing author (engine.author.run_whiteboard_author) calls `gemini-3.8-flash` on the Google Gemini API (OpenAI-compatible endpoint, key GEMINI_API_KEY from .env);
  * every other model call keeps its Azure deployment: page summaries still use AZURE_OPENAI_DEPLOYMENT (gpt-4.1 today).
One routing client does both, chosen by the model name of each call. A call for any other model name is an error, and a failed Gemini call is an error: nothing ever
falls back to GPT-4.1 for drawing.

What it does not change: .env, the database (DATABASE_URL, as the normal server), the log (logs/learning_platform.jsonl, which scripts/shadow_report.py reads), the
authoritative validator, the shadow validator (it must be ON: this launcher refuses to start with LP_SHADOW_VALIDATOR off, because collecting its records is the point),
the prompt, the renderer. It does not use --reload: the override lives in the process, and a reload would restart the app without it.

It refuses to start (and says why) when: GEMINI_API_KEY or the Azure key/endpoint is missing, the shadow validator is off, the database is not on this machine, the port is
already in use (stop the running backend first), or the routing cannot be verified. The check is local: no network call is made at start-up.

Start-up prints the mode and the models, and writes a `dev_gemini_active` record to the log. Afterwards `model_usage` events in the log name the model that really served
each drawing turn; `python scripts/shadow_report.py --since <date>` summarises the shadow records.
"""
import os
import socket
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DRAW_MODEL = "gemini-3.8-flash"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
HOST, PORT = "127.0.0.1", 8100
LOCAL_DB_HOSTS = {"", "127.0.0.1", "localhost", "::1"}
LOG_FILE = ROOT / "logs" / "learning_platform.jsonl"          # what backend.main writes (relative to the working directory) and scripts/shadow_report.py reads


class ConfigError(Exception):
    """The launcher cannot start safely. `problems` lists everything that is wrong, in plain words (never a secret)."""

    def __init__(self, problems: List[str]):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


@dataclass
class Settings:
    draw_model: str = DRAW_MODEL
    azure_deployment: str = ""
    database: str = ""
    log_file: str = ""
    port: int = PORT
    notes: List[str] = field(default_factory=list)


# ---- routing ---------------------------------------------------------------------------------------------------------------------------------
class RoutingClient:
    """Stands in for engine.author.get_azure_client(): the same `chat.completions.create` surface. The model name of a call decides where it goes:
    the drawing model to Gemini, the Azure deployment to Azure, anything else is an error. Nothing is retried elsewhere."""

    def __init__(self, draw_model: str, azure_models: set, gemini_factory: Callable, azure_factory: Callable):
        self.draw_model, self.azure_models = draw_model, set(azure_models)
        self._factories = {"gemini": gemini_factory, "azure": azure_factory}
        self._clients: dict = {}
        self._lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def route_for(self, model) -> str:
        if model == self.draw_model:
            return "gemini"
        if model in self.azure_models:
            return "azure"
        raise ConfigError([f"unexpected model name {model!r}: this launcher routes only {self.draw_model!r} (Gemini) and {sorted(self.azure_models)} (Azure)"])

    def _client(self, which: str):
        with self._lock:
            if which not in self._clients:
                self._clients[which] = self._factories[which]()
            return self._clients[which]

    def _create(self, **kw):
        return self._client(self.route_for(kw.get("model"))).chat.completions.create(**kw)


def gemini_client(au, env=None):
    """The real Gemini client: the OpenAI SDK against Google's OpenAI-compatible endpoint, with the app's own timeouts (as the benchmark did)."""
    import httpx
    from openai import OpenAI
    key = (env or os.environ).get("GEMINI_API_KEY")
    return OpenAI(api_key=key, base_url=GEMINI_BASE, timeout=httpx.Timeout(au.MODEL_TIMEOUT_S, connect=au.MODEL_CONNECT_TIMEOUT_S), max_retries=au.MODEL_MAX_RETRIES)


# ---- checks ----------------------------------------------------------------------------------------------------------------------------------
def check_database_url(url: Optional[str]) -> List[str]:
    """No DATABASE_URL = the app's own SQLite file (local). A Postgres URL must point at this machine."""
    if not url:
        return []
    from sqlalchemy.engine import make_url
    try:
        u = make_url(url)
    except Exception:
        return ["DATABASE_URL cannot be read"]
    if u.get_backend_name() == "sqlite":
        return []
    if (u.host or "") not in LOCAL_DB_HOSTS:
        return [f"DATABASE_URL points at {u.host!r}, not at this machine: refusing to run against a remote database"]
    return []


def redact_database(url) -> str:
    from sqlalchemy.engine import make_url
    return make_url(str(url)).render_as_string(hide_password=True) if url else "(app default: SQLite file)"


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def report_log_path() -> Path:
    """The log file scripts/shadow_report.py reads (it imports only the standard library at load time)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("shadow_report", ROOT / "scripts" / "shadow_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return Path(mod.LOG)


def verify(au, env=None, port: int = PORT) -> Settings:
    """Everything that can be checked without a network call. Raises ConfigError listing ALL problems; returns the settings otherwise."""
    env = os.environ if env is None else env
    problems: List[str] = []
    if not (env.get("GEMINI_API_KEY") or "").strip():
        problems.append("GEMINI_API_KEY is missing or empty (set it in .env): refusing to start; there is no fallback to GPT-4.1")
    for name in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        if not (env.get(name) or "").strip():
            problems.append(f"{name} is missing or empty: page summaries keep using Azure and would fail")
    if au.AZURE_OPENAI_DEPLOYMENT == DRAW_MODEL:
        problems.append(f"the Azure deployment is named {DRAW_MODEL!r}: the routing could not tell the two apart")
    import engine.shadow as shadow
    if not shadow.enabled():
        problems.append("the shadow validator is switched off (LP_SHADOW_VALIDATOR): this launcher exists to collect its records; unset the variable or set it to 1")
    problems += check_database_url(env.get("DATABASE_URL"))
    if not port_is_free(HOST, port):
        problems.append(f"port {port} is already in use: stop the running backend first (no second server is started)")
    try:
        reads = report_log_path().resolve()
    except Exception:
        reads = None
    if reads != LOG_FILE.resolve():
        problems.append(f"scripts/shadow_report.py reads {reads}, not {LOG_FILE}: the records would not be where the report looks")
    if Path(os.getcwd()).resolve() != ROOT:
        problems.append(f"the working directory is {os.getcwd()}, not the repository root: the log would not be written where the report reads it")
    if problems:
        raise ConfigError(problems)
    s = Settings(azure_deployment=au.AZURE_OPENAI_DEPLOYMENT, database=redact_database(env.get("DATABASE_URL")), log_file=str(LOG_FILE), port=port)
    if (env.get("AZURE_OPENAI_AUTHOR_DEPLOYMENT") or "").strip():
        s.notes.append("AZURE_OPENAI_AUTHOR_DEPLOYMENT is set; it is ignored in this mode (the drawing model is fixed to " + DRAW_MODEL + ")")
    return s


def install(au, settings: Settings, gemini_factory: Optional[Callable] = None, azure_factory: Optional[Callable] = None) -> RoutingClient:
    """Patch engine.author for this process: get_azure_client() returns the routing client, AUTHOR_DEPLOYMENT is the drawing model. Verifies the result; raises
    ConfigError (and leaves engine.author as it was) if the routing cannot be confirmed."""
    original = au.get_azure_client
    router = RoutingClient(settings.draw_model, {au.AZURE_OPENAI_DEPLOYMENT}, gemini_factory or (lambda: gemini_client(au)), azure_factory or original)
    if router.route_for(settings.draw_model) != "gemini" or router.route_for(au.AZURE_OPENAI_DEPLOYMENT) != "azure":
        raise ConfigError(["the routing could not be verified"])
    saved = (au.get_azure_client, au.AUTHOR_DEPLOYMENT)
    au.get_azure_client = lambda: router
    au.AUTHOR_DEPLOYMENT = settings.draw_model
    if au.AUTHOR_DEPLOYMENT != DRAW_MODEL or au.get_azure_client() is not router:
        au.get_azure_client, au.AUTHOR_DEPLOYMENT = saved
        raise ConfigError(["the model override did not take effect"])
    return router


def banner(s: Settings) -> str:
    lines = ["=" * 78,
             "  DEVELOPMENT ONLY: Gemini Flash is writing the board in this server process",
             f"  Drawing model:        {s.draw_model} (Google Gemini API, OpenAI-compatible endpoint; GEMINI_API_KEY from .env)",
             f"  Everything else:      Azure deployment {s.azure_deployment} (page summaries); no fallback between the two",
             f"  Database:             {s.database}",
             f"  Diagnostics log:      {s.log_file}",
             "  Shadow validator:     ON (connector_text diagnostic is log-only)",
             "  Auto-reload:          OFF (the override lives in this process)",
             f"  Open the app at:      http://localhost:5173   (backend http://{HOST}:{s.port})"]
    lines += [f"  Note:                 {n}" for n in s.notes]
    lines.append("=" * 78)
    return "\n".join(lines)


def announce_in_log(bm, s: Settings) -> None:
    """After the app's own start-up (which opens the log), write one record saying this server is the development-only Gemini one."""
    original = bm.on_startup

    def on_startup_with_dev_record():
        original()
        from core.log import get_logger
        get_logger("backend").info("dev_gemini_active", f"Development-only launcher: drawing model {s.draw_model}",
                                   data={"mode": "development-only", "drawing_model": s.draw_model, "other_models": f"azure:{s.azure_deployment}", "reload": False,
                                         "shadow_validator": True, "database": s.database, "pid": os.getpid()})
    bm.on_startup = on_startup_with_dev_record


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")


def main() -> int:
    os.chdir(ROOT)
    _load_env()
    sys.path.insert(0, str(ROOT))
    try:
        import engine.author as au
        settings = verify(au, port=PORT)
        install(au, settings)
        import backend.main as bm                                   # after the override: it opens the same database and log as the normal server
        eng = getattr(bm, "engine", None)
        if eng is None:
            raise ConfigError(["the app's database engine could not be found"])
        url = eng.url.render_as_string(hide_password=False)          # the database the app really opened, checked again after the import
        if check_database_url(url):
            raise ConfigError(check_database_url(url))
        settings.database = redact_database(url)
        announce_in_log(bm, settings)
    except ConfigError as e:
        print("dev_gemini: NOT STARTED", file=sys.stderr)
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    print(banner(settings), flush=True)
    import uvicorn
    uvicorn.run(bm.app, host=HOST, port=settings.port, reload=False, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
