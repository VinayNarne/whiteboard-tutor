"""
engine/grouping.py
An element is ONE `<g id="element_id">` group. Writing it that way is a recording detail, so the code owns it instead of
trusting the model: the id is how annotations, edits, undo, hover and the layout and overlap checks find the element, and
the sanitiser parses a fragment as one XML document, so it keeps the FIRST top-level node and silently drops every other one
(a card sent as <rect/><text>...</text><text>...</text> used to be stored as the bare rectangle, text and all gone).

  ensure_group(fragment, element_id) -> (fragment, reason)

reason is None when the fragment already is exactly one <g id="element_id"> (returned untouched), else:
  bare_tag            one top-level tag that is not a group (a single <rect>, <text> ...)
  multiple_top_level  several top-level tags
  group_id            one top-level <g> whose id is missing or is another id
The whole fragment is then wrapped in <g id="element_id">, and an id equal to element_id on a tag inside is removed, so the
page never holds two. Nothing the model drew is changed or dropped; the existing guards (frame, transform, id uniqueness,
sanitiser allowlist, geometry) still run on the result. This must run BEFORE the sanitiser.
"""
import html
import re

import lxml.etree as LET

from engine.sanitiser import repair_text_markup

_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.IGNORECASE)


def _top_level(fragment: str):
    """The top-level elements of a fragment, read as leniently as the sanitiser's own fallback parser does."""
    text = _XML_DECLARATION.sub("", repair_text_markup(fragment))
    try:
        root = LET.fromstring(f"<root>{text}</root>".encode("utf-8"),
                              parser=LET.XMLParser(recover=True, no_network=True, resolve_entities=False))
    except Exception:
        return None
    return [c for c in root if isinstance(c.tag, str)] if root is not None else None


def ensure_group(fragment: str, element_id: str):
    """(fragment as one <g id=element_id> group, reason it had to be repaired or None). See the module docstring."""
    nodes = _top_level(fragment or "")
    if nodes is not None and not nodes:
        return fragment, None                       # nothing to group: the sanitiser reports an empty drawing as before
    if nodes is not None and len(nodes) == 1 and LET.QName(nodes[0]).localname == "g" and nodes[0].get("id") == element_id:
        return fragment, None
    if nodes is None or len(nodes) > 1:
        reason = "multiple_top_level"
    elif LET.QName(nodes[0]).localname == "g":
        reason = "group_id"
    else:
        reason = "bare_tag"
    inner = _XML_DECLARATION.sub("", fragment)
    inner = re.sub(r"""\s+id\s*=\s*(["'])""" + re.escape(element_id) + r"\1", "", inner)   # the id moves to the wrapper
    return f'<g id="{html.escape(element_id, quote=True)}">{inner}</g>', reason
