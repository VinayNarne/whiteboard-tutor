"""
engine/fonts.py
Font injection and subsetting utilities.
Implements trusted style injection after SVG sanitisation (SAD §6.1, §8.3, R10).
Subsets and base64-inlines WOFF2 font data (T18 / R10).
"""

import re
import xml.etree.ElementTree as ET
try:
    from ._font_data import INTER_REGULAR_WOFF2_B64, INTER_BOLD_WOFF2_B64
except (ImportError, ValueError):
    try:
        from engine._font_data import INTER_REGULAR_WOFF2_B64, INTER_BOLD_WOFF2_B64
    except (ImportError, ValueError):
        from _font_data import INTER_REGULAR_WOFF2_B64, INTER_BOLD_WOFF2_B64

SVG_NS = "http://www.w3.org/2000/svg"

DEFAULT_FONT_CSS = f"""
@font-face {{
  font-family: 'Inter';
  font-style: normal;
  font-weight: 400;
  src: url(data:font/woff2;base64,{INTER_REGULAR_WOFF2_B64}) format('woff2');
}}
@font-face {{
  font-family: 'Inter';
  font-style: normal;
  font-weight: 700;
  src: url(data:font/woff2;base64,{INTER_BOLD_WOFF2_B64}) format('woff2');
}}
text, tspan {{
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}}
"""


def get_trusted_font_css() -> str:
    """Return the base64-inlined @font-face CSS for Inter (Regular 400 + Bold 700)."""
    return DEFAULT_FONT_CSS.strip()


def inject_trusted_font(svg_text: str, font_css: str = None) -> str:
    """
    Inject trusted typography and base64 @font-face CSS into the SVG's <defs> block.
    Called strictly AFTER sanitisation so model-generated styles are stripped
    and only presenter-trusted fonts/styles are added (SAD §6.1, §8.3, R10).
    """
    try:
        root = ET.fromstring(svg_text)
        local_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

        # Leaf elements like <rect>, <circle>, <line> cannot have <defs> as children in SVG
        if local_tag not in ("svg", "g"):
            return svg_text

        if not font_css:
            font_css = get_trusted_font_css()

        ns = f"{{{SVG_NS}}}"

        # Locate or create <defs>
        defs = root.find(f"{ns}defs")
        if defs is None:
            defs = root.find("defs")
        if defs is None:
            defs = ET.Element(f"{ns}defs")
            root.insert(0, defs)

        style = ET.Element(f"{ns}style")
        style.set("type", "text/css")
        style.text = font_css
        defs.insert(0, style)

        return ET.tostring(root, encoding="unicode")
    except Exception:
        return svg_text


_FONT_STYLE = re.compile(r"<style[^>]*>(?:(?!</style>).)*?@font-face(?:(?!</style>).)*?</style>", re.DOTALL)


def strip_embedded_fonts(svg_text):
    """The page SVG with the inlined font data removed (~16 KB of base64). For what the MODEL reads: it cannot use the
    font and it costs thousands of tokens on every call. Stored drawings and exports keep the font."""
    return _FONT_STYLE.sub("", svg_text) if svg_text else svg_text
