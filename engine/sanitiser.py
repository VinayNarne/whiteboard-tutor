#!/usr/bin/env python3
"""
sanitize_svg.py
Security sanitiser for model-generated SVGs before broadcasting or rendering in client browsers.
Uses an allowlist of tags and attributes, strips event handlers (on*), restricts url(...) to local IDs,
and removes scripts/foreignObjects/styles. Trusted fonts are injected AFTER sanitisation.
"""

import sys
import re
from contextvars import ContextVar
import html.entities as html_entities
from pathlib import Path
import xml.etree.ElementTree as ET

_this_dir = Path(__file__).parent
_root_dir = _this_dir.parent
for _p in [str(_this_dir), str(_root_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.events import EngineEvent
from core.log import get_logger

logger = get_logger("engine")

ET.register_namespace('', 'http://www.w3.org/2000/svg')

ALLOWED_TAGS = {
    "svg", "g", "rect", "circle", "ellipse", "line", "path", "polygon", "polyline",
    "text", "tspan", "defs", "marker", "linearGradient", "radialGradient", "stop",
    "filter", "feGaussianBlur", "feMerge", "feMergeNode", "title", "desc"
}

DISALLOWED_TAGS_CONFIRMED = {
    "script", "foreignObject", "iframe", "embed", "object", "image", "use", "a",
    "style", "animate", "set", "animateTransform", "animateMotion"
}

ALLOWED_ATTRS = {
    "x", "y", "width", "height", "rx", "ry", "cx", "cy", "r", "x1", "y1", "x2", "y2",
    "points", "d", "dx", "dy", "fill", "stroke", "stroke-width",
    "stroke-dasharray", "stroke-dashoffset", "stroke-linecap", "stroke-linejoin",
    "opacity", "fill-opacity", "stroke-opacity", "font-size", "font-weight",
    "font-family", "text-anchor", "dominant-baseline", "id", "class", "data-label",
    "viewBox", "xmlns", "preserveAspectRatio", "marker-start", "marker-end",
    "markerWidth", "markerHeight", "refX", "refY", "orient", "offset", "stop-color",
    "stop-opacity", "gradientUnits", "filter", "stdDeviation", "in", "in2", "result"
}

# Resource caps to prevent SVG denial-of-service / browser resource exhaustion (T61)
MAX_ELEMENTS = 500
MAX_PATH_LENGTH = 10000
MAX_FILTERS = 10
MAX_INPUT_CHARS = 500_000  # raw fragment size, checked before parsing
MAX_BLUR_STD_DEV = 30.0

SLIDE_FIXTURE_FILENAME = "slide_1.svg"

# Attributes a caller may add for its own call (scene mode: `transform`, for MathJax formulas and a rotated chart label, on SVG the code
# built). The raw-SVG path never passes any: its overlap checks assume untransformed elements.
_EXTRA_ATTRS: ContextVar[frozenset] = ContextVar("_EXTRA_ATTRS", default=frozenset())
_SAFE_TRANSFORM = re.compile(r"^[a-z0-9 ,.()\-]*$", re.I)   # translate/scale/rotate/matrix and numbers, nothing else


class SanitiserResourceCapError(ValueError):
    """Raised when an SVG exceeds safety resource caps (element count, path complexity, filters) (T61)."""
    pass

def tag_local(tag: str) -> str:

    return tag.split("}")[-1] if "}" in tag else tag

def attr_local(attr: str) -> str:
    return attr.split("}")[-1] if "}" in attr else attr

def _clean_children(elem, removed_tags_log, removed_attrs_log):
    children_to_remove = []
    for child in elem:
        local_t = tag_local(child.tag)
        if local_t not in ALLOWED_TAGS:
            children_to_remove.append(child)
        else:
            sanitize_element(child, removed_tags_log, removed_attrs_log)

    for child in children_to_remove:
        local_t = tag_local(child.tag)
        removed_tags_log.append(local_t)
        elem.remove(child)
        # Preserve trailing tail text if any
        if child.tail:
            if len(elem) > 0:
                last = elem[-1]
                last.tail = (last.tail or "") + child.tail
            else:
                elem.text = (elem.text or "") + child.tail

def _clean_single_attribute(elem, attr_name: str, attr_val: str, loc_name: str, removed_attrs_log: list) -> bool:
    if loc_name.lower().startswith("on"):
        removed_attrs_log.append((loc_name, "starts with 'on'"))
        return True

    if loc_name not in ALLOWED_ATTRS and not (loc_name in _EXTRA_ATTRS.get() and _SAFE_TRANSFORM.match(attr_val)):
        removed_attrs_log.append((loc_name, "not in ALLOWED_ATTRS"))
        return True

    if loc_name == "d" and len(attr_val) > MAX_PATH_LENGTH:
        raise SanitiserResourceCapError(f"SVG path length ({len(attr_val)}) exceeds maximum allowed cap of {MAX_PATH_LENGTH}")

    if loc_name.lower() == "stddeviation":
        try:
            parts = attr_val.strip().split()
            clamped_parts = [str(min(float(p), MAX_BLUR_STD_DEV)) for p in parts]
            elem.attrib[attr_name] = " ".join(clamped_parts)
            attr_val = elem.attrib[attr_name]
        except ValueError:
            pass

    if "url(" in attr_val.lower():
        urls = re.findall(r'url\s*\((.*?)\)', attr_val, flags=re.IGNORECASE)
        disallowed = any(not re.fullmatch(r'#[\w\-\.:]+', u.strip().strip("'\"")) for u in urls)
        if disallowed:
            removed_attrs_log.append((loc_name, f"disallowed url: {attr_val}"))
            return True

    return False

def sanitize_element(elem, removed_tags_log=None, removed_attrs_log=None):
    if removed_tags_log is None:
        removed_tags_log = []
    if removed_attrs_log is None:
        removed_attrs_log = []

    _clean_children(elem, removed_tags_log, removed_attrs_log)

    to_delete = []
    for attr_name, attr_val in elem.attrib.items():
        loc_name = attr_local(attr_name)
        if _clean_single_attribute(elem, attr_name, attr_val, loc_name, removed_attrs_log):
            to_delete.append(attr_name)

    for a in to_delete:
        del elem.attrib[a]

# Every element name that can legitimately start a tag in this pipeline: the SVG elements (allowed or not) plus the
# dangerous ones the allowlist must still see and remove. A "<" followed by anything else is board text, not markup.
_KNOWN_TAGS = {t.lower() for t in ALLOWED_TAGS | DISALLOWED_TAGS_CONFIRMED | {
    "symbol", "pattern", "clipPath", "mask", "switch", "textPath", "tref", "metadata", "view", "cursor", "mpath",
    "feBlend", "feColorMatrix", "feComponentTransfer", "feComposite", "feConvolveMatrix", "feDiffuseLighting",
    "feDisplacementMap", "feDistantLight", "feDropShadow", "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR",
    "feImage", "feMorphology", "feOffset", "fePointLight", "feSpecularLighting", "feSpotLight", "feTile",
    "feTurbulence", "html", "body", "div", "span", "img", "link", "meta", "base", "form", "input", "button",
    "video", "audio", "source", "math", "template", "applet", "frame", "frameset"}}
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_NAMED_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]{1,31});")
# HTML habits the model brings into board text: <br/> is a line break; inline tags only style the words inside them.
_LINE_BREAK = re.compile(r"<\s*/?\s*br\s*/?\s*>", re.IGNORECASE)
_INLINE_HTML = re.compile(r"</?(?:b|i|u|em|strong|sub|sup|small|span|p|code)(?:\s+[^<>]*)?/?>", re.IGNORECASE)
_STRAY_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_STRAY_LT = re.compile(r"<(?!(?:/?(?:" + "|".join(sorted(_KNOWN_TAGS, key=len, reverse=True)) + r")(?=[\s/>])|[!?]))", re.IGNORECASE)


def _named_to_numeric(m):
    """&rarr; -> &#8594; (XML only knows five named entities; HTML names would otherwise be shown as literal text)."""
    name = m.group(1)
    if name in _XML_ENTITIES:
        return m.group(0)
    chars = html_entities.html5.get(name + ";")
    return "".join(f"&#{ord(c)};" for c in chars) if chars else m.group(0)


# Control characters carry no meaning on a board, and XML 1.0 cannot carry most of them: the C0 controls except tab,
# newline and carriage return, DEL (0x7f), and the C1 range (0x80-0x9f). A model sometimes emits one where it meant a
# symbol (an arrow, "x squared"). They are REPLACED by a visible placeholder, never deleted, so the board shows that something
# was meant there and the tutor can be told (engine/lossless.py, the note in the draw result).
CONTROL_PLACEHOLDER = "\ufffd"
_CONTROL_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_NUMERIC_REF = re.compile(r"&#(?:[xX]([0-9a-fA-F]+)|([0-9]+));")


def _is_control(code: int) -> bool:
    return code <= 8 or code in (11, 12) or 14 <= code <= 31 or 127 <= code <= 159


def replace_control_chars(text: str):
    """(text with every control character replaced by CONTROL_PLACEHOLDER, how many). Also numeric references to them (&#0; &#x1b;)."""
    replaced = 0

    def placeholder_for_ref(m):
        nonlocal replaced
        code = int(m.group(1), 16) if m.group(1) else int(m.group(2))
        if _is_control(code):
            replaced += 1
            return CONTROL_PLACEHOLDER
        return m.group(0)
    text = _NUMERIC_REF.sub(placeholder_for_ref, text)
    replaced += len(_CONTROL_CHARS.findall(text))
    return _CONTROL_CHARS.sub(CONTROL_PLACEHOLDER, text), replaced


# ONE model slip is repaired, exactly this pattern and no other: inside a tag, `font-size"20"` with the equals sign missing (baselines H and J:
# gpt-4.1-mini drops the "=" after font-size now and then, and the recovery parser then cut the rest of the drawing). Every repair is logged.
# Other missing-equals typos (x"75", fill"#000") are NOT repaired: they are caught by the lossless check and the tutor is told.
_FONT_SIZE_MISSING_EQUALS = re.compile(r'(<[A-Za-z][^<>]*?\sfont-size)"(\d+(?:\.\d+)?(?:px|pt|em|rem|%)?)"')


def repair_font_size_typo(text: str):
    """(text with `font-size"20"` made `font-size="20"` inside tags, the list of snippets repaired). Anything else is left alone."""
    snippets = []

    def fix(m):
        snippets.append(f'font-size"{m.group(2)}"')
        return f'{m.group(1)}="{m.group(2)}"'
    while True:                                          # a tag can have it twice; each pass fixes the first of each tag
        fixed = _FONT_SIZE_MISSING_EQUALS.sub(fix, text)
        if fixed == text:
            return text, snippets
        text = fixed


def _repair(svg_text: str):
    text, typos = repair_font_size_typo(svg_text)
    text, stripped = replace_control_chars(text)
    text = _LINE_BREAK.sub(" ", text)
    text = _INLINE_HTML.sub("", text)
    text = _NAMED_ENTITY.sub(_named_to_numeric, text)
    text = _STRAY_AMP.sub("&amp;", text)
    return _STRAY_LT.sub("&lt;", text), stripped, typos


def repair_text_markup(svg_text: str) -> str:
    """
    Make model output well-formed XML WITHOUT losing the learner-visible text, before parsing:
      - `font-size"20"` (equals sign missing, only that attribute) becomes `font-size="20"`
      - control characters are replaced by a visible placeholder (see replace_control_chars)
      - HTML entity names (&rarr; &le; &hellip;) become numeric references, so the board shows the character
      - a "<" that does not start a known element ("low <= high", "a < b", "x<5") becomes &lt;
      - a "&" that is not part of a valid entity ("x & y", "AT&T") becomes &amp;
      - HTML line breaks (<br/>) become a space and inline HTML tags (<b>, <i>, <sub> ...) are dropped, keeping their text
    Only text is touched; real tags, and therefore everything the allowlist removes, are parsed exactly as before.
    """
    return _repair(svg_text)[0]


def sanitize_svg(svg_text: str, extra_attrs=frozenset()) -> str:
    """
    Sanitizes untrusted model-generated SVG using an allowlist and enforces resource caps (T61).
    Returns cleaned SVG string. extra_attrs: allowed in this call only (scene mode passes {"transform"}).
    """
    token = _EXTRA_ATTRS.set(frozenset(extra_attrs))
    try:
        return _sanitize_svg(svg_text)
    finally:
        _EXTRA_ATTRS.reset(token)


def _sanitize_svg(svg_text: str) -> str:
    if len(svg_text) > MAX_INPUT_CHARS:
        raise SanitiserResourceCapError(f"SVG text ({len(svg_text)} chars) exceeds maximum allowed {MAX_INPUT_CHARS}")
    # DTDs/entities are never needed for drawings and enable XXE / entity-expansion attacks
    if re.search(r"<!(DOCTYPE|ENTITY)", svg_text, flags=re.IGNORECASE):
        raise ValueError("SVG must not contain a DOCTYPE or ENTITY declaration")
    clean_text, stripped, typos = _repair(svg_text)
    for snippet in typos:                                # one log line per repair
        logger.info(EngineEvent.ATTRIBUTE_REPAIRED, f"Repaired a missing equals sign in model SVG: {snippet}",
                    data={"attribute": "font-size", "reason": "missing_equals", "snippet": snippet})
    if stripped:
        logger.warn(EngineEvent.CONTROL_CHARS_REPLACED, f"Replaced {stripped} control character(s) in model SVG with a visible placeholder",
                    data={"count": stripped})
    try:
        root = ET.fromstring(clean_text)
    except ET.ParseError:
        try:
            import lxml.etree as LET
            parser = LET.XMLParser(recover=True, no_network=True, resolve_entities=False)
            lxml_root = LET.XML(clean_text.encode("utf-8"), parser=parser)
            recovered = LET.tostring(lxml_root, encoding="unicode")
            root = ET.fromstring(recovered)
        except Exception:
            # Re-raise original ET ParseError if recovery fails
            root = ET.fromstring(clean_text)

    local_root = tag_local(root.tag)
    if local_root not in ALLOWED_TAGS:
        raise ValueError(f"Root element <{local_root}> is not an allowed SVG tag")

    # Resource Cap 1: Total element count (T61)
    elements = list(root.iter())
    if len(elements) > MAX_ELEMENTS:
        raise SanitiserResourceCapError(f"SVG element count ({len(elements)}) exceeds maximum allowed cap of {MAX_ELEMENTS}")

    # Resource Cap 2: Filter count (T61)
    filters = [el for el in elements if tag_local(el.tag) == "filter"]
    if len(filters) > MAX_FILTERS:
        raise SanitiserResourceCapError(f"SVG filter count ({len(filters)}) exceeds maximum allowed cap of {MAX_FILTERS}")

    removed_tags = []
    removed_attrs = []
    sanitize_element(root, removed_tags, removed_attrs)
    return ET.tostring(root, encoding="unicode")


def _test_removal_rules() -> bool:
    print("--- Half 1: Must Be Removed ---")
    removal_tests = [
        ("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script><rect id='r1' width='100' height='50'/></svg>",
         "<script>", lambda s: "<script" not in s and "alert" not in s),
        
        ("<svg xmlns='http://www.w3.org/2000/svg'><rect id='r1' onload='alert(1)' width='100' height='50'/></svg>",
         "onload attribute", lambda s: "onload" not in s and "alert" not in s),
        
        ("<svg xmlns='http://www.w3.org/2000/svg'><foreignObject><div>x</div></foreignObject></svg>",
         "<foreignObject>", lambda s: "foreignObject" not in s and "<div>" not in s),
        
        ("<svg xmlns='http://www.w3.org/2000/svg'><a href='javascript:alert(1)'><rect width='10' height='10'/></a></svg>",
         "<a> tag / javascript href", lambda s: "<a " not in s and "javascript:" not in s),
        
        ("<svg xmlns='http://www.w3.org/2000/svg'><rect id='r1' fill='url(https://evil.example/x)' width='100' height='50'/></svg>",
         "fill='url(https://...)'", lambda s: "evil.example" not in s and "https:" not in s),
        
        ("<svg xmlns='http://www.w3.org/2000/svg'><animate attributeName='href' values='javascript:alert(1)'/></svg>",
         "<animate>", lambda s: "animate" not in s and "javascript:" not in s),
        
        ("<svg xmlns='http://www.w3.org/2000/svg'><style>@import url(https://evil.example)</style></svg>",
         "<style>", lambda s: "<style" not in s and "evil.example" not in s),
    ]

    passed = True
    for raw, desc, check_fn in removal_tests:
        cleaned = sanitize_svg(raw)
        ok = check_fn(cleaned)
        status = "PASS" if ok else "FAIL"
        if not ok:
            passed = False
        print(f"[{status}] Must remove {desc}: Result='{cleaned.strip()}'")
    return passed


def _test_resource_caps() -> bool:
    print("\n--- Resource Cap Tests (T61) ---")
    passed = True

    # 1. Element flood (>500 elements)
    flood_elems = "".join(f"<rect id='r{i}' x='{i}' y='0' width='1' height='1'/>" for i in range(505))
    flood_svg = f"<svg xmlns='http://www.w3.org/2000/svg'>{flood_elems}</svg>"
    try:
        sanitize_svg(flood_svg)
        print("[FAIL] Must reject element flood (>500 elements)")
        passed = False
    except SanitiserResourceCapError as e:
        print(f"[PASS] Must reject element flood (>500 elements): {e}")

    # 2. Filter flood (>10 filters)
    flood_filters = "".join(f"<filter id='f{i}'/>" for i in range(12))
    filter_svg = f"<svg xmlns='http://www.w3.org/2000/svg'><defs>{flood_filters}</defs></svg>"
    try:
        sanitize_svg(filter_svg)
        print("[FAIL] Must reject filter flood (>10 filters)")
        passed = False
    except SanitiserResourceCapError as e:
        print(f"[PASS] Must reject filter flood (>10 filters): {e}")

    # 3. Path flood (>10000 chars)
    giant_d = "M 0 0 " + "L 1 1 " * 2500
    path_svg = f"<svg xmlns='http://www.w3.org/2000/svg'><path d='{giant_d}'/></svg>"
    try:
        sanitize_svg(path_svg)
        print("[FAIL] Must reject path length flood (>10000 chars)")
        passed = False
    except SanitiserResourceCapError as e:
        print(f"[PASS] Must reject path length flood (>10000 chars): {e}")

    # 4. Blur stdDeviation clamping
    blur_svg = "<svg xmlns='http://www.w3.org/2000/svg'><filter id='f1'><feGaussianBlur stdDeviation='85.5'/></filter></svg>"
    cleaned_blur = sanitize_svg(blur_svg)
    if "stdDeviation=\"30.0\"" in cleaned_blur or "stdDeviation='30.0'" in cleaned_blur:
        print(f"[PASS] Must clamp excessive blur stdDeviation to 30.0: {cleaned_blur.strip()}")
    else:
        print(f"[FAIL] Blur stdDeviation not clamped to 30.0: {cleaned_blur.strip()}")
        passed = False

    return passed


def _diff_single_bbox(k: str, orig_bboxes: dict, san_bboxes: dict) -> list:
    if k not in san_bboxes:
        return [f"Missing ID in sanitized bboxes: {k}"]
    b1 = orig_bboxes[k].get("getBBox")
    b2 = san_bboxes[k].get("getBBox")
    if b1 is None and b2 is None:
        return []
    if (b1 is None) != (b2 is None):
        return [f"getBBox None mismatch on {k}: orig={b1}, san={b2}"]
    diffs = []
    for dim in ("x", "y", "w", "h"):
        if abs(b1[dim] - b2[dim]) > 0.01:
            diffs.append(f"BBox mismatch on {k}.{dim}: orig={b1[dim]}, san={b2[dim]}")
    return diffs


def _compare_bboxes(temp_orig: Path, temp_san: Path) -> bool:
    try:
        from engine.validator import get_bboxes_via_playwright
    except ImportError:
        from validator import get_bboxes_via_playwright
    orig_bboxes = get_bboxes_via_playwright(str(temp_orig))
    san_bboxes = get_bboxes_via_playwright(str(temp_san))

    diffs = []
    for k in orig_bboxes:
        diffs.extend(_diff_single_bbox(k, orig_bboxes, san_bboxes))

    if diffs:
        print("[FAIL] Bounding box differences found:")
        for d in diffs:
            print("  ", d)
        return False
    print("[PASS] Bounding boxes match 100% identically across all elements.")
    return True


def _test_real_slide_preservation() -> bool:
    print("\n--- Half 2: Must Survive Unchanged (Real Generated Slide) ---")
    candidate_paths = [
        Path(__file__).parent.parent / "tests" / "fixtures" / SLIDE_FIXTURE_FILENAME,
        Path(__file__).parent / "slides" / SLIDE_FIXTURE_FILENAME,
        Path(__file__).parent.parent / "spikes" / "spike6-core-loop" / "slides" / SLIDE_FIXTURE_FILENAME
    ]
    slide_path = next((p for p in candidate_paths if p.exists()), None)
    if not slide_path:
        print("[SKIP] Real slide slide_1.svg not found for half 2 test.")
        return True

    orig_svg = slide_path.read_text(encoding="utf-8")
    san_svg = sanitize_svg(orig_svg)

    orig_tree = ET.fromstring(orig_svg)
    san_tree = ET.fromstring(san_svg)

    orig_elements = [el for el in orig_tree.iter() if not (tag_local(el.tag) == "style" and any(k in (el.text or "") for k in ("System UI", "Inter")))]
    san_elements = list(san_tree.iter())

    orig_ids = [el.get("id") for el in orig_elements if el.get("id")]
    san_ids = [el.get("id") for el in san_elements if el.get("id")]

    print(f"Element count before: {len(orig_elements)}")
    print(f"Element count after:  {len(san_elements)}")
    print(f"ID count before:      {len(orig_ids)}")
    print(f"ID count after:       {len(san_ids)}")

    if len(orig_elements) != len(san_elements) or orig_ids != san_ids:
        print("[FAIL] Element or ID count changed during sanitisation!")
        return False
    print("[PASS] Element and ID counts match exactly.")

    # Playwright Bounding Box Check
    temp_dir = Path(__file__).parent.parent / "tests" / "fixtures"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_orig = temp_dir / "temp_orig_check.svg"
    temp_san = temp_dir / "temp_san_check.svg"
    temp_orig.write_text(orig_svg, encoding="utf-8")
    temp_san.write_text(san_svg, encoding="utf-8")

    try:
        return _compare_bboxes(temp_orig, temp_san)
    except Exception as e:
        print(f"[FAIL] Playwright bbox comparison failed: {e}")
        return False
    finally:
        if temp_orig.exists():
            temp_orig.unlink()
        if temp_san.exists():
            temp_san.unlink()


def run_self_tests() -> bool:
    print("=== SVG Sanitiser Self-Tests (Both Halves) ===\n")
    p1 = _test_removal_rules()
    p2 = _test_resource_caps()
    p3 = _test_real_slide_preservation()
    all_passed = p1 and p2 and p3
    print(f"\nFinal Verdict: {'ALL SANITISER SELF-TESTS PASSED' if all_passed else 'SANITISER SELF-TESTS FAILED'}")
    return all_passed

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        success = run_self_tests()
        sys.exit(0 if success else 1)
    elif len(sys.argv) > 1:
        in_file = Path(sys.argv[1])
        out_file = Path(sys.argv[2]) if len(sys.argv) > 2 else in_file
        cleaned = sanitize_svg(in_file.read_text(encoding="utf-8"))
        out_file.write_text(cleaned, encoding="utf-8")
        print(f"Sanitized SVG saved to {out_file}")
    else:
        print("Usage: python sanitize_svg.py <input.svg> [output.svg] OR python sanitize_svg.py --test")
