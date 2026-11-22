"""Long adversarial strings must not stall the regexes Sonar flagged as backtracking-prone (security hotspots review)."""
import time

from engine import author, lesson_plan, sanitiser

N = 50_000


def _fast(fn):
    t = time.perf_counter()
    fn()
    assert time.perf_counter() - t < 1.0


def test_last_question_long_reply_is_fast():
    _fast(lambda: author.last_question([{"role": "assistant", "content": "a" * N}]))


def test_step_titles_long_plan_is_fast():
    fn = lesson_plan.path_titles
    _fast(lambda: fn("STEPS:\n" + "\n" * N + "1"))


def test_sanitiser_html_patterns_are_fast():
    _fast(lambda: sanitiser._INLINE_HTML.search("<b" + " " * N))
    _fast(lambda: sanitiser._LINE_BREAK.search("<" * N + " " * N))
    _fast(lambda: sanitiser._LINE_BREAK.search("<" + " /" * (N // 2)))


def test_sanitiser_html_behaviour_unchanged():
    assert sanitiser._LINE_BREAK.sub("|", "a<br>b< / br / >c<BR/>d") == "a|b|c|d"
    assert sanitiser._INLINE_HTML.sub("", "<b>x</b><span class='k'>y</span><p>") == "xy"
