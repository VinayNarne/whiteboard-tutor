# SonarQube security hotspots review

14 hotspots reviewed. 3 files had real polynomial-backtracking problems (measured: 15 s to 70 s on a 50k-character input); fixed with tests in `tests/test_regex_dos.py`. The rest are safe.

| Key | File:line | Category | Decision | Reason |
|---|---|---|---|---|
| 6511af8c, aab6e800 | engine/author.py:147 | dos | FIXED | `[^.!?\n]*\?` on uncapped model reply was quadratic (15 s at 50k chars); reply is now cut to its last 2000 chars before the regex. |
| e515fae5 | engine/lesson_plan.py:184 | dos | FIXED | `^\s*...` over uncapped model plan was quadratic (70 s); the steps block is capped at 20000 chars. |
| 6574f07a | engine/sanitiser.py:158 | dos | FIXED | `<\s*/?\s*br...` had overlapping quantifiers; rewritten unambiguously with identical matches. |
| f8614dfe | engine/sanitiser.py:159 | dos | FIXED | `\s+[^<>]*` overlapped (29 s at 50k); now `\s[^<>]*`, same language. |
| 34ee6009 | engine/markers.py:20 | dos | SAFE | Each match anchors on a literal `[`/`mark:`, so work is linear (measured 0.01 s at 50k). |
| 8c0ac4b6 | engine/scene.py:454 | dos | SAFE | Runs on a single note line already length-limited by the sanitiser/scene caps; lazy `.+?` between `$` anchors measured linear. |
| 99cdfa31 | engine/scene.py:483 | dos | SAFE | Runs once on our own MathJax SVG output (not model or learner text). |
| 36bb9f9c, f377d365 | scripts/lesson_eval.py:52 | dos | SAFE | Dev-only eval script over our own recorded replies, never reachable from a request. |
| 25ded8a4 | frontend WhiteboardCanvas.tsx:782 | weak-cryptography | SAFE | `Math.random` only makes a client-side stroke id suffix next to `Date.now()`; nothing security-relevant depends on it. |
| (new) | scripts/memory_eval.py:116 | dos | FIXED | Lazy `.+?` plus optional quotes before `\s*$` rewritten with string methods (`quote_after_marker`); same quote on normal judge output. Dev-only script. |
| 1bb31878 | engine/fonts.py:19 | encrypt-data | SAFE | `http://www.w3.org/2000/svg` is an XML namespace identifier, never fetched. |
| e19fce62 | engine/sanitiser.py:28 | encrypt-data | SAFE | Same SVG namespace identifier passed to `register_namespace`. |

Commit for the FIXED rows: see the commit that added this file.
