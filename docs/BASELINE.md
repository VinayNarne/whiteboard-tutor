# Baseline of the live tutor (before any prompt change)

**Rule of the eval: before blaming the model for what is missing on the board, compare the raw model output with the stored board** (`tests/eval_lossless.py`; the log keeps every drawing as the model wrote it). A silent loss in our own code cost three experiments (F, G and half of C to E) before it was found.

Taken 2026-10-07 with the prompt, tools and guards exactly as committed at `c852a26`. Three runs of the 8-topic eval
(history, maths, biology, code, economics, physics, language, a deliberately dense OSI/TCP-IP request), two learner
turns per topic, so 16 turns per run, real model (Azure deployment `gpt-4o-mini`, which serves **`gpt-4.1-mini`**, see "Which model is behind the name" below) and real voice. Script:
`LP_API=http://127.0.0.1:8100/api python tests/eval_baseline.py --runs 3`. Raw data: `docs/baseline/run{1,2,3}.json`
(embedded font removed), the text of every run in `docs/baseline/run{1,2,3}_texts.md`, summary in
`docs/baseline/summary.json`. Re-run the same command after a prompt change and compare.

## Which model is behind the name

The deployment is called `gpt-4o-mini`, but Azure upgraded it to `gpt-4.1-mini` under the same name (the resource lists it as
model `gpt-4.1-mini`, checked 2026-10-08, and the service answers a call with `gpt-4.1-mini-2025-04-14`). It was last changed
on 2025-12-23, before baseline A (2026-10-04), so **all runs of A to E used gpt-4.1-mini** under that name. The model stays
the same for F (a stronger model was considered and not used, no deployment was created). Runs from baseline F on
record the model the service reported in `run{n}.json` (`metrics.author`) and in every `model_usage` log line (`model`,
`deployment`, `cached_tokens`); runs before that did not, so their model is taken from this paragraph. The resource also holds
`gpt-35-turbo-16k` (another label on `gpt-4.1-mini`) and `text-embedding-3-small`: no stronger chat model is deployed.

Author model setting: `AZURE_OPENAI_AUTHOR_DEPLOYMENT` (default: the same deployment as before). The eval judge always uses
`AZURE_OPENAI_DEPLOYMENT`, so it does not move when the author does.

Prices used for cost per turn (US dollars per 1M tokens, standard tier; OpenAI pricing page https://developers.openai.com/api/docs/pricing
read 2026-10-08, and the Azure OpenAI price list gives the same figures for global standard):

| model | input | cached input | output |
|---|---|---|---|
| gpt-4.1-mini (the model in A to F) | 0.40 | 0.10 | 1.60 |

Cost per turn in `tests/compare_baselines.py` is the logged prompt and completion tokens at these list prices with **no cache
discount**, so every column is on the same basis (baselines A to E did not log cached tokens).

## Per run

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| **Retries** (guardrail rejections that made the tutor redraw) | 13 | 7 | 13 |
| ... label text overlaps | 8 | 2 | 2 |
| ... background-frame guard (800/600) | 2 | 3 | 6 |
| ... element overlap | 3 | 2 | 4 |
| ... other | 0 | 0 | 1 |
| Chat replies / distinct first sentences | 16 / 16 | 16 / 16 | 16 / 16 |
| ... distinct 3-word openers | 12 | 13 | 12 |
| Narrations / distinct first sentences | 23 / 23 | 25 / 25 | 23 / 23 |
| ... distinct 3-word openers | 14 | 17 | 19 |
| **Layouts**: distinct by element boxes rounded to 100 px (of 8) | 8 | 7 | 8 |
| ... clusters of similar layouts (drawn area overlaps 50% or more) (of 8) | 3 | 2 | 2 |
| ... mean overlap between topics' drawn areas (Jaccard) | 0.51 | 0.46 | 0.42 |
| ... most similar pair | biology / language 0.95 | economics / history 0.82 | dense / language 0.72 |
| Advisory hints shown / modify events | 1 / 1 | 1 / 0 | 0 / 0 |
| `get_current_page_state` calls (16 turns) | 5 | 4 | 3 |
| Model calls / prompt tokens / completion tokens | 51 / 320k / 31k | 44 / 238k / 20k | 50 / 296k / 34k |
| Speech characters | 9,355 | 9,934 | 9,264 |
| Hard failures | 0 | 0 | 0 |

**How to read the sentence and layout rows.** Every first sentence is different because the topics differ, so that
count says little. Openers are the better signal. Across the 3 runs, **62% of the 48 chat replies and 65% of the 71
narrations start with "Here ..." or "This diagram/visual ..."** ("here is" 24 times, "here we" 20, "here you" 14,
"this diagram" 12). The layout measure compares the area each topic's first page covers, using every element's bounding
box; two topics count as "the same layout" when those areas overlap by 50% or more. With 8 topics that gives 2 to 3
distinct layouts. In 21 of 24 topic-runs the first element starts in the same top-left cell (x under 100 px, y between 100 and 300 px).

**Narration length.** The prompt asks for 80-200 words. Measured: median 52, range 16-146 words, and **21 of 71 inside
the asked range**. So that instruction is already mostly ignored.

## Factual review

Reviewer: Claude Opus (a stronger model than the tutor), one fresh reviewer per run, reading `run<N>_texts.md` (replies,
spoken narration and text written on the board) from its own knowledge with no web access, factual errors only. The
Fable model was tried first and was unavailable on this plan. One reviewer per run, nobody cross-checked the others, and
severity was judged separately each time, so treat the counts as an estimate.

| topic | run 1 | run 2 | run 3 | total |
|---|---|---|---|---|
| history | 1 | 2 | 2 | 5 |
| maths | 0 | 0 | 2 (1 major) | 2 |
| biology | 2 | 1 | 1 | 4 |
| code (binary search) | 1 (major, **our bug**) | 1 | 0 | 2 |
| economics | 0 | 0 | 1 | 1 |
| physics | 1 | 1 | 1 | 3 |
| language | 0 | 0 | 0 | 0 |
| dense (OSI / TCP-IP) | 3 (2 major) | 1 | 0 | 4 |
| **total** | **8 (3 major)** | **6 (0 major)** | **7 (1 major)** | **21 (4 major)** |

Four major errors in 24 topic-runs, one of them caused by our sanitiser, not the model. Examples:

- **Major, model (maths, run 3):** narration says "the green vertical and horizontal lines form the tangent line"; a
  tangent is a single straight line touching the curve, those lines show rise and run.
- **Major, model (dense, run 1):** the TCP handshake is drawn with "&larr; ACK" and the TLS step as "Certificate &rarr;":
  the last ACK goes client to server and the certificate goes server to client, so the arrows are backwards.
- **Major, our bug (code, run 1):** the board reads "3. While low = high:" and "Else if array[mid]  target". The model
  wrote `<=` and `<`; our sanitiser deleted them (see below). The spoken narration was right.
- **Minor, model (biology, run 2):** "Water (H20O)" instead of H2O.
- **Minor, repeated in 2 of 3 runs (history):** the Triple Entente described as a mutual-defence pact (it was a set of
  informal understandings; Britain had no treaty duty to fight).
- **Minor, repeated in 2 of 3 runs (biology):** the Calvin cycle "produces glucose" (it produces G3P; glucose is made
  afterwards), and "dark reactions" as the name.
- **Minor, repeated in 2 of 3 runs (physics):** a book "remains at rest until an external force acts on it" (it is a net
  force; gravity and the table's push already act on it).
- **Minor (dense, run 2):** "Transport (TCP, UDP) ensures data delivery" (UDP does not).
- Maths (2 of 3 runs), economics (2 of 3 runs) and language (3 of 3 runs) had no errors.

**What this says.** On intro-level topics the tutor is mostly accurate; errors are small simplifications, several of which recur in 2 of 3 runs
(habits of the model, so a prompt change is unlikely to remove them). The serious ones sit in
detail: step-by-step protocol arrows, pseudocode and the tangent description. There is no grounding or checking
(`PHASE1_AUDIT.md`, item 10), so nothing would catch them. Not measured: topics outside these 8, other languages,
sources for any claim.

## A bug found by the review: our sanitiser corrupted board text (fixed, see below)

Reproduced in `engine.sanitiser.sanitize_svg` before the fix:

| the model writes in a `<text>` | stored and shown |
|---|---|
| `While low <= high:` | `While low = high:` (the `<` and whatever follows up to the next `>` was dropped) |
| `Else if array[mid] < target` | `Else if array[mid]  target` |
| `SYN &rarr; server` (an HTML entity, not valid XML) | `SYN &amp;rarr; server`, shown literally as "&rarr;" |
| `While low &lt;= high:` (escaped) | correct |
| `SYN &#8594; server` (numeric entity) | correct |

**Corrected count.** The baseline holds 12 corrupted board lines, all in run 1: 10 double-encoded arrows in one
drawing (`tcp_tls_http_handshake`, dense topic) and 2 lines with a deleted `<` in `binary_search_overview` (code topic).
An earlier version of this file said "10 double-encoded entities across the 3 runs"; I had scanned run 1 only, and runs
2 and 3 had none. One more board line, "Energy for Plant Growth  Metabolism" (run 2, biology), has a double space where
something was deleted; I cannot tell what, because the model's raw output was not saved at the time.

## Sanitiser fix: before and after

The fix (`engine/sanitiser.py: repair_text_markup`) runs before parsing: HTML entity names become numeric references, a
`<` that does not start a known element becomes `&lt;`, and a `&` that is not a valid entity becomes `&amp;`. Real tags
are parsed as before, so the allowlist removes the same things. "Before" below is the OLD sanitiser run on the model
input reconstructed from the stored text (the raw model output was not saved); it reproduces the stored text exactly in
all 12 cases, which is what makes the reconstruction trustworthy. From now on the raw drawing text is logged
(`draw_started.raw_svg`).

| # | where | stored on the board (baseline) | reconstructed model input | old sanitiser reproduces it? | new sanitiser shows |
|---|---|---|---|---|---|
| 1 | run 1, dense, handshake | `SYN &amp;rarr;` | `SYN &rarr;` | yes | `SYN →` |
| 2 | run 1, dense, handshake | `&amp;larr; SYN-ACK` | `&larr; SYN-ACK` | yes | `← SYN-ACK` |
| 3 | run 1, dense, handshake | `&amp;larr; ACK` | `&larr; ACK` | yes | `← ACK` |
| 4 | run 1, dense, handshake | `ClientHello &amp;rarr;` | `ClientHello &rarr;` | yes | `ClientHello →` |
| 5 | run 1, dense, handshake | `&amp;larr; ServerHello` | `&larr; ServerHello` | yes | `← ServerHello` |
| 6 | run 1, dense, handshake | `Certificate &amp;rarr;` | `Certificate &rarr;` | yes | `Certificate →` |
| 7 | run 1, dense, handshake | `&amp;larr; CertificateVerify` | `&larr; CertificateVerify` | yes | `← CertificateVerify` |
| 8 | run 1, dense, handshake | `Finished &amp;rarr;` | `Finished &rarr;` | yes | `Finished →` |
| 9 | run 1, dense, handshake | `&amp;larr; Finished` | `&larr; Finished` | yes | `← Finished` |
| 10 | run 1, dense, handshake | `GET /index.html &amp;rarr;` | `GET /index.html &rarr;` | yes | `GET /index.html →` |
| 11 | run 1, code, binary search | `3. While low = high:` | `3. While low <= high:` | yes | `3. While low <= high:` |
| 12 | run 1, code, binary search | `- Else if array[mid]  target, low = mid + 1` | `- Else if array[mid] < target, low = mid + 1` | yes | `- Else if array[mid] < target, low = mid + 1` |

Tests: `tests/test_sanitiser_text.py` (41 pass, plus one browser test that reads the characters from the live board).
Must survive: `low <= high`, `a < b`, `x & y`, `&rarr;`, `&lt;` and 10 more forms, also after draw, modify, save and
reload, in the export, and idempotent. Must still be caught: script tag, `onload`, `foreignObject`, `javascript:` href,
external href (on `<image>` and on a shape), `<style>` with `url()`, style attribute with `url()`, external `fill`
url, a script hidden in text, a broken-up `<scr<script>ipt>`, `onerror`; DOCTYPE and ENTITY are still refused. Run
against the old sanitiser, 20 of the "must survive" tests fail and every "must still be caught" test passes, so they
test the fix and nothing else.

Note the reviewers' counts in the table above include the run-1 binary-search item (major) that was our bug, not the
model's; the arrow directions in the handshake diagram were the model's own mistake and remain.

# Baseline B: after the code fixes, prompt unchanged

Taken after the sanitiser fix (`d091e48`, `04d4ed4`) and the shared frame constant (`5577118`). Same script, same 8
topics, 3 runs: `docs/baseline_B/`. Compare any time with `python tests/compare_baselines.py`.

**One correction on the way.** The first attempt at B (kept in `docs/baseline_B_with_br_bug/`) exposed a regression in
my first sanitiser fix: the model writes `<br/>` as a line break in board text (4 of 77 raw drawings), and after the
fix it was shown as the literal text "<br/>". Fixed in `04d4ed4` (a line break becomes a space, inline tags keep their
words) and B was re-run; the table below is the corrected B.

**Rule for claims** (yours): A's range is the noise band; a metric only changed if all three runs of the new condition
are outside it on the same side. Otherwise "no clear change".

| metric | A (before) | B (after code fixes) | verdict |
|---|---|---|---|
| Retries, total | 13 / 7 / 13 | 8 / 7 / 11 | no clear change |
| ... background-frame guard | 2 / 3 / 6 | 0 / 0 / 0 | **clear change** for this cause (all below A's band) |
| ... element overlap | 3 / 2 / 4 | 1 / 3 / 3 | no clear change |
| ... label text overlap | 8 / 2 / 2 | 5 / 3 / 2 | no clear change |
| ... transform | 0 / 0 / 0 | 0 / 1 / 0 | |
| ... other (all are "bleeds canvas": a line or box pushed past the bottom edge) | 0 / 0 / 1 | 2 / 0 / 6 | **new in B**, see below |
| Distinct 3-word reply openers (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | no clear change |
| Distinct narration openers (% of narrations) | 61 / 68 / 83 | 60 / 67 / 70 | no clear change |
| Replies+narrations starting "Here ..." / "This diagram ..." | 64 / 59 / 69 % | 71 / 60 / 64 % | no clear change |
| Layout clusters (of 8 topics) | 3 / 2 / 2 | 2 / 5 / 2 | no clear change |
| Mean layout overlap between topics (Jaccard) | 0.51 / 0.46 / 0.42 | 0.46 / 0.39 / 0.43 | no clear change |
| Words per narration, median | 52 / 51 / 58 | 59 / 60 / 61 | not judged (no good direction) |
| Narrations inside 80-200 words | 39 / 24 / 26 % | 40 / 25 / 35 % | |
| Hard failures (of 8 topics) | 0 / 0 / 0 | 0 / 0 / 0 | no clear change |
| Drawings whose raw text needed repair | not recorded | 1/33, 2/31, 2/31 (5%) | |

**What B says.**
- Steps 1 and 2 did exactly what they were meant to: the 11 background-frame retries of A are gone, and the sanitiser no
  longer eats text (5% of drawings contained something that needed repair).
- They did not reduce total retries. The frame rejections were replaced by a new kind: "bleeds canvas" (2, 0 and 6 retries),
  almost all in the tall handshake diagram of the dense topic. A plausible reason, not proven: the old guard forced the
  tutor to draw narrower shapes, which also kept drawings inside the board; without it the tutor draws wider and taller.
- Openers and layouts did not move, as expected: no prompt change yet.

**The noise band is wider than three runs suggest.** The first B attempt had the same prompt and almost the same code, yet
its median narration length was 68 / 80 / 78 words against 59 / 60 / 61 in the corrected B and 52 / 51 / 58 in A. Total
retries were 2 / 10 / 6. So when judging C, `compare_baselines.py` also shows a verdict against a 9-run band (A + B + the
first B), and a change should be trusted only if it is outside both.

# Baseline C: after the prompt changes (code guards untouched)

Taken after `c99e125`. Three runs: `docs/baseline_C/`. Factual review by Opus, one reviewer per run (same method as A).
Table made by `python tests/compare_baselines.py`. Verdicts follow your rule: only a move that puts all three runs outside
A's range counts, and I also give the verdict against the wider 9-run range (A + B + the first B) because B's runs showed
the noise is wider than A alone.

## A / B / C

| metric | A before | B after code fixes | C after prompt changes | C vs A band | C vs 9-run band |
|---|---|---|---|---|---|
| **Retries, total** | 13 / 7 / 13 | 8 / 7 / 11 | **92 / 97 / 70** | **clear: worse** | **clear: worse** |
| ... of which "diagram card has no `<text>` labels" | not a cause | not a cause | **77 / 97 / 69** | | |
| ... background frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | | |
| ... element overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | | |
| ... label text overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | | |
| ... transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | | |
| Distinct 3-word reply openers (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | **clear: worse** | **clear: worse** |
| Distinct 3-word narration openers (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | no clear change | no clear change |
| Replies+narrations starting "Here/This ..." | 64 / 59 / 69 % | 71 / 60 / 64 % | 40 / 22 / 28 % | clear: better | clear: better |
| Layout clusters (of 8) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | clear: better | no clear change |
| Mean layout overlap (Jaccard) | 0.51 / 0.46 / 0.42 | 0.46 / 0.39 / 0.43 | 0.07 / 0.03 / 0.19 | clear: better | clear: better |
| **Words per narration, median** | 52 / 51 / 58 | 59 / 60 / 61 | **18 / 18 / 18** | (not judged) | |
| Narrations inside the old 80-200 words | 39 / 24 / 26 % | 40 / 25 / 35 % | 2 / 0 / 0 % | | |
| Hard failures (of 8 topics) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change |
| Drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | **66 / 76 / 56** | | |
| Prompt tokens per turn | 20,026 / 14,878 / 18,533 | 14,871 / 15,156 / 19,439 | 30,490 / 44,022 / 25,803 | | |
| Speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | | |
| Minutes per run | 6 / 5 / 8 | 6 / 5 / 5 | **10.5 / 12.4 / 9.5** | | |
| Factual errors flagged | 8 / 6 / 7 | not run | 7 / 6 / 3 | no clear change | no clear change |
| ... of which major | 3 / 0 / 1 | not run | 1 / 0 / 0 | no clear change | no clear change |
| ... model-only (not our bugs) | 7 / 6 / 7 | not run | 7 / 6 / 3 | no clear change | no clear change |

## What went worse, and why

1. **Retries went up about eight-fold, from one rule.** 243 of the 259 retries in C are the validator's blocking
   "Semantic Whiteboard Rule" (`validate_geometry`, now C9 in `PROMPT_RULES.md`): a drawing that contains a rectangle of
   at least 120x60 and no `<text>` anywhere in the same drawing is rejected. **I missed it in the audit**: I listed the
   advisory hint C1 ("no label inside") but not this blocking twin. While the prompt demanded "container + title +
   labels" in every element, the tutor always satisfied it by habit. Once that recipe was removed (as you approved) the
   tutor started drawing shapes and their labels as separate elements, and every shape-only element was rejected.
   Runs took 9.5 to 12.4 minutes instead of 5 to 8, and prompt tokens per turn rose to 26k-44k.
2. **The tutor started talking to the learner about the rejections.** Three replies in the three runs, for example:
   "I see the system still rejects the detailed process card because it expects text inside a diagram card" and "my
   previous attempts to draw the boxes with text failed due to technical issues with the SVG formatting".
3. **Boards got fragmented and sparse.** Median text lines per element fell from 7 to 1, and 18% of drawn elements (37 of
   198) have no text at all (A and B: 1%). The tutor invented workarounds (`single_card_test`, `osi_app_card_text_only`,
   `handshake_diagram_simple`). Reviewers noted replies that describe content that is not on the board: the dense topic in
   runs 2 and 3 shows only titles ("Application Layer - HTTP") while the reply says all layers were drawn; biology shapes
   blank apart from four labels; in run 1 the economics reply never answers "what happens when demand rises".
4. **Narration became very short.** Median 18 words (A 52, B 60). Removing the 80-word floor, as asked, did this: only 2
   of about 200 narrations are inside the old range. Total speech per turn did not fall (about 500-580 characters),
   because there are three times as many drawings. Whether 18 words per drawing is a good spoken explanation is a product
   decision for you.
5. **Reply openers did not diversify, they swapped templates.** Replies starting "Here/This ..." fell from 64% to 10%, but
   replies starting "I have drawn/added/shown ..." rose from 10% to 64% (23 of 48 are "I have drawn ..."). Distinct
   3-word reply openers fell (12-13 to 8-9). Narrations did improve: starting "Here/This ..." 71% (A) to 41% (C), though
   "Here is the ..." is still the most common narration opener.

## What did not clearly change, or is unreliable

- **Layout diversity looks "better" (clusters 7/8/4, overlap 0.07/0.03/0.19), but I would not claim it.** The boards it
  was measured on are sparse and fragmented because of the rejection storm, which scatters small pieces around. Re-measure
  after the label rule is fixed.
- **Factual errors: no clear change** (7/6/3 against 8/6/7; major 1/0/0 against 3/0/1), and there was less content to
  check. Run 1 still had one major error (a wrong binary-search midpoint: "middle element value 8" for an array whose
  middle is 16). Recurring minor imprecisions are unchanged: Triple Entente as an alliance, Italy shown in the wartime
  Triple Alliance, "a force" instead of "net force", present perfect described as repeated or recent.
- **Hard failures 0/0/0** in every condition: the eval's own checks cannot see any of the problems above, so a "PASS" in
  `eval_tutor.py` does not mean the tutor is fine. It needs checks for retries, empty elements and replies that claim
  content not on the board.
- **New, unrelated:** in run 1 the model emitted a DEL control character (`\x7f`) where it meant an arrow in five lines of
  a worked example ("lim (h \x7f 0)"). It is in the model's raw output, not our sanitiser. Stripping control characters
  would at least avoid invisible garbage, but the arrow is not recoverable.
- The reviewers' notes about "&lt;" and "&amp;" in labels were an artefact of how I exported the text (it showed the
  stored XML escapes); the export now unescapes.

## Net effect of steps 1, 2 and 4

- Steps 1 and 2 (B): worked as intended; no measurable harm; total retries unchanged because a new cause ("bleeds canvas")
  replaced the frame retries.
- Step 4 (C): removed the copied example and most content rules as approved, but exposed a content rule in code. On the
  measures you listed, **retries clearly worse, reply-opener variety clearly worse, narration much shorter, factual errors
  no clear change, layouts not trustworthy.** I would not call anything improved except the share of "Here is ..." openers
  in narrations.

## Proposed next step (not started)

Remove the blocking rule C9 (and decide C1/C2), keep the guards that measure physics (bounds, overlap, label overlap,
duplicate ids, transform), then re-run C as D with the same prompt. Two smaller items for the same decision: strip control
characters in board text, and add eval checks for retries per turn, text-less elements and "reply mentions a rejection".

# Baseline D: label rule is a note, control characters stripped, prompt unchanged from C

Code changes only since C: the blocking "card has no text" rule is now a log note (`e73d631`), control characters are
stripped (`7905738`), and the eval has the new checks (`3aef661`). The prompt and tool text are byte-identical to C
(checked by hash, `a4c1dcb7e7`). Three runs: `docs/baseline_D/`. Factual review: Opus, one reviewer per run, with the added
task of listing every reply or narration that describes something not in the board text.

**Normal range = the six runs of A and B.** "Clear" means all three runs of C or D are outside it on the same side;
"2 of 3 outside" is a near miss and counts as no clear change. Two things could not be computed everywhere: "replies
describing what is not on the board" exists only for D (it was not asked for A, B, C), and B has no factual review.

## A / B / C / D

| metric | A | B | C | D | C vs normal | D vs normal |
|---|---|---|---|---|---|---|
| retries, total | 13 / 7 / 13 | 8 / 7 / 11 | 92 / 97 / 70 | 0 / 1 / 1 | clear: worse | clear: better |
| retries per turn (total) | 0.81 / 0.44 / 0.81 | 0.5 / 0.44 / 0.69 | 5.75 / 6.06 / 4.38 | 0.0 / 0.06 / 0.06 | clear: worse | clear: better |
| retries per turn (worst topic) | 2.5 / 1.5 / 1.5 | 1.5 / 1.5 / n/a | 12.0 / 13.0 / 10.5 | 0 / 0.5 / 0.5 | clear: worse | clear: better |
|   retries: background_frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 1 |  |  |
|   retries: overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | 0 / 0 / 0 |  |  |
|   retries: labels_overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | 0 / 0 / 0 |  |  |
|   retries: transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | 0 / 0 / 0 |  |  |
|   retries: other | 0 / 0 / 1 | 2 / 0 / 6 | 80 / 97 / 69 | 0 / 0 / 0 |  |  |
| elements with no text (%) | 0 / 4 / 0 | 0 / 4 / 0 | 12 / 21 / 23 | 71 / 62 / 50 | clear: worse | clear: worse |
| median text lines per element | 8 / 7 / 8 | 8 / 6.0 / 9.0 | 1.0 / 1.0 / 1.0 | 0 / 0.0 / 0.5 | clear: worse | clear: worse |
| replies/narrations that mention a rejection | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 1 | 0 / 0 / 0 | clear: worse | no clear change |
| narration words, median | 52 / 51 / 58 | 59 / 60.0 / 59.5 | 18.0 / 17.5 / 18.0 | 22 / 18.5 / 21.0 |  |  |
| narration words per turn | 91 / 95 / 90 | 107 / 96 / 77 | 90 / 91 / 74 | 88 / 73 / 89 |  |  |
| same first two words: replies (%) | 25 / 25 / 19 | 25 / 31 / 25 | 62 / 62 / 69 | 56 / 62 / 56 | clear: worse | clear: worse |
| same first two words: narrations (%) | 30 / 20 / 17 | 40 / 33 / 40 | 45 / 18 / 30 | 35 / 33 / 22 | no clear change | no clear change |
| reply openers, distinct 3-word (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | 11 / 10 / 10 | clear: worse | no clear change (2 of 3 outside) |
| narration openers, distinct 3-word (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | 71 / 71 / 70 | no clear change (2 of 3 outside) | no clear change |
| replies+narrations starting 'Here/This' (%) | 64 / 59 / 69 | 71 / 60 / 64 | 40 / 22 / 28 | 28 / 29 / 21 | clear: better | clear: better |
| layout clusters (of 8) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | no clear change (2 of 3 outside) | clear: better |
| layout overlap between topics (Jaccard) | 0.506 / 0.456 / 0.42 | 0.461 / 0.389 / 0.431 | 0.07 / 0.032 / 0.185 | 0.002 / 0.0 / 0.0 | clear: better | clear: better |
| narrations with no [[MARK]] marker (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | clear: worse | clear: worse |
| narrations with a single-bracket marker (read aloud) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 6 / 0 | 0 / 5 / 0 | no clear change | no clear change |
| hard failures (of 8) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change |
| drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | 66 / 76 / 56 | 55 / 52 / 64 |  |  |
| prompt tokens per turn | 20026 / 14878 / 18533 | 14871 / 15156 / 19439 | 30490 / 44022 / 25803 | 10485 / 8126 / 11079 |  |  |
| speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | 552 / 465 / 556 |  |  |
| tutor seconds per turn (mean) | 24.6 / 18.5 / 28.1 | 21.2 / 17.6 / 20.1 | 39.4 / 46.2 / 35.5 | 15.2 / 13.1 / 14.4 |  |  |
| factual errors flagged | 8 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | no clear change | no clear change |
|   of which major | 3 / 0 / 1 | n/a / n/a / n/a | 1 / 0 / 0 | 1 / 1 / 0 | no clear change | no clear change |
|   model-only (not our bugs) | 7 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | no clear change | no clear change |
| replies describing what is not on the board | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 36 / 37 / 28 |  |  |

## What D fixed

- **The rejection storm is gone.** Retries 0 / 1 / 1 (normal 7-13; C had 92 / 97 / 70). The only two rejections were the
  frame guard: a 1080x560 and a 1080x580 panel (63% and 65% of the board, just over the 60% limit). A panel that size is a
  legitimate diagram area, so the limit may deserve a second look; I have not changed it.
- Runs got faster and cheaper: 13-15 seconds per turn (A 18-28), prompt tokens per turn 8-11k (A 15-20k).
- Control characters: none stripped in these 3 runs (`control_chars_stripped` count 0), so the DEL glitch did not recur.
- "Here/This ..." openers: 21-29% (normal 59-71%), but see the next section for what replaced them.

## What is still worse than A

1. **Boards are mostly blank shapes.** Elements with no text inside them: **71 / 62 / 50%** (normal 0-4%). **Median text
   lines per element: 0 / 0 / 0.5** (normal 6-9). Of 103 text-less elements over the three runs, **all 103 have no text from
   any other element on top of them either**: the labels are not drawn as separate elements, they are not drawn at all.
2. **Replies and narrations describe content that is not on the board: 36 / 37 / 28** (reviewer counts, text only; purely
   visual claims excluded; never measured before D). Examples from the reports: the OSI model element has 56 words of
   narration naming seven layers and their protocols, and is one blank shape; the physics "three cards" are three blank cards
   with only a title; the binary-search steps have no numbers; the derivative "formula" element is a heading with no formula.
3. **Markers.** 40 / 56 / 42% of narrations have no `[[MARK:id]]` marker (A and B: 0%), and 5 narrations in run 2 write it
   with single brackets, which the voice would read aloud ("MARK colon ..."). Without a marker the element is not revealed at
   its spoken word. This is a recording rule the model followed 100% of the time while the prompt had an example; since the
   example was removed (as instructed) it follows it about half the time. No test or guard catches it.
4. **Replies share one template.** The same first two words start 56 / 62 / 56% of replies (normal 19-31%): "I have
   drawn ...". The "Here is ..." template was swapped for another, not removed. Narrations: no clear change.
5. **Narrations are short** (median 22 / 18.5 / 21 words against 51-60). Total narration per turn is about the same (73-89 words)
   because there are twice as many drawings (52-64 per run against 20-25).
6. The advisory hint "this card has no label" was shown 62 times in the three runs; the tutor edited a drawing 5 times (2, 0, 3).
   The hint does not change what it does.

**Hard failures: 0 / 0 / 0** again: the eval's own pass/fail cannot see any of this.

## What I would not call better, even though a number moved

- **Layout diversity** (8 of 8 clusters in every run; overlap between topics about 0): the boards it is measured on are
  small blank shapes, so different positions say nothing about teaching. Not claimed.
- **Factual errors** 6 / 6 / 5 flagged (major 1 / 1 / 0) against A 6-8 (major 0-3): no clear change. Majors: binary search
  with the wrong midpoint (40 instead of 50; run 2) and a search that discards a match (run 1). With the board mostly
  blank there is less that can be checked.

## The median element has about 0 text lines: why (not edited)

In D, an "element" is one primitive. Run 1: 39 elements are a single shape with no text, 13 are a single text (a title),
3 combine shape and text; runs 2 and 3: 32 / 19 / 1 and 32 / 29 / 3. Examples: `osi_model` (1 shape, no text, 56 words of
narration), `axes` (1 path), `step1` ... `step5` (1 rectangle each). Before the C prompt, an element was a whole labelled
diagram component, because of the recipe that was removed. Nothing now says what an element contains. The lines I think
cause it, with line numbers in `engine/author.py`:

| line | text | why |
|---|---|---|
| 203 | `draw_new_element`: "Adds a new named element to the whiteboard, drawn as one <g id='element_id'> group." | defines an element only as "one group". With the old recipe gone, the natural reading is one shape per call. This is the most likely cause |
| 215 | `svg_fragment`: "The complete SVG element to add, wrapped in <g id='...'>." | "SVG element" in SVG vocabulary is a single shape (`rect`, `path`); the model supplies one |
| 222, 229 | `narration` (a required parameter): "What you say aloud when this element appears ..." with "[[MARK:element_id]] MUST be the very first thing" | one spoken passage and one marker per element rewards splitting an explanation into many small elements, each narrated when it appears |
| 92 and 112 | "Each element you draw comes with narration that is spoken aloud as the element appears." / "draw it as you speak" | the same push: build the explanation piece by piece. Drawings per run went from 23 to 52-64 |
| 106 | "Whatever the learner needs to identify should be identifiable on the board." | too weak: the tutor counts its own narration as identifying the shape, and the hint that says otherwise (62 times) is advisory |

The current prompt does not say that text belongs on the board at all. I have not edited any of these lines.

## New rejection reasons

None. All 2 retries are the frame guard (63% and 65% panels). The old label rule is no longer a rejection. New non-rejection
findings: missing or single-bracket markers (above), and `unlabeled_card_note` was logged 62 times (36% of the 171 drawings).

## Proposals (not done)

1. **Make the marker the system's job.** Prepend `[[MARK:element_id]]` in code when the narration lacks it, and turn
   `[MARK:id]` into the double-bracket form. This is a recording detail, not content, and the model stopped doing it
   reliably once the example went. It needs a test and no prompt change.
2. Decide how an element is described in the five places above (your call, I will not add an example).
3. Frame limit: 0.6 rejected two legitimate 1080x560-580 panels; 0.7 would accept them. Needs your decision.
4. Eval: add "replies describing content not on the board" as an automatic check (the reviewer found 28-37 per run), and a
   check for narrations without a marker.

# Targets for baseline E (fixed before the run)

Written and committed before E was run. The only change planned between D and E is: the marker is repaired by code
(`f323a2c`) and the element definition in the two tool-description lines is rewritten (next commit). Nothing else.

| # | target (your wording) | how I will judge it, fixed now |
|---|---|---|
| 1 | retries 13 or fewer per run | every one of the 3 E runs has 13 or fewer `draw_failed` events |
| 2 | elements with no text 15 percent or less | every E run is at or below 15% (elements with no `<text>` at all, `tests/eval_checks.py`) |
| 3 | replies or narrations describing content not on the board: clearly below D (28 to 37) | the Opus reviewer's count (same method as D) is below 28 in every E run. The cheap-model judge is reported next to it (D: 26 / 41 / 34; normal range 5-13), as a second signal, not the test |
| 4 | hard failures 0 | 0 in every E run |
| 5 | opener variety and layout clusters not worse than D | no E run below D's lowest value: distinct 3-word reply openers at least 10 of 16, distinct 3-word narration openers at least 70%, layout clusters at least 8 of 8 (D was at the maximum, so any E run below 8 counts as worse; layout is measured on bounding boxes and means little on mostly blank boards) |
| 6 | factual errors not above D | no E run above D's highest (6) flagged errors; the mean is shown too (D: 5.7) |

Also reported, no target: median text lines per element, total narration words per turn, narrations whose marker was
missing or wrong as the model wrote them (from the repair log), the judge count, new rejection reasons, what is still worse
than A. The normal range for any claim of "better" or "worse" stays the six runs of A and B.

## About the two new checks

- **Marker as the model wrote it.** For runs before the repair, from the stored narrations (A, B, C, D); for E, from the
  `marker_repaired` events in the log (stored text is repaired). The two are comparable but not identical: stored
  narrations cover accepted drawings, the log covers every attempt.
- **Content not on the board (cheap-model judge, `tests/eval_judge.py`).** One call per statement to the tutor's own
  small model. On baseline D it flags 101 statements in total, the same as the Opus reviewer (101), with single runs
  differing by up to 10, and it flags 5-13 per run on the well-labelled A and B runs. It separates D and C from A and B
  by about four times, so it is a regression signal, not an exact count. A one-call-per-topic first version found only
  4 / 9 / 4 and was dropped.

# Baseline E: markers repaired by code, element definition rewritten (two tool-description lines)

Changes since D: the marker is repaired in code (`f323a2c`), the two element-definition lines in the tool text are rewritten
(`37e7dc6`: "an element is one <g> group, any number of shapes and text; the narration is tied to it through its id, so whatever
the narration refers to must be inside the same group"), and two new eval checks exist (`de517e2`). The system prompt, the
hints and every guard are unchanged. Three runs: `docs/baseline_E/`; Opus review per run, same method as D.

## A / B / C / D / E

| metric | A | B | C | D | E | C vs normal | D vs normal | E vs normal |
|---|---|---|---|---|---|---|---|---|
| retries, total | 13 / 7 / 13 | 8 / 7 / 11 | 92 / 97 / 70 | 0 / 1 / 1 | 1 / 6 / 1 | clear: worse | clear: better | clear: better |
| retries per turn (total) | 0.81 / 0.44 / 0.81 | 0.5 / 0.44 / 0.69 | 5.75 / 6.06 / 4.38 | 0.0 / 0.06 / 0.06 | 0.06 / 0.38 / 0.06 | clear: worse | clear: better | clear: better |
| retries per turn (worst topic) | 2.5 / 1.5 / 1.5 | 1.5 / 1.5 / n/a | 12.0 / 13.0 / 10.5 | 0 / 0.5 / 0.5 | 0.5 / 2.0 / 0.5 | clear: worse | clear: better | no clear change (2 of 3 outside) |
|   retries: background_frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 1 | 0 / 0 / 1 |  |  |  |
|   retries: overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | 0 / 0 / 0 | 0 / 5 / 0 |  |  |  |
|   retries: labels_overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |
|   retries: transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 |  |  |  |
|   retries: other | 0 / 0 / 1 | 2 / 0 / 6 | 80 / 97 / 69 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |
| elements with no text (%) | 0 / 4 / 0 | 0 / 4 / 0 | 12 / 21 / 23 | 71 / 62 / 50 | 40 / 52 / 56 | clear: worse | clear: worse | clear: worse |
| median text lines per element | 8 / 7 / 8 | 8 / 6.0 / 9.0 | 1.0 / 1.0 / 1.0 | 0 / 0.0 / 0.5 | 1 / 0.0 / 0 | clear: worse | clear: worse | clear: worse |
| replies/narrations that mention a rejection | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 1 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | no clear change | no clear change |
| narration words, median | 52 / 51 / 58 | 59 / 60.0 / 59.5 | 18.0 / 17.5 / 18.0 | 22 / 18.5 / 21.0 | 25 / 25.5 / 23 |  |  |  |
| narration words per turn | 91 / 95 / 90 | 107 / 96 / 77 | 90 / 91 / 74 | 88 / 73 / 89 | 94 / 84 / 78 |  |  |  |
| same first two words: replies (%) | 25 / 25 / 19 | 25 / 31 / 25 | 62 / 62 / 69 | 56 / 62 / 56 | 62 / 56 / 88 | clear: worse | clear: worse | clear: worse |
| same first two words: narrations (%) | 30 / 20 / 17 | 40 / 33 / 40 | 45 / 18 / 30 | 35 / 33 / 22 | 28 / 38 / 30 | no clear change | no clear change | no clear change |
| reply openers, distinct 3-word (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | 11 / 10 / 10 | 10 / 9 / 5 | clear: worse | no clear change (2 of 3 outside) | clear: worse |
| narration openers, distinct 3-word (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | 71 / 71 / 70 | 64 / 62 / 65 | no clear change (2 of 3 outside) | no clear change | no clear change |
| replies+narrations starting 'Here/This' (%) | 64 / 59 / 69 | 71 / 60 / 64 | 40 / 22 / 28 | 28 / 29 / 21 | 23 / 29 / 31 | clear: better | clear: better | clear: better |
| layout clusters (of 8) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | 8 / 7 / 7 | no clear change (2 of 3 outside) | clear: better | clear: better |
| layout overlap between topics (Jaccard) | 0.506 / 0.456 / 0.42 | 0.461 / 0.389 / 0.431 | 0.07 / 0.032 / 0.185 | 0.002 / 0.0 / 0.0 | 0.0 / 0.021 / 0.034 | clear: better | clear: better | clear: better |
| narrations with no valid marker, as the model wrote them (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 35 / 19 / 14 | clear: worse | clear: worse | clear: worse |
| narrations with no marker, as stored (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 0 / 0 / 0 | clear: worse | clear: worse | no clear change |
| narrations with a single-bracket marker, as stored | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 6 / 0 | 0 / 5 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change |
| hard failures (of 8) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change |
| drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | 66 / 76 / 56 | 55 / 52 / 64 | 53 / 42 / 43 |  |  |  |
| prompt tokens per turn | 20026 / 14878 / 18533 | 14871 / 15156 / 19439 | 30490 / 44022 / 25803 | 10485 / 8126 / 11079 | 12188 / 9280 / 10124 |  |  |  |
| speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | 552 / 465 / 556 | 633 / 544 / 524 |  |  |  |
| tutor seconds per turn (mean) | 24.6 / 18.5 / 28.1 | 21.2 / 17.6 / 20.1 | 39.4 / 46.2 / 35.5 | 15.2 / 13.1 / 14.4 | 16.0 / 15.9 / 14.0 |  |  |  |
| factual errors flagged | 8 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | no clear change | no clear change | no clear change |
|   of which major | 3 / 0 / 1 | n/a / n/a / n/a | 1 / 0 / 0 | 1 / 1 / 0 | 0 / 0 / 2 | no clear change | no clear change | no clear change |
|   model-only (not our bugs) | 7 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | no clear change | no clear change | no clear change |
| replies describing what is not on the board | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 36 / 37 / 28 | 33 / 26 / 29 |  |  |  |
| judge: statements describing content not on the board | 10 / 13 / 12 | 8 / 12 / 5 | 27 / 28 / 30 | 26 / 41 / 34 | 31 / 32 / 30 | clear: worse | clear: worse | clear: worse |

## Targets (fixed before the run, `de517e2`)

| # | target | E | result |
|---|---|---|---|
| 1 | retries 13 or fewer per run | 1 / 6 / 1 | **met** |
| 2 | elements with no text 15% or less | 40 / 52 / 56% | **missed** (D: 71 / 62 / 50%; normal 0-4%) |
| 3 | content described but not on the board clearly below D (28-37): reviewer count below 28 in every run | 33 / 26 / 29 | **missed** (two runs above 28; mean 29.3 against D's 33.7). The cheap judge says 31 / 32 / 30 against D's 26 / 41 / 34: no change |
| 4 | hard failures 0 | 0 / 0 / 0 | **met** |
| 5 | opener variety and layout clusters not worse than D | reply openers 10 / 9 / 5 (D 11 / 10 / 10); narration openers 64 / 62 / 65% (D 71 / 71 / 70); layout clusters 8 / 7 / 7 (D 8 / 8 / 8) | **missed**: lower than D's lowest value in 2 runs (replies), 3 runs (narrations), 2 runs (layout). Against the normal range, narration openers and layout are within it; reply openers are clearly worse (run 3: 5 of 16, 14 of 16 replies start "I have drawn") |
| 6 | factual errors not above D (most 6) | 7 / 3 / 7 | **missed** by the fixed rule (two runs at 7); the mean is the same as D's (5.7), and the two majors in run 3 are both binary-search traces (the middle element of the right half given as 9 instead of 12, and 7 for an array that has no 7) |

**Two of six targets met.** Both are about the rejection storm, which D had already fixed.

## What changed against D, and what did not

- **Markers:** as the model wrote them, 35% / 19% / 14% of narrations had a missing or wrong marker (D: 40 / 56 / 42%). Every
  narration is now stored with a valid marker and nothing marker-like reaches the voice. Reasons in the log: missing 27, wrong
  format 7. This is a real fix of a recording problem, not a change in what the model writes.
- **Boards: a little less blank, still mostly blank.** Elements with no text 40 / 52 / 56% (D 71 / 62 / 50%); median text lines per
  element 1 / 0 / 0 (A and B: 6-9). Element mix: shape only 21 / 22 / 24, text only 21 / 17 / 14, shape and text together
  11 / 3 / 5 (D: 3 / 1 / 3). Run 1 shows what the new definition can do (11 combined elements); runs 2 and 3 do not. Drawings per run
  fell from 52-64 (D) to 42-53.
- **Narration** is a little longer (median 23-25.5 words; D 18.5-22; A 52) and total narration per turn is the same (78-94 words).
- **Reply template got worse:** "I have drawn ..." starts 62 / 56 / 88% of replies (normal 19-31%). Narrations still start "Here is ..."
  28-38% of the time.
- **Retries** 1 / 6 / 1 (run 2: 5 overlaps in biology and economics); no new rejection reason. Runs take 14-16 seconds a turn.
- **Facts:** 7 / 3 / 7 errors flagged (D 6 / 6 / 5; A 8 / 6 / 7); major 0 / 0 / 2. No clear change from normal.

## What the boards look like

The two sentences the reviewers wrote for all three runs are the same: the tutor speaks content the board does not hold. Examples:
- **Physics:** six elements per run, each with 1-2 sentences of narration (the three laws and an everyday example of each),
  none of them with any text. The board shows only the title.
- **OSI / TCP-IP and the handshakes:** blocks and diagrams with no layer names, protocol names or message names; the narration
  lists seven layers with their protocols.
- **Language:** two blank boxes for "past simple" and "present perfect" with narration of the rules and the example sentences.
- **Maths:** the "worked example" element is empty (no f(x) = x squared, no steps, no 2x). **Code:** the array has no numbers, so
  "the middle element is 16" refers to nothing visible. **Economics:** axes and curves with no axis or curve labels.
- Where it works: the WWI causes (one labelled element per cause, in runs 1 and 3), the binary-search step lists, and every title.

## Which unchanged line still pushes toward single shapes

My judgement, with the evidence. The definition lines did what they can: they told the tutor an element may hold any number of
shapes and text, and run 1 used it (11 combined elements). What they do not change is that **every element is spoken about on its
own**:

1. **`narration` is a required field of `draw_new_element` (line 230) and the marker must open it (lines 223-225).** One element
   means one narration and one marker. The tutor builds an explanation as a sequence of elements, each one sentence. In the data
   the narration per element is about 25 words and the physics laws are three separate elements. This is the strongest
   candidate, because a combined element would carry several sentences and the tutor is not writing them.
2. **System prompt line 93, "Each element you draw comes with narration that is spoken aloud as the element appears", and line 113,
   "draw it as you speak".** They say the same thing as the schema and ask for piece-by-piece drawing.
3. **Line 107, "Whatever the learner needs to identify should be identifiable on the board".** Nothing says that written words
   are meant. The tutor reads its own narration as the identification. The advisory "no label" hint, which does say it, was shown
   50 times in the three runs and led to 4 edits.

I have not edited any of these.

## Proposals (not done)

1. Decide about the narration-per-element coupling (the strongest cause above). It changes what the tool schema asks for, so it
   needs your decision.
2. Add one honest eval check next to the content check: "narration of an element whose group has no text" (computed, no model call).
3. Keep the marker repair: it works, and 14-35% of narrations needed it.
4. Cheap judge: it over-counts about 40% on blank boards and has a floor of 5-13 on good ones; keep it as a trend line, use the
   reviewer for decisions.

# Targets for baseline F (fixed before the run)

Written and committed before F was run. The only change between E and F is one sentence, word for word as you drafted it,
added to the element definition in the two tool-description strings (`draw_new_element.description` and its
`svg_fragment.description`):

> Saved pages are opened without audio and printed, so an element must be understandable from what is drawn on it alone:
> names, values and labels belong inside the element, not only in the narration.

The system prompt, the hints and every guard are untouched (only `engine/author.py` tool text changed; the diff has no line
in the prompt). The model is the same as in A to E (`gpt-4.1-mini` under the deployment name `gpt-4o-mini`). F is 3 runs of the
8-topic eval with the Opus review, as in E.

The six old targets, unchanged and judged the same way as for E (see "Targets for baseline E" above):

| # | target | how it is judged |
|---|---|---|
| 1 | retries 13 or fewer per run | every F run has 13 or fewer `draw_failed` events |
| 2 | elements with no text 15 percent or less | every F run at or below 15% |
| 3 | replies or narrations describing content not on the board clearly below D (28 to 37) | the Opus reviewer's count is below 28 in every F run; the cheap judge is shown next to it as a second signal |
| 4 | hard failures 0 | 0 in every F run |
| 5 | opener variety and layout clusters not worse than D | no F run below D's lowest: distinct 3-word reply openers at least 10 of 16, distinct 3-word narration openers at least 70%, layout clusters 8 of 8 |
| 6 | factual errors not above D | no F run above 6 flagged errors; the mean is shown too |

Two new targets, judged on the mean of the 3 F runs against the mean of the 3 E runs (the per-run values are shown too):

| # | target | E (mean of 3) | limit for F |
|---|---|---|---|
| 7 | total cost per turn (LLM + speech) not more than 1.25 times E's | $0.0288 (0.0321 / 0.0276 / 0.0267) | **$0.0360** |
| 8 | seconds per turn not more than 1.25 times E's | 15.3 s (16.0 / 15.9 / 14.0) | **19.1 s** |

How cost is computed (`tests/compare_baselines.py`, the same for every column):
- **LLM:** the logged prompt and completion tokens of the run, at gpt-4.1-mini list prices, $0.40 per 1M input and $1.60 per 1M
  output, no cache discount (OpenAI pricing page https://developers.openai.com/api/docs/pricing, read 2026-10-08).
- **Speech:** the logged `audio_synthesis_completed.chars` of the run at **$0.04 per 1,000 characters**. The tutor calls
  ElevenLabs model `eleven_turbo_v2_5` (`engine/voice.py`), which is the "Flash / Turbo" row of ElevenLabs' own API price list
  (https://elevenlabs.io/pricing/api, read 2026-10-08). It is the list price for API use, before any allowance in a plan;
  I do not know which plan you are on. The Phase 1 audit used third-party figures of $0.05-0.11 per 1,000 characters, so
  the speech share of the total would be larger at those.
- **Second line:** the LLM cost with the cached-token discount ($0.10 per 1M cached input tokens), only for runs that logged
  cached tokens. A to E did not, so that line exists for F only.
- **Seconds per turn:** the mean of the measured seconds of the tutor's reply to each learner message, as in E.

Also reported, no target: median text lines per element, total narration words per turn, narrations whose marker was missing
or wrong as the model wrote them, the judge count, new rejection reasons. The normal range for any claim of "better" or
"worse" stays the six runs of A and B.


# Baseline F: one sentence added to the element definition (`b320450`)

Change since E: the sentence "Saved pages are opened without audio and printed, so an element must be understandable from what is
drawn on it alone: names, values and labels belong inside the element, not only in the narration." in the two element-definition
strings. System prompt, hints, guards and model (`gpt-4.1-mini-2025-04-14`, logged for the first time in these runs) unchanged.
Three runs: `docs/baseline_F/`; Opus review per run, same prompt as D and E.

## A / B / C / D / E / F

Normal range = the six runs of A and B. 'clear' = all three runs outside it on the same side.

| metric | A | B | C | D | E | F | C vs normal | D vs normal | E vs normal | F vs normal |
|---|---|---|---|---|---|---|---|---|---|---|
| retries, total | 13 / 7 / 13 | 8 / 7 / 11 | 92 / 97 / 70 | 0 / 1 / 1 | 1 / 6 / 1 | 3 / 1 / 4 | clear: worse | clear: better | clear: better | clear: better |
| retries per turn (total) | 0.81 / 0.44 / 0.81 | 0.5 / 0.44 / 0.69 | 5.75 / 6.06 / 4.38 | 0.0 / 0.06 / 0.06 | 0.06 / 0.38 / 0.06 | 0.19 / 0.06 / 0.25 | clear: worse | clear: better | clear: better | clear: better |
| retries per turn (worst topic) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0 / n/a / n/a | n/a / n/a / n/a | 1.0 / 0.5 / 1.5 |  |  |  |  |
|   retries: background_frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 1 | 0 / 0 / 1 | 0 / 0 / 1 |  |  |  |  |
|   retries: overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | 0 / 0 / 0 | 0 / 5 / 0 | 1 / 0 / 1 |  |  |  |  |
|   retries: labels_overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 0 / 1 |  |  |  |  |
|   retries: transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | 1 / 0 / 1 |  |  |  |  |
|   retries: other | 0 / 0 / 1 | 2 / 0 / 6 | 80 / 97 / 69 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 0 |  |  |  |  |
| elements with no text (%) | 0 / 4 / 0 | 0 / 4 / 0 | 12 / 21 / 23 | 71 / 62 / 50 | 40 / 52 / 56 | 61 / 81 / 52 | clear: worse | clear: worse | clear: worse | clear: worse |
| median text lines per element | 8 / 7 / 8 | 8 / 6.0 / 9.0 | 1.0 / 1.0 / 1.0 | 0 / 0.0 / 0.5 | 1 / 0.0 / 0 | 0 / 0.0 / 0.0 | clear: worse | clear: worse | clear: worse | clear: worse |
| replies/narrations that mention a rejection | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 1 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | no clear change | no clear change | no clear change |
| narration words, median | 52 / 51 / 58 | 59 / 60.0 / 59.5 | 18.0 / 17.5 / 18.0 | 22 / 18.5 / 21.0 | 25 / 25.5 / 23 | 25.5 / 27 / 25.5 |  |  |  |  |
| narration words per turn | 91 / 95 / 90 | 107 / 96 / 77 | 90 / 91 / 74 | 88 / 73 / 89 | 94 / 84 / 78 | 76 / 85 / 89 |  |  |  |  |
| same first two words: replies (%) | 25 / 25 / 19 | 25 / 31 / 25 | 62 / 62 / 69 | 56 / 62 / 56 | 62 / 56 / 88 | 88 / 81 / 56 | clear: worse | clear: worse | clear: worse | clear: worse |
| same first two words: narrations (%) | 30 / 20 / 17 | 40 / 33 / 40 | 45 / 18 / 30 | 35 / 33 / 22 | 28 / 38 / 30 | 52 / 39 / 35 | no clear change | no clear change | no clear change | no clear change |
| reply openers, distinct 3-word (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | 11 / 10 / 10 | 10 / 9 / 5 | 5 / 6 / 10 | clear: worse | no clear change (2 of 3 outside) | clear: worse | clear: worse |
| narration openers, distinct 3-word (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | 71 / 71 / 70 | 64 / 62 / 65 | 54 / 69 / 58 | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) |
| replies+narrations starting 'Here/This' (%) | 64 / 59 / 69 | 71 / 60 / 64 | 40 / 22 / 28 | 28 / 29 / 21 | 23 / 29 / 31 | 40 / 33 / 34 | clear: better | clear: better | clear: better | clear: better |
| layout clusters (of 8) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | 8 / 7 / 7 | 8 / 8 / 8 | no clear change (2 of 3 outside) | clear: better | clear: better | clear: better |
| layout overlap between topics (Jaccard) | 0.506 / 0.456 / 0.42 | 0.461 / 0.389 / 0.431 | 0.07 / 0.032 / 0.185 | 0.002 / 0.0 / 0.0 | 0.0 / 0.021 / 0.034 | 0.009 / 0.0 / 0.036 | clear: better | clear: better | clear: better | clear: better |
| narrations with no valid marker, as the model wrote them (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 35 / 19 / 14 | 45 / 57 / 50 | clear: worse | clear: worse | clear: worse | clear: worse |
| narrations with no marker, as stored (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | no clear change | no clear change |
| narrations with a single-bracket marker, as stored | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 6 / 0 | 0 / 5 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change |
| hard failures (of 8) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change |
| drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | 66 / 76 / 56 | 55 / 52 / 64 | 53 / 42 / 43 | 41 / 42 / 52 |  |  |  |  |
| author model | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini-2025-04-14 |  |  |  |  |
| prompt tokens per turn | 20026 / 14878 / 18533 | 14871 / 15156 / 19439 | 30490 / 44022 / 25803 | 10485 / 8126 / 11079 | 12188 / 9280 / 10124 | 9769 / 10692 / 11718 |  |  |  |  |
| completion tokens per turn | 1909 / 1303 / 2138 | 1708 / 1379 / 1630 | 2688 / 3486 / 2741 | 1086 / 974 / 1046 | 1188 / 1306 / 1048 | 1180 / 1486 / 1198 |  |  |  |  |
| LLM cost per turn (USD, list price, no cache discount) | 0.0111 / 0.008 / 0.0108 | 0.0087 / 0.0083 / 0.0104 | 0.0165 / 0.0232 / 0.0147 | 0.0059 / 0.0048 / 0.0061 | 0.0068 / 0.0058 / 0.0057 | 0.0058 / 0.0067 / 0.0066 | clear: worse | clear: better | clear: better | clear: better |
| speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | 552 / 465 / 556 | 633 / 544 / 524 | 513 / 557 / 595 |  |  |  |  |
| speech cost per turn (USD, $0.04 per 1,000 characters) | 0.0234 / 0.0248 / 0.0232 | 0.0267 / 0.024 / 0.0194 | 0.0233 / 0.0227 / 0.0196 | 0.0221 / 0.0186 / 0.0222 | 0.0253 / 0.0218 / 0.021 | 0.0205 / 0.0223 / 0.0238 |  |  |  |  |
| TOTAL cost per turn (USD, LLM + speech) | 0.0345 / 0.0328 / 0.034 | 0.0354 / 0.0323 / 0.0298 | 0.0398 / 0.0459 / 0.0343 | 0.028 / 0.0234 / 0.0283 | 0.0321 / 0.0276 / 0.0267 | 0.0263 / 0.029 / 0.0304 | no clear change (2 of 3 outside) | clear: better | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) |
| LLM cost per turn with cached-token discount (USD, where logged) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0.0033 / 0.0039 / 0.0035 |  |  |  |  |
| tutor seconds per turn (mean) | 24.6 / 18.5 / 28.1 | 21.2 / 17.6 / 20.1 | 39.4 / 46.2 / 35.5 | 15.2 / 13.1 / 14.4 | 16.0 / 15.9 / 14.0 | 16.6 / 19.7 / 18.6 | clear: worse | clear: better | clear: better | no clear change |
| factual errors flagged | 8 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | no clear change | no clear change | no clear change | clear: better |
|   of which major | 3 / 0 / 1 | n/a / n/a / n/a | 1 / 0 / 0 | 1 / 1 / 0 | 0 / 0 / 2 | 1 / 0 / 0 | no clear change | no clear change | no clear change | no clear change |
|   model-only (not our bugs) | 7 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | no clear change | no clear change | no clear change | clear: better |
| replies describing what is not on the board | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 36 / 37 / 28 | 33 / 26 / 29 | 38 / 50 / 37 |  |  |  |  |
| judge: statements describing content not on the board | 10 / 13 / 12 | 8 / 12 / 5 | 27 / 28 / 30 | 26 / 41 / 34 | 31 / 32 / 30 | 33 / 36 / 36 | clear: worse | clear: worse | clear: worse | clear: worse |

* the model was not logged before baseline F; the deployment 'gpt-4o-mini' serves gpt-4.1-mini and was last changed before baseline A (docs/BASELINE.md).

## Targets (fixed before the run, `b320450`)

| # | target | F | result |
|---|---|---|---|
| 1 | retries 13 or fewer per run | 3 / 1 / 4 | **met** |
| 2 | elements with no text 15% or less | 61 / 81 / 52% (E 40 / 52 / 56; D 71 / 62 / 50) | **missed** |
| 3 | content described but not on the board: reviewer count below 28 in every run | 38 / 50 / 37 (E 33 / 26 / 29; D 36 / 37 / 28). The cheap judge: 33 / 36 / 36 (E 31 / 32 / 30) | **missed**, and higher than D and E |
| 4 | hard failures 0 | 0 / 0 / 0 | **met** |
| 5 | opener variety and layout not worse than D | reply openers 5 / 6 / 10 (need 10 or more); narration openers 54 / 69 / 58% (need 70% or more); layout clusters 8 / 8 / 8 | **missed** on openers (replies in 2 runs, narrations in 3 runs); layout is fine |
| 6 | factual errors: no run above 6 | 4 / 4 / 3 (major 1 / 0 / 0); mean 3.7 against D's 5.7 | **met** |
| 7 | total cost per turn (LLM + speech): mean not above 1.25 times E's ($0.0360) | $0.0263 / 0.0290 / 0.0304, mean **$0.0286** = 0.99 times E | **met** |
| 8 | seconds per turn: mean not above 1.25 times E's (19.1 s) | 16.6 / 19.7 / 18.6, mean **18.3 s** = 1.20 times E | **met** (run 2 alone is above 19.1; the target is on the mean) |

**Five of eight met; three of the six old ones.** The three that matter for the purpose of F, text on the board and no description
of content that is not there, are the ones that were missed, and F is not better than E on any of them: no change is
measurable (E and F ranges overlap) and the F values are on the worse side.

Two notes on the table: the normal range for factual errors is A's three runs only (8 / 6 / 7), because B was not fact-checked,
so "clear: better" for F rests on A alone. The model's marker mistakes as written were 45 / 57 / 50% (E 35 / 19 / 14%); the code
repairs all of them, so nothing reaches the voice.

## Cost per turn

| | LLM, no cache discount | LLM, with the cached-token discount | speech ($0.04 per 1,000 characters) | total (no cache discount) |
|---|---|---|---|---|
| F run 1 / 2 / 3 | $0.0058 / 0.0067 / 0.0066 | $0.0033 / 0.0039 / 0.0035 | $0.0205 / 0.0223 / 0.0238 | $0.0263 / 0.0290 / 0.0304 |
| E run 1 / 2 / 3 | $0.0068 / 0.0058 / 0.0057 | not logged | $0.0253 / 0.0218 / 0.0210 | $0.0321 / 0.0276 / 0.0267 |

86% of the prompt tokens in F were served from the cache (441,472 of 514,859). Speech is about 78% of the total (about 86% if the cache discount is applied to the LLM).
Prices: gpt-4.1-mini $0.40 / $0.10 cached / $1.60 per 1M tokens (OpenAI price page); eleven_turbo_v2_5 is the "Flash / Turbo" row at
$0.04 per 1,000 characters (ElevenLabs price page); both read 2026-10-08. The speech price is a list price; your plan may differ.

## What F did to the boards

- **Nothing in the right direction.** Of 135 elements in F, 86 (64%) have no `<text>`. Shape only 25 / 34 / 27, text only 10 / 7 / 18,
  shape and text together 6 / 1 / 7 (E 11 / 3 / 5; D 3 / 1 / 3). Median text lines per element 0 / 0 / 0.
- **The tutor ignored the hint as well as the sentence.** The advisory hint "The card ... has no label inside it" was shown to the
  tutor for 22 / 25 / 20 elements (67 in all). After it, text was added to the element 0 times: the few `modify_existing_element`
  calls (4 / 5 / 0) were short fragments of under 120 characters, none containing `<text>`.
- **Narration substitutes for text.** Elements with no text have a longer narration (median 26 words) than elements with text
  (23). Per topic, elements without text: physics 18 of 21, dense 15 of 19, language 13 of 16, biology 5 of 7, code 12 of 28, maths 7 of 13,
  history 6 of 10, economics 10 of 21.
- **Where text does appear** it is in separate text-only elements (code run 3: 12 text-only step elements) or in titles, not on
  the shapes the narration talks about. The physics boards are the clearest: the six law and example cards per run have no
  text on them, and each has about 25 words of narration naming the law or the example.
- **Reviewer detail:** run 1 had one major error (an increase in demand drawn and spoken as a shift to the left); runs 2 and 3
  had none. The 37 to 50 "not on the board" items per run are the same pattern as E: names, formulas, array values and
  steps that exist only in speech.
- **Replies:** 88 / 81 / 56% start with the same two words ("I have ..."; E 62 / 56 / 88%; normal 19-31%); distinct 3-word reply openers 5 / 6 / 10 of 16.
- **Retries:** 3 / 1 / 4 (overlaps, label overlaps, a transform, one frame, one reply that hit the token cap); no new rejection reason.

## Three most likely causes of the missed element-text target, in order (not tested)

1. **Nothing makes an element without text cost anything, and the tutor treats advice as optional.** In A and B three things pushed
   text onto shapes: prompt rule P4 ("NEVER draw a bare, empty geometric shape"), the recipe in the tool text (T3/T4) and the
   blocking label rule (C9, a rejected drawing and a retry). Elements with no text were 0 to 4% there. C removed the first two
   and kept the third (12 to 23%), D turned the third into a log note (50 to 71%), and E and F add advice only (40 to 81%). The
   direct evidence is in F: two pieces of advice (the sentence and the hint) and 0 of 67 times acted on.
2. **The narration field is required for every element and carries the content.** The tutor must speak about every element it
   draws, so the natural size of an element is one spoken idea, and the idea is in the speech. Elements without text have longer
   narrations than those with text. This is the cause named in E (lines 223 to 225 and 230 of `engine/author.py`), and F's
   sentence did not move it.
3. **The system prompt frames drawing as an accompaniment to speech, and it outranks the tool text.** Lines 93 and 113 ("narration
   spoken aloud as the element appears", "draw it as you speak") and the weak line 107 ("identifiable on the board") never say that
   written words belong on the board; F's sentence is the only place that does, at the end of a tool description. I cannot tell
   this apart from model size: a stronger model was not tried (experiment M was cancelled).

**What I would test next (not done):** put the same sentence in the system prompt, in place of line 107, tool text unchanged, 3 runs.
It is one sentence and no guard or schema change. If elements with no text fall to about 30% or lower, cause 3 (placement) was it. If
not, the next step is cause 2 (allow an element without its own narration), and cause 1 would need a guard, which is your decision.

## Tests and cost of the experiment

- Offline suite before the runs: 392 passed, 30 skipped (live ones). Live-server suite after the runs, including the live
  cheap-model judge tests: **443 passed, 0 skipped, 0 failed** (21 of them are the judge tests, 220 s).
- Model usage of the three runs: 146 model calls, 514,859 prompt tokens (441,472 cached), 61,821 completion tokens, about $0.31 at list
  price ($0.17 with the cache discount); 26,645 speech characters, about $1.07 at $0.04 per 1,000. Plus three Opus reviews.


# Targets for baseline G (fixed before the run)

Written and committed before G was run. **One variable only.** The weak line "Whatever the learner needs to identify should be
identifiable on the board." (third bullet of Harness Rule 1; "line 107" in the older notes, line 110 of `engine/author.py` after the
model-setting commit) is replaced, word for word as you drafted it, by:

> Saved pages are opened without audio, so the board itself must carry each concept: its name, values and labels are written on
> the board. Narration adds to what is drawn. It does not replace it.

The tool text is exactly as in F (the F sentence is in both element-definition strings, pinned by a test). The guards, the hints and
the model (`gpt-4.1-mini`) are unchanged; the engine diff is that one line. G is 3 runs of the 8-topic eval with the Opus review, as in F.

**Stop rule (yours):** if G misses its targets, prompt tuning stops, and you decide between sparse boards and a code-level label
requirement.

| # | target | how it is judged |
|---|---|---|
| 1 | retries 13 or fewer in every run | every G run has 13 or fewer `draw_failed` events |
| 2 | elements with no text 15% or less in every run | every G run at or below 15% |
| 3 | median text lines per element 6 or less | every G run at or below 6 (catches overshoot; A and B were 6-9) |
| 4 | not-on-board count below 28 in every run, by both counters | the Opus reviewer's count and the cheap judge's count are each below 28 in every G run |
| 5 | layout clusters and reply openers not worse than F | no G run below F's lowest: layout clusters 8 of 8, distinct 3-word reply openers at least 5 of 16 (F: 5 / 6 / 10, so this bar is low; the means are shown too) |
| 6 | hard failures 0 | 0 in every G run |
| 7 | factual errors 6 or fewer | every G run at 6 or fewer flagged errors |
| 8 | total cost per turn (LLM + speech) at most 1.25 times E's | mean of the 3 G runs at most **$0.0360** (E mean $0.0288) |
| 9 | seconds per turn at most 1.25 times E's | mean of the 3 G runs at most **19.1 s** (E mean 15.3 s) |

Cost is computed as in F (logged tokens at gpt-4.1-mini list prices, no cache discount, plus logged speech characters at $0.04 per
1,000, see "Targets for baseline F"); the cached-token discount is shown as a second line. Also reported, no target: narration
openers, narration words per turn, shape-only / text-only / combined element counts, new rejection reasons. The normal range for any
claim of "better" or "worse" stays the six runs of A and B.


# Baseline G: the weak system-prompt line replaced (`d7d1575`)

Change since F: the third bullet of Harness Rule 1 ("Whatever the learner needs to identify should be identifiable on the board.")
is now "Saved pages are opened without audio, so the board itself must carry each concept: its name, values and labels are written on
the board. Narration adds to what is drawn. It does not replace it." Tool text exactly as in F; guards, hints and model
(`gpt-4.1-mini-2025-04-14`) unchanged. Three runs: `docs/baseline_G/`; Opus review per run, same prompt as D, E and F.

## A / B / C / D / E / F / G

Normal range = the six runs of A and B. 'clear' = all three runs outside it on the same side.

| metric | A | B | C | D | E | F | G | C vs normal | D vs normal | E vs normal | F vs normal | G vs normal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| retries, total | 13 / 7 / 13 | 8 / 7 / 11 | 92 / 97 / 70 | 0 / 1 / 1 | 1 / 6 / 1 | 3 / 1 / 4 | 0 / 5 / 2 | clear: worse | clear: better | clear: better | clear: better | clear: better |
| retries per turn (total) | 0.81 / 0.44 / 0.81 | 0.5 / 0.44 / 0.69 | 5.75 / 6.06 / 4.38 | 0.0 / 0.06 / 0.06 | 0.06 / 0.38 / 0.06 | 0.19 / 0.06 / 0.25 | 0.0 / 0.31 / 0.12 | clear: worse | clear: better | clear: better | clear: better | clear: better |
| retries per turn (worst topic) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0 / n/a / n/a | n/a / n/a / n/a | 1.0 / 0.5 / 1.5 | 0 / 1.5 / 1.0 |  |  |  |  |  |
|   retries: background_frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 1 | 0 / 0 / 1 | 0 / 0 / 1 | 0 / 0 / 0 |  |  |  |  |  |
|   retries: overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | 0 / 0 / 0 | 0 / 5 / 0 | 1 / 0 / 1 | 0 / 2 / 2 |  |  |  |  |  |
|   retries: labels_overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 0 / 1 | 0 / 3 / 0 |  |  |  |  |  |
|   retries: transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | 1 / 0 / 1 | 0 / 0 / 0 |  |  |  |  |  |
|   retries: other | 0 / 0 / 1 | 2 / 0 / 6 | 80 / 97 / 69 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 0 | 0 / 0 / 0 |  |  |  |  |  |
| elements with no text (%) | 0 / 4 / 0 | 0 / 4 / 0 | 12 / 21 / 23 | 71 / 62 / 50 | 40 / 52 / 56 | 61 / 81 / 52 | 62 / 55 / 69 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
| median text lines per element | 8 / 7 / 8 | 8 / 6.0 / 9.0 | 1.0 / 1.0 / 1.0 | 0 / 0.0 / 0.5 | 1 / 0.0 / 0 | 0 / 0.0 / 0.0 | 0 / 0.0 / 0 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
|   elements: shape only | 0 / 1 / 0 | 0 / 0 / 0 | 8 / 16 / 13 | 39 / 32 / 32 | 21 / 22 / 24 | 25 / 34 / 27 | 28 / 22 / 27 |  |  |  |  |  |
|   elements: text only | 1 / 2 / 0 | 0 / 0 / 0 | 34 / 45 / 25 | 13 / 19 / 29 | 21 / 17 / 14 | 10 / 7 / 18 | 17 / 8 / 9 |  |  |  |  |  |
|   elements: shape and text | 22 / 22 / 23 | 25 / 24 / 20 | 24 / 15 / 18 | 3 / 1 / 3 | 11 / 3 / 5 | 6 / 1 / 7 | 0 / 10 / 3 |  |  |  |  |  |
| elements that are a bare tag, not a <g id> group (%) | 0 / 0 / 0 | 0 / 0 / 0 | 64 / 82 / 68 | 95 / 96 / 95 | 79 / 93 / 86 | 85 / 98 / 87 | 100 / 75 / 90 |  |  |  |  |  |
| elements the layout code can see (%) | 100 / 96 / 100 | 100 / 100 / 100 | 23 / 16 / 23 | 5 / 0 / 0 | 11 / 7 / 14 | 5 / 2 / 13 | 0 / 25 / 10 |  |  |  |  |  |
| replies/narrations that mention a rejection | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 1 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | no clear change | no clear change | no clear change | no clear change |
| narration words, median | 52 / 51 / 58 | 59 / 60.0 / 59.5 | 18.0 / 17.5 / 18.0 | 22 / 18.5 / 21.0 | 25 / 25.5 / 23 | 25.5 / 27 / 25.5 | 26 / 30.0 / 28 |  |  |  |  |  |
| narration words per turn | 91 / 95 / 90 | 107 / 96 / 77 | 90 / 91 / 74 | 88 / 73 / 89 | 94 / 84 / 78 | 76 / 85 / 89 | 80 / 90 / 83 |  |  |  |  |  |
| same first two words: replies (%) | 25 / 25 / 19 | 25 / 31 / 25 | 62 / 62 / 69 | 56 / 62 / 56 | 62 / 56 / 88 | 88 / 81 / 56 | 69 / 75 / 62 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
| same first two words: narrations (%) | 30 / 20 / 17 | 40 / 33 / 40 | 45 / 18 / 30 | 35 / 33 / 22 | 28 / 38 / 30 | 52 / 39 / 35 | 42 / 50 / 51 | no clear change | no clear change | no clear change | no clear change | clear: worse |
| reply openers, distinct 3-word (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | 11 / 10 / 10 | 10 / 9 / 5 | 5 / 6 / 10 | 8 / 8 / 10 | clear: worse | no clear change (2 of 3 outside) | clear: worse | clear: worse | clear: worse |
| narration openers, distinct 3-word (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | 71 / 71 / 70 | 64 / 62 / 65 | 54 / 69 / 58 | 42 / 48 / 49 | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) | clear: worse |
| replies+narrations starting 'Here/This' (%) | 64 / 59 / 69 | 71 / 60 / 64 | 40 / 22 / 28 | 28 / 29 / 21 | 23 / 29 / 31 | 40 / 33 / 34 | 34 / 46 / 42 | clear: better | clear: better | clear: better | clear: better | clear: better |
| layout clusters (of 8) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | 8 / 7 / 7 | 8 / 8 / 8 | 8 / 7 / 7 | no clear change (2 of 3 outside) | clear: better | clear: better | clear: better | clear: better |
| layout overlap between topics (Jaccard) | 0.506 / 0.456 / 0.42 | 0.461 / 0.389 / 0.431 | 0.07 / 0.032 / 0.185 | 0.002 / 0.0 / 0.0 | 0.0 / 0.021 / 0.034 | 0.009 / 0.0 / 0.036 | 0.0 / 0.06 / 0.052 | clear: better | clear: better | clear: better | clear: better | clear: better |
| narrations with no valid marker, as the model wrote them (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 35 / 19 / 14 | 45 / 57 / 50 | 53 / 49 / 71 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
| narrations with no marker, as stored (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | no clear change | no clear change | no clear change |
| narrations with a single-bracket marker, as stored | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 6 / 0 | 0 / 5 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change |
| hard failures (of 8) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change |
| drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | 66 / 76 / 56 | 55 / 52 / 64 | 53 / 42 / 43 | 41 / 42 / 52 | 45 / 40 / 39 |  |  |  |  |  |
| author model | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 |  |  |  |  |  |
| prompt tokens per turn | 20026 / 14878 / 18533 | 14871 / 15156 / 19439 | 30490 / 44022 / 25803 | 10485 / 8126 / 11079 | 12188 / 9280 / 10124 | 9769 / 10692 / 11718 | 11236 / 12222 / 10282 |  |  |  |  |  |
| completion tokens per turn | 1909 / 1303 / 2138 | 1708 / 1379 / 1630 | 2688 / 3486 / 2741 | 1086 / 974 / 1046 | 1188 / 1306 / 1048 | 1180 / 1486 / 1198 | 1391 / 1626 / 1378 |  |  |  |  |  |
| LLM cost per turn (USD, list price, no cache discount) | 0.0111 / 0.008 / 0.0108 | 0.0087 / 0.0083 / 0.0104 | 0.0165 / 0.0232 / 0.0147 | 0.0059 / 0.0048 / 0.0061 | 0.0068 / 0.0058 / 0.0057 | 0.0058 / 0.0067 / 0.0066 | 0.0067 / 0.0075 / 0.0063 | clear: worse | clear: better | clear: better | clear: better | clear: better |
| speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | 552 / 465 / 556 | 633 / 544 / 524 | 513 / 557 / 595 | 524 / 582 / 539 |  |  |  |  |  |
| speech cost per turn (USD, $0.04 per 1,000 characters) | 0.0234 / 0.0248 / 0.0232 | 0.0267 / 0.024 / 0.0194 | 0.0233 / 0.0227 / 0.0196 | 0.0221 / 0.0186 / 0.0222 | 0.0253 / 0.0218 / 0.021 | 0.0205 / 0.0223 / 0.0238 | 0.021 / 0.0233 / 0.0216 |  |  |  |  |  |
| TOTAL cost per turn (USD, LLM + speech) | 0.0345 / 0.0328 / 0.034 | 0.0354 / 0.0323 / 0.0298 | 0.0398 / 0.0459 / 0.0343 | 0.028 / 0.0234 / 0.0283 | 0.0321 / 0.0276 / 0.0267 | 0.0263 / 0.029 / 0.0304 | 0.0277 / 0.0308 / 0.0279 | no clear change (2 of 3 outside) | clear: better | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) |
| LLM cost per turn with cached-token discount (USD, where logged) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0.0033 / 0.0039 / 0.0035 | 0.004 / 0.0044 / 0.0036 |  |  |  |  |  |
| tutor seconds per turn (mean) | 24.6 / 18.5 / 28.1 | 21.2 / 17.6 / 20.1 | 39.4 / 46.2 / 35.5 | 15.2 / 13.1 / 14.4 | 16.0 / 15.9 / 14.0 | 16.6 / 19.7 / 18.6 | 19.4 / 23.0 / 18.4 | clear: worse | clear: better | clear: better | no clear change | no clear change |
| factual errors flagged | 8 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | no clear change | no clear change | no clear change | clear: better | no clear change |
|   of which major | 3 / 0 / 1 | n/a / n/a / n/a | 1 / 0 / 0 | 1 / 1 / 0 | 0 / 0 / 2 | 1 / 0 / 0 | 0 / 1 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change |
|   model-only (not our bugs) | 7 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | no clear change | no clear change | no clear change | clear: better | no clear change |
| replies describing what is not on the board | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 36 / 37 / 28 | 33 / 26 / 29 | 38 / 50 / 37 | 47 / 32 / 35 |  |  |  |  |  |
| judge: statements describing content not on the board | 10 / 13 / 12 | 8 / 12 / 5 | 27 / 28 / 30 | 26 / 41 / 34 | 31 / 32 / 30 | 33 / 36 / 36 | 37 / 36 / 36 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |

* the model was not logged before baseline F; the deployment 'gpt-4o-mini' serves gpt-4.1-mini and was last changed before baseline A (docs/BASELINE.md).

## Targets (fixed before the run, `d7d1575`)

| # | target | G | result |
|---|---|---|---|
| 1 | retries 13 or fewer in every run | 0 / 5 / 2 | **met** |
| 2 | elements with no text 15% or less in every run | 62 / 55 / 69% (F 61 / 81 / 52; E 40 / 52 / 56) | **missed** |
| 3 | median text lines per element 6 or less | 0 / 0 / 0 | **met**, but only because there is nothing to overshoot |
| 4 | not-on-board count below 28 in every run, Opus and cheap judge | Opus 47 / 32 / 35; judge 37 / 36 / 36 | **missed** (both counters, every run) |
| 5 | layout clusters 8 of 8 and reply openers at least 5 of 16 (not worse than F) | layout 8 / 7 / 7; reply openers 8 / 8 / 10 | **missed** on layout (two runs at 7). That measure is unreliable here, see "The unit is not formed" |
| 6 | hard failures 0 | 0 / 0 / 0 | **met** |
| 7 | factual errors 6 or fewer in every run | 8 / 6 / 2 (major 0 / 1 / 0) | **missed** by the fixed rule (run 1: 8 minor errors); mean 5.3 |
| 8 | total cost per turn, mean at most $0.0360 | $0.0277 / 0.0308 / 0.0279, mean **$0.0288** = 1.00 times E | **met** |
| 9 | seconds per turn, mean at most 19.1 s | 19.4 / 23.0 / 18.4, mean **20.3 s** = 1.32 times E | **missed** |

**Four of nine met. The text target (2) and the not-on-board target (4) are missed, in every run, by a wide margin, and G is no
better than F or E.** Your stop rule applies: prompt tuning stops and the decision is yours.

Cost: LLM per turn $0.0067 / 0.0075 / 0.0063 (with the cached-token discount $0.0040 / 0.0044 / 0.0036; 85% of prompt tokens were
cached), speech $0.0210 / 0.0233 / 0.0216 at $0.04 per 1,000 characters, same prices as F. Model use of the three runs: 152
calls, 539,848 prompt tokens (459,008 cached), 70,307 completion tokens, about $0.33 at list price ($0.19 with the cache discount);
26,319 speech characters, about $1.05.

## What the G boards look like

- Of 124 elements, 77 (62%) have no `<text>`. Shape only 28 / 22 / 27, text only 17 / 8 / 9, shape and text together 0 / 10 / 3
  (F 6 / 1 / 7; E 11 / 3 / 5). Median text lines per element 0 / 0 / 0.
- Per topic, elements without text: dense 15 of 16, physics 15 of 21, language 13 of 18, code 12 of 20, maths 9 of 15,
  biology 7 of 12, history 3 of 8, economics 3 of 14. Economics and the history alliance diagram come closest to carrying their concepts
  in writing; physics, language, the OSI/TCP-IP part of dense, and most of code and maths show
  coloured cards and titles while the narration says the laws, the rules, the layers and the array values.
- The physics boards: three law cards and three example cards, each a single `<rect>` of about 110 characters, with 30 words
  of narration naming the law or the example ("This is Newton's First Law, also known as the Law of Inertia...").
- Elements with no text have a longer narration (median 30 words) than elements with text (25).
- The new sentence did not show in the tutor's behaviour: replies still say "each layer clearly labeled and an example
  protocol inside each layer" for elements that contain no text. The hint "The card ... has no label inside it" was shown 20 / 20 / 24
  times (63 elements); none of the 63 was given text afterwards, as in F (0 of 67).

## The unit is not formed (new finding, from re-reading the stored fragments for this report)

The system prompt (Harness Rule 1, first bullet) and the tool text say every element is one `<g id="element_id">` group. The
stored fragments show that the tutor mostly does not do that. Share of drawn elements that are a bare tag (one `<rect>`, `<text>`,
`<line>` ... with no `<g>` wrapper and no id):

| | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| bare tags, % per run | 0 / 0 / 0 | 0 / 0 / 0 | 64 / 82 / 68 | 95 / 96 / 95 | 79 / 93 / 86 | 85 / 98 / 87 | 100 / 75 / 90 |
| layout code can see the element, % | 100 / 96 / 100 | 100 / 100 / 100 | 23 / 16 / 23 | 5 / 0 / 0 | 11 / 7 / 14 | 5 / 2 / 13 | 0 / 25 / 10 |

- **When the tutor does form a group, it holds text** (A 99%, B 100%, C 100%, D 88%, E 100%, F 100%, G 100% of grouped elements
  contain `<text>`). Of the bare tags, 29-30% are bare `<text>` (labels sent as their own elements) and the rest are single
  shapes. So the missing text is mostly a missing group: one tool call is one primitive.
- **It started at C**, when the container + title + label recipe, "NEVER draw a bare, empty geometric shape" and (in D) the blocking
  label rule were removed or softened; A and B had no bare tags at all. The sentences added in E, F and G ("an element is one
  group, any number of shapes and text", "names, values and labels belong inside the element", "the board itself must carry each
  concept") did not change it: grouped elements were 20, 14 and 14 of about 130 per baseline.
- **The code accepts a bare tag without any message.** Nothing validates that a fragment is a `<g id>` group, and the sanitiser
  keeps it as it is (checked: a bare `<rect>` is stored bare, with no id).
- **Consequence for the guards (not changed):** `extract_element_bboxes` reads only `<g id>` groups and shapes that carry an id, so
  a bare tag is invisible to `occupied_regions` (the free-space map the tutor is shown), to the overlap check, and to the layout
  metrics in this document. From D on the layout code sees 0-25% of the drawn elements. The "layout clusters 8 of 8" in D to G
  therefore means little (empty masks are all different). Crude check on the final boards, rectangles only, pairs from
  different elements overlapping by more than a quarter of the smaller one: A 0 / 0 / 1, B 0 / 0 / 0, C 1 / 0 / 0, D 4 / 1 / 1,
  E 0 / 2 / 4, F 3 / 2 / 2, G 1 / 3 / 6 per run.

## Does the narration-per-element coupling still look like the cause?

Not as the main cause. A and B had the same required narration per element and the same marker, and every element was a group with
7 to 8 text lines. What changed from B to C is the unit: one call is now one primitive, and a primitive with a narration is
"drawn" in the tutor's own account. The coupling probably adds to it (each call is one tag and one spoken idea, narration is
longer where there is no text, 30 against 25 words), but it does not explain why grouped elements always have text and bare ones
mostly do not. The better reading of the data: the tutor ignores the instruction to form a group when the instruction is only
advice, and the code does not mind.

## What the rejection said in C when a card had no text (read only)

The blocking "Semantic Whiteboard Rule" (`validate_geometry`, C9) rejected a drawing that contained a `<rect>` of at least
120x60 and no `<text>` anywhere in the same drawing. The tutor received this tool result:

> Element geometry invalid: Diagram card has no <text> labels. Every whiteboard diagram card must include descriptive <text> labels inside so the student can read the concepts.

(logged as "Element '<id>' rejected: ..."). It says what to add, but not which rectangle, not the size limit (so a smaller
shape would have passed), and not that the text must be in the same drawing as the rectangle: "inside" could mean inside the card
or inside the call. In C, 64-82% of the tutor's calls were a single bare tag, so a rectangle sent alone could never satisfy it.

What happened (244 rejections of this kind in the three C runs, from the log of 2026-10-07): they came in 55 chains of
consecutive rejections, all 55 ended with an accepted drawing, none with a turn that gave up. Only 10 chains (18%) were fixed on
the first retry, the median chain was 3 rejections, 17 chains (31%) had six or more, the longest 17. In the longest chain the
tutor sent the same three ids (`osi_model`, `tcp_ip_model`, `comparison_box`) four times in a row, then sent five variants of one merged id, and the accepted drawing was called `single_card_test`. The rejected fragments were not logged, so I cannot say
whether the retries were unchanged or only changed in shape. After the rule was satisfied the text was minimal: median text lines
per element 1 in C against 7 to 8 in A and B. So: **clear about the requirement, not clear about the scope**, and it took the
tutor about four attempts per drawing to find a form that passed, at the cost of 70 to 97 retries a run, 26-44k prompt tokens a
turn and 35-46 s a turn.

## Tests and cost

- Offline suite before the runs: 413 passed, 30 skipped (live ones), 21 judge tests deselected.
- Live-server suite after the runs, including the live cheap-model judge tests: **464 passed, 0 skipped, 0 failed** in 210 s (21 of them are the judge tests, run with the real cheap model).

## Proposals (not done)

1. Per your stop rule, no more prompt tuning. The data add a third option to "sparse boards" and "a label requirement":
   **a group requirement**, a recording rule rather than a content rule: every draw call must be one `<g id=element_id>` group
   (reject a bare tag with a clear message, or wrap it in code like the marker repair). It would not decide what is drawn. It would
   make the free-space map, the overlap check and the layout metrics see every element again, and the data say grouped elements
   hold text 99-100% of the time. Untested; to be tested, not assumed.
2. If sparse boards are the choice, the honest fix is on the speaking side: replies and narrations should not describe text
   that is not on the board (the 32-50 items per run).
3. A label requirement without a group requirement would repeat C: the rule would reject single bare shapes, and the tutor needed
   about four attempts each time.
4. Whatever is chosen, add the "bare tag" check to the eval next to the other recording checks (it is in
   `tests/compare_baselines.py` now, computed from saved runs).


# Check before experiment H: bare tags, and layout and overlap recomputed on all shapes and text

Read only; nothing in the tutor's prompt, tool text, guards or hints was changed. Written before H was built.

## a) What a bare tag can and cannot do

A bare tag (one `<rect>`, `<text>` ... with no `<g>`) does **not** carry the element_id as its own id: in G, 45 of 45, 30 of 40 and 35 of
39 elements are bare and none has `id="element_id"` (A and B: no bare tags). Tested in the browser on a board built through the real
draw and annotate endpoints with one bare `<rect>` copied from G run 1 (physics `law1`) and one proper group (`law2`), then replayed:

| function | on a bare tag |
|---|---|
| reveal at the marker (replay) | **works**: the shape appeared at about 1.3 s, at its marker. The frontend keys the reveal on the event's element_id and wraps the fragment in an id-less `<g>` |
| annotation (circle) | **fails silently**: the engine answers "created successfully" (it checks the event ids), the frontend looks for `[id="law1"]` in the SVG, logs `Could not find target bounds for 'law1'` and draws nothing. The circle on the proper group was drawn |
| `modify_existing_element` | **half works**: the engine answers OK and the replay shows the new shape, but the page's stored SVG (`current_svg`, used for the engine state and the saved page) keeps the old shape, because the old fragment is looked up by id and not found |
| hover label, learner "ask about this" | **cannot work**: both need an id on the group |
| `occupied_regions`, overlap check, layout metrics | **blind**: `extract_element_bboxes` reads only `<g id>` groups and shapes with an id |

## b) Layout and overlap recomputed with every shape and text label (`tests/eval_layout.py`)

Each cell is run 1 / run 2 / run 3. "Overlapping pairs" are pairs of different drawn elements on a page that the overlap guard's own rule
(`check_overlap`: more than 20% of the smaller box, thin boxes under 20 px ignored) would have rejected, with one box per element made of
all its shapes and labels. "Crossing" pairs are the ones where the smaller box is not (almost) inside the other; the rest are labels or
parts lying on a card drawn by another element.

| | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| layout clusters, old method (groups with an id only) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | 8 / 7 / 7 | 8 / 8 / 8 | 8 / 7 / 7 |
| **layout clusters, all shapes and text** | 3 / 4 / 3 | 3 / 5 / 3 | 7 / 7 / 5 | 5 / 4 / 6 | 6 / 6 / 7 | 5 / 5 / 5 | 5 / 4 / 3 |
| overlapping pairs | 1 / 2 / 0 | 2 / 1 / 1 | 35 / 17 / 11 | 12 / 11 / 7 | 5 / 3 / 10 | 14 / 9 / 4 | 4 / 7 / 7 |
| of which crossing | 1 / 2 / 0 | 2 / 1 / 1 | 8 / 8 / 1 | 7 / 4 / 1 | 3 / 3 / 7 | 8 / 4 / 2 | 0 / 4 / 0 |

## Which earlier layout claims change

1. **"Layout clusters 8 of 8" in D, F and "8 / 7 / 7" in E and G was an artifact**: the masks were built from the 0-25% of elements the old
   extraction could see, and near-empty masks are all different. The real values are 3-7. Against the normal range (A and B, 2-5) D, F
   and G are within it and E (6 / 6 / 7) is above it; "clear: better" for D to G in the earlier tables was wrong.
2. **Target 5 of E, F and G ("layout not worse")** was measured wrongly. G is still worse than F on the new numbers (5 / 4 / 3 against
   5 / 5 / 5), so its verdict stands. E's layout part, counted as missed, is met on the new numbers (6 / 6 / 7 against D's 5 / 4 / 6);
   E's target 5 was also missed on openers, so its overall verdict stands.
3. **"Overlaps 0-1 per run in A to C" (crude rectangle check in the G section) is wrong for C**: 35 / 17 / 11 pairs, 8 / 8 / 1 of them real
   crossings. A and B stay at 0-2. D to F have up to 8 crossings per run, G 0 / 4 / 0.
4. Nothing else in the tables used the old extraction, but the "elements the layout code can see" and "bare tag" rows stay as the
   measure of how blind the guards are.

The comparison table (`tests/compare_baselines.py`) now takes layout clusters, layout Jaccard and overlapping pairs from this method for
every column, and keeps the old clusters as a labelled row. `tests/eval_baseline.py` records the new numbers for new runs
(`metrics.board_layout`).


# Targets for baseline H (fixed before the run)

Written and committed before H was run. **One change, in code only**: an element is one `<g id="element_id">` group, and the code makes it
so (`engine/grouping.py`, called in the draw handler before the sanitiser, and in the modify handler). No prompt, tool text, guard or hint
changed (the diff of `engine/author.py` is the two calls and the import).

**Why before the sanitiser, and the finding behind H.** `sanitize_svg` parses a fragment as one XML document and keeps only the first
top-level node; every other top-level tag was silently dropped, and the tool answered "ok". The model writes a card as sibling tags
(`<rect/><text>title</text><text>line</text>...`) in 48-88% of drawings from C on (G: 82 / 56 / 76%; B: 0-6%, when it wrapped everything in a
`<g>`), so the stored board kept the rectangle and lost all its text. Measured on the raw model output in the log (`draw_started.raw_svg`):

| raw drawings with several top-level tags | B | C | D | E | F | G |
|---|---|---|---|---|---|---|
| % per run | 0 / 6 / n/a | 63 / 69 / 67 | 64 / 74 / 48 | 70 / 73 / 75 | 68 / 88 / 70 | 82 / 56 / 76 |

(The raw SVG is logged only from 2026-10-07 evening on, so there is no figure for A; B run 3's window overlaps C's first minutes and is
left out.) Everything the numbers of C to G say about "elements with no text", "bare tags" and "content not on the board" was measured after
this loss. The earlier readings in this document that blame the tutor for ignoring advice or for putting content in the narration are
withdrawn: the tutor wrote the text, the code deleted it.

**What H does.** `ensure_group(fragment, element_id)`: if the fragment is exactly one `<g id="element_id">` it is untouched; otherwise
everything is wrapped in `<g id="element_id">`, an id equal to `element_id` on a tag inside is removed (so there is one), and a repair is
logged as `group_repaired` with a reason: `bare_tag` (one top-level tag that is not a group), `multiple_top_level` (several top-level
tags), `group_id` (one `<g>` whose id is missing or another id; 3% of drawings, added because the id must be findable). Nothing the model
drew is changed or dropped; the existing guards (id uniqueness, frame, transform, sanitiser allowlist, geometry, overlap) run on the result.
Tests: `tests/test_grouping.py` (24).

H is 3 runs of the 8-topic eval. The cheap checks and the cheap-model judge run for every run; **the Opus review only for run 3**.

| # | target | how it is judged |
|---|---|---|
| 1 | elements with no text 15% or less in every run | every H run at or below 15% |
| 2 | overlapping pairs not above A to C | every H run at or below 35 (the highest of the nine A to C runs: `tests/eval_layout.py`, the guard's own rule over all shapes and text). Also shown against A and B alone (highest 2); C had 11 / 17 / 35 |
| 3 | retries 13 or fewer | every H run has 13 or fewer `draw_failed` events |
| 4 | layout 8 of 8, recomputed method | every H run at 8 of 8 distinct layouts on all shapes and text. **No baseline has ever reached 8 on this method (best 7; A and B 2-5)**, so this target will probably be missed even if layout is fine; the position against the A and B range is shown too |
| 5 | hard failures 0 | 0 in every H run |
| 6 | total cost per turn at most 1.25 times E's | mean of the 3 H runs at most **$0.0360** (E mean $0.0288) |
| 7 | seconds per turn at most 1.25 times E's | mean of the 3 H runs at most **19.1 s** (E mean 15.3 s) |

Risk written down before the run: with the text kept, the page state the tutor reads on every call carries every label again (A and B read
15-20k prompt tokens per turn, D to G 8-12k), so cost and seconds per turn may rise; targets 6 and 7 are the ones to watch.
Also reported, no target: group repairs by reason, retries by cause (the overlap guard now sees every element), median text lines per element,
the judge count for every run, the Opus counts (factual errors and content not on the board) for run 3 only, narration words per turn.
The normal range for any claim of "better" or "worse" stays the six runs of A and B.

If H misses target 1 (text), experiment I follows: a bare tag is rejected once with a message that says to wrap everything for the element in
one `<g id="element_id">` group; if the retry is still bare the code wraps it as in H. Same runs, same targets; rejection counts and how
many were fixed on the first retry are reported. After H or I, whichever is last, nothing else is tried.


# H, first attempt (`docs/baseline_H1`): the repair worked, one piece of bookkeeping did not

Run with the code of `b8f35ea` and the targets above, unchanged. Opus review for run 3 only, as planned.

| | H1 run 1 | run 2 | run 3 |
|---|---|---|---|
| elements with no text | 0% | 3% | 0% |
| median text lines per element | 5 | 4 | 5 |
| drawings the code wrapped in a group | 79% (39 several tags, 3 bare) | 54% (23, 7) | 60% (20, 4) |
| elements the layout code can see | 100% | 97% | 100% |
| retries | 21 | 19 | 8 |
| hard failures | 2 | 1 | 0 |
| overlapping pairs (guard rule) | 9 | 7 | 3 |
| layout clusters (of 8) | 4 | 3 | 5 |
| judge: content not on the board | 9 | 9 | 10 (G 37 / 36 / 36; A and B 5-13) |
| total cost per turn / seconds per turn | $0.0293 / 20.2 | $0.0305 / 21.1 | $0.0254 / 19.1 |
| prompt tokens per turn | 19,338 | 17,350 | 12,041 |

The text came back: shape-only elements went from 22-28 per run to 0-1, and the judge's count fell to the A and B level. But overlaps
and "hard failures" (the eval's own replay of the overlap guard over the stored boards) were still there: 9, 7, 3 pairs, and
`binary_search_visual overlaps binary_search_process`, `step_1 overlaps binary_search_example_list` and similar in 3 topics.

**The gap.** The author loop keeps its own running copy of the page (`current_svg`) for the checks later in the same turn, and it
appended the **raw** fragment the model sent, not the repaired group. Elements drawn earlier in the same turn were therefore still
bare sibling tags to the overlap check, the free-space map shown to the tutor and the id-uniqueness check; only elements from earlier
turns (read back from the stored page) were seen. Most of a page is drawn in one turn. Three tests that fail without the fix are in
`tests/test_grouping.py`: the overlap with a card drawn earlier in the same turn is rejected, the free-space map holds the card
just drawn, and a reused id in the same turn is rejected. The fix is two lines in `engine/author.py`: the loop's copy takes the
output of `ensure_group` on draw and on modify.

Notes from the review of run 3 (Opus): 5 factual errors, 1 major (the worked example shows "f(x) = x" with the answer 2x: the model wrote
control characters where x squared should be, and the sanitiser removed them; the board also shows "lim h18 0" where an arrow was meant: the model's raw
text there is the letter h, a control character and "18"). 10 statements describing content not on the board (G 32-47), 6 of them the language example sentences, which
the model's own text cuts off (`- Example: "I visited`). The comparison table keeps this attempt as column H1.

H is run again with the fix; its targets are the ones above, unchanged. The text dump for the review (`run{n}_texts.md`) now keeps text
inside `<tspan>` (4 in H1; none in E to G).


# Baseline H: the code makes every element one `<g id>` group (`b8f35ea` + `d2d7c96`)

Change since G: `engine/grouping.py` wraps a drawing that is not exactly one `<g id="element_id">` before the sanitiser reads it (draw and
modify), and the author loop's own copy of the page holds the repaired group. Prompt, tool text, hints and guards are as in G (so F's
tool-text sentence and G's system-prompt line are still in place: H was tested on top of them, not without them). Three runs:
`docs/baseline_H/`; cheap checks and judge for every run, the Opus review for run 3 only. The first attempt, before the loop fix, is
`docs/baseline_H1` (column H1).

## A to H

Normal range = the six runs of A and B. 'clear' = all three runs outside it on the same side.

| metric | A | B | C | D | E | F | G | H1 | H | C vs normal | D vs normal | E vs normal | F vs normal | G vs normal | H1 vs normal | H vs normal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| retries, total | 13 / 7 / 13 | 8 / 7 / 11 | 92 / 97 / 70 | 0 / 1 / 1 | 1 / 6 / 1 | 3 / 1 / 4 | 0 / 5 / 2 | 21 / 19 / 8 | 13 / 13 / 5 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change |
| retries per turn (total) | 0.81 / 0.44 / 0.81 | 0.5 / 0.44 / 0.69 | 5.75 / 6.06 / 4.38 | 0.0 / 0.06 / 0.06 | 0.06 / 0.38 / 0.06 | 0.19 / 0.06 / 0.25 | 0.0 / 0.31 / 0.12 | 1.31 / 1.19 / 0.5 | 0.81 / 0.81 / 0.31 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change |
| retries per turn (worst topic) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0 / n/a / n/a | n/a / n/a / n/a | 1.0 / 0.5 / 1.5 | 0 / 1.5 / 1.0 | 6.0 / 6.0 / n/a | 3.0 / 4.0 / 1.0 |  |  |  |  |  |  |  |
|   retries: background_frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 1 | 0 / 0 / 1 | 0 / 0 / 1 | 0 / 0 / 0 | 1 / 0 / 1 | 0 / 0 / 1 |  |  |  |  |  |  |  |
|   retries: overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | 0 / 0 / 0 | 0 / 5 / 0 | 1 / 0 / 1 | 0 / 2 / 2 | 6 / 15 / 4 | 5 / 4 / 0 |  |  |  |  |  |  |  |
|   retries: labels_overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 0 / 1 | 0 / 3 / 0 | 6 / 4 / 2 | 5 / 3 / 0 |  |  |  |  |  |  |  |
|   retries: transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | 1 / 0 / 1 | 0 / 0 / 0 | 1 / 0 / 1 | 1 / 0 / 0 |  |  |  |  |  |  |  |
|   retries: other | 0 / 0 / 1 | 2 / 0 / 6 | 80 / 97 / 69 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 0 | 0 / 0 / 0 | 7 / 0 / 0 | 2 / 6 / 4 |  |  |  |  |  |  |  |
| elements with no text (%) | 0 / 4 / 0 | 0 / 4 / 0 | 12 / 21 / 23 | 71 / 62 / 50 | 40 / 52 / 56 | 61 / 81 / 52 | 62 / 55 / 69 | 0 / 3 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change |
| median text lines per element | 8 / 7 / 8 | 8 / 6.0 / 9.0 | 1.0 / 1.0 / 1.0 | 0 / 0.0 / 0.5 | 1 / 0.0 / 0 | 0 / 0.0 / 0.0 | 0 / 0.0 / 0 | 5 / 4 / 5.0 | 5 / 5 / 5.0 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
|   elements: shape only | 0 / 1 / 0 | 0 / 0 / 0 | 8 / 16 / 13 | 39 / 32 / 32 | 21 / 22 / 24 | 25 / 34 / 27 | 28 / 22 / 27 | 0 / 1 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |
|   elements: text only | 1 / 2 / 0 | 0 / 0 / 0 | 34 / 45 / 25 | 13 / 19 / 29 | 21 / 17 / 14 | 10 / 7 / 18 | 17 / 8 / 9 | 5 / 10 / 7 | 4 / 6 / 3 |  |  |  |  |  |  |  |
|   elements: shape and text | 22 / 22 / 23 | 25 / 24 / 20 | 24 / 15 / 18 | 3 / 1 / 3 | 11 / 3 / 5 | 6 / 1 / 7 | 0 / 10 / 3 | 28 / 26 / 25 | 23 / 29 / 23 |  |  |  |  |  |  |  |
| drawings the code wrapped in a group (%, from baseline H on) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 79 / 54 / 60 | 78 / 69 / 59 |  |  |  |  |  |  |  |
| elements that are a bare tag, not a <g id> group (%) | 0 / 0 / 0 | 0 / 0 / 0 | 64 / 82 / 68 | 95 / 96 / 95 | 79 / 93 / 86 | 85 / 98 / 87 | 100 / 75 / 90 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |
| elements the layout code can see (%) | 100 / 96 / 100 | 100 / 100 / 100 | 23 / 16 / 23 | 5 / 0 / 0 | 11 / 7 / 14 | 5 / 2 / 13 | 0 / 25 / 10 | 100 / 97 / 100 | 100 / 100 / 100 |  |  |  |  |  |  |  |
| replies/narrations that mention a rejection | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 1 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| narration words, median | 52 / 51 / 58 | 59 / 60.0 / 59.5 | 18.0 / 17.5 / 18.0 | 22 / 18.5 / 21.0 | 25 / 25.5 / 23 | 25.5 / 27 / 25.5 | 26 / 30.0 / 28 | 32 / 27 / 32.0 | 27 / 29 / 37.0 |  |  |  |  |  |  |  |
| narration words per turn | 91 / 95 / 90 | 107 / 96 / 77 | 90 / 91 / 74 | 88 / 73 / 89 | 94 / 84 / 78 | 76 / 85 / 89 | 80 / 90 / 83 | 73 / 83 / 71 | 60 / 71 / 64 |  |  |  |  |  |  |  |
| same first two words: replies (%) | 25 / 25 / 19 | 25 / 31 / 25 | 62 / 62 / 69 | 56 / 62 / 56 | 62 / 56 / 88 | 88 / 81 / 56 | 69 / 75 / 62 | 56 / 81 / 50 | 56 / 75 / 69 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
| same first two words: narrations (%) | 30 / 20 / 17 | 40 / 33 / 40 | 45 / 18 / 30 | 35 / 33 / 22 | 28 / 38 / 30 | 52 / 39 / 35 | 42 / 50 / 51 | 33 / 54 / 47 | 44 / 36 / 38 | no clear change | no clear change | no clear change | no clear change | clear: worse | no clear change (2 of 3 outside) | no clear change |
| reply openers, distinct 3-word (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | 11 / 10 / 10 | 10 / 9 / 5 | 5 / 6 / 10 | 8 / 8 / 10 | 9 / 7 / 10 | 9 / 9 / 5 | clear: worse | no clear change (2 of 3 outside) | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
| narration openers, distinct 3-word (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | 71 / 71 / 70 | 64 / 62 / 65 | 54 / 69 / 58 | 42 / 48 / 49 | 67 / 54 / 53 | 67 / 66 / 62 | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) | clear: worse | no clear change (2 of 3 outside) | no clear change |
| replies+narrations starting 'Here/This' (%) | 64 / 59 / 69 | 71 / 60 / 64 | 40 / 22 / 28 | 28 / 29 / 21 | 23 / 29 / 31 | 40 / 33 / 34 | 34 / 46 / 42 | 24 / 40 / 33 | 37 / 27 / 33 | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better |
| layout clusters (of 8), all shapes and text | 3 / 4 / 3 | 3 / 5 / 3 | 7 / 7 / 5 | 5 / 4 / 6 | 6 / 6 / 7 | 5 / 5 / 5 | 5 / 4 / 3 | 4 / 3 / 5 | 5 / 6 / 3 | no clear change (2 of 3 outside) | no clear change | clear: better | no clear change | no clear change | no clear change | no clear change |
| layout overlap between topics (Jaccard), all shapes and text | 0.472 / 0.43 / 0.385 | 0.424 / 0.397 / 0.404 | 0.228 / 0.232 / 0.278 | 0.304 / 0.316 / 0.323 | 0.289 / 0.262 / 0.256 | 0.346 / 0.318 / 0.277 | 0.31 / 0.33 / 0.379 | 0.341 / 0.362 / 0.319 | 0.356 / 0.379 / 0.338 | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better |
| overlapping element pairs on the boards (guard rule, all shapes and text) | 1 / 2 / 0 | 2 / 1 / 1 | 35 / 17 / 11 | 12 / 11 / 7 | 5 / 3 / 10 | 14 / 9 / 4 | 4 / 7 / 7 | 9 / 7 / 3 | 1 / 4 / 2 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change |
|   layout clusters, old method (groups with an id only: wrong from C on) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | 8 / 7 / 7 | 8 / 8 / 8 | 8 / 7 / 7 | 3 / 4 / 3 | 3 / 3 / 4 |  |  |  |  |  |  |  |
| narrations with no valid marker, as the model wrote them (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 35 / 19 / 14 | 45 / 57 / 50 | 53 / 49 / 71 | 70 / 61 / 55 | 40 / 67 / 44 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse |
| narrations with no marker, as stored (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change |
| narrations with a single-bracket marker, as stored | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 6 / 0 | 0 / 5 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| hard failures (of 8) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 2 / 1 / 0 | 0 / 0 / 1 | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change (2 of 3 outside) | no clear change |
| drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | 66 / 76 / 56 | 55 / 52 / 64 | 53 / 42 / 43 | 41 / 42 / 52 | 45 / 40 / 39 | 33 / 37 / 32 | 27 / 35 / 26 |  |  |  |  |  |  |  |
| author model | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 |  |  |  |  |  |  |  |
| prompt tokens per turn | 20026 / 14878 / 18533 | 14871 / 15156 / 19439 | 30490 / 44022 / 25803 | 10485 / 8126 / 11079 | 12188 / 9280 / 10124 | 9769 / 10692 / 11718 | 11236 / 12222 / 10282 | 19338 / 17350 / 12041 | 13226 / 14157 / 7504 |  |  |  |  |  |  |  |
| completion tokens per turn | 1909 / 1303 / 2138 | 1708 / 1379 / 1630 | 2688 / 3486 / 2741 | 1086 / 974 / 1046 | 1188 / 1306 / 1048 | 1180 / 1486 / 1198 | 1391 / 1626 / 1378 | 1529 / 1509 / 1316 | 1632 / 1455 / 1005 |  |  |  |  |  |  |  |
| LLM cost per turn (USD, list price, no cache discount) | 0.0111 / 0.008 / 0.0108 | 0.0087 / 0.0083 / 0.0104 | 0.0165 / 0.0232 / 0.0147 | 0.0059 / 0.0048 / 0.0061 | 0.0068 / 0.0058 / 0.0057 | 0.0058 / 0.0067 / 0.0066 | 0.0067 / 0.0075 / 0.0063 | 0.0102 / 0.0094 / 0.0069 | 0.0079 / 0.008 / 0.0046 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change | no clear change (2 of 3 outside) |
| speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | 552 / 465 / 556 | 633 / 544 / 524 | 513 / 557 / 595 | 524 / 582 / 539 | 477 / 528 / 463 | 396 / 468 / 417 |  |  |  |  |  |  |  |
| speech cost per turn (USD, $0.04 per 1,000 characters) | 0.0234 / 0.0248 / 0.0232 | 0.0267 / 0.024 / 0.0194 | 0.0233 / 0.0227 / 0.0196 | 0.0221 / 0.0186 / 0.0222 | 0.0253 / 0.0218 / 0.021 | 0.0205 / 0.0223 / 0.0238 | 0.021 / 0.0233 / 0.0216 | 0.0191 / 0.0211 / 0.0185 | 0.0159 / 0.0187 / 0.0167 |  |  |  |  |  |  |  |
| TOTAL cost per turn (USD, LLM + speech) | 0.0345 / 0.0328 / 0.034 | 0.0354 / 0.0323 / 0.0298 | 0.0398 / 0.0459 / 0.0343 | 0.028 / 0.0234 / 0.0283 | 0.0321 / 0.0276 / 0.0267 | 0.0263 / 0.029 / 0.0304 | 0.0277 / 0.0308 / 0.0279 | 0.0293 / 0.0305 / 0.0254 | 0.0238 / 0.0267 / 0.0213 | no clear change (2 of 3 outside) | clear: better | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | clear: better |
| LLM cost per turn with cached-token discount (USD, where logged) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0.0033 / 0.0039 / 0.0035 | 0.004 / 0.0044 / 0.0036 | 0.005 / 0.0049 / 0.0039 | 0.0045 / 0.0043 / 0.0028 |  |  |  |  |  |  |  |
| tutor seconds per turn (mean) | 24.6 / 18.5 / 28.1 | 21.2 / 17.6 / 20.1 | 39.4 / 46.2 / 35.5 | 15.2 / 13.1 / 14.4 | 16.0 / 15.9 / 14.0 | 16.6 / 19.7 / 18.6 | 19.4 / 23.0 / 18.4 | 20.2 / 21.1 / 19.1 | 22.1 / 21.1 / 53.6 | clear: worse | clear: better | clear: better | no clear change | no clear change | no clear change | no clear change |
| factual errors flagged | 8 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | n/a / n/a / 5 | n/a / n/a / 8 | no clear change | no clear change | no clear change | clear: better | no clear change |  |  |
|   of which major | 3 / 0 / 1 | n/a / n/a / n/a | 1 / 0 / 0 | 1 / 1 / 0 | 0 / 0 / 2 | 1 / 0 / 0 | 0 / 1 / 0 | n/a / n/a / 1 | n/a / n/a / 1 | no clear change | no clear change | no clear change | no clear change | no clear change |  |  |
|   model-only (not our bugs) | 7 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | n/a / n/a / 5 | n/a / n/a / 8 | no clear change | no clear change | no clear change | clear: better | no clear change |  |  |
| replies describing what is not on the board | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 36 / 37 / 28 | 33 / 26 / 29 | 38 / 50 / 37 | 47 / 32 / 35 | n/a / n/a / 10 | n/a / n/a / 7 |  |  |  |  |  |  |  |
| judge: statements describing content not on the board | 10 / 13 / 12 | 8 / 12 / 5 | 27 / 28 / 30 | 26 / 41 / 34 | 31 / 32 / 30 | 33 / 36 / 36 | 37 / 36 / 36 | 9 / 9 / 10 | 8 / 5 / 6 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change |

* the model was not logged before baseline F; the deployment 'gpt-4o-mini' serves gpt-4.1-mini and was last changed before baseline A (docs/BASELINE.md).

## Targets (fixed before the run, `b8f35ea`)

| # | target | H (3 runs) | result |
|---|---|---|---|
| 1 | elements with no text 15% or less in every run | 0 / 0 / 0% (G 62 / 55 / 69; H1 0 / 3 / 0) | **met** |
| 2 | overlapping pairs not above A to C (every run at or below 35) | 1 / 4 / 2 (A 1 / 2 / 0, B 2 / 1 / 1, C 35 / 17 / 11; G 4 / 7 / 7) | **met**; against A and B alone (at most 2) run 2 is above |
| 3 | retries 13 or fewer | 13 / 13 / 5 | **met** (4 of run 3's 5 are service timeouts, not guard rejections) |
| 4 | layout 8 of 8 on the recomputed method | 5 / 6 / 3 (A and B 2-5, best of any baseline 7) | **missed**; within or one above the A and B range |
| 5 | hard failures 0 | 0 / 0 / 1 | **missed**, but not by the code: in run 3 three model calls timed out and one connection failed (see below), so the code topic drew nothing |
| 6 | total cost per turn, mean at most $0.0360 | $0.0238 / 0.0267 / 0.0213, mean **$0.0239** = 0.83 times E | **met** |
| 7 | seconds per turn, mean at most 19.1 s | 22.1 / 21.1 / 53.6, mean **32.3 s** = 2.1 times E | **missed**. Without run 3 (service timeouts) the mean is 21.6 s = 1.41 times E, still above; H1 was 20.1 s |

**Four of seven met (1, 2, 3, 6); the text target is met in every run, by a wide margin. Experiment I was not run: it is only for the case
where H misses the text target.** Targets 5 and the size of target 7's miss come from run 3's service trouble; target 4 and the rest of 7
are real.

## The repair, measured: what the model drew against what was stored

For every drawing, the number of text labels and shapes in the raw model output (log `draw_started.raw_svg`) against the stored fragment:

| | G run 1 / 2 / 3 | H1 run 1 / 2 / 3 | H run 1 / 2 / 3 |
|---|---|---|---|
| drawings that lost text or shapes between the model and the board | **37 of 45 / 25 of 40 / 31 of 39** | 0 of 33 / 0 of 37 / 0 of 32 | 0 of 27 / 0 of 35 / **1 of 26** |

The one drawing in H is a second silent-loss path, not touched by H: `dense/handshake_diagram_no_bg` (run 3). The model wrote a malformed
attribute (`font-size"16"`, no `=`); the sanitiser's recovery parser kept the XML up to that tag and dropped the other 19 labels, and the tool
answered "ok". Six of the seven "not on the board" items the reviewer found in run 3 are that one drawing.

## What the boards look like now

- Elements with no text 0 / 0 / 0%; median text lines per element 5 / 5 / 5 (A and B 6-9); shape-only elements 0 (G 22-28), text-only 4 / 6 / 3,
  shape and text together 23 / 29 / 23 (G 0 / 10 / 3). The layout code sees every element (100%).
- Drawings the code wrapped: 78 / 69 / 59% (bare tag 3 / 3 / 2, several top-level tags 28 / 30 / 14). The tutor still hardly ever writes
  the `<g>` itself.
- The judge's count of statements describing content not on the board is 8 / 5 / 6 (A and B 5-13, G 36-37). The Opus reviewer's count for
  run 3 is 7 (G 32-47), 6 of them the truncated handshake drawing. Factual errors in run 3: 8, 1 major (the model's own: its worked example
  has control characters where x squared and an arrow should be, which the sanitiser removes, leaving "f(x) = x" and "h1e0").
- Speech is shorter: 60 / 71 / 64 narration words per turn (G 80-90) and 396-468 spoken characters per turn (G 524-582), so speech cost
  per turn fell to $0.016-0.019. I do not know why; the board now carries what the narration used to carry.

## What the guards do now that they see everything

Retries 13 / 13 / 5 (G 0 / 5 / 2, E 1 / 6 / 1): overlap 5 / 4 / 0, labels overlapping 5 / 3 / 0, other 2 / 6 / 4 (run 3: the four service
failures), and in runs 1 and 2 a series of "Element bleeds canvas" rejections for step lists the tutor wrote below y = 800 (the binary-search
steps; previously the text was dropped before it was measured). Overlapping pairs on the final boards: 1 / 4 / 2 (G 4 / 7 / 7). The tutor
now reads the full page (13.2k and 14.2k prompt tokens per turn in runs 1 and 2, against 10-12k), and makes more model calls per turn
(2.9 and 3.5, G 3.0-3.2). These are the likely reasons seconds per turn are 21-22 s in runs 1 and 2 against 14-16 s in E.

**Run 3's service trouble:** the log has three "Model call failed: Request timed out" and one "Connection error" in run 3; turns took 212, 155 and
132 s, the code topic's turns got no model answer ("nothing was drawn", the hard failure).
Run 3 is therefore not a clean measure of seconds or hard failures. I did not repeat it (you asked for three runs and no more experiments).

## What changes in earlier conclusions

1. **Withdrawn:** that the tutor ignored the advice about writing text (F, G), and that the narration-per-element coupling was a leading cause.
   The tutor wrote the text; the code deleted it. F's sentence and G's prompt line did not matter for that.
2. **Numbers measured on stored boards from C to G are inflated or wrong** for: elements with no text, bare tags, shape/text mix, the
   Opus and judge "not on the board" counts, median text lines, and the hard-failure count (the eval's own overlap replay was blind to bare
   tags, so "0" from D to G means "not measured"). Layout and overlap are recomputed (see the check section above).
3. **Still true:** narration repair of markers, the rejection storm and its fix in C and D, the cost model, and the facts about what was
   said (the reviewers read the model's words, not the board).
4. **New silent losses, not fixed:** (a) a malformed attribute truncates a drawing (1 of 88 in H); (b) control characters in the model's
   text turn "x squared" and an arrow into "x" and "h18 0" (seen in the reviewed run 3 of both H1 and H); both are invisible to the model, which is told
   "ok". An eval check that compares raw and stored drawing is now cheap (the numbers above).

## Tests

- Offline suite after the fix: 446 passed, 30 skipped (the live ones), 21 judge tests deselected.
- Live-server suite after the runs, including the live cheap-model judge tests: **497 passed, 0 skipped, 0 failed** in 302 s (21 of them are
  the judge tests, run against the real cheap model).

## Which to keep

**H.** It repairs a defect (from C to G, 48-88% of the tutor's drawings lost everything after their first tag, and most elements had no id) without telling the model what to draw.
Costs: more guard rejections and a longer prompt, so about 6 s more per turn than E; no baseline has ever reached 8 of 8 layouts (best 7).
Not decided here (yours): whether to keep F's tool-text sentence and G's prompt line, which were never needed for the text and were not tested
without H; whether to make the sanitiser reject, instead of recover, a drawing it cannot parse; and whether to tell the tutor about a
guard that is about to reject the step list before it draws it (seconds per turn).


# Experiment J: F's sentence and G's prompt line removed again; the prompt and tool text are frozen (targets fixed before the run)

Decision (yours): keep H, the group repair and the earlier recording fixes; remove F's sentence (tool text) and G's sentence (system prompt
line 110) and restore the E wording in both places. Done in code: `engine/author.py` now has the E system prompt and the E tool text,
**byte for byte** (checked by loading the code of commit `37e7dc6` and comparing the system prompt string and the tool definitions:
both identical). `tests/test_prompt_rules.py` pins the E wording, pins that none of the F or G sentences is anywhere in the prompt or the
tool text, and **freezes** both: a test compares a SHA-256 of the system prompt and of the tool definitions, so any later edit fails
until the digests are changed on purpose in the same commit. From here the prompt and the tool text are not tuned again.

J is H on the E wording: the code as at `793a5fc` plus the lossless check (`e706c29`), nothing else (the new tutor-facing messages for lost
content and the control-character placeholder come after this run, so J measures one change only). Three runs of the 8-topic eval,
cheap checks and the cheap-model judge, and the lossless check (every drawing as the model wrote it against what is stored). **No Opus
review unless something is clearly worse than H.**

| # | target (fixed now) | how it is judged |
|---|---|---|
| 1 | elements with no text 15% or less | every J run at or below 15% |
| 2 | retries 13 or fewer | every J run at or below 13 `draw_failed` events |
| 3 | overlapping pairs not above A and B plus 2 | A and B's highest is 2, so every J run at or below **4** (`tests/eval_layout.py`, the guard's own rule on all shapes and text) |
| 4 | hard failures 0 | every J run at 0 |

**"Worse than H"** (fixed now): for any row of the comparison table that has a direction (better or worse), all three J runs lie outside the
range of H's three runs on the bad side (the same "clear" rule as against the normal range; column "J vs H"). The means of the key rows are
also stated. If that rule says clearly worse on elements with no text, the not-on-board judge count, retries, hard failures, overlapping
pairs or the lossless check, the Opus review of run 3 is run, and said so.

Reported without a target: seconds and cost per turn (H: seconds 22 / 21 / 54 with service timeouts in run 3; cost $0.0238 / 0.0267 / 0.0213),
the lossless check (H: 0 / 0 / 8% of drawings lost something), median text lines per element, layout clusters, reply and narration openers.
Service timeouts in a run (log lines "Model call failed") are listed, not repaired or repeated.


# Baseline J: F's sentence and G's prompt line removed, H unchanged (`8a04688`)

Change since H: the system prompt and the tool text are the E wording again (byte for byte, tested), and frozen. Everything else is H: the group
repair, the loop fix, the markers, the lossless check. Three runs in `docs/baseline_J/`; cheap checks, the cheap-model judge and the lossless
check; **no Opus review** (see "Worse than H"). The first J attempt was lost: I edited engine files while the eval process was still running and
it imported the changed author module at its judge step; run 1 of that attempt crashed before it was saved. These are the three runs of the
clean second attempt; no code changed while they ran.

## A to J

Normal range = the six runs of A and B. 'clear' = all three runs outside it on the same side.

| metric | A | B | C | D | E | F | G | H1 | H | J | C vs normal | D vs normal | E vs normal | F vs normal | G vs normal | H1 vs normal | H vs normal | J vs normal | J vs H |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| retries, total | 13 / 7 / 13 | 8 / 7 / 11 | 92 / 97 / 70 | 0 / 1 / 1 | 1 / 6 / 1 | 3 / 1 / 4 | 0 / 5 / 2 | 21 / 19 / 8 | 13 / 13 / 5 | 13 / 5 / 12 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change |
| retries per turn (total) | 0.81 / 0.44 / 0.81 | 0.5 / 0.44 / 0.69 | 5.75 / 6.06 / 4.38 | 0.0 / 0.06 / 0.06 | 0.06 / 0.38 / 0.06 | 0.19 / 0.06 / 0.25 | 0.0 / 0.31 / 0.12 | 1.31 / 1.19 / 0.5 | 0.81 / 0.81 / 0.31 | 0.81 / 0.31 / 0.75 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change |
| retries per turn (worst topic) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0 / n/a / n/a | n/a / n/a / n/a | 1.0 / 0.5 / 1.5 | 0 / 1.5 / 1.0 | 6.0 / 6.0 / n/a | 3.0 / 4.0 / 1.0 | 2.5 / 1.0 / 2.0 |  |  |  |  |  |  |  |  | no clear change |
|   retries: background_frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 1 | 0 / 0 / 1 | 0 / 0 / 1 | 0 / 0 / 0 | 1 / 0 / 1 | 0 / 0 / 1 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  |
|   retries: overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | 0 / 0 / 0 | 0 / 5 / 0 | 1 / 0 / 1 | 0 / 2 / 2 | 6 / 15 / 4 | 5 / 4 / 0 | 6 / 4 / 4 |  |  |  |  |  |  |  |  |  |
|   retries: labels_overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 0 / 1 | 0 / 3 / 0 | 6 / 4 / 2 | 5 / 3 / 0 | 7 / 0 / 3 |  |  |  |  |  |  |  |  |  |
|   retries: transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | 1 / 0 / 1 | 0 / 0 / 0 | 1 / 0 / 1 | 1 / 0 / 0 | 0 / 1 / 0 |  |  |  |  |  |  |  |  |  |
|   retries: other | 0 / 0 / 1 | 2 / 0 / 6 | 80 / 97 / 69 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 0 | 0 / 0 / 0 | 7 / 0 / 0 | 2 / 6 / 4 | 0 / 0 / 5 |  |  |  |  |  |  |  |  |  |
| elements with no text (%) | 0 / 4 / 0 | 0 / 4 / 0 | 12 / 21 / 23 | 71 / 62 / 50 | 40 / 52 / 56 | 61 / 81 / 52 | 62 / 55 / 69 | 0 / 3 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change | no clear change | no clear change |
| median text lines per element | 8 / 7 / 8 | 8 / 6.0 / 9.0 | 1.0 / 1.0 / 1.0 | 0 / 0.0 / 0.5 | 1 / 0.0 / 0 | 0 / 0.0 / 0.0 | 0 / 0.0 / 0 | 5 / 4 / 5.0 | 5 / 5 / 5.0 | 5 / 3 / 5 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change |
|   elements: shape only | 0 / 1 / 0 | 0 / 0 / 0 | 8 / 16 / 13 | 39 / 32 / 32 | 21 / 22 / 24 | 25 / 34 / 27 | 28 / 22 / 27 | 0 / 1 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  |
|   elements: text only | 1 / 2 / 0 | 0 / 0 / 0 | 34 / 45 / 25 | 13 / 19 / 29 | 21 / 17 / 14 | 10 / 7 / 18 | 17 / 8 / 9 | 5 / 10 / 7 | 4 / 6 / 3 | 7 / 6 / 8 |  |  |  |  |  |  |  |  |  |
|   elements: shape and text | 22 / 22 / 23 | 25 / 24 / 20 | 24 / 15 / 18 | 3 / 1 / 3 | 11 / 3 / 5 | 6 / 1 / 7 | 0 / 10 / 3 | 28 / 26 / 25 | 23 / 29 / 23 | 22 / 29 / 29 |  |  |  |  |  |  |  |  |  |
| drawings the code wrapped in a group (%, from baseline H on) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 79 / 54 / 60 | 78 / 69 / 59 | 71 / 82 / 77 |  |  |  |  |  |  |  |  |  |
| drawings that lost something between the model and the board (%) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 64 / 73 / 55 | 70 / 83 / 77 | 73 / 88 / 73 | 82 / 65 / 79 | 0 / 0 / 3 | 0 / 0 / 8 | 0 / 3 / 0 |  |  |  |  |  |  |  |  | no clear change |
|   dropped text lines (model wrote them, not on the board) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 155 / 145 / 134 | 131 / 157 / 128 | 147 / 160 / 136 | 185 / 144 / 197 | 0 / 0 / 6 | 0 / 0 / 25 | 0 / 5 / 0 |  |  |  |  |  |  |  |  | no clear change |
|   dropped characters of text | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 4253 / 3103 / 2226 | 3028 / 3082 / 3379 | 3328 / 3964 / 3331 | 3362 / 3286 / 4108 | 0 / 0 / 7 | 0 / 0 / 367 | 0 / 161 / 0 |  |  |  |  |  |  |  |  | no clear change |
|   dropped tags (all kinds) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 192 / 205 / 181 | 207 / 224 / 177 | 193 / 214 / 189 | 265 / 185 / 289 | 0 / 0 / 0 | 0 / 0 / 35 | 0 / 4 / 0 |  |  |  |  |  |  |  |  | no clear change |
| elements that are a bare tag, not a <g id> group (%) | 0 / 0 / 0 | 0 / 0 / 0 | 64 / 82 / 68 | 95 / 96 / 95 | 79 / 93 / 86 | 85 / 98 / 87 | 100 / 75 / 90 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  |
| elements the layout code can see (%) | 100 / 96 / 100 | 100 / 100 / 100 | 23 / 16 / 23 | 5 / 0 / 0 | 11 / 7 / 14 | 5 / 2 / 13 | 0 / 25 / 10 | 100 / 97 / 100 | 100 / 100 / 100 | 100 / 100 / 100 |  |  |  |  |  |  |  |  |  |
| replies/narrations that mention a rejection | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 1 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| narration words, median | 52 / 51 / 58 | 59 / 60.0 / 59.5 | 18.0 / 17.5 / 18.0 | 22 / 18.5 / 21.0 | 25 / 25.5 / 23 | 25.5 / 27 / 25.5 | 26 / 30.0 / 28 | 32 / 27 / 32.0 | 27 / 29 / 37.0 | 27 / 24 / 28 |  |  |  |  |  |  |  |  |  |
| narration words per turn | 91 / 95 / 90 | 107 / 96 / 77 | 90 / 91 / 74 | 88 / 73 / 89 | 94 / 84 / 78 | 76 / 85 / 89 | 80 / 90 / 83 | 73 / 83 / 71 | 60 / 71 / 64 | 66 / 61 / 74 |  |  |  |  |  |  |  |  |  |
| same first two words: replies (%) | 25 / 25 / 19 | 25 / 31 / 25 | 62 / 62 / 69 | 56 / 62 / 56 | 62 / 56 / 88 | 88 / 81 / 56 | 69 / 75 / 62 | 56 / 81 / 50 | 56 / 75 / 69 | 38 / 62 / 56 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change |
| same first two words: narrations (%) | 30 / 20 / 17 | 40 / 33 / 40 | 45 / 18 / 30 | 35 / 33 / 22 | 28 / 38 / 30 | 52 / 39 / 35 | 42 / 50 / 51 | 33 / 54 / 47 | 44 / 36 / 38 | 31 / 29 / 35 | no clear change | no clear change | no clear change | no clear change | clear: worse | no clear change (2 of 3 outside) | no clear change | no clear change | clear: better |
| reply openers, distinct 3-word (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | 11 / 10 / 10 | 10 / 9 / 5 | 5 / 6 / 10 | 8 / 8 / 10 | 9 / 7 / 10 | 9 / 9 / 5 | 13 / 9 / 9 | clear: worse | no clear change (2 of 3 outside) | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change (2 of 3 outside) | no clear change |
| narration openers, distinct 3-word (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | 71 / 71 / 70 | 64 / 62 / 65 | 54 / 69 / 58 | 42 / 48 / 49 | 67 / 54 / 53 | 67 / 66 / 62 | 69 / 71 / 59 | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) | clear: worse | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) |
| replies+narrations starting 'Here/This' (%) | 64 / 59 / 69 | 71 / 60 / 64 | 40 / 22 / 28 | 28 / 29 / 21 | 23 / 29 / 31 | 40 / 33 / 34 | 34 / 46 / 42 | 24 / 40 / 33 | 37 / 27 / 33 | 22 / 22 / 34 | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) |
| layout clusters (of 8), all shapes and text | 3 / 4 / 3 | 3 / 5 / 3 | 7 / 7 / 5 | 5 / 4 / 6 | 6 / 6 / 7 | 5 / 5 / 5 | 5 / 4 / 3 | 4 / 3 / 5 | 5 / 6 / 3 | 3 / 4 / 3 | no clear change (2 of 3 outside) | no clear change | clear: better | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| layout overlap between topics (Jaccard), all shapes and text | 0.472 / 0.43 / 0.385 | 0.424 / 0.397 / 0.404 | 0.228 / 0.232 / 0.278 | 0.304 / 0.316 / 0.323 | 0.289 / 0.262 / 0.256 | 0.346 / 0.318 / 0.277 | 0.31 / 0.33 / 0.379 | 0.341 / 0.362 / 0.319 | 0.356 / 0.379 / 0.338 | 0.37 / 0.377 / 0.476 | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change |
| overlapping element pairs on the boards (guard rule, all shapes and text) | 1 / 2 / 0 | 2 / 1 / 1 | 35 / 17 / 11 | 12 / 11 / 7 | 5 / 3 / 10 | 14 / 9 / 4 | 4 / 7 / 7 | 9 / 7 / 3 | 1 / 4 / 2 | 3 / 6 / 9 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | clear: worse | no clear change (2 of 3 outside) |
|   layout clusters, old method (groups with an id only: wrong from C on) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | 8 / 7 / 7 | 8 / 8 / 8 | 8 / 7 / 7 | 3 / 4 / 3 | 3 / 3 / 4 | 2 / 3 / 3 |  |  |  |  |  |  |  |  |  |
| narrations with no valid marker, as the model wrote them (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 35 / 19 / 14 | 45 / 57 / 50 | 53 / 49 / 71 | 70 / 61 / 55 | 40 / 67 / 44 | 17 / 8 / 17 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: better |
| narrations with no marker, as stored (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| narrations with a single-bracket marker, as stored | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 6 / 0 | 0 / 5 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| hard failures (of 8) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 2 / 1 / 0 | 0 / 0 / 1 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change |
| drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | 66 / 76 / 56 | 55 / 52 / 64 | 53 / 42 / 43 | 41 / 42 / 52 | 45 / 40 / 39 | 33 / 37 / 32 | 27 / 35 / 26 | 29 / 35 / 37 |  |  |  |  |  |  |  |  |  |
| author model | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 |  |  |  |  |  |  |  |  |  |
| prompt tokens per turn | 20026 / 14878 / 18533 | 14871 / 15156 / 19439 | 30490 / 44022 / 25803 | 10485 / 8126 / 11079 | 12188 / 9280 / 10124 | 9769 / 10692 / 11718 | 11236 / 12222 / 10282 | 19338 / 17350 / 12041 | 13226 / 14157 / 7504 | 11138 / 9254 / 13810 |  |  |  |  |  |  |  |  |  |
| completion tokens per turn | 1909 / 1303 / 2138 | 1708 / 1379 / 1630 | 2688 / 3486 / 2741 | 1086 / 974 / 1046 | 1188 / 1306 / 1048 | 1180 / 1486 / 1198 | 1391 / 1626 / 1378 | 1529 / 1509 / 1316 | 1632 / 1455 / 1005 | 1194 / 949 / 1648 |  |  |  |  |  |  |  |  |  |
| LLM cost per turn (USD, list price, no cache discount) | 0.0111 / 0.008 / 0.0108 | 0.0087 / 0.0083 / 0.0104 | 0.0165 / 0.0232 / 0.0147 | 0.0059 / 0.0048 / 0.0061 | 0.0068 / 0.0058 / 0.0057 | 0.0058 / 0.0067 / 0.0066 | 0.0067 / 0.0075 / 0.0063 | 0.0102 / 0.0094 / 0.0069 | 0.0079 / 0.008 / 0.0046 | 0.0064 / 0.0052 / 0.0082 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change |
| speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | 552 / 465 / 556 | 633 / 544 / 524 | 513 / 557 / 595 | 524 / 582 / 539 | 477 / 528 / 463 | 396 / 468 / 417 | 419 / 413 / 480 |  |  |  |  |  |  |  |  |  |
| speech cost per turn (USD, $0.04 per 1,000 characters) | 0.0234 / 0.0248 / 0.0232 | 0.0267 / 0.024 / 0.0194 | 0.0233 / 0.0227 / 0.0196 | 0.0221 / 0.0186 / 0.0222 | 0.0253 / 0.0218 / 0.021 | 0.0205 / 0.0223 / 0.0238 | 0.021 / 0.0233 / 0.0216 | 0.0191 / 0.0211 / 0.0185 | 0.0159 / 0.0187 / 0.0167 | 0.0168 / 0.0165 / 0.0192 |  |  |  |  |  |  |  |  |  |
| TOTAL cost per turn (USD, LLM + speech) | 0.0345 / 0.0328 / 0.034 | 0.0354 / 0.0323 / 0.0298 | 0.0398 / 0.0459 / 0.0343 | 0.028 / 0.0234 / 0.0283 | 0.0321 / 0.0276 / 0.0267 | 0.0263 / 0.029 / 0.0304 | 0.0277 / 0.0308 / 0.0279 | 0.0293 / 0.0305 / 0.0254 | 0.0238 / 0.0267 / 0.0213 | 0.0232 / 0.0217 / 0.0274 | no clear change (2 of 3 outside) | clear: better | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | clear: better | clear: better | no clear change |
| LLM cost per turn with cached-token discount (USD, where logged) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0.0033 / 0.0039 / 0.0035 | 0.004 / 0.0044 / 0.0036 | 0.005 / 0.0049 / 0.0039 | 0.0045 / 0.0043 / 0.0028 | 0.0036 / 0.003 / 0.0048 |  |  |  |  |  |  |  |  |  |
| tutor seconds per turn (mean) | 24.6 / 18.5 / 28.1 | 21.2 / 17.6 / 20.1 | 39.4 / 46.2 / 35.5 | 15.2 / 13.1 / 14.4 | 16.0 / 15.9 / 14.0 | 16.6 / 19.7 / 18.6 | 19.4 / 23.0 / 18.4 | 20.2 / 21.1 / 19.1 | 22.1 / 21.1 / 53.6 | 21.2 / 16.0 / 26.3 | clear: worse | clear: better | clear: better | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| factual errors flagged | 8 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | n/a / n/a / 5 | n/a / n/a / 8 | n/a / n/a / n/a | no clear change | no clear change | no clear change | clear: better | no clear change |  |  |  |  |
|   of which major | 3 / 0 / 1 | n/a / n/a / n/a | 1 / 0 / 0 | 1 / 1 / 0 | 0 / 0 / 2 | 1 / 0 / 0 | 0 / 1 / 0 | n/a / n/a / 1 | n/a / n/a / 1 | n/a / n/a / n/a | no clear change | no clear change | no clear change | no clear change | no clear change |  |  |  |  |
|   model-only (not our bugs) | 7 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | n/a / n/a / 5 | n/a / n/a / 8 | n/a / n/a / n/a | no clear change | no clear change | no clear change | clear: better | no clear change |  |  |  |  |
| replies describing what is not on the board | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 36 / 37 / 28 | 33 / 26 / 29 | 38 / 50 / 37 | 47 / 32 / 35 | n/a / n/a / 10 | n/a / n/a / 7 | n/a / n/a / n/a |  |  |  |  |  |  |  |  |  |
| judge: statements describing content not on the board | 10 / 13 / 12 | 8 / 12 / 5 | 27 / 28 / 30 | 26 / 41 / 34 | 31 / 32 / 30 | 33 / 36 / 36 | 37 / 36 / 36 | 9 / 9 / 10 | 8 / 5 / 6 | 6 / 10 / 4 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change | no clear change | no clear change |

* the model was not logged before baseline F; the deployment 'gpt-4o-mini' serves gpt-4.1-mini and was last changed before baseline A (docs/BASELINE.md).

## Targets (fixed before the run, `8a04688`)

| # | target | J | result |
|---|---|---|---|
| 1 | elements with no text 15% or less | 0 / 0 / 0% | **met** |
| 2 | retries 13 or fewer | 13 / 5 / 12 | **met** |
| 3 | overlapping pairs not above A and B plus 2 (at most 4 per run) | 3 / 6 / 9 (H 1 / 4 / 2) | **missed** (runs 2 and 3) |
| 4 | hard failures 0 | 0 / 0 / 0 | **met** |

## Is anything worse than H?

By the rule fixed before the run (all three J runs outside H's range on the bad side) **nothing is clearly worse**, so no Opus review was run. Plainly,
on means and on single runs:

- **Worse (not clearly): overlapping pairs on the boards**, 3 / 6 / 9 against 1 / 4 / 2; two of three runs are above H's highest. Layout variety is
  also lower: 3 / 4 / 3 distinct layouts against 5 / 6 / 3 (A and B: 2-5, so J is inside their range).
- **Same:** elements with no text, retries (mean 10 against 10.3), hard failures, the judge's not-on-board count (6 / 10 / 4 against 8 / 5 / 6),
  total cost per turn (mean $0.0241 against $0.0239), median text lines (5 / 3 / 5 against 5 / 5 / 5).
- **Better:** seconds per turn 21.2 / 16.0 / 26.3 (H 22.1 / 21.1 / 53.6, run 3 with service timeouts; J's runs had none); narrations written with a
  wrong or missing marker 17 / 8 / 17% (H 40 / 67 / 44%; the code repairs them either way); narration openers more varied; replies and narrations
  starting "Here/This" 22 / 22 / 34% (H 37 / 27 / 33).

**The overlapping pairs are text running into a neighbour, which the guard cannot see.** Counted with the guard's own boxes, both H and J have 0 pairs
on every page (the guard does its job). Counted with the real size of every text label there are 1 / 4 / 2 (H) and 3 / 6 / 9 (J): the guard's box for a
`<text>` is a fixed 80 x 20 px guess, so a long label that runs into the next element passes. That is a measurement gap, not a regression of J's
prompt, and I cannot say from three runs that J is really worse on it than H.

## The lossless check on J

1 of 101 drawings lost something (run 2, maths `worked_example`: 4 text labels, 161 characters). Cause: `font-size"20"` in the model's SVG, a missing `=`,
exactly the typo that cut H run 3's handshake drawing, so both remaining silent losses in H and J come from the same model slip. Before the changes
below the tutor was told nothing about it ("ok"); it is now told (next section) and the loss is logged.


# No silent recovery: what the tutor is told, and the control-character placeholder (after J)

Two changes to what the tutor is told and what the board keeps, made after J so J measured one change only. The system prompt and the tool
text were not touched (they are frozen); this is a field in the tool *result*.

**The lost-content note** (`engine/lossless.py`, called from the draw and modify handlers). The drawing is compared with what was stored
(the same comparison as the eval's lossless check). If anything the model wrote is not on the board, the result keeps `"status": "ok"` (the
element is stored; this is not a rejection), gains a `lost_content` field, and a `content_lost` event is logged with the counts. The wording:

- Something lost: *Not everything you wrote for 'law1' reached the board: 2 text labels are missing (first: "Law 1: First Law"); tags removed: <line> x1, <script> x1. Redraw it with modify_existing_element (same element_id) so everything you meant to show is on the board.*
- Control characters only: *In 'law1', 2 control characters (code 0, 2) cannot be drawn, so the board shows � there. You probably meant a symbol such as an arrow or a superscript. Redraw it with modify_existing_element (same element_id), writing the real character (for example → or ²) or an entity (&#8594; or &#178;).*
- Both: the first message, then *Also, 2 control characters (code 0, 2) cannot be drawn and show as � on the board; use the real character or an entity (&#8594; &#178;) when you redraw.*

Formatting tags the repair removes on purpose with their text kept (`<br>`, `<b>`, `<sup>` ...) are logged (`told_tutor: false`) but are not a loss and
do not ask for a redraw.

**Control characters** (DEL, NUL, the C1 range, also as numeric references) are no longer deleted. Each one becomes one visible placeholder, U+FFFD
(the replacement character), so "x²" garbled by the model into two control characters shows as "x��", and the log event is now
`control_chars_replaced`. Real arrows and superscripts, written as characters, entities or numeric references, are untouched.

Tests: `tests/test_lost_content_message.py` (9: the exact message for four sibling tags with a malformed attribute, a removed `<script>`, a clean
drawing says nothing, formatting tags are logged only, control characters get the placeholder and are reported, real arrows and superscripts say
nothing, both in one drawing, the modify path, and the tool result the model actually reads), `tests/test_sanitiser_control_chars.py` (30, both ways),
`tests/test_lossless.py` (9, the check itself, both ways). Live: a drawing with four sibling tags, a malformed attribute and two NULs sent to the
running backend came back with the note above and "Title stays x��" on the board; a 3-topic quick eval on the final code showed no loss events
(21 drawings, 17 group repairs, 3 guard rejections, 0 hard failures).

**A remaining model slip worth a repair, not done:** both silent losses left in H and J (a handshake drawing, a worked example) come from the same
typo in the model's SVG, `font-size"20"` with the `=` missing. The note now tells the tutor; a precise repair of exactly that typo would not need to.

# What happens today when a model call times out or the connection fails (read only)

- **Retries:** the code has none of its own and no overall time limit. The Azure client is created per turn with the SDK defaults: connect timeout 5 s,
  read, write and pool timeout 600 s, and `max_retries = 2`, so the SDK repeats a failed call up to twice more (connection errors, timeouts, 408, 409,
  429, 5xx) with a short back-off. The call runs in a worker thread, so a barge-in stops the wait for it but not the call.
- **After the last failure:** `run_whiteboard_author` logs a `draw_failed` warning ("Model call failed: Request timed out." or "Connection error.")
  and ends the turn at once with the fixed sentence *"I couldn't reach the tutor model just now. Please try asking again in a moment."*, even if earlier
  calls of the same turn had drawn things. There is no retry of the turn.
- **What the learner sees:** that sentence as an ordinary tutor chat message (same bubble, no error state), after the wait. What was already drawn in
  that turn stays on the board. Nothing is re-sent; the learner must ask again.
- **Stored:** yes. The learner's message is saved before the agent starts and the apology is saved as the tutor's turn, so it is part of the 15-turn
  history the model reads next (the tutor sees its own apology). The eval counts it as a normal reply; the turn is a hard failure only if nothing was drawn.
- **Seen in H run 3:** three "Request timed out" and one "Connection error"; the waits before the apology were 34, 31, 132 and 32 s.
- Not changed.

# Annotation on a drawing written as bare tags (browser test)

`tests/test_browser_annotation_on_repaired_drawing.py` (Playwright, needs the backend and Vite, skips otherwise; two short narrations with the
real voice): for a drawing sent as sibling tags and for a single bare `<rect>` it draws the drawing and a permanent circle annotation on it through
the API, opens the page in Chromium, and checks that the stored drawing carries its element id, that the drawing can be found by that id in the page,
that the circle (`.rough-annotation-mark`) is drawn around it, and that the page logged no "Could not find target bounds". Before the group repair the
same flow drew nothing for a bare tag.

# Test counts at the end of this round

- Offline suite (no servers): 446 + the new tests; the full run is below.
- Live-server suite, backend and Vite running, including the live cheap-model judge tests and the new browser test: **485 passed, 0 skipped, 0 failed** in 242 s.


# Phase 2 foundations: the two open items (typo repair, text-width hint)

**Typo repair** (`engine/sanitiser.py: repair_font_size_typo`): inside a tag, `font-size"20"` (equals sign missing, numeric size with an optional unit) becomes
`font-size="20"`, exactly that pattern and no other; `x"75"`, `fill"#000"`, the same characters inside text, and non-numeric values are left alone (the lossless
check and the note to the tutor still report them). One `attribute_repaired` log event per repair, with the snippet. Both remaining silent losses of H and J came
from this slip. 15 tests.

**Text-width hint** (`engine/validator.py: find_text_width_hints`, advisory only, never a rejection): a label's estimated width is characters x font size x 0.55.
A hint goes into the draw result's `layout_hint` when the label runs off the canvas, past the right edge of the card it starts in (10 px of slack), or into an
element already on the page (30% of the label's own box). Logged as `text_width_hint`. The blocking checks keep their older, cruder text box. 15 tests.

**How often it would fire, offline on the saved boards (D to J)** (`tests/eval_text_width.py`; each page replayed element by element, the way the draw handler sees it):

| | drawings with at least one hint, runs 1 / 2 / 3 | share | kinds (3 runs) |
|---|---|---|---|
| H1, stored | 14/33, 20/37, 11/32 | 44% | card 57, canvas 23, neighbour 33 |
| H, stored | 11/27, 14/35, 14/26 | 44% | card 61, canvas 29 |
| J, stored | 15/29, 14/35, 21/37 | 50% | card 51, canvas 36, neighbour 6 |
| D to G, as the model wrote them (group-repaired; the stored boards had lost most of their text) | 28-36/55, 22-28/42, 20-27/52 ... | 40-65% | card 80-100, neighbour 78-131, canvas 13-19 |
| D to G, stored | 0-10 per run | 2-19% | (the text was mostly missing) |

So at 0.55 the hint would fire on **about one drawing in two** (44-50% where the text is intact), mostly "label runs past its card".

**Calibration** (`tests/measure_text_width.py`, 1,045 labels of H and J rendered in Chromium): the real width is 0.46 em per character (median), so 0.55 over-estimates by about
19% (real width / estimate: median 0.84, 10th to 90th percentile 0.75 to 0.99; the estimate is too small for only 7% of labels). At 0.46 the same replay fires on 34% (H1), 30% (H)
and 37% (J) of drawings. The constant is `TEXT_WIDTH_FACTOR`; it is 0.55 as decided. A hint on every second drawing may cost extra redraw calls (seconds per turn); that is
to be read in the next eval.


# Baseline K: the Phase 2 foundations on the tutor (targets and rule fixed before the run)

K is J plus everything changed since J that reaches the tutor: the `font-size"20"` repair, the advisory text-width hint (0.55), the lost-content note in the draw and modify results, the
visible placeholder for control characters, the page summary on save and the changed context header (and, invisible to the tutor, the unique (page_id, seq) index, the learners table and the
event store). The system prompt and the tool text are the E wording, frozen (digests unchanged). Three runs of the 8-topic eval, cheap checks, the cheap-model judge and the lossless check; no
Opus review. J's four targets are shown for reference (text 15% or less, retries 13 or fewer, overlapping pairs at most 4, hard failures 0).

**"Worse than J"** (fixed now): for any row of the comparison table with a direction, all three K runs outside the range of J's three runs on the bad side (column "K vs J"); the means of the key rows
are stated as well, and so is anything that is worse in two of three runs. Expected, written down before the run: seconds per turn and retries may rise (a text-width hint on about every second drawing
invites redraws; the summary call adds 1-3 s when a page is saved, which in this eval happens only when the tutor opens a new page).


## K results (three runs, `docs/baseline_K/`)

Normal range = the six runs of A and B. 'clear' = all three runs outside it on the same side.

| metric | A | B | C | D | E | F | G | H1 | H | J | K | C vs normal | D vs normal | E vs normal | F vs normal | G vs normal | H1 vs normal | H vs normal | J vs normal | K vs normal | J vs H | K vs J |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| retries, total | 13 / 7 / 13 | 8 / 7 / 11 | 92 / 97 / 70 | 0 / 1 / 1 | 1 / 6 / 1 | 3 / 1 / 4 | 0 / 5 / 2 | 21 / 19 / 8 | 13 / 13 / 5 | 13 / 5 / 12 | 8 / 34 / 9 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change | no clear change | no clear change |
| retries per turn (total) | 0.81 / 0.44 / 0.81 | 0.5 / 0.44 / 0.69 | 5.75 / 6.06 / 4.38 | 0.0 / 0.06 / 0.06 | 0.06 / 0.38 / 0.06 | 0.19 / 0.06 / 0.25 | 0.0 / 0.31 / 0.12 | 1.31 / 1.19 / 0.5 | 0.81 / 0.81 / 0.31 | 0.81 / 0.31 / 0.75 | 0.5 / 2.12 / 0.56 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change | no clear change | no clear change |
| retries per turn (worst topic) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0 / n/a / n/a | n/a / n/a / n/a | 1.0 / 0.5 / 1.5 | 0 / 1.5 / 1.0 | 6.0 / 6.0 / n/a | 3.0 / 4.0 / 1.0 | 2.5 / 1.0 / n/a | 2.0 / 10.0 / 2.0 |  |  |  |  |  |  |  |  |  |  | no clear change |
|   retries: background_frame | 2 / 3 / 6 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 1 | 0 / 0 / 1 | 0 / 0 / 1 | 0 / 0 / 0 | 1 / 0 / 1 | 0 / 0 / 1 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  |  |  |
|   retries: overlap | 3 / 2 / 4 | 1 / 3 / 3 | 9 / 0 / 1 | 0 / 0 / 0 | 0 / 5 / 0 | 1 / 0 / 1 | 0 / 2 / 2 | 6 / 15 / 4 | 5 / 4 / 0 | 6 / 4 / 4 | 5 / 21 / 9 |  |  |  |  |  |  |  |  |  |  |  |
|   retries: labels_overlap | 8 / 2 / 2 | 5 / 3 / 2 | 1 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 0 / 1 | 0 / 3 / 0 | 6 / 4 / 2 | 5 / 3 / 0 | 7 / 0 / 3 | 3 / 10 / 0 |  |  |  |  |  |  |  |  |  |  |  |
|   retries: transform | 0 / 0 / 0 | 0 / 1 / 0 | 2 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | 1 / 0 / 1 | 0 / 0 / 0 | 1 / 0 / 1 | 1 / 0 / 0 | 0 / 1 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  |  |  |
|   retries: other | 0 / 0 / 1 | 2 / 0 / 6 | 80 / 97 / 69 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 1 / 0 | 0 / 0 / 0 | 7 / 0 / 0 | 2 / 6 / 4 | 0 / 0 / 5 | 0 / 3 / 0 |  |  |  |  |  |  |  |  |  |  |  |
| elements with no text (%) | 0 / 4 / 0 | 0 / 4 / 0 | 12 / 21 / 23 | 71 / 62 / 50 | 40 / 52 / 56 | 61 / 81 / 52 | 62 / 55 / 69 | 0 / 3 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| median text lines per element | 8 / 7 / 8 | 8 / 6.0 / 9.0 | 1.0 / 1.0 / 1.0 | 0 / 0.0 / 0.5 | 1 / 0.0 / 0 | 0 / 0.0 / 0.0 | 0 / 0.0 / 0 | 5 / 4 / 5.0 | 5 / 5 / 5.0 | 5 / 3 / 5 | 4 / 4.0 / 4.0 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change |
|   elements: shape only | 0 / 1 / 0 | 0 / 0 / 0 | 8 / 16 / 13 | 39 / 32 / 32 | 21 / 22 / 24 | 25 / 34 / 27 | 28 / 22 / 27 | 0 / 1 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  |  |  |
|   elements: text only | 1 / 2 / 0 | 0 / 0 / 0 | 34 / 45 / 25 | 13 / 19 / 29 | 21 / 17 / 14 | 10 / 7 / 18 | 17 / 8 / 9 | 5 / 10 / 7 | 4 / 6 / 3 | 7 / 6 / 8 | 4 / 6 / 6 |  |  |  |  |  |  |  |  |  |  |  |
|   elements: shape and text | 22 / 22 / 23 | 25 / 24 / 20 | 24 / 15 / 18 | 3 / 1 / 3 | 11 / 3 / 5 | 6 / 1 / 7 | 0 / 10 / 3 | 28 / 26 / 25 | 23 / 29 / 23 | 22 / 29 / 29 | 29 / 28 / 30 |  |  |  |  |  |  |  |  |  |  |  |
| drawings the code wrapped in a group (%, from baseline H on) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 79 / 54 / 60 | 78 / 69 / 59 | 71 / 82 / 77 | 68 / 90 / 69 |  |  |  |  |  |  |  |  |  |  |  |
| drawings that lost something between the model and the board (%) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 64 / 73 / 55 | 70 / 83 / 77 | 73 / 88 / 73 | 82 / 65 / 79 | 0 / 0 / 3 | 0 / 0 / 8 | 0 / 3 / 0 | 0 / 3 / 0 |  |  |  |  |  |  |  |  |  | no clear change | no clear change |
|   dropped text lines (model wrote them, not on the board) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 155 / 145 / 134 | 131 / 157 / 128 | 147 / 160 / 136 | 185 / 144 / 197 | 0 / 0 / 6 | 0 / 0 / 25 | 0 / 5 / 0 | 0 / 1 / 0 |  |  |  |  |  |  |  |  |  | no clear change | no clear change |
|   dropped characters of text | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 4253 / 3103 / 2226 | 3028 / 3082 / 3379 | 3328 / 3964 / 3331 | 3362 / 3286 / 4108 | 0 / 0 / 7 | 0 / 0 / 367 | 0 / 161 / 0 | 0 / 13 / 0 |  |  |  |  |  |  |  |  |  | no clear change | no clear change |
|   dropped tags (all kinds) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 192 / 205 / 181 | 207 / 224 / 177 | 193 / 214 / 189 | 265 / 185 / 289 | 0 / 0 / 0 | 0 / 0 / 35 | 0 / 4 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  | no clear change | no clear change |
| elements that are a bare tag, not a <g id> group (%) | 0 / 0 / 0 | 0 / 0 / 0 | 64 / 82 / 68 | 95 / 96 / 95 | 79 / 93 / 86 | 85 / 98 / 87 | 100 / 75 / 90 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |  |  |  |  |  |  |  |  |  |  |  |
| elements the layout code can see (%) | 100 / 96 / 100 | 100 / 100 / 100 | 23 / 16 / 23 | 5 / 0 / 0 | 11 / 7 / 14 | 5 / 2 / 13 | 0 / 25 / 10 | 100 / 97 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 |  |  |  |  |  |  |  |  |  |  |  |
| replies/narrations that mention a rejection | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 1 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| narration words, median | 52 / 51 / 58 | 59 / 60.0 / 59.5 | 18.0 / 17.5 / 18.0 | 22 / 18.5 / 21.0 | 25 / 25.5 / 23 | 25.5 / 27 / 25.5 | 26 / 30.0 / 28 | 32 / 27 / 32.0 | 27 / 29 / 37.0 | 27 / 24 / 28 | 26 / 25.0 / 26.0 |  |  |  |  |  |  |  |  |  |  |  |
| narration words per turn | 91 / 95 / 90 | 107 / 96 / 77 | 90 / 91 / 74 | 88 / 73 / 89 | 94 / 84 / 78 | 76 / 85 / 89 | 80 / 90 / 83 | 73 / 83 / 71 | 60 / 71 / 64 | 66 / 61 / 74 | 67 / 63 / 69 |  |  |  |  |  |  |  |  |  |  |  |
| same first two words: replies (%) | 25 / 25 / 19 | 25 / 31 / 25 | 62 / 62 / 69 | 56 / 62 / 56 | 62 / 56 / 88 | 88 / 81 / 56 | 69 / 75 / 62 | 56 / 81 / 50 | 56 / 75 / 69 | 38 / 62 / 56 | 38 / 53 / 38 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change |
| same first two words: narrations (%) | 30 / 20 / 17 | 40 / 33 / 40 | 45 / 18 / 30 | 35 / 33 / 22 | 28 / 38 / 30 | 52 / 39 / 35 | 42 / 50 / 51 | 33 / 54 / 47 | 44 / 36 / 38 | 31 / 29 / 35 | 58 / 50 / 33 | no clear change | no clear change | no clear change | no clear change | clear: worse | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) | clear: better | no clear change (2 of 3 outside) |
| reply openers, distinct 3-word (of 16) | 12 / 13 / 12 | 12 / 11 / 12 | 9 / 9 / 8 | 11 / 10 / 10 | 10 / 9 / 5 | 5 / 6 / 10 | 8 / 8 / 10 | 9 / 7 / 10 | 9 / 9 / 5 | 13 / 9 / 9 | 14 / 9 / 13 | clear: worse | no clear change (2 of 3 outside) | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change |
| narration openers, distinct 3-word (%) | 61 / 68 / 83 | 60 / 67 / 70 | 39 / 61 / 50 | 71 / 71 / 70 | 64 / 62 / 65 | 54 / 69 / 58 | 42 / 48 / 49 | 67 / 54 / 53 | 67 / 66 / 62 | 69 / 71 / 59 | 45 / 62 / 56 | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) | clear: worse | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) |
| replies+narrations starting 'Here/This' (%) | 64 / 59 / 69 | 71 / 60 / 64 | 40 / 22 / 28 | 28 / 29 / 21 | 23 / 29 / 31 | 40 / 33 / 34 | 34 / 46 / 42 | 24 / 40 / 33 | 37 / 27 / 33 | 22 / 22 / 34 | 43 / 41 / 33 | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) |
| layout clusters (of 8), all shapes and text | 3 / 4 / 3 | 3 / 5 / 3 | 7 / 7 / 5 | 5 / 4 / 6 | 6 / 6 / 7 | 5 / 5 / 5 | 5 / 4 / 3 | 4 / 3 / 5 | 5 / 6 / 3 | 3 / 4 / 3 | 6 / 2 / 4 | no clear change (2 of 3 outside) | no clear change | clear: better | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| layout overlap between topics (Jaccard), all shapes and text | 0.472 / 0.43 / 0.385 | 0.424 / 0.397 / 0.404 | 0.228 / 0.232 / 0.278 | 0.304 / 0.316 / 0.323 | 0.289 / 0.262 / 0.256 | 0.346 / 0.318 / 0.277 | 0.31 / 0.33 / 0.379 | 0.341 / 0.362 / 0.319 | 0.356 / 0.379 / 0.338 | 0.37 / 0.377 / 0.476 | 0.344 / 0.437 / 0.309 | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | clear: better | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change | no clear change (2 of 3 outside) |
| overlapping element pairs on the boards (guard rule, all shapes and text) | 1 / 2 / 0 | 2 / 1 / 1 | 35 / 17 / 11 | 12 / 11 / 7 | 5 / 3 / 10 | 14 / 9 / 4 | 4 / 7 / 7 | 9 / 7 / 3 | 1 / 4 / 2 | 3 / 6 / 9 | 10 / 5 / 6 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | clear: worse | clear: worse | no clear change (2 of 3 outside) | no clear change |
|   layout clusters, old method (groups with an id only: wrong from C on) | 3 / 2 / 2 | 2 / 5 / 2 | 7 / 8 / 4 | 8 / 8 / 8 | 8 / 7 / 7 | 8 / 8 / 8 | 8 / 7 / 7 | 3 / 4 / 3 | 3 / 3 / 4 | 2 / 3 / 3 | 4 / 2 / 2 |  |  |  |  |  |  |  |  |  |  |  |
| narrations with no valid marker, as the model wrote them (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 35 / 19 / 14 | 45 / 57 / 50 | 53 / 49 / 71 | 70 / 61 / 55 | 40 / 67 / 44 | 17 / 8 / 17 | 15 / 12 / 13 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | clear: better | no clear change |
| narrations with no marker, as stored (%) | 0 / 0 / 0 | 0 / 0 / 0 | 44 / 75 / 34 | 40 / 56 / 42 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | clear: worse | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| narrations with a single-bracket marker, as stored | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 6 / 0 | 0 / 5 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| hard failures (of 8) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 2 / 1 / 0 | 0 / 0 / 1 | 0 / 0 / 0 | 0 / 1 / 0 | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change | no clear change | no clear change |
| drawings per run | 23 / 25 / 23 | 25 / 24 / 20 | 66 / 76 / 56 | 55 / 52 / 64 | 53 / 42 / 43 | 41 / 42 / 52 | 45 / 40 / 39 | 33 / 37 / 32 | 27 / 35 / 26 | 29 / 35 / 37 | 33 / 34 / 36 |  |  |  |  |  |  |  |  |  |  |  |
| author model | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini* | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 | gpt-4.1-mini-2025-04-14 |  |  |  |  |  |  |  |  |  |  |  |
| prompt tokens per turn | 20026 / 14878 / 18533 | 14871 / 15156 / 19439 | 30490 / 44022 / 25803 | 10485 / 8126 / 11079 | 12188 / 9280 / 10124 | 9769 / 10692 / 11718 | 11236 / 12222 / 10282 | 19338 / 17350 / 12041 | 13226 / 14157 / 7504 | 11138 / 9254 / 13810 | 16469 / 22841 / 14508 |  |  |  |  |  |  |  |  |  |  |  |
| completion tokens per turn | 1909 / 1303 / 2138 | 1708 / 1379 / 1630 | 2688 / 3486 / 2741 | 1086 / 974 / 1046 | 1188 / 1306 / 1048 | 1180 / 1486 / 1198 | 1391 / 1626 / 1378 | 1529 / 1509 / 1316 | 1632 / 1455 / 1005 | 1194 / 949 / 1648 | 1476 / 2194 / 1471 |  |  |  |  |  |  |  |  |  |  |  |
| LLM cost per turn (USD, list price, no cache discount) | 0.0111 / 0.008 / 0.0108 | 0.0087 / 0.0083 / 0.0104 | 0.0165 / 0.0232 / 0.0147 | 0.0059 / 0.0048 / 0.0061 | 0.0068 / 0.0058 / 0.0057 | 0.0058 / 0.0067 / 0.0066 | 0.0067 / 0.0075 / 0.0063 | 0.0102 / 0.0094 / 0.0069 | 0.0079 / 0.008 / 0.0046 | 0.0064 / 0.0052 / 0.0082 | 0.0089 / 0.0126 / 0.0082 | clear: worse | clear: better | clear: better | clear: better | clear: better | no clear change | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change | no clear change | no clear change (2 of 3 outside) |
| speech characters per turn | 585 / 621 / 579 | 667 / 600 / 485 | 582 / 568 / 489 | 552 / 465 / 556 | 633 / 544 / 524 | 513 / 557 / 595 | 524 / 582 / 539 | 477 / 528 / 463 | 396 / 468 / 417 | 419 / 413 / 480 | 433 / 416 / 456 |  |  |  |  |  |  |  |  |  |  |  |
| speech cost per turn (USD, $0.04 per 1,000 characters) | 0.0234 / 0.0248 / 0.0232 | 0.0267 / 0.024 / 0.0194 | 0.0233 / 0.0227 / 0.0196 | 0.0221 / 0.0186 / 0.0222 | 0.0253 / 0.0218 / 0.021 | 0.0205 / 0.0223 / 0.0238 | 0.021 / 0.0233 / 0.0216 | 0.0191 / 0.0211 / 0.0185 | 0.0159 / 0.0187 / 0.0167 | 0.0168 / 0.0165 / 0.0192 | 0.0173 / 0.0166 / 0.0183 |  |  |  |  |  |  |  |  |  |  |  |
| TOTAL cost per turn (USD, LLM + speech) | 0.0345 / 0.0328 / 0.034 | 0.0354 / 0.0323 / 0.0298 | 0.0398 / 0.0459 / 0.0343 | 0.028 / 0.0234 / 0.0283 | 0.0321 / 0.0276 / 0.0267 | 0.0263 / 0.029 / 0.0304 | 0.0277 / 0.0308 / 0.0279 | 0.0293 / 0.0305 / 0.0254 | 0.0238 / 0.0267 / 0.0213 | 0.0232 / 0.0217 / 0.0274 | 0.0262 / 0.0292 / 0.0265 | no clear change (2 of 3 outside) | clear: better | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | no clear change (2 of 3 outside) | clear: better | clear: better | clear: better | no clear change | no clear change |
| LLM cost per turn with cached-token discount (USD, where logged) | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 0.0033 / 0.0039 / 0.0035 | 0.004 / 0.0044 / 0.0036 | 0.005 / 0.0049 / 0.0039 | 0.0045 / 0.0043 / 0.0028 | 0.0036 / 0.003 / 0.0048 | 0.0049 / 0.0066 / 0.0045 |  |  |  |  |  |  |  |  |  |  |  |
| tutor seconds per turn (mean) | 24.6 / 18.5 / 28.1 | 21.2 / 17.6 / 20.1 | 39.4 / 46.2 / 35.5 | 15.2 / 13.1 / 14.4 | 16.0 / 15.9 / 14.0 | 16.6 / 19.7 / 18.6 | 19.4 / 23.0 / 18.4 | 20.2 / 21.1 / 19.1 | 22.1 / 21.1 / 53.6 | 21.2 / 16.0 / 26.3 | 22.6 / 33.7 / 24.4 | clear: worse | clear: better | clear: better | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |
| factual errors flagged | 8 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | n/a / n/a / 5 | n/a / n/a / 8 | n/a / n/a / n/a | n/a / n/a / n/a | no clear change | no clear change | no clear change | clear: better | no clear change |  |  |  |  |  |  |
|   of which major | 3 / 0 / 1 | n/a / n/a / n/a | 1 / 0 / 0 | 1 / 1 / 0 | 0 / 0 / 2 | 1 / 0 / 0 | 0 / 1 / 0 | n/a / n/a / 1 | n/a / n/a / 1 | n/a / n/a / n/a | n/a / n/a / n/a | no clear change | no clear change | no clear change | no clear change | no clear change |  |  |  |  |  |  |
|   model-only (not our bugs) | 7 / 6 / 7 | n/a / n/a / n/a | 7 / 6 / 3 | 6 / 6 / 5 | 7 / 3 / 7 | 4 / 4 / 3 | 8 / 6 / 2 | n/a / n/a / 5 | n/a / n/a / 8 | n/a / n/a / n/a | n/a / n/a / n/a | no clear change | no clear change | no clear change | clear: better | no clear change |  |  |  |  |  |  |
| replies describing what is not on the board | n/a / n/a / n/a | n/a / n/a / n/a | n/a / n/a / n/a | 36 / 37 / 28 | 33 / 26 / 29 | 38 / 50 / 37 | 47 / 32 / 35 | n/a / n/a / 10 | n/a / n/a / 7 | n/a / n/a / n/a | n/a / n/a / n/a |  |  |  |  |  |  |  |  |  |  |  |
| judge: statements describing content not on the board | 10 / 13 / 12 | 8 / 12 / 5 | 27 / 28 / 30 | 26 / 41 / 34 | 31 / 32 / 30 | 33 / 36 / 36 | 37 / 36 / 36 | 9 / 9 / 10 | 8 / 5 / 6 | 6 / 10 / 4 | 10 / 5 / 9 | clear: worse | clear: worse | clear: worse | clear: worse | clear: worse | no clear change | no clear change | no clear change | no clear change | no clear change | no clear change |

* the model was not logged before baseline F; the deployment 'gpt-4o-mini' serves gpt-4.1-mini and was last changed before baseline A (docs/BASELINE.md).

Against J's four targets: elements with no text 0 / 0 / 0% (**met**), retries 8 / 34 / 9 (run 2 **missed**: 34), overlapping pairs 10 / 5 / 6 (limit 4, **missed**, J 3 / 6 / 9),
hard failures 0 / 1 / 0 (**missed** in run 2: the maths topic returned an empty reply).

**Is anything worse than J?** By the rule fixed before the run (all three runs outside J's range on the bad side): **nothing is clearly worse**. In plain terms, on means and on single runs, it
is worse in these ways, and no better in any:

| | J | K |
|---|---|---|
| retries per run | 13 / 5 / 12 (mean 10) | 8 / 34 / 9 (mean 17; run 2 had 21 overlap rejections, 10 in one topic) |
| seconds per turn | 21.2 / 16.0 / 26.3 (mean 21.2) | 22.6 / 33.7 / 24.4 (mean 26.9, +27%) |
| prompt tokens per turn | 11.1k / 9.3k / 13.8k | 16.5k / 22.8k / 14.5k |
| model calls per turn | 3.1 / 2.6 / 3.3 | 3.8 / 4.5 / 3.6 |
| `modify_existing_element` calls per run | 1 / 0 / 1 | 22 / 15 / 15 |
| LLM cost per turn | $0.0064 / 0.0052 / 0.0082 | $0.0089 / 0.0126 / 0.0082 (total per turn mean $0.0241 -> $0.0273, +13%) |
| narrations starting "Here/This" (two of three runs worse) | 22 / 22 / 34% | 43 / 41 / 33% |
| distinct narration openers (two of three runs worse) | 69 / 71 / 59% | 45 / 62 / 56% |

**The cause is the text-width hint, and it does not pay.** It fired in 23 / 17 / 19 drawings per run; the tutor acted on it (modify calls up from about 1 to 15-22 per run, each one a model call with the
whole page in its context), unlike the older "no label" hint it never answered. But the boards did not get better: the share of elements whose final form still overflows (measured at the real browser width
factor 0.46) is 45% in K against 37% in J, and at the requested 0.55 it is 52% against 50%. The estimate over-estimates width by about 19%, so a part of what it flags fits, and a redraw there changes nothing.
**Recommendation (not done):** turn the hint off (one constant), or keep only the canvas-edge kind, or calibrate it to 0.46 and re-measure first.

**Unchanged by the new code:** text on the board (0% of elements without text), the lossless check (0 / 3 / 0% of drawings, one label lost in run 2 despite the note), the judge's
not-on-board count (10 / 5 / 9 against 6 / 10 / 4), marker mistakes (15 / 12 / 13% as written against 17 / 8 / 17%).

**Page summaries in the eval:** written 0 / 1 / 2 times (a summary is written only when the tutor opens a new page), no failure logged. **Control characters:** 12 in run 2's model text, now visible as
the placeholder on the board and reported to the tutor.


# Baseline L: the text-width hint off, the page summaries still on (rule and attribution fixed before the run)

L is K with one change: the text-width estimate is no longer shown to the tutor (`7b6a3d6`; it is written to the log as `text_width_note`). Everything else is K: the `font-size"20"` repair, the
lost-content note, the visible placeholder for control characters, the page summary on save and the changed context header. The system prompt and tool text are the E wording, frozen (digests
unchanged). Three runs of the 8-topic eval, cheap checks, the cheap-model judge and the lossless check; no Opus review unless something is worse than J by the rule below.

**What each pair of columns can attribute** (written before the run):

- **K minus L = the text-width hint**, and nothing else (the one other difference, the summary text in a log line, is invisible to the tutor). Any change from K to L that lies outside K's range on
  all three runs is the hint's doing: modify calls, retries, seconds, tokens, narration openers.
- **L minus J = four changes together**: the `font-size"20"` repair, the lost-content note, the placeholder for control characters, and the page summaries with the changed context header. The eval
  cannot separate them, and the summaries reach the tutor only when it opens a new page (0 / 1 / 2 times per run in K), so the effect of the summaries on the eval numbers is expected to be small.
  Any difference between L and J is therefore "the Phase 2 recording changes together", not a single cause.
- K minus J was the hint plus those four; L tells whether the hint was the whole of K's cost.

**"Worse than J"** (fixed now): for any row of the comparison table with a direction, all three L runs outside the range of J's three runs on the bad side (column "L vs J"); the means of the key rows
are stated as well, and so is anything worse in two of three runs. J's four targets are shown for reference: text 15% or less, retries 13 or fewer, overlapping pairs at most 4, hard failures 0.
Expected, written down before the run: seconds per turn and modify calls back near J (the hint was the cause of their rise); overflow on the final boards the same as K (the hint did not improve it).

## L results (three runs, `docs/baseline_L/`; code `f0425a4`)

Column "L" in `python tests/compare_baselines.py` (the table has the same rows as K's, plus "L vs J" and "L vs K"). Hint shown to the tutor: 0 times in every run; `text_width_note` written to the log: 47 times
(drawings with at least one estimated overflow: 47 of 113, 42%, so the offline measure still works). Lossless check: 0 / 0 / 0% of drawings lose anything (control characters: 3 in run 3, all shown as the placeholder).

| | J | K (hint on) | **L (hint off)** |
|---|---|---|---|
| retries per run | 13 / 5 / 12 (mean 10) | 8 / 34 / 9 (mean 17) | **6 / 9 / 5 (mean 6.7)** |
| seconds per turn | 21.2 / 16.0 / 26.3 (mean 21.2) | 22.6 / 33.7 / 24.4 (mean 26.9) | **18.9 / 21.4 / 23.1 (mean 21.1)** |
| prompt tokens per turn | 11.1k / 9.3k / 13.8k | 16.5k / 22.8k / 14.5k | **11.0k / 11.7k / 10.0k** |
| model calls per run | 50 / 41 / 53 | 61 / 72 / 57 | **48 / 51 / 45** |
| `modify_existing_element` calls per run | 1 / 0 / 1 | 22 / 15 / 15 | **0 / 0 / 2** |
| LLM cost per turn | $0.0064 / 0.0052 / 0.0082 | $0.0089 / 0.0126 / 0.0082 | **$0.0061 / 0.0065 / 0.0056** |
| total cost per turn (LLM + speech), mean | $0.0241 | $0.0273 | **$0.0248** |
| overlapping pairs on the boards | 3 / 6 / 9 | 10 / 5 / 6 | **4 / 3 / 6** |
| elements with no text | 0 / 0 / 0% | 0 / 0 / 0% | **0 / 0 / 0%** |

J's four targets, for reference: text 15% or less **met** (0 / 0 / 0%); retries 13 or fewer **met** (6 / 9 / 5); overlapping pairs at most 4: runs 1 and 2 **met** (4, 3), run 3 **missed** (6); hard failures 0: run 3
**missed** (1: the maths topic's second turn returned an HTTP 500 after 19.5 s; see "What the hard failures were" below).

### What L lets us attribute

- **K minus L = the text-width hint**, the only thing the tutor sees differently. Removing it brings back J's cost and speed: modify calls 15-22 -> 0-2 a run, model calls 57-72 -> 45-51, prompt tokens 14.5-22.8k -> 10.0-11.7k
  per turn, seconds per turn 26.9 -> 21.1 (mean), total cost per turn $0.0273 -> $0.0248. Against K, L is "clear: better" on LLM cost and total cost per turn and on retries in the worst topic, and 2 of 3 runs lower
  on retries (8 / 34 / 9 -> 6 / 9 / 5), seconds and overlapping pairs (10 / 5 / 6 -> 4 / 3 / 6). **The hint was the whole of K's extra cost.** It did not make the boards better (K's overlapping pairs and
  layouts are not better than L's).
- **L minus J = the four recording changes together** (`font-size"20"` repair, lost-content note, visible placeholder, page summaries with the new context header). On cost, seconds, retries and tokens L equals J or is below it
  (retries 6.7 against 10 on average; seconds 21.1 against 21.2; total cost $0.0248 against $0.0241), so those four changes cost nothing measurable. Summaries were written twice in the three runs (dense, runs 2 and 3), no failure.

### What is worse than J (by the rule fixed before the run: all three L runs outside J's range on the bad side)

| row | J | K | L | verdict L vs J |
|---|---|---|---|---|
| narrations with no valid marker, as the model wrote them | 17 / 8 / 17% | 15 / 12 / 13% | **39 / 29 / 40%** | **clear: worse** (and worse than K) |
| narrations that start with the same two words | 31 / 29 / 35% | 58 / 50 / 33% | **39 / 40 / 40%** | **clear: worse** (K is higher still) |
| judge: statements describing content not on the board | 6 / 10 / 4 | 10 / 5 / 9 | **12 / 15 / 9** | no clear change (2 of 3 outside) |

**These three cannot be attributed to the hint or to the recording changes.** The marker is written in the narration before any hint exists, K (hint on) wrote them as well as J (15 / 12 / 13%), and the code between K and L differs
only by the hint (`git diff 7bc45ca HEAD -- engine` shows the hint, the log-only note and the tool-call log). The repairs in L are 8 / 6 / 6 "format" (a single bracket or spaces inside the marker; J: 0, K: 0 / 2 / 3) and 9 / 8 / 10
"missing" (J: 7 / 3 / 8): the model's marker style drifted in these three runs. Three runs taken back to back share one service state, so I cannot separate "the service behaved differently today" from "no hint" with this data; I
can say that the code does not touch it. Stored narrations without a valid marker stay at 0% (the repair works), so the learner sees no difference.

**Opus review (triggered by the rule, run 3 only, as for H):** 2 factual errors, 1 major, 1 reply sentence describing something not on the board. Against H run 3 (8 / 1 major / 7) and D to G (28 to 47 not-on-board) that is the
lowest count of any reviewed run. The major error is a model slip in the dense topic (the board maps "OSI Application" to "TCP/IP Application" 1:1, which hides layers 5 and 6); the other is a garbled superscript in the
maths worked example (x^8 drawn with control characters, shown as the placeholder). So the explanations did not get worse by this reviewer's count. `docs/baseline_L/factual.json` has the numbers.

**Recommendation:** keep the hint off. If you want certainty about the markers, repeat L once (about $3 and 25 minutes) and see whether the as-written rate returns to 15%; I did not, because you asked for three runs.

### What the hard failures were (K run 2 and L run 3: not an empty reply, a bug of ours)

My K report called K run 2's failure "the maths topic returned an empty reply". That was wrong: the stored turn says "Internal Server Error" (HTTP 500), and L run 3 has the same failure at the same place (maths, turn 2, 19 s). In both the model drew a worked example whose
exponent came out as control characters, was told so by the lost-content note, and modified the element **twice in the same turn**. The tutor's loop keeps its own copy of the page and builds it from what the model wrote, not from what was stored. The first modify therefore replaced a
group that contained the model's raw text; the second looked up the old group in that copy, got text with a NUL character (code 0), and tried to store it as `old_svg_fragment`; Postgres refuses a NUL in a text column, and the request ended as a 500.
Reproduced in a scratch run: **any modify of an element drawn in the same turn does not reach the stored page** (the live board and the event log are right, `pages.current_svg` keeps the old drawing), and with a NUL in the drawing the same path fails on Postgres. This is fixed in its own commit (see "Fix: the loop's copy of the page is what was stored").

### Correction to the K analysis: the final boards, replayed from the stored events (`python tests/eval_final_form.py`)

In K I wrote that the redraws "did not make the boards better" and quoted 45% against 37% (browser width 0.46 em) and 52% against 50% (0.55 em) of elements whose final form overflows. Replaying the stored events (the element's last modify, else its draw; independent of `pages.current_svg`, so the same-turn modify bug
fixed in the L round does not touch it) gives, for elements with a label estimated wider than its card or the canvas:

| share of elements, 0.46 em (0.55 em) | run 1 | run 2 | run 3 | mean |
|---|---|---|---|---|
| J, as first drawn = final (no hint, 1 modify in 3 runs) | 34 (48) | 29 (40) | 41 (54) | 35 (47) |
| K, as first drawn | 64 (70) | 38 (47) | 47 (53) | 50 (57) |
| K, final form (after the hint-driven redraws) | 58 (67) | 26 (35) | 42 (47) | **42 (50)** |
| L, as first drawn = final (no hint) | 37 (50) | 28 (35) | 34 (37) | **33 (41)** |

So the earlier figures were not exact (that script is not in the repo), and the statement needs to be more careful: **inside K the redraws did lower the overflow, by 8 points (50% to 42% at 0.46 em), but the final boards were still no better than the runs that never saw the hint** (J 35%, L 33%); the K runs
simply drew more overflowing labels in the first place (50% against 33 to 35%), which the hint cannot cause because it comes after the drawing. The hint paid 15 to 22 extra model calls a run for those 8 points. Conclusion unchanged (keep it off), reasoning corrected.


# Baseline L2: L plus the L round's fixes, a repeat of L for the model (rule fixed before the run)

L2 is the code after the L round: the failed-turn handling (typed 503, `chat_turns.status`, Try again), the 60 s model timeout with one retry, control characters in client text, the tutor loop's copy of the page = what was stored, the page-summary boundary rule, the new summary instruction (what was taught, nothing about
what was not asked), and `EmptyReply`. System prompt and tool text unchanged (digests unchanged). Three runs of the 8-topic eval, cheap checks, the cheap-model judge and the lossless check; Opus review only under the rule below.

**What the tutor model sees, L against L2.** The system prompt, tool text, page state and history of every turn are the same as in L. What differs for the model: (1) the summary lines in the context block, which exist only when an earlier page was saved and summarised (the instruction and the boundary rule changed what they say; the eval's topics have two turns and the tutor opens a new page in the second one, so
the summary is written after the last turn and is almost never read: counted from the log after the run); (2) the loop's copy of the page used for the same-turn overlap and bounds checks now holds the stored text (the sanitised group with the font) instead of the raw text, so a same-turn check can differ in a rare case; (3) the 60 s timeout can cut the rare call that runs to the 6,000-token cap (4 of 2,146 logged calls).
So for the markers and the openers, which are written before any of this applies, **L2 is a repeat of L with the same inputs**. That is what makes it informative: if the marker rate and the same-opening-words rate come back toward J without any change in what the model reads, the L difference was run-to-run (service) variance, not our code.

**A result counts only if it is outside J's range** (the rule of K and L): for a row with a direction, all three L2 runs outside the range of J's three runs on the bad side (column "L2 vs J"); the same comparison of L2 against L is shown ("L2 vs L") to see what moved. Means of the key rows and rows worse in two of three runs are stated. Opus review of run 3 only if a row is **clearly worse than J** ("L2 vs J"), as for L.
**Questions to answer in the report:** (a) did the as-written marker rate (L 39 / 29 / 40%, J 17 / 8 / 17%) and the same-first-two-words rate of narrations (L 39 / 40 / 40%, J 31 / 29 / 35%) move back toward J, and what that does and does not tell us; (b) how many tutor turns had at least one prior-page summary in their context (counted from the structured log: a turn counts when
its notebook already had a `page_summarised` event before the turn started), so we know how much the summaries were really exercised; (c) J's four targets for reference (text 15% or less, retries 13 or fewer, overlapping pairs at most 4, hard failures 0).



## L2 results (three runs, `docs/baseline_L2/`; code `e382378`)

Column "L2" in `python tests/compare_baselines.py` (rows as before, plus "L2 vs J" and "L2 vs L"). Lossless check: 0 / 1 / 0 drawings of 30 / 37 / 38 lose something (run 2: one label, 15 characters; J: 0 / 1 / 0). Page summaries written 1 / 1 / 4, none failed.

| | J | L | **L2** |
|---|---|---|---|
| retries per run | 13 / 5 / 12 (mean 10) | 6 / 9 / 5 (mean 6.7) | **14 / 14 / 14 (mean 14)** |
| seconds per turn | 21.2 / 16.0 / 26.3 (mean 21.2) | 18.9 / 21.4 / 23.1 (mean 21.1) | **21.2 / 15.1 / 13.6 (mean 16.6)** |
| model calls per run | 50 / 41 / 53 | 48 / 51 / 45 | **70 / 57 / 56** |
| prompt tokens per turn | 11.1k / 9.3k / 13.8k | 11.0k / 11.7k / 10.0k | **28.6k / 14.1k / 12.9k** |
| LLM cost per turn | $0.0064 / 0.0052 / 0.0082 | $0.0061 / 0.0065 / 0.0056 | **$0.0147 / 0.0079 / 0.0069** |
| total cost per turn, mean | $0.0241 | $0.0248 | **$0.0276** |
| overlapping pairs on the boards | 3 / 6 / 9 | 4 / 3 / 6 | **2 / 3 / 4** |
| elements with no text | 0 / 0 / 0% | 0 / 0 / 0% | **0 / 0 / 0%** |
| elements whose final form overflows (0.46 em, `tests/eval_final_form.py`) | 34 / 29 / 41% | 37 / 28 / 34% | **30 / 24 / 32%** |
| narrations with no valid marker, as written | 17 / 8 / 17% | 39 / 29 / 40% | **16 / 31 / 37%** |
| narrations starting with the same two words | 31 / 29 / 35% | 39 / 40 / 40% | **33 / 38 / 32%** |
| distinct 3-word reply openers (of 16) | 13 / 9 / 9 | 9 / 8 / 9 | **12 / 11 / 10** |
| judge: statements describing content not on the board | 6 / 10 / 4 | 12 / 15 / 9 | **9 / 9 / 12** |

**J's four targets:** text 15% or less **met** (0 / 0 / 0%); retries 13 or fewer **missed in all three runs** (14 / 14 / 14); overlapping pairs at most 4 **met in all three** (2 / 3 / 4; J and L missed it in two runs and one); hard failures 0 **met** (0 / 0 / 0; L had one).

**Outside J's range on the bad side (the rule):** only the retries rows are **clear: worse** (14 in every run against J's 5 to 13; per turn 0.88 against 0.31 to 0.81). Retries are three different mixes that happen to sum to 14 (5 + 4 + 5, 4 + 5 + 5, 11 + 2 + 1: canvas bleeds, label overlaps, overlaps), the same kinds of rejection as in J and L, no new kind. Two of three outside, not clear: marker validity (below),
layout overlap between topics (0.377 / 0.326 / 0.329 against J 0.37 to 0.476, lower = more varied, so this is the better side). Seconds per turn are lower than J in two runs. **Against L** L2 is clear: worse on retries and LLM cost per turn, clear: better on the narration openers and the reply openers. The retries row triggered the Opus review of run 3.

### The marker rate and the opening-words rate: did they move back toward J?

- **Same opening words (narrations):** yes, back inside or at the edge of J's range (L2 33 / 38 / 32%; J 31 / 29 / 35%; L 39 / 40 / 40%). Reply openers too (12 / 11 / 10 distinct against J 13 / 9 / 9 and L 9 / 8 / 9). "Clear: better" than L.
- **Markers as written:** partly. L2 16 / 31 / 37% (mean 28%) between J (mean 14%) and L (mean 36%): run 1 is inside J's range, runs 2 and 3 are not (verdict against J: no clear change, 2 of 3 outside; against L: no clear change). The repairs behind it: "missing" (the model leaves the marker out) 4 / 13 / 7 (J 7 / 3 / 8, L 9 / 8 / 10) and "format" (a single bracket or spaces) 3 / 3 / 12 (J 0 / 0 / 0, L 8 / 6 / 6): both kinds swing widely from run to run.
- **What this does tell us.** L2 is a repeat of L for the model (same prompt, tool text, state and history; the summary lines that differ were read in 1 of 48 turns). The two rows that were **clearly** worse than J in L are **not** reproduced as clearly worse in L2: the opening-words rate is back, the marker rate is no longer clear. So L's finding was not stable, and it cannot be pinned on our code (between L and L2 nothing changed that the model reads before it writes a marker, and between K and L only the hint did). The same code and prompt gave 16% and 37% inside the single L2 session, a spread as large as the whole gap between J and L.
- **What it does not tell us.** Whether the service behaves differently on different days or at different times (J, K, L and L2 each ran in one window); whether J's 8 to 17% was itself a lucky draw (K 15 / 12 / 13 with the hint on, L2 run 1 at 16%, against L and L2 runs 2 and 3 at 29 to 40%); or whether a real, smaller rise remains (the mean 28% is above J's 14%). Three runs of 8 topics cannot resolve a difference of that size when the same condition varies by 20 points. It would take a larger sample, or an interleaved design (conditions alternated within one session), to say more.

### How much the summaries were really exercised

Counted from the structured log: a turn counts when its notebook already had a `page_summarised` event before the turn started. **L2: 1 of 48 tutor turns** (run 3, the only run in which the tutor opened pages more than once: 4 summaries written). **K: 0 of 48, L: 0 of 48.** The reason is structural: each eval topic has two turns, the tutor opens the new page *in* turn 2, and the summary of the old page is written at that moment, after the last turn. So the summaries, their boundary rule and their new instruction have been checked as text (8 pages read, 3 fixture pages, the replay of the real conversation) but
**almost never read by the tutor in an eval**. To exercise them the eval would need a third turn after a page change (not done).

### A new finding: the lost-content note can start a redraw loop (maths, run 1)

L2 run 1 has 20 `modify_existing_element` calls and 70 model calls (J 50, L 48), all in the maths topic: the worked example `derivative_example` was redrawn **19 times** in turn 2. Each redraw again had the exponent or arrow written as a control character (20 replaced, 23 lost-content notes in the log), the note told the tutor to redraw it with a real character, and the model did not. The loop ended at the 20-iteration limit; the learner read the canned
"I've drawn quite a bit on this page. Let me know if you'd like to continue on a new page ..." (80.6 s for the turn), and the element on the board still carries 5 placeholders ("lim h �10 ..."). That one topic is the whole of run 1's extra cost (457k prompt tokens against about 180k, LLM cost per turn $0.0147 against about $0.007) and the "hard failures 0" of the eval does not see it, because the canned reply counts as an answer.
The same slip appears in the Opus review of run 3 (the biology formula "C6H12O6" drawn with control characters, 2 errors). **Proposals, not done:** (1) tell the tutor about a lost character at most twice per element per turn, and after that leave the placeholder (the note's cost is now a loop; the earlier 500 was the other face of the same problem); (2) count the iteration-limit reply as a failed turn in the eval and in the app (it is neither an answer nor an error today).

### Opus review of run 3 (triggered by the retries rule)

4 factual errors, 1 major, 3 not-on-board items (L run 3: 2 / 1 / 1; H run 3: 8 / 1 / 7; D to G: 28 to 47 not-on-board). The major one is the same dense-topic slip as in L ("OSI Application = TCP/IP Application", which leaves presentation and session unmapped). Two errors are the biology board garble (control characters where the subscripts of C6H12O6 and O2 belong), one minor (coax and fibre called protocols). Not-on-board: two biology sentences naming carbon dioxide and water, which are not on that board, and an economics title narration that describes a demand shift the page did not show.
`docs/baseline_L2/factual.json`. Within the range of the reviewed runs, a little above L.

### Conclusion

- The L-round fixes cost nothing for the model: L2 equals J on text, overlap pairs (better), seconds (lower), final-form overflow (lower) and lossless. What is worse than J is the retry count by one run-length (14 against 13), and one topic's redraw loop that explains the cost outlier.
- The L marker and opening-word findings do not reproduce clearly; they were not caused by the code, and their cause is not settled.
- The hint stays off; the summaries are correct as text but unexercised by the eval.


# Eval M: do the page summaries help? (design and rule, fixed before the run)

`tests/eval_multipage.py`. Three topics that open a **second page** (binary search, photosynthesis, supply and demand), **three turns each**; turn 2 asks for a new page, turn 3 is the same neutral sentence for every topic and says nothing about what was covered: *"Now build on what we covered earlier."* (If the tutor does not open the second page in turn 2 the harness does what the learner's "New page" button does, and the run records it as `forced_page`.)
The summary of page 1 is written at that moment, so it is in the tutor's context for turn 3 and for no earlier turn. Each run is judged by the cheap model on the third answer against what page 1 held (verdicts: correct and specific, correct but general, wrong, no reference); the third answers themselves are printed to be read.

**Conditions** (2 runs each, interleaved so a drift in the service falls on all of them: on, off, on, off):
- **on15**: summaries in context, history window 15 (the product as it is). **off15**: the same with `LP_TEST_SUMMARIES_OFF=1` (page titles stay, every summary reads "No summary."), a test-only environment flag, default on (`backend/page_state.py`). These two are what was asked for.
- **on2 / off2** (an addition, not requested): the same with `LP_TEST_HISTORY_TURNS=2`, a test-only flag (default 15), so the earlier page is **not** in the history. **Why:** with a 15-turn window and three turns, the learner's question and the tutor's reply about page 1 are in the prompt in both settings, which can hide the effect of the summary. In on2/off2 the summary (or only the title) is all the tutor has of page 1's details.
- Every turn logs `context_built` (earlier pages, how many show a summary, history turns, both flags), which is where "turns with a prior-page summary in context" comes from.

**Expectation, written before the run.** on15 against off15: no clear difference in the third answers (the history carries page 1). on2 against off2: if the summaries are worth anything it shows here, in the share of "correct and specific" answers. Seconds and cost: the summary adds a few hundred prompt tokens to one turn per scenario, no measurable change expected.
**A result counts only if outside the run-to-run range:** the two runs of a condition give its range for each measure (turns with a summary, third answers judged correct and specific out of 3, seconds per turn, total cost per turn); a difference between two conditions counts only when their ranges do not overlap. Two runs is a small sample, so the report says so where ranges are wide.


## M results (eight runs, `docs/baseline_M/`; code `d378740`)

Order of the runs: on15, off15, on15, off15, on2, off2, on2, off2 (interleaved). 3 topics x 3 turns = 9 turns per run, 72 turns in all, no failed turn, no iteration limit, no forced page (the tutor opened the second page in turn 2 every time).

| condition | run | turns with a prior-page summary in context (of 9) | third answers by the cheap judge: correct+specific / correct but general / wrong / no reference | s per turn | total cost per turn | model calls |
|---|---|---|---|---|---|---|
| on15 | 1 | 3 | 3 / 0 / 0 / 0 | 17.7 | $0.0263 | 41 |
| on15 | 2 | 3 | 3 / 0 / 0 / 0 | 14.8 | $0.0207 | 29 |
| off15 | 1 | 0 | 2 / 0 / 1 / 0 | 16.8 | $0.0270 | 31 |
| off15 | 2 | 0 | 3 / 0 / 0 / 0 | 13.4 | $0.0253 | 28 |
| on2 | 1 | 3 | 3 / 0 / 0 / 0 | 14.1 | $0.0243 | 26 |
| on2 | 2 | 3 | 3 / 0 / 0 / 0 | 17.6 | $0.0263 | 32 |
| off2 | 1 | 0 | 3 / 0 / 0 / 0 | 19.3 | $0.0318 | 54 |
| off2 | 2 | 0 | 3 / 0 / 0 / 0 | 18.4 | $0.0316 | 40 |

(on2 / off2 = the history window shrunk to 2 turns, the addition explained above.)

**1. Turns with a prior-page summary in context.** 3 of 9 in every "on" run and 0 of 9 in every "off" run, read from the `context_built` event (flags confirmed per run): exactly the third turn of each scenario, which is the only turn that has an earlier page. In the old 8-topic eval it was 1 of 48 turns (L2) and 0 of 48 (K, L).

**2. Does the third answer refer correctly to the earlier page?** By the rule (ranges of two runs): **no clear difference** in either window (on15 3..3 against off15 2..3 correct-and-specific answers; on2 3..3 against off2 3..3).
The judge is too lenient to carry this, though. It called 23 of 24 third answers "correct and specific", including answers that contain nothing from page 1. So I read the six answers of the primary comparison myself (first run of on15 and off15; full texts in the output of `python tests/eval_multipage.py report docs/baseline_M`):

| | page 1 held | the third answer says | my reading |
|---|---|---|---|
| on15, binary search | sorted array 2 5 8 12 16 23 38 56 72 91, five steps | redraws the halving "on 1000 elements, middle at index 500, discard the left half, next middle 750" | continues the page-2 request; does not use page 1's array; accurate binary search. General, not specific (the judge said specific) |
| on15, photosynthesis | chloroplast, sunlight, CO2, water, glucose C6H12O6 | a diagram of the process inside the chloroplast, sunlight, water and CO2 turned into glucose; an arrow from the "energy and materials" diagram | refers to page 1's chloroplast and glucose accurately: specific |
| on15, supply and demand | only a title and the axes | a graph with D, D' (shifted right), S and two equilibrium points | continues the page-2 request; page 1 had little to build on. General |
| off15, binary search | sorted array 2 5 8 12 ... 91, Low/Mid/High | "a sorted array of 10 numbers ... find 13 ... the middle element is 9 at index 4" | a different array from page 1's: **wrong about page 1** (judge: wrong; I agree). The on15 answer also ignored page 1's array but made no claim about it |
| off15, photosynthesis | process, chlorophyll, glucose, steps | sunlight, CO2 and water enter the chloroplast, glucose and oxygen come out; "highlighted the energy and material sources from the previous diagram" | accurate, uses page 1's terms: specific |
| off15, supply and demand | demand curve, supply curve, market equilibrium | a new page "Combined Effects": supply and demand curves and two equilibrium points | accurate, general |

An objective proxy that needs no judge: the number of **page-1-only terms** (words and numbers on page 1 that are neither in the learner's messages nor on page 2) the third answer reuses, per scenario: on15 mean 6.2 against off15 8.3; on2 5.5 against off2 3.0. The direction flips between the two windows and the per-run totals overlap (on2 10 to 23, off2 5 to 13): not outside the run-to-run range.

**3. Cost and seconds.** on15 against off15: overlapping ranges, no difference (14.8 to 17.7 s against 13.4 to 16.8 s; $0.0207 to 0.0263 against $0.0253 to 0.0270). on2 against off2: **outside the run-to-run range** by the rule, and in the *wrong direction* for a cost of the summary: off2 is slower (18.4 to 19.3 s against 14.1 to 17.6 s) and dearer ($0.0316 to 0.0318 against $0.0243 to 0.0263). The summary adds a few hundred prompt tokens to
one turn per scenario; what differs is the number of model calls (off2 54 and 40, on2 26 and 32), i.e. how much the tutor drew and redrew in these runs. So this is chance with two runs per condition, not an effect of the summary, and the rule's range is too narrow to say otherwise.

### What eval M does and does not show

- The summaries reach the tutor exactly where they should (3 of 9 turns per run), at no measurable cost.
- It shows **no benefit and no harm** in the third answer, in either window. But the scenario cannot detect a benefit: the neutral third message is answered by continuing the live request (the page-2 task), which does not need page 1 at all, and the answers draw a fresh example instead of reusing page 1's (binary search twice). Where page 1 had content to build on (photosynthesis) both settings used it.
- **To measure value the third turn would have to depend on a detail of the earlier page** (for instance "use the same example as before"), which breaks the "no hint" rule, or the notebook would have to be long enough that the earlier page has left the 15-turn history. The history-2 conditions were meant to approximate that; the answers there were no worse without the summary (the tutor kept to the page-2 request).
- The cheap judge needs a stricter rubric (a detail that appears only on page 1) before it is used again.
