"""
Control characters in board text are REPLACED by a visible placeholder (and counted in the log); real text is never touched.

Replaced: C0 controls except tab, newline and carriage return, DEL (0x7f), and the C1 range (0x80-0x9f), also when written as numeric
references. Seen in baselines C and H: the model emitted DEL where it meant an arrow ("lim (h <DEL> 0)") and NUL and STX where it meant
"x squared". They used to be deleted, which left "f(x) = x" on the board and nothing to show that anything was missing. Now the board
shows the placeholder and the tutor is told (tests/test_lost_content_message.py).
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EngineEvent
from engine.sanitiser import CONTROL_PLACEHOLDER as PH, replace_control_chars, sanitize_svg


def shown(raw):
    out = sanitize_svg(f'<g id="a"><text x="1" y="2">{raw}</text></g>')
    return "".join(t.text or "" for t in ET.fromstring(out).iter() if t.tag.endswith("text"))


def test_the_placeholder_is_the_unicode_replacement_character():
    assert PH == chr(0xFFFD)


# ---- a) control characters get the placeholder, one for one ----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("lim (h \x7f 0)", f"lim (h {PH} 0)"),                 # DEL, the real case from baseline C
    ("a\x00b", f"a{PH}b"),                                  # NUL
    ("esc\x1b[0m", f"esc{PH}[0m"),                          # ESC
    ("next\x85line", f"next{PH}line"),                      # C1: NEL
    ("a\x01\x02\x03b", f"a{PH * 3}b"),
    ("a\x0bb\x0cc", f"a{PH}b{PH}c"),                        # vertical tab, form feed
    ("a\x0eb\x1fc", f"a{PH}b{PH}c"),
    ("a\x80b\x9fc", f"a{PH}b{PH}c"),                        # both ends of the C1 range
    ("&#0;x&#127;y&#x1b;z&#133;", f"{PH}x{PH}y{PH}z{PH}"),  # written as numeric references
    ("f(x) = x\x00\x00", f"f(x) = x{PH}{PH}"),             # baseline H: the model's "x squared"
    ("lim h\x0218 0", f"lim h{PH}18 0"),                    # baseline H: the model's arrow
])
def test_control_characters_get_the_visible_placeholder(raw, expected):
    assert shown(raw) == expected


def test_each_listed_range_is_replaced_and_nothing_next_to_it():
    must_change = list(range(0, 9)) + [11, 12] + list(range(14, 32)) + list(range(127, 160))
    for code in must_change:
        assert replace_control_chars(f"a{chr(code)}b") == (f"a{PH}b", 1), hex(code)


def test_a_control_character_inside_a_tag_name_cannot_make_a_script_tag():
    """With the character deleted the name used to close up into <script> (and the allowlist removed it); with a placeholder it never
    becomes a tag at all: the text is escaped and inert."""
    out = sanitize_svg("<g id='a'><scr\x00ipt>alert(1)</scr\x00ipt><text x='1' y='2'>ok</text></g>")
    assert not any(el.tag.endswith("script") for el in ET.fromstring(out).iter())
    assert "<script" not in out and "ok" in out


# ---- b) real arrows, superscripts and other text survive untouched ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "→ ← ↔ ⇒",                    # arrows
    "x² x³ xⁿ m/s² 10⁻³ H₂O",    # superscripts and subscripts
    "café über naïve ñ",           # accents
    "नमस्ते दुनिया",               # Hindi
    "你好，世界",                     # Chinese
    "日本語 한국어 العربية",         # Japanese, Korean, Arabic
    "\U0001F600 \U0001F389 \U0001F9EA",           # emoji (outside the BMP)
    "plain words with   normal  spaces",
    " no-break space and   em space",   # 0xA0 is just above the C1 range: must stay
    "tab\there",
    "line one\nline two",
])
def test_real_text_survives(text):
    assert shown(text) == text
    assert replace_control_chars(text) == (text, 0)


def test_arrows_and_superscripts_written_as_entities_or_references_survive():
    assert shown("h &rarr; 0, x&sup2; and x&#178; and &#8594; and &#x2192;") == "h → 0, x² and x² and → and →"


def test_carriage_return_is_not_replaced():
    assert replace_control_chars("a\rb") == ("a\rb", 0)
    out = shown("a\r\nb")
    assert out.startswith("a") and out.endswith("b")      # the XML parser normalises the line ending; nothing is lost


def test_a_numeric_reference_to_normal_text_is_not_touched():
    assert shown("&#8594; &#233; &#9731;") == "→ é ☃"


# ---- the count is logged ---------------------------------------------------------------------------------------------

def test_the_count_is_logged_when_something_is_replaced():
    with patch("engine.sanitiser.logger") as log:
        shown("a\x7fb\x00c&#27;d")
    calls = [c for c in log.warn.call_args_list if c.args[0] == EngineEvent.CONTROL_CHARS_REPLACED]
    assert len(calls) == 1 and calls[0].kwargs["data"] == {"count": 3}


def test_nothing_is_logged_for_clean_text():
    with patch("engine.sanitiser.logger") as log:
        shown("→ café x² 你好 \U0001F600\ttab\nline")
    assert not log.warn.called
