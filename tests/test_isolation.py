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


def test_publishing_an_element_leaves_the_real_output_dir_untouched():
    import asyncio
    from unittest.mock import patch
    from engine.author import publish_element

    real = Path(__file__).parent.parent / "generated_notebooks"
    before = {p.name for p in real.iterdir()} if real.exists() else set()

    async def emit(*a, **k): pass
    async def persist(**k): pass
    frag = '<g id="iso"><rect x="100" y="100" width="300" height="80"/><text x="120" y="140">Hi</text></g>'
    with patch("engine.author.generate_narration_audio", return_value=(1.0, 5, {"is_synthetic": False})):
        asyncio.run(publish_element("iso_nb", "iso_pg", "iso", frag, "Hi.", emit, persist))
    after = {p.name for p in real.iterdir()} if real.exists() else set()
    assert after == before and "iso_nb" not in after
