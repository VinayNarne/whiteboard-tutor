"""
tests/eval_checks.py
Checks on what a tutor run produced. Pure functions (no network), used by eval_baseline.py and compare_baselines.py,
and tested on fixtures in tests/test_eval_checks.py. No pass/fail thresholds yet: they will be set from the normal range
of baselines A and B.

  retries per turn            how often the guards made the tutor redraw (total and per topic)
  elements with no text       drawn elements that contain no <text> at all, and the median number of text lines per element
  mentions a rejection        replies or narrations in which the tutor talks about the system rejecting its drawing
  narration length            median words, and total narration words per turn
  same first two words        the most common two-word opening among replies, and among narrations
  no valid marker             narrations whose [[MARK:id]] was missing or wrongly written, as the model produced them
"""
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.markers import normalise_marker  # noqa: E402


def clean(text):
    return re.sub(r"\[\[MARK:[^\]]*\]\]\s*", "", text or "").strip()


# ---- retries ----------------------------------------------------------------------------------------------------

def retries_per_turn(total_retries, turns):
    return round(total_retries / turns, 2) if turns else 0.0


def retries_by_topic(log_rows, start, end, first_prompt_to_domain):
    """
    Draw rejections in [start, end) per topic, from the structured log. A rejection carries its notebook id
    (session_id); the notebook_created event of that id carries the first prompt, which names the topic.
    """
    topic_of = {}
    for r in log_rows:
        if r.get("event") == "notebook_created":
            m = re.search(r"Notebook created: (\S+)", r.get("message", ""))
            topic = (r.get("data") or {}).get("topic")
            if m and topic in first_prompt_to_domain:
                topic_of[m.group(1)] = first_prompt_to_domain[topic]
    out = {}
    for r in log_rows:
        if r.get("event") == "draw_failed" and start <= r["ts"][:19] < end:
            domain = topic_of.get(r.get("session_id"))
            if domain:
                out[domain] = out.get(domain, 0) + 1
    return out


# ---- text inside elements -------------------------------------------------------------------------------------------

def text_lines(fragment):
    """Number of non-empty <text> elements in a drawn fragment."""
    try:
        root = ET.fromstring(fragment)
    except ET.ParseError:
        return len(re.findall(r"<text\b[^>]*>\s*[^<\s][^<]*</text>", fragment))
    return sum(1 for el in root.iter() if el.tag.split("}")[-1] == "text" and "".join(el.itertext()).strip())


def elements_without_text(fragments):
    """(count with no text at all, total, percent)."""
    fragments = list(fragments)
    none = sum(1 for f in fragments if text_lines(f) == 0)
    return none, len(fragments), (round(100 * none / len(fragments)) if fragments else 0)


def median_text_lines(fragments):
    lines = [text_lines(f) for f in fragments]
    return statistics.median(lines) if lines else 0


# ---- the tutor talking about the system instead of teaching ----------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# what a rejection message is about: drawings, not science
_DRAWING = re.compile(r"\b(card|diagram|drawing|element|shape|label|svg|whiteboard|tool)s?\b", re.I)
_ALWAYS = re.compile(
    r"\b(validator|validation (error|failed|rule)|guardrail|sanitis\w*|sanitiz\w*|svg formatting|"
    r"technical (issues?|problems?|difficult\w+))\b", re.I)
_IN_DRAWING_CONTEXT = re.compile(
    r"\b(rejects?|rejected|rejecting|rejection|disallowed|not allowed|isn't allowed|not permitted|expects?|requires? (text|labels?))\b", re.I)
_SYSTEM = re.compile(
    r"\bthe system\b[^.!?]{0,40}\b(rejects?|rejected|refuses?|refused|blocks?|blocked|expects?|won't accept|"
    r"does not accept|doesn't accept|does not allow|doesn't allow)\b", re.I)
_ATTEMPT_FAILED = re.compile(
    r"\b(my|previous|earlier|first|last)\s+(attempts?|tries)\b[^.!?]{0,60}\b(fail\w*|rejected|did not work|didn't work)\b", re.I)


def mentions_rejection(text):
    """The sentences in which the tutor talks about its drawing being rejected or about the system, validator or tool."""
    hits = []
    for sentence in _SENTENCE.split(clean(text)):
        if (_ALWAYS.search(sentence) or _SYSTEM.search(sentence) or _ATTEMPT_FAILED.search(sentence)
                or (_DRAWING.search(sentence) and _IN_DRAWING_CONTEXT.search(sentence))):
            hits.append(sentence.strip())
    return hits


# ---- narration length and repeated openings -------------------------------------------------------------------------

def narration_stats(narrations, turns):
    words = [len(clean(n).split()) for n in narrations if clean(n)]
    return {"count": len(words), "median_words": statistics.median(words) if words else 0,
            "total_words_per_turn": round(sum(words) / turns) if turns else 0}


def opener(text, n=2):
    return " ".join(re.findall(r"[A-Za-z']+", clean(text).lower())[:n])


def top_opener_share(texts, n=2):
    """The most common n-word opening and its share: {'opener', 'count', 'total', 'percent'}."""
    texts = [t for t in texts if clean(t)]
    if not texts:
        return {"opener": "", "count": 0, "total": 0, "percent": 0}
    counts = {}
    for t in texts:
        counts[opener(t, n)] = counts.get(opener(t, n), 0) + 1
    top, k = max(counts.items(), key=lambda kv: kv[1])
    return {"opener": top, "count": k, "total": len(texts), "percent": round(100 * k / len(texts))}


# ---- markers ---------------------------------------------------------------------------------------------------------------------

def narrations_without_valid_marker(topics):
    """
    (count, total, percent) of stored narrations that do not hold exactly one canonical [[MARK:element_id]] marker.
    For runs taken before the marker repair this IS what the model produced. Runs taken after it store repaired text, so
    those use the repair count in the log instead (eval_baseline records metrics["markers"]).
    """
    pairs = [(e["element_id"], e["narration"]) for d in topics.values() for pg in d["pages"] for e in pg["events"]
             if e["kind"] == "draw" and e["narration"]]
    bad = sum(1 for eid, n in pairs if normalise_marker(n, eid)[1])
    return bad, len(pairs), (round(100 * bad / len(pairs)) if pairs else 0)


# ---- everything for one run ---------------------------------------------------------------------------------------

def run_checks(topics, turns, retries_total, retries_by_domain=None):
    """`topics` is the saved run data (domain -> {turns, pages}); returns the dictionary printed and stored per run."""
    fragments = [e["svg_fragment"] for d in topics.values() for pg in d["pages"] for e in pg["events"] if e["kind"] == "draw"]
    replies = [clean(t["text"]) for d in topics.values() for t in d["turns"] if t.get("ok")]
    narrations = [clean(e["narration"]) for d in topics.values() for pg in d["pages"] for e in pg["events"]
                  if e["kind"] == "draw" and e["narration"]]
    none, total, pct = elements_without_text(fragments)
    mentions = [{"where": "reply", "sentence": s} for r in replies for s in mentions_rejection(r)]
    mentions += [{"where": "narration", "sentence": s} for n in narrations for s in mentions_rejection(n)]
    return {
        "retries_per_turn": {"total": retries_per_turn(retries_total, turns),
                             "per_topic": {d: round(c / max(1, len(topics[d]["turns"])), 2) for d, c in (retries_by_domain or {}).items()}},
        "elements_without_text": {"count": none, "of": total, "percent": pct},
        "median_text_lines_per_element": median_text_lines(fragments),
        "mentions_rejection": {"count": len(mentions), "of_texts": len(replies) + len(narrations), "sentences": mentions},
        "narration": narration_stats(narrations, turns),
        "same_first_two_words": {"replies": top_opener_share(replies), "narrations": top_opener_share(narrations)},
    }


def format_checks(c):
    pt = c["retries_per_turn"]
    topics = ", ".join(f"{d} {v}" for d, v in pt["per_topic"].items()) or "per-topic not available"
    e = c["elements_without_text"]
    m = c["mentions_rejection"]
    n = c["narration"]
    s = c["same_first_two_words"]
    lines = [
        f"  retries per turn: {pt['total']} total; per topic: {topics}",
        f"  elements with no text: {e['count']} of {e['of']} ({e['percent']}%); median text lines per element: {c['median_text_lines_per_element']}",
        f"  replies/narrations that mention a rejection or the system: {m['count']} of {m['of_texts']}",
    ]
    lines += [f"      - [{x['where']}] {x['sentence'][:200]}" for x in m["sentences"]]
    lines += [
        f"  narration: median {n['median_words']} words; {n['total_words_per_turn']} words per turn",
        f"  same first two words: replies '{s['replies']['opener']}' {s['replies']['percent']}% ({s['replies']['count']}/{s['replies']['total']}); "
        f"narrations '{s['narrations']['opener']}' {s['narrations']['percent']}% ({s['narrations']['count']}/{s['narrations']['total']})",
    ]
    return "\n".join(lines)
