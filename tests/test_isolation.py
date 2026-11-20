"""The test suite must not write into the real output folder or a real database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_tests_use_a_temp_output_dir_and_a_test_database():
    import backend.main as bm
    import engine.author as author
    from backend.database import engine as db_engine

    real = Path(__file__).parent.parent / "generated_notebooks"
    assert bm.OUTPUT_DIR != real and author.OUTPUT_DIR != real
    assert bm.OUTPUT_DIR == author.OUTPUT_DIR
    name = str(db_engine.url.database)
    assert name.endswith("_test") or str(db_engine.url).startswith("sqlite"), name


def test_a_draw_through_the_handler_leaves_the_real_output_dir_untouched():
    import asyncio
    from unittest.mock import patch
    from engine.author import _handle_draw_new_element

    real = Path(__file__).parent.parent / "generated_notebooks"
    before = {p.name for p in real.iterdir()} if real.exists() else set()

    async def emit(*a, **k): pass
    async def persist(**k): pass
    frag = '<g id="iso"><rect x="100" y="100" width="300" height="80"/><text x="120" y="140">Hi</text></g>'
    with patch("engine.author.generate_narration_audio", return_value=(1.0, 5, {"is_synthetic": False})):
        res = asyncio.run(_handle_draw_new_element("iso_nb", "iso_pg", "active", "iso", frag, "Hi.", None, emit, persist))
    assert res["status"] == "ok"
    after = {p.name for p in real.iterdir()} if real.exists() else set()
    assert after == before and "iso_nb" not in after


def test_eval_script_registers_notebooks_for_cleanup_before_any_turn_runs():
    src = (Path(__file__).parent / "eval_tutor.py").read_text(encoding="utf-8")
    create = src.index('requests.post(f"{API}/notebooks"')
    assert src.index("created.append(nb)") < src.index("for msg in (first, second)") and create < src.index("created.append(nb)")
