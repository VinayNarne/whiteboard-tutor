"""
Postgres is optional: the default install (requirements.txt) has no psycopg2 and the app runs on SQLite; with a Postgres DATABASE_URL and no driver it stops
at start with a message that says what to install. Each case runs in a fresh interpreter in which importing psycopg2 is made to fail.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

BLOCK = '''
import sys
class _NoPsycopg2:
    def find_spec(self, name, path=None, target=None):
        if name == "psycopg2" or name.startswith("psycopg2."):
            raise ImportError("psycopg2 is not installed (blocked by this test)")
sys.meta_path.insert(0, _NoPsycopg2())
sys.path.insert(0, %r)
'''


def _run(code, env_url=None, tmp_path=None):
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "TEST_DATABASE_URL")}
    if env_url:
        env["DATABASE_URL"] = env_url
    return subprocess.run([sys.executable, "-c", BLOCK % str(ROOT) + code], cwd=tmp_path or ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_the_requirements_split_the_driver_out_of_the_default_install():
    default = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "psycopg2" not in default
    postgres = (ROOT / "requirements-postgres.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in postgres and "psycopg2-binary" in postgres
    assert "requirements-postgres.txt" in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")


def test_the_app_starts_and_works_on_sqlite_without_psycopg2(tmp_path):
    db = (tmp_path / "plain.db").as_posix()
    code = '''
from fastapi.testclient import TestClient
import backend.main as bm
with TestClient(bm.app) as c:
    assert c.get("/health").status_code == 200
    nb = c.post("/api/notebooks", json={"topic": "No Postgres"}).json()["id"]
    assert c.get("/api/notebooks/" + nb).json()["pages"][0]["page_number"] == 1
assert "psycopg2" not in sys.modules
print("OK")
'''
    r = _run(code, env_url=f"sqlite:///{db}", tmp_path=tmp_path)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-1500:]


def test_a_postgres_url_without_the_driver_stops_at_start_with_a_message_that_says_what_to_install(tmp_path):
    r = _run("import backend.database", env_url="postgresql://user:pw@127.0.0.1:5432/x", tmp_path=tmp_path)
    assert r.returncode != 0
    assert "points at Postgres" in r.stderr and "requirements-postgres.txt" in r.stderr and "unset DATABASE_URL" in r.stderr


def test_the_readme_says_sqlite_is_the_default_and_where_postgres_comes_from():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "SQLite by default" in readme and "pip install -r requirements-postgres.txt" in readme
