"""
engine/lossless.py
What the model wrote against what is stored on the board. Anything that goes missing between the two is a loss, and a loss nobody
sees is how the tutor came to describe labels the board never had (docs/BASELINE.md: before blaming the model, compare raw model
output with the stored board).

  compare(raw, stored) -> Loss
      raw     the drawing exactly as the model wrote it (before any repair)
      stored  what the pipeline kept (the sanitiser's output; with or without the font the page adds)

A Loss counts, in what the model wrote and is not in what is stored:
  tags        element tags (by name): <text>, <rect>, but also anything the allowlist removed (<style>, <script> ...)
  text_lines  text labels (<text> bodies, tspans included), compared after decoding entities and collapsing whitespace
  chars       visible characters of that text (spaces ignored)
  control     control characters the model wrote where it probably meant a symbol (an arrow, a superscript)
Formatting tags the repair removes on purpose while keeping their text (<br>, <b>, <i>, <sup> ...) are counted apart (`formatting`):
nothing visible is missing, so they do not make a drawing "lost". Tags the pipeline ADDS (the <g id> wrapper, the page font) are not losses. Attributes are not compared.
"""
import html
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List

from engine.sanitiser import _CONTROL_CHARS, CONTROL_PLACEHOLDER      # the placeholder that stands on the board where the model wrote a control character

_TAG = re.compile(r"<([A-Za-z][\w:.-]*)")
_TEXT_BODY = re.compile(r"<text\b[^>]*?>(.*?)</text>", re.IGNORECASE | re.DOTALL)
_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
# the sanitiser's repair drops these and keeps what they wrapped (engine/sanitiser.py: _LINE_BREAK, _INLINE_HTML)
FORMATTING_TAGS = {"br", "b", "i", "u", "em", "strong", "sub", "sup", "small", "span", "p", "code"}


@dataclass
class Loss:
    tags: Counter = field(default_factory=Counter)
    text_lines: List[str] = field(default_factory=list)
    chars: int = 0
    control: List[int] = field(default_factory=list)      # code points of the control characters in the model's text
    formatting: Counter = field(default_factory=Counter)  # <br>, <b> ... removed on purpose, their text kept

    def lost(self) -> bool:
        """True if anything that was written is not on the board. Control characters count separately (`control`)."""
        return bool(self.tags or self.text_lines or self.chars)

    def any(self) -> bool:
        return self.lost() or bool(self.control)

    def as_dict(self) -> dict:
        return {"tags": dict(self.tags), "text_lines": len(self.text_lines), "chars": self.chars, "control": len(self.control),
                "formatting": dict(self.formatting)}


def _decode(text: str) -> str:
    return html.unescape(_ANY_TAG.sub("", _BREAK.sub(" ", text)))


def _lines(svg: str, control: List[int] = None) -> List[str]:
    """Normalised text of every <text> in `svg`: tags gone, entities decoded, control characters as the placeholder, spaces collapsed."""
    out = []
    for body in _TEXT_BODY.findall(svg or ""):
        text = _decode(body)
        if control is not None:
            control.extend(ord(c) for c in _CONTROL_CHARS.findall(text))
        text = re.sub(r"\s+", " ", _CONTROL_CHARS.sub(CONTROL_PLACEHOLDER, text)).strip()
        if text:
            out.append(text)
    return out


def _tags(svg: str) -> Counter:
    return Counter(t.lower() for t in _TAG.findall(svg or ""))


def compare(raw: str, stored: str) -> Loss:
    control: List[int] = []
    raw_lines, kept_lines = _lines(raw, control), _lines(stored)
    missing = Counter(raw_lines) - Counter(kept_lines)
    lost_lines = []
    for line in raw_lines:                                  # in the order the model wrote them
        if missing[line] > 0:
            missing[line] -= 1
            lost_lines.append(line)
    raw_chars = Counter(c for line in raw_lines for c in line if not c.isspace())
    kept_chars = Counter(c for line in kept_lines for c in line if not c.isspace())
    gone = _tags(raw) - _tags(stored)
    return Loss(tags=Counter({t: n for t, n in gone.items() if t not in FORMATTING_TAGS}), text_lines=lost_lines,
                chars=sum((raw_chars - kept_chars).values()), control=control,
                formatting=Counter({t: n for t, n in gone.items() if t in FORMATTING_TAGS}))


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def lost_content_note(element_id: str, loss: Loss) -> str:
    """What the tutor is told when part of a drawing did not reach the board (empty string when nothing was lost). Honest, not a rejection:
    the element is stored; the tutor is asked to redraw it with modify_existing_element."""
    codes = ", ".join(str(c) for c in sorted(set(loss.control)))
    n_control = len(loss.control)
    control_what = (f"{n_control} control {_plural(n_control, 'character', 'characters')} (code {codes})") if n_control else ""
    use_real = "the character itself (for example \u00b2, \u2192 or \u2082) and not an escape sequence such as \\u0000"
    if not loss.lost():
        if not n_control:
            return ""
        return (f"In '{element_id}', {control_what} cannot be drawn, so the board shows {CONTROL_PLACEHOLDER} there. You probably meant a "
                f"symbol such as an arrow or a superscript. Redraw it with modify_existing_element (same element_id), writing {use_real}.")
    parts = []
    if loss.text_lines:
        n = len(loss.text_lines)
        parts.append(f"{n} text {_plural(n, 'label is', 'labels are')} missing (first: \"{loss.text_lines[0][:60]}\")")
    elif loss.chars:
        parts.append(f"{loss.chars} characters of text are missing")
    tags = {t: n for t, n in loss.tags.items() if not (t == "text" and loss.text_lines)}
    if tags:
        parts.append("tags removed: " + ", ".join(f"<{t}> x{n}" for t, n in sorted(tags.items())))
    note = (f"Not everything you wrote for '{element_id}' reached the board: {'; '.join(parts)}. Redraw it with modify_existing_element "
            f"(same element_id) so everything you meant to show is on the board.")
    if n_control:
        note += (f" Also, {control_what} cannot be drawn and {_plural(n_control, 'shows', 'show')} as {CONTROL_PLACEHOLDER} on the board; "
                 f"write the character itself (for example \u00b2, \u2192 or \u2082), not an escape sequence such as \\u0000, when you redraw.")
    return note
