"""
engine/markers.py
The [[MARK:id]] marker: the token in a narration that says WHEN an element appears (at the spoken word that follows it).
Writing it correctly is a recording detail, so the code owns it instead of trusting the model:

  normalise_marker(narration, element_id)   exactly one valid marker per narration, however the model wrote it
  strip_markers(text)                        no marker-like token survives (voice input, chat replies, exports)

Accepted as a marker: one or two square brackets on each side, any spacing, any case of "mark", with or without the
closing bracket: [[MARK:x]]  [MARK:x]  [[ mark : x ]]  [MARK: x]]  [[MARK:x .  Ordinary square brackets are not
touched: "a[0]", "[1]", "[[2]]", "[Mark Twain wrote it]" and "[MARK]" (no colon) stay as written.
"""
import re

# a complete token: [ or [[, optional spaces, "mark", colon, an id (anything except brackets), ] or ]]
_TERMINATED = r"\[{1,2}\s*mark\s*:[^\[\]\n]*\]{1,2}"
# a token whose closing bracket is missing: the id is the run of id characters right after the colon
_UNTERMINATED = r"\[{1,2}\s*mark\s*:\s*[\w\-.]+"
MARKER_LIKE = re.compile(f"(?:{_TERMINATED})|(?:{_UNTERMINATED})", re.IGNORECASE)
_ID = re.compile(r"mark\s*:\s*([^\[\]\n]*?)\s*\]*$", re.IGNORECASE)


def marker(element_id: str) -> str:
    return f"[[MARK:{element_id}]]"


def strip_markers(text: str) -> str:
    """Remove every marker-like token, and the space that followed it. Used for anything that is read or shown."""
    return re.sub(r"[ \t]{2,}", " ", MARKER_LIKE.sub("", text or "")).lstrip() if text else (text or "")


def _token_id(token: str) -> str:
    m = _ID.search(token.strip("[] \t"))
    return (m.group(1) if m else "").strip()


def normalise_marker(narration: str, element_id: str):
    """
    Returns (narration with exactly one canonical marker, reasons). `reasons` is empty when the model got it right.

    - no marker at all            -> the element's marker is attached at the start ("missing")
    - a marker, wrongly written   -> rewritten as [[MARK:element_id]] where it stood ("format"); a marker naming another
                                     element gets this element's id ("wrong_id")
    - more than one marker        -> only the first is kept ("duplicate")
    A marker that the model placed later in the sentence keeps its place: it is where the element should appear.
    """
    text = narration or ""
    tokens = list(MARKER_LIKE.finditer(text))
    canonical = marker(element_id)
    if not tokens:
        return f"{canonical} {text.strip()}".strip() if text.strip() else canonical, ["missing"]

    first = tokens[0]
    reasons = []
    if _token_id(first.group(0)) != element_id:
        reasons.append("wrong_id")
    elif first.group(0) != canonical:
        reasons.append("format")
    if len(tokens) > 1:
        reasons.append("duplicate")

    rest = re.sub(r" {2,}", " ", MARKER_LIKE.sub("", text[first.end():]))
    if rest and not rest[0].isspace():
        rest = " " + rest                      # "[MARK:x]Hello" -> "[[MARK:x]] Hello"
    return text[:first.start()] + canonical + rest, reasons
