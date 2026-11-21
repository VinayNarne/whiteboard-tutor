"""
Board text must survive the sanitiser, and the sanitiser must still strip everything dangerous.

Why: a model writing code or arrows in board text produces raw "<", "<=", "&" and HTML entity names like &rarr;, none of
which are valid XML. The old preflight turned &rarr; into the literal text "&amp;rarr;", and the recovery parser silently
deleted a raw "<" ("low <= high" became "low = high"). Now the text is repaired before parsing.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.sanitiser import sanitize_svg


def board_text(fragment_xml):
    """The text a learner would read from a sanitised fragment."""
    return "".join(el.text or "" for el in ET.fromstring(fragment_xml).iter() if el.tag.split("}")[-1] == "text")


def shown(raw_text):
    return board_text(sanitize_svg(f'<g id="a"><text x="1" y="2">{raw_text}</text></g>'))


# ---- a) must pass -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("low <= high", "low <= high"),
    ("a < b", "a < b"),
    ("x & y", "x & y"),
    ("&rarr;", "→"),
    ("&lt;", "<"),
    # forms the model really uses
    ("3. While low <= high:", "3. While low <= high:"),
    ("Else if array[mid] < target, low = mid + 1", "Else if array[mid] < target, low = mid + 1"),
    ("a<b", "a<b"),
    ("if x<5 then", "if x<5 then"),
    ("AT&T", "AT&T"),
    ("a &&& b", "a &&& b"),
    ("&le; &ge; &hellip;", "≤ ≥ …"),
    ("SYN &larr; ACK", "SYN ← ACK"),
    ("already &amp; fine", "already & fine"),
    ("&#8594; numeric", "→ numeric"),
])
def test_board_text_survives(raw, expected):
    assert shown(raw) == expected


# the 10 double-encoded strings stored in baseline run 1 (docs/baseline/run1.json, dense topic, tcp_tls_http_handshake)
@pytest.mark.parametrize("stored,expected", [
    ("SYN &amp;rarr;", "SYN →"), ("&amp;larr; SYN-ACK", "← SYN-ACK"), ("&amp;larr; ACK", "← ACK"),
    ("ClientHello &amp;rarr;", "ClientHello →"), ("&amp;larr; ServerHello", "← ServerHello"),
    ("Certificate &amp;rarr;", "Certificate →"), ("&amp;larr; CertificateVerify", "← CertificateVerify"),
    ("Finished &amp;rarr;", "Finished →"), ("&amp;larr; Finished", "← Finished"),
    ("GET /index.html &amp;rarr;", "GET /index.html →"),
])
def test_the_baseline_arrow_cases_now_show_arrows(stored, expected):
    raw_from_model = stored.replace("&amp;", "&")          # what the model wrote before the old preflight mangled it
    assert shown(raw_from_model) == expected


# HTML habits the model brings into board text. Found in baseline B: <br/> was shown as the literal text "<br/>"
# (4 of 77 raw drawings used it). A line break becomes a space, inline tags keep their words.
@pytest.mark.parametrize("raw,expected", [
    ("Sunlight absorbed by<br/>Chloroplast", "Sunlight absorbed by Chloroplast"),
    ("a<br>b", "a b"),
    ("a<BR />b", "a b"),
    ("<b>Bold</b> and <i>it</i>", "Bold and it"),
    ("H<sub>2</sub>O", "H2O"),
    ('<span style="color:red">hi</span>', "hi"),
    # a "<" followed by a letter that is not one of those tags is still just text
    ("if a<b then", "if a<b then"),
    ("if i<n and j<p then", "if i<n and j<p then"),
    ("x <brain> y", "x <brain> y"),
])
def test_html_line_breaks_and_inline_tags_in_board_text(raw, expected):
    assert shown(raw) == expected


def test_stripping_inline_tags_cannot_assemble_a_script_tag():
    out = sanitize_svg('<g id="a"><text x="1" y="2"><scr<b>ipt>alert(1)</scr</b>ipt></text></g>')
    assert "<script" not in out and "alert" not in out


def test_sanitising_twice_changes_nothing():
    once = sanitize_svg('<g id="a"><text x="1" y="2">while low <= high &rarr; x & y &lt; z</text></g>')
    assert sanitize_svg(once) == once


def test_real_markup_is_still_parsed_as_markup():
    out = sanitize_svg('<g id="a"><rect x="1" y="1" width="9" height="9"/><text x="1" y="2">a <tspan>b</tspan> c</text></g>')
    root = ET.fromstring(out)
    assert [el.tag for el in root.iter()].count("rect") == 1 and any(el.tag == "tspan" for el in root.iter())


# ---- b) must still be caught ---------------------------------------------------------------------------------------

SVG = "<svg xmlns='http://www.w3.org/2000/svg'>{}</svg>"


@pytest.mark.parametrize("name,body,gone", [
    ("script tag", "<script>alert(1)</script><rect id='r' width='9' height='9'/>", ["<script", "alert"]),
    ("onload attribute", "<rect id='r' onload='alert(1)' width='9' height='9'/>", ["onload", "alert"]),
    ("foreignObject", "<foreignObject><div>x</div></foreignObject>", ["foreignObject", "<div"]),
    ("javascript: href", "<a href='javascript:alert(1)'><rect width='9' height='9'/></a>", ["<a ", "javascript:"]),
    ("external href", "<image href='https://evil.example/x.png' width='9' height='9'/>", ["evil.example", "<image"]),
    ("external href on a shape", "<rect href='https://evil.example/x' width='9' height='9'/>", ["evil.example"]),
    ("style with url()", "<style>@import url(https://evil.example)</style>", ["<style", "evil.example"]),
    ("style attribute with url()", "<rect style='fill:url(https://evil.example/x)' width='9' height='9'/>", ["evil.example", "style="]),
    ("fill with external url()", "<rect fill='url(https://evil.example/x)' width='9' height='9'/>", ["evil.example"]),
    ("script inside text", "<text x='1' y='2'>hi<script>alert(1)</script></text>", ["<script", "alert"]),
    ("broken-up script tag", "<text x='1' y='2'><scr<script>ipt>alert(1)</scr</script>ipt></text>", ["<script", "<scr<"]),
    ("onerror on an image", "<image href='x' onerror='alert(1)'/>", ["onerror", "<image"]),
])
def test_dangerous_content_is_still_removed(name, body, gone):
    out = sanitize_svg(SVG.format(body))
    for needle in gone:
        assert needle not in out, f"{name}: {needle!r} survived in {out!r}"


def test_doctype_and_entity_declarations_are_still_refused():
    for bad in ("<!DOCTYPE svg [<!ENTITY x 'y'>]><svg xmlns='http://www.w3.org/2000/svg'/>", "<!ENTITY x 'y'><g id='a'/>"):
        with pytest.raises(ValueError):
            sanitize_svg(bad)


# ---- in a real browser ---------------------------------------------------------------------------------------------
