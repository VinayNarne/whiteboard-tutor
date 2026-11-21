"""Sanitiser guards (XXE/DTD, size cap, built-in removal + resource-cap suites) and font-once-per-page."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import init_db
from engine import sanitiser
from engine.sanitiser import sanitize_svg

init_db()
client = TestClient(app)


def test_builtin_removal_and_cap_suites_pass():
    assert sanitiser._test_removal_rules()
    assert sanitiser._test_resource_caps()


def test_doctype_and_entities_rejected():
    xxe = ('<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           '<svg xmlns="http://www.w3.org/2000/svg"><text id="t">&x;</text></svg>')
    with pytest.raises(ValueError):
        sanitize_svg(xxe)


def test_oversized_input_rejected():
    with pytest.raises(sanitiser.SanitiserResourceCapError):
        sanitize_svg("<svg>" + "<g/>" * 200_000 + "</svg>")


def test_tts_retries_once_on_429_then_uses_audio():
    import base64
    from unittest.mock import MagicMock
    from engine import voice

    limited = MagicMock(status_code=429, text="slow down")
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": {}}
    with patch("requests.post", side_effect=[limited, ok]) as post, patch("time.sleep"), \
         patch.dict("os.environ", {"ELEVENLABS_API_KEY": "k"}):
        audio, _, _, fallback = voice._call_elevenlabs_tts("hello there")
    assert post.call_count == 2 and audio == b"mp3" and fallback is False
