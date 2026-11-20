# Controlled benchmark: the current drawing model against Gemini 3.8 Flash and Gemini 4 Argon (2026-10-15)

Isolated benchmark and documentation only. No production prompt, tool text, drawing logic, validator, runtime behaviour, model setting or deployment was changed, no production data was read or written, and no realtime model was used. This follows the smaller first benchmark (`docs/BENCHMARK_MODELS.md`), whose results were too thin to decide anything. All evidence is in `docs/benchmark_runs/2026-10-15-controlled/` (run files, screenshots, review sheet, scripts). Every quality verdict is mine, by eye, on the screenshots; you can override any of them in the review sheet (`benchmark_runs/2026-10-15-controlled/review_sheet.html`), and the totals recompute.

## 0. Findings in short
- **The production model is not "mini".** The board is written by Azure deployment `gpt-4.1`, which serves `gpt-4.1-2025-04-14` (section 1). Both Gemini names are real model IDs on your key.
- **13 prompts, 3 models, 39 attempts, same pipeline.** Usable diagrams: **gpt-4.1 0 of 13, Gemini 3.8 Flash 3 of 13, Gemini 4 Argon 7 of 13.** Only the Argon-against-gpt-4.1 difference is clearly more than chance (exact test p = 0.005); Argon against Flash (p = 0.23) and Flash against gpt-4.1 (p = 0.22) are not separable with this sample.
- **gpt-4.1 is fast, cheap and never failed, but its boards are rarely right:** one drawing per answer, first drawing at about 14 s, $0.03 per attempt, and only 5 of 13 boards were structurally sound (complete, arrows not failed).
- **Argon draws the best boards but is not reliable under today's production limits.** Of the 9 boards it drew, 7 were usable and 2 were perfect (mean 6.8 of 8 points). But 5 of 13 attempts failed outright (the app's own 60 s request timeout, 1 retry, and 90 s ceiling), and the first drawing appears after a median of 55 s.
- **Flash sits between:** 11 boards drawn, mostly complete (10 of 11), but label and overlap defects keep most of them from being usable (3 of 13). 2 attempts failed because the 6000-token output cap was used up by thinking with nothing left to show.
- **A separate production finding:** the hand-drawn renderer drops arrowheads on `<line>` elements; about half of all arrowheads the models asked for never appeared on screen, for all three models (section 6). It does not change the ranking.
- **Spend:** $3.36 estimated ($4.20 with the 25% safety padding) of the $5 cap. No budget stop.
- **Recommendation: keep `gpt-4.1` in production for now, and investigate one candidate further: `gemini-4-argon`** (section 9). The evidence does not support switching to either Gemini model as configured.

## 1. Verified model IDs and benchmark configuration
| Configuration | Provider | Name in the project | What the service reports | How it was verified |
|---|---|---|---|---|
| **Baseline (production)** | Azure OpenAI | deployment `gpt-4.1` (`AZURE_OPENAI_DEPLOYMENT=gpt-4.1` in `.env`; `AZURE_OPENAI_AUTHOR_DEPLOYMENT` unset, so the board author, the eval judge and the page summaries all use it; `engine/author.py` lines 55-58) | model `gpt-4.1-2025-04-14` | a live call through the production client today; the 14 Oct production log (7 logged model calls: `model gpt-4.1-2025-04-14`, `deployment gpt-4.1`); the resource's deployment list holds only `gpt-4.1` and `text-embedding-3-small` |
| **Candidate Flash** | Google Gemini API, OpenAI-compatible endpoint | `gemini-3.8-flash` | `models.get`: "Gemini 3.8 Flash", 1,048,576 input / 65,536 output tokens, thinking on; the chat reply reports model `gemini-3.8-flash`; listed in both model lists | free metadata calls plus one tiny chat call |
| **Candidate Argon** | same | `gemini-4-argon` | `models.get`: "Gemini 4 Argon", 1,048,576 input / 32,768 output tokens, thinking on; the chat reply reports model `gemini-4-argon` | same |

Raw output: `benchmark_runs/2026-10-15-controlled/verify_models.json`.
- **The "GPT-4.1 mini" discrepancy.** It is real history: `docs/BASELINE.md` baselines A to G (4 to 9 Oct) ran on a deployment called `gpt-4o-mini` that served `gpt-4.1-mini-2025-04-14`. That deployment no longer exists on the resource (a call returns 404 `DeploymentNotFound`, as do `gpt-4.1-mini` and `gpt-35-turbo-16k`). `.env` now points at `gpt-4.1`, and the production log of 14 Oct shows `gpt-4.1-2025-04-14`. So the baseline here is the full GPT-4.1, which is what production uses today. A mini configuration cannot be accessed, so it was **not** tested and not substituted.
- **The Gemini IDs** are what Google's API returns for your key; the API gives no fuller description (both show version "3.0" and repeat their name as description). Prices come from the list prices read in the earlier research, not from the API, and billing was estimated, not read from an invoice.
- **Settings, identical for all three** (production values): temperature 0.7, `max_tokens` 6000, `tool_choice` auto, the unchanged system prompt, tools, canvas, renderer and overlap/geometry checks, the app's own limits (60 s request timeout with one retry, 90 s ceiling per model call), Gemini thinking left at its default. Page summaries off, speech synthesis faked (so "first drawing" excludes speech time), shadow hook off, one scratch database and log per model (production files untouched; the natural log's size and time stamp were checked unchanged).
- **How the runs were made.** Each prompt went to the real chat route (`POST /api/notebooks/{id}/chat`) of the production app, once per model, with the three models running at the same time on the same prompt (same hour, same load). One attempt per prompt per model, no retries, no prompt tuning. Prompt order was a seeded shuffle (seed 20261015): A2 D1 B1 C1 C2 A1 E1 D2 E2 B2, then the three extras C3 B3 A3 (section 2), run only because the first ten finished at $3.38 of the $5 cap.
- **Budget control.** Every call was checked against the combined $5 cap before it was made (padded estimate, with room for the other calls in flight); a model call that timed out without a usage report is charged at its worst-case cost, because the provider may still bill it (section 7).

## 2. The prompts
13 prompts in five categories, sent word for word to every model (full text in section 11). The first ten were written before any run of this experiment (B1 and C1 are the first benchmark's two prompts, reused for continuity). The last three (A3, B3, C3) were written after the first five rounds had come in, before their own runs, and were chosen to fill the thinnest categories rather than for any model's results; they ran only because the first ten finished with budget to spare.

| order | id | category | title | what it stresses |
|---|---|---|---|---|
| 1 | A2 | simple concept | Simple electric circuit | closed loop of three parts, current direction |
| 2 | D1 | text-heavy | Scientific method | four long exact labels, a loop-back arrow with a label |
| 3 | B1 | flowchart | Browser opens a website | decision with two paths that rejoin, labelled paths |
| 4 | C1 | architecture | Six-component web application | six components, forward request and return response |
| 5 | C2 | architecture | Job queue with workers | fan-out to three workers and fan-in to a database |
| 6 | A1 | simple concept | Water cycle | loop of four stages, directional arrows |
| 7 | E1 | complex | CI/CD pipeline | eight steps, two labelled branches, a return path |
| 8 | D2 | text-heavy | Three database types | heading and three cards of long exact text, no connectors |
| 9 | E2 | complex | Photosynthesis with labelled arrows | six parts and five arrows, each with a long exact label |
| 10 | B2 | flowchart | Bug fix lifecycle | decision with a loop back, Pass/Fail labels |
| 11 | C3 | architecture | Load-balanced site with cache | load balancer, two servers, each wired to cache and database |
| 12 | B3 | flowchart | Login with retry | decision with a retry loop, Correct/Wrong labels |
| 13 | A3 | simple concept | Food chain | five-step chain with arrows |


## 3. Quality rubric (applied to every board)
Each criterion is scored pass = 2, minor = 1, fail = 0 (so 0 to 8). **A board is usable if no criterion is fail.** A model's own claim of completeness counts for nothing.
- **Complete (follows the prompt):** every required part and connection is on one canvas. minor = only an optional detail is missing; fail = a required part or connection is missing or the content is wrong.
- **Arrows:** every required arrow joins the right two shapes, points the right way and has a visible head. minor = some heads missing or hard to see but the direction is still clear; fail = wrong shapes, wrong direction, detached, or no heads on the main flow.
- **Labels:** readable, inside their shape (or beside their arrow), not overlapping other text. minor = touches a border but fully readable; fail = text spills out of its shape, is clipped, or is covered by a line or another shape.
- **Collisions:** no shape or connector runs through another shape's text or body. minor = a line grazes a box edge or two lines cross; fail = a line or shape runs through text or a box, or shapes hide each other.
A run where nothing was drawn scores 0. Boards were looked at as the real frontend renders them (hand-drawn style), as screenshots.

## 4. Results
| | gpt-4.1 | gemini-3.8-flash | gemini-4-argon |
|---|---|---|---|
| attempts (13 prompts x 1 run) | 13 | 13 | 13 |
| finished without an app error (HTTP 200) | 13 of 13 | 11 of 13 | 8 of 13 |
| boards with something drawn | 13 | 11 | 9 |
| **usable diagrams** (no criterion = fail) | **0 of 13** (0%) | **3 of 13** (23%) | **7 of 13** (54%) |
| usable and the turn also finished cleanly | 0 | 3 | 6 |
| clean boards (8 of 8 points) | 0 | 0 | 2 |
| mean quality score, all attempts (0-8; no board = 0) | 2.92 | 4.15 | 4.69 |
| mean quality score, boards that were drawn | 2.92 | 4.91 | 6.78 |
| complete / arrows / labels / collisions = pass (of drawn boards) | 6 / 1 / 2 / 3 of 13 | 10 / 5 / 3 / 5 of 11 | 9 / 6 / 4 / 9 of 9 |
| complete / arrows / labels / collisions = fail (of drawn boards) | 1 / 8 / 10 / 7 of 13 | 0 / 2 / 7 / 4 of 11 | 0 / 1 / 2 / 0 of 9 |
| time to first visible drawing, median (p90, max) | 13.8 s (16.2, 21.6) | 20.3 s (35.5, 48.1) | 55.2 s (61.1, 61.9) |
| total completion time, median (max) | 16.7 s (24.4) | 90.6 s (150.4) | 122.1 s (226.3) |
| model calls / drawing calls | 33 / 20 | 97 / 73 | 41 / 69 |
| drawing calls rejected by the app's checks | 6 (30%) | 8 (11%) | 10 (14%) |
| re-drawn after a rejection / element ids drawn twice | 2 / 5 | 4 / 5 | 1 / 1 |
| invalid tool calls (from the call log) | 0 (13 runs with a call log) | 0 (11 runs with a call log) | 0 (9 runs with a call log) |
| incomplete outputs (6000-token cap reached) / failed model calls | 0 / 0 | 2 / 0 | 3 / 3 |
| estimated cost, all 13 attempts (raw / padded x1.25) | $0.37 / $0.47 | $1.24 / $1.55 | $1.74 / $2.18 |
| estimated cost per attempt (raw) | $0.029 | $0.095 | $0.134 |
| estimated cost per usable diagram (raw / padded) | none usable | $0.41 / $0.52 | $0.25 / $0.31 |
| offline shadow validator would reject (drawings) | 8 of 14 | 16 of 67 | 14 of 67 |


Usable diagrams by category (prompts in brackets; each cell is one run per prompt, so these are small numbers):

| category (prompts) | gpt-4.1 | gemini-3.8-flash | gemini-4-argon |
|---|---|---|---|
| architecture (3) | 0 of 3 | 1 of 3 | 2 of 3 |
| complex (2) | 0 of 2 | 0 of 2 | 1 of 2 |
| flowchart (3) | 0 of 3 | 0 of 3 | 1 of 3 |
| simple concept (3) | 0 of 3 | 1 of 3 | 1 of 3 |
| text-heavy (2) | 0 of 2 | 1 of 2 | 2 of 2 |


Per prompt, in run order (score out of 8; "usable" = no criterion failed):

| order | prompt | category | gpt-4.1 | gemini-3.8-flash | gemini-4-argon |
|---|---|---|---|---|---|
| 1 | A2 Simple electric circuit | simple concept | 3/8 | 6/8 **usable** | FAILED, nothing drawn |
| 2 | D1 Scientific method | text-heavy | 4/8 | 6/8 **usable** | 8/8 **usable** |
| 3 | B1 Browser opens a website | flowchart | 2/8 | 5/8 | 6/8 |
| 4 | C1 Six-component web application | architecture | 2/8 | FAILED, nothing drawn | 4/8 |
| 5 | C2 Job queue with workers | architecture | 1/8 | 7/8 **usable** | 7/8 **usable** |
| 6 | A1 Water cycle | simple concept | 2/8 | 4/8 | FAILED, nothing drawn |
| 7 | E1 CI/CD pipeline | complex | 2/8 | 4/8 | FAILED, nothing drawn |
| 8 | D2 Three database types | text-heavy | 6/8 | FAILED, nothing drawn | 7/8 **usable** (turn failed) |
| 9 | E2 Photosynthesis with labelled arrows | complex | 3/8 | 6/8 | 7/8 **usable** |
| 10 | B2 Bug fix lifecycle | flowchart | 3/8 | 3/8 | FAILED, nothing drawn |
| 11 | C3 Load-balanced site with cache | architecture | 2/8 | 3/8 | 7/8 **usable** |
| 12 | B3 Login with retry | flowchart | 3/8 | 6/8 | 7/8 **usable** |
| 13 | A3 Food chain | simple concept | 5/8 | 4/8 | 8/8 **usable** |


What the numbers say:
- **Quality:** Argon is clearly ahead on boards it manages to draw (mean 6.8 of 8 against 4.9 for Flash and 2.9 for gpt-4.1). Counting only usable diagrams, 7 of 13 against 3 and 0. With a looser view, boards that are at least structurally sound (complete, arrows not failed) were 5 of 13 for gpt-4.1, 9 of 13 for Flash and 8 of 13 for Argon: Flash gets the structure about as right as Argon but leaves more label and overlap defects.
- **What gpt-4.1 does:** one drawing per answer (1 to 2), so it answers in 14 s, but the single drawing is the whole board in one go, and most of them have text running out of boxes, lines through text, or connectors without heads. 8 of its 13 boards have an arrows fail and 10 a labels fail.
- **What the Gemini models do:** they build the board in several elements (Flash 3 to 9, Argon 5 to 13) with titles, legends and explanation panels, usually more than the prompt asked for. Flash does this over many small model calls (about 7.5 per run; 97 in all); Argon drafts most of the board in one or two very large calls (41 in all, median 2 per run): when it answers in time, that first call takes 44 to 62 s, and sometimes much longer.
- **Latency:** the first drawing appears after a median of 13.8 s for gpt-4.1, 20.3 s for Flash and 55.2 s for Argon. Total time for answers that finished is similar for the two Gemini models (about 92 to 96 s median) and about 17 s for gpt-4.1.
- **Argon's median first drawing (55 s) sits just under the app's 60 s request timeout.** That is why it fails so often as configured (section 5), and a failed request makes the learner wait about two minutes (the app retries once) before an error.
- **Tool use:** no invalid tool calls in any run that left a call log (every run that drew something did). Rejections by the app's own checks: gpt-4.1 30% of its drawing calls, Flash 11%, Argon 14%; re-draws accepted under the same element id after a rejection were 2, 4 and 1 (a re-draw under a new id is not counted).
- **Models' own claims are not evidence:** every one of the 11 HTTP-200 boards that failed on completeness or arrows (8 gpt-4.1, 2 Flash, 1 Argon) ended with a normal closing message that describes the board as if it were right (for example "Here is the complete flowchart showing how a website login works" for a board whose forward connectors had no arrowheads).

## 5. Failures and incomplete outputs (all kept, none excluded)
| run | what happened |
|---|---|
| C1 gemini-3.8-flash | HTTP 503 after 55 s, 0 drawing(s) saved: the 6000-token output cap was used up (thinking) with no visible output |
| D2 gemini-3.8-flash | HTTP 503 after 43 s, 0 drawing(s) saved: the 6000-token output cap was used up (thinking) with no visible output |
| A1 gemini-4-argon | HTTP 503 after 112 s, 0 drawing(s) saved: a model call took 112 s, past the app's 90 s ceiling (the turn was ended) |
| A2 gemini-4-argon | HTTP 503 after 122 s, 0 drawing(s) saved: no answer within the app's request timeout (60 s, 1 retry): the call ended after 122 s |
| B2 gemini-4-argon | HTTP 503 after 125 s, 0 drawing(s) saved: no answer within the app's request timeout (60 s, 1 retry): the call ended after 125 s |
| D2 gemini-4-argon | HTTP 503 after 161 s, 5 drawing(s) saved: a model call took 113 s, past the app's 90 s ceiling (the turn was ended) |
| E1 gemini-4-argon | HTTP 503 after 123 s, 0 drawing(s) saved: no answer within the app's request timeout (60 s, 1 retry): the call ended after 123 s |


- Flash: both failures are the same mechanism: the first call spent the whole 6000-token output cap on thinking (finish reason `length`, no visible output), and the app reported an empty reply.
- Argon: three requests got no answer inside the app's request timeout (60 s, plus one retry); in A1 the call did return, but after 112 s, past the 90 s ceiling; in D2 five drawings were saved from the first call and the second call took 113 s, past the ceiling, so the learner would see a complete board followed by an error (that board is counted as usable, but the turn did not finish cleanly).
- Argon also used the whole 6000-token cap on the first call in three runs that still drew (C1, C2, C3); the app drew what it had parsed (scores 4, 7 and 7 of 8).
- These limits (60 s, 90 s, 6000 tokens) are today's production values; I did not change them, so the failures are failures of "this model in this app as configured", not necessarily of the model.

## 6. What the review found
- **Arrowheads on `<line>` elements never reach the screen.** The renderer (`frontend/src/services/roughRenderer.ts`, the `line` branch around lines 93-98) rebuilds a `<line>` from its end points and stroke only, so `marker-end` (and `stroke-dasharray`) are dropped; a `<path>` is passed through unchanged and keeps its head. Counting the SVG each model wrote:

| model | arrowheads requested on a path (shown) | arrowheads requested on a line (dropped by the renderer) | runs with at least one dropped head |
|---|---|---|---|
| gpt-4.1 | 27 | 33 | 6 of 13 |
| gemini-3.8-flash | 13 | 14 | 4 of 13 |
| gemini-4-argon | 12 | 13 | 3 of 13 |


  That is about half of every model's requested arrowheads, so many "arrows" verdicts for all three models are partly the renderer's doing. If those heads were shown, at most one more board per model would pass on arrows alone (gpt-4.1 A3, Flash B3), so the ranking would not change (0/13 to 1/13, 3/13 to 4/13, 7/13 unchanged). That estimate is inferred from the SVG, not re-rendered. Not changed in this benchmark.
  **Update (fixed afterwards):** `roughRenderer.ts` now leaves a `<line>` that carries a marker as written (as a `<path>` arrow already was) and passes `stroke-dasharray` on to Rough.js; regression tests are in `tests/test_rough_renderer_markers.py`. All 33 boards were re-rendered from the saved drawings with the fixed renderer (13 had dropped arrowheads); those re-rendered screenshots are kept locally and are not part of the repository. The verdicts, scores and numbers in this report were made on the old renders and were not re-judged or changed.
- **A dark rule through the title text** (a header band's line drawn across its own heading) ruins the labels on two Flash boards (A1 water cycle, E1 pipeline) even though their structure is right.
- **Text wider than its shape** (diamond labels, long card lines, connector labels) was the commonest labels fail for all three models.
- **Extra content:** the Gemini boards usually add title banners, side panels and legends that were not asked for ("simple" prompts included); gpt-4.1 mostly does not. I did not penalise this unless it overflowed or collided.
- **The shadow validator as a signal:**

| my collisions verdict | boards | boards the shadow validator flagged (any drawing it would reject, or a rejecting collision on the final page) |
|---|---|---|
| fail | 11 | 8 |
| minor | 5 | 3 |
| pass | 17 | 12 |


| model | boards drawn | boards flagged by the shadow validator | drawings it would reject |
|---|---|---|---|
| gpt-4.1 | 13 | 8 | 8 of 14 |
| gemini-3.8-flash | 11 | 8 | 16 of 67 |
| gemini-4-argon | 9 | 7 | 14 of 67 |


  It flagged about 70% of boards whatever my collisions verdict was (8 of 11 with a collision fail, 12 of 17 with none), so on this sample it does not separate clean boards from colliding ones; more than half of its flags are "connector through a shape that is not one of its ends" (52 of the 89 rejecting collisions on final pages), which long connectors across busy boards trigger often. It was shown next to each run and not used to judge.

## 7. Cost
| item | raw estimate | padded estimate (x1.25) |
|---|---|---|
| gemini-3.8-flash | $1.240 | $1.550 |
| gemini-4-argon | $1.744 | $2.180 |
| gpt-4.1 | $0.373 | $0.466 |
| verification calls (model identity checks) | $0.000 | $0.000 |
| **total** | **$3.358** | **$4.197** |


- Prices (USD per 1M tokens, list prices as used in the first benchmark): gpt-4.1 $2 in / $8 out with no cached-input discount assumed (so this errs high), Flash $0.75 / $3.75, Argon $2 / $10, thinking tokens counted as output. The earlier research quoted both Gemini prices as rising later this year (Argon on 1 Dec 2026, Flash after 31 Dec 2026); re-check before any budget decision.
- "Raw" is tokens times those prices; "padded" is raw times 1.25, and the cap was enforced on the padded figure. The raw total includes a worst-case charge of $0.41 raw ($0.51 padded) for three Argon requests that timed out without a usage report (A2, B2, E1), because Google may still bill them. These are estimates, not an invoice.
- Estimate before the run: about $4.7 padded for ten prompts (from the first benchmark's per-attempt costs). Actual for the first ten: $3.38 padded; the three extra prompts added $0.81.
- Per attempt (raw): gpt-4.1 $0.029, Flash $0.095, Argon $0.134. Per usable diagram (raw): Flash $0.41, Argon $0.25; none for gpt-4.1.

## 8. Limitations
- One run per prompt per model, 13 prompts: category cells are 2 to 3 runs, so only the headline counts mean anything. p-values are two-sided exact (Fisher) tests on the usable counts.
- One reviewer, and it is an AI model looking at screenshots (no human review, no vision-model judge). The rubric is strict: a single covered letter or a line through a label makes a board unusable, which is why usable counts are low for everyone; the "structurally sound" counts are given as the looser view. **Blinding was imperfect:** boards were reviewed under random codes, but I printed the code-to-model map by mistake before reviewing the six boards of B1 and C1, boards where nothing was drawn identified themselves, and the drawing styles differ by model.
- This is a result for "this model inside this app with today's limits" (60 s timeout, 90 s ceiling, 6000 tokens, default thinking). Argon's and Flash's failures may disappear with different limits; that was not tested.
- The three models ran at the same time on the same machine, so latencies include whatever load the providers had at that hour; first-drawing times exclude speech synthesis.
- Costs are estimates; failed timed-out requests are charged at worst case.
- The first benchmark used a looser rubric on three prompts, so its 4 of 6 results are not comparable with these.
- Only final boards were reviewed (not the step-by-step reveal), and the review used the production hand-drawn renderer with its arrowhead limitation.

## 9. Recommendation
**Keep `gpt-4.1` in production for now; investigate one candidate further: `gemini-4-argon`.**
- gpt-4.1 is fast, cheap and reliable, but 0 of 13 boards were usable and only 5 of 13 were even structurally sound.
- Argon is the only model with a result clearly beyond chance on quality (7 of 13 against 0 of 13), and when it answers its boards are good. But it is not a winner yet: it failed 5 of 13 attempts under the current limits, the first drawing takes about 55 s against 14 s, and its failures all come from latency, which a live tutor cannot hide.
- Flash is faster and more reliable than Argon (11 of 13 answered, first drawing 20 s) and structurally almost as sound, but only 3 of 13 boards were usable; it is not clearly better than gpt-4.1 on this evidence (p = 0.22) and costs about three times as much per attempt.
- Do not switch either Gemini model on this evidence alone.
- **Single most useful next step:** run Argon alone on the same 13 prompts with only its call limits relaxed (request timeout, ceiling and output cap) and measure the first-drawing wait a learner would actually see; that separates "Argon's quality" from "Argon as configured". About $1.8 padded, the same as its share here; needs your approval.

## 10. Artifacts
Folder `docs/benchmark_runs/2026-10-15-controlled/`: `review_sheet.html` (all 39 boards, the same prompt side by side for the three models, with metrics, my verdicts, the checklist aid, the shadow signal, override controls and live totals), `summary.json`, `results.json`, `verdicts_by_attempt.json` (my verdicts and notes), `verdicts_by_blind_code.json` and `blind_map.json`, `head_audit.json`, `verify_models.json`, `ledger.jsonl` (every paid call), `order.json`, `runs/` (one file per attempt: the prompt, settings, saved drawings, per-call trace, log events), `shots/` (board screenshots, JPEG, named by review code; the mapping is in `blind_map.json` and in the table below), `round_logs/`, `harness/` (all scripts). Full-size PNGs and the scratch databases stay in the scratchpad. (The first benchmark's committed `harness/common.py` was missing the `cost_text` helper that its `test1.py` calls; it is added back there.)

| run | HTTP | first drawing s | total s | model calls | draws ok / rejected | cost raw | score | usable | artifacts |
|---|---|---|---|---|---|---|---|---|---|
| A2 gpt-4.1 | 200 | 10.1 | 20 | 4 | 2 / 1 | $0.047 | 3/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_A2.json), [board](benchmark_runs/2026-10-15-controlled/shots/XCVJ_1.jpg) |
| A2 gemini-3.8-flash | 200 | 15.3 | 91 | 5 | 3 / 1 | $0.082 | 6/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_A2.json), [board](benchmark_runs/2026-10-15-controlled/shots/NGQC_1.jpg) |
| A2 gemini-4-argon | 503 | - | 122 | 1 | 0 / 1 | $0.134 | 0/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_A2.json), no board |
| D1 gpt-4.1 | 200 | 7.4 | 21 | 5 | 1 / 3 | $0.054 | 4/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_D1.json), [board](benchmark_runs/2026-10-15-controlled/shots/RCXF_1.jpg) |
| D1 gemini-3.8-flash | 200 | 48.1 | 96 | 10 | 7 / 1 | $0.114 | 6/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_D1.json), [board](benchmark_runs/2026-10-15-controlled/shots/CDRR_1.jpg) |
| D1 gemini-4-argon | 200 | 44.3 | 53 | 2 | 7 / 0 | $0.056 | 8/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_D1.json), [board](benchmark_runs/2026-10-15-controlled/shots/DKDW_1.jpg) |
| B1 gpt-4.1 | 200 | 16.2 | 18 | 2 | 1 / 0 | $0.025 | 2/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_B1.json), [board](benchmark_runs/2026-10-15-controlled/shots/XMWH_1.jpg) |
| B1 gemini-3.8-flash | 200 | 14.0 | 112 | 11 | 8 / 1 | $0.126 | 5/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_B1.json), [board](benchmark_runs/2026-10-15-controlled/shots/KXCX_1.jpg) |
| B1 gemini-4-argon | 200 | 51.0 | 61 | 2 | 7 / 0 | $0.076 | 6/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_B1.json), [board](benchmark_runs/2026-10-15-controlled/shots/CWGM_1.jpg) |
| C1 gpt-4.1 | 200 | 14.2 | 16 | 2 | 1 / 0 | $0.023 | 2/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_C1.json), [board](benchmark_runs/2026-10-15-controlled/shots/FXXJ_1.jpg) |
| C1 gemini-3.8-flash | 503 | - | 55 | 1 | 0 / 1 | $0.023 | 0/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_C1.json), no board |
| C1 gemini-4-argon | 200 | 61.9 | 160 | 5 | 7 / 2 | $0.231 | 4/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_C1.json), [board](benchmark_runs/2026-10-15-controlled/shots/RGWF_1.jpg) |
| C2 gpt-4.1 | 200 | 13.8 | 15 | 2 | 1 / 0 | $0.024 | 1/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_C2.json), [board](benchmark_runs/2026-10-15-controlled/shots/PFWD_1.jpg) |
| C2 gemini-3.8-flash | 200 | 15.0 | 84 | 8 | 6 / 0 | $0.085 | 7/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_C2.json), [board](benchmark_runs/2026-10-15-controlled/shots/TWRN_1.jpg) |
| C2 gemini-4-argon | 200 | 56.1 | 78 | 3 | 7 / 1 | $0.117 | 7/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_C2.json), [board](benchmark_runs/2026-10-15-controlled/shots/MKHK_1.jpg) |
| A1 gpt-4.1 | 200 | 8.5 | 10 | 2 | 1 / 0 | $0.019 | 2/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_A1.json), [board](benchmark_runs/2026-10-15-controlled/shots/DXMV_1.jpg) |
| A1 gemini-3.8-flash | 200 | 22.6 | 89 | 8 | 6 / 0 | $0.090 | 4/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_A1.json), [board](benchmark_runs/2026-10-15-controlled/shots/XCZJ_1.jpg) |
| A1 gemini-4-argon | 503 | - | 112 | 1 | 0 / 1 | $0.056 | 0/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_A1.json), no board |
| E1 gpt-4.1 | 200 | 15.3 | 18 | 2 | 1 / 0 | $0.026 | 2/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_E1.json), [board](benchmark_runs/2026-10-15-controlled/shots/PZTX_1.jpg) |
| E1 gemini-3.8-flash | 200 | 35.5 | 96 | 7 | 5 / 0 | $0.096 | 4/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_E1.json), [board](benchmark_runs/2026-10-15-controlled/shots/ZDFV_1.jpg) |
| E1 gemini-4-argon | 503 | - | 123 | 1 | 0 / 1 | $0.137 | 0/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_E1.json), no board |
| D2 gpt-4.1 | 200 | 17.4 | 19 | 4 | 1 / 2 | $0.046 | 6/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_D2.json), [board](benchmark_runs/2026-10-15-controlled/shots/WXNN_1.jpg) |
| D2 gemini-3.8-flash | 503 | - | 43 | 1 | 0 / 1 | $0.023 | 0/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_D2.json), no board |
| D2 gemini-4-argon | 503 | 48.2 | 161 | 2 | 5 / 1 | $0.116 | 7/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_D2.json), [board](benchmark_runs/2026-10-15-controlled/shots/RHNG_1.jpg) |
| E2 gpt-4.1 | 200 | 21.6 | 24 | 2 | 1 / 0 | $0.025 | 3/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_E2.json), [board](benchmark_runs/2026-10-15-controlled/shots/CJMG_1.jpg) |
| E2 gemini-3.8-flash | 200 | 24.1 | 98 | 10 | 8 / 0 | $0.119 | 6/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_E2.json), [board](benchmark_runs/2026-10-15-controlled/shots/TDCM_1.jpg) |
| E2 gemini-4-argon | 200 | 55.2 | 226 | 15 | 13 / 0 | $0.378 | 7/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_E2.json), [board](benchmark_runs/2026-10-15-controlled/shots/PBSP_1.jpg) |
| B2 gpt-4.1 | 200 | 14.1 | 17 | 2 | 1 / 0 | $0.023 | 3/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_B2.json), [board](benchmark_runs/2026-10-15-controlled/shots/HZFT_1.jpg) |
| B2 gemini-3.8-flash | 200 | 34.5 | 150 | 13 | 9 / 2 | $0.199 | 3/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_B2.json), [board](benchmark_runs/2026-10-15-controlled/shots/SDDL_1.jpg) |
| B2 gemini-4-argon | 503 | - | 125 | 1 | 0 / 1 | $0.136 | 0/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_B2.json), no board |
| C3 gpt-4.1 | 200 | 13.5 | 15 | 2 | 1 / 0 | $0.022 | 2/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_C3.json), [board](benchmark_runs/2026-10-15-controlled/shots/WLRP_1.jpg) |
| C3 gemini-3.8-flash | 200 | 20.3 | 133 | 10 | 6 / 1 | $0.140 | 3/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_C3.json), [board](benchmark_runs/2026-10-15-controlled/shots/KQQT_1.jpg) |
| C3 gemini-4-argon | 200 | 61.1 | 126 | 4 | 8 / 2 | $0.167 | 7/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_C3.json), [board](benchmark_runs/2026-10-15-controlled/shots/DHSQ_1.jpg) |
| B3 gpt-4.1 | 200 | 7.7 | 9 | 2 | 1 / 0 | $0.020 | 3/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_B3.json), [board](benchmark_runs/2026-10-15-controlled/shots/WLGR_1.jpg) |
| B3 gemini-3.8-flash | 200 | 17.6 | 80 | 8 | 6 / 0 | $0.078 | 6/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_B3.json), [board](benchmark_runs/2026-10-15-controlled/shots/HGKK_1.jpg) |
| B3 gemini-4-argon | 200 | 38.6 | 44 | 2 | 6 / 0 | $0.056 | 7/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_B3.json), [board](benchmark_runs/2026-10-15-controlled/shots/LMBG_1.jpg) |
| A3 gpt-4.1 | 200 | 7.6 | 9 | 2 | 1 / 0 | $0.018 | 5/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gpt-4.1_A3.json), [board](benchmark_runs/2026-10-15-controlled/shots/RWPZ_1.jpg) |
| A3 gemini-3.8-flash | 200 | 16.1 | 72 | 5 | 3 / 0 | $0.065 | 4/8 | no | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-3.8-flash_A3.json), [board](benchmark_runs/2026-10-15-controlled/shots/QKGD_1.jpg) |
| A3 gemini-4-argon | 200 | 61.0 | 105 | 2 | 7 / 0 | $0.084 | 8/8 | yes | [run](benchmark_runs/2026-10-15-controlled/runs/gemini-4-argon_A3.json), [board](benchmark_runs/2026-10-15-controlled/shots/BTXH_1.jpg) |


## 11. Exact prompts
Sent verbatim as the learner's message (no system text added by me; the app adds its own, unchanged).

**A2: Simple electric circuit** (simple concept)

```text
Teach a beginner what a simple electric circuit is.
Draw a battery, a switch and a light bulb connected in a closed loop, and label each part. Use arrows to show the direction the current flows: from the battery to the switch, from the switch to the light bulb, and from the light bulb back to the battery.
Keep the diagram on one canvas with readable labels.
```

**D1: Scientific method** (text-heavy)

```text
Teach a beginner the scientific method.
Draw four boxes in order, each containing exactly this text:

1. "Observe something surprising in nature or in an experiment"
2. "Form a testable hypothesis that predicts what you should see"
3. "Run a controlled experiment and record every measurement carefully"
4. "Compare the results with the prediction and decide what to change"

Connect the boxes with arrows in order, and add an arrow from box 4 back to box 1 labelled "Repeat with a better question". Keep all the text inside its box and readable, on one canvas.
```

**B1: Browser opens a website** (flowchart)

```text
Teach a beginner how a web browser opens a website.
Draw a flowchart showing these steps:

1. The user enters a website address.
2. The browser checks its DNS cache.
3. If the address is not cached, the browser looks up the server's IP address.
4. The browser connects to the server and sends an HTTP request.
5. The server returns the webpage, and the browser displays it.

Show the cached and uncached paths clearly, with directional arrows and readable labels. Keep the diagram on one canvas and make the relationships between the steps easy to understand.
```

**C1: Six-component web application** (architecture)

```text
Teach a beginner how a web application processes a user's request.
Draw a software architecture diagram containing these components:

1. User
2. Frontend
3. API Gateway
4. Authentication Service
5. Backend Service
6. Database

Show the request moving from the user through the frontend, API gateway, authentication service and backend to the database. Show the response returning to the user.
Arrange the components so the direction of communication is easy to follow. Make the arrows connect to the appropriate components, keep labels readable, and avoid unnecessary line crossings.
Use one canvas. Do not omit any component or connection.
```

**C2: Job queue with workers** (architecture)

```text
Teach a beginner how a job queue spreads work across workers.
Draw an architecture diagram with these components: Web App, API Server, Message Queue, Worker 1, Worker 2, Worker 3 and Database.
Show the Web App sending requests to the API Server, the API Server putting jobs on the Message Queue, each of the three Workers taking jobs from the Message Queue, and each Worker saving its result to the Database.
Make the arrows connect the right components, keep labels readable and avoid unnecessary line crossings. Use one canvas and do not omit any component or connection.
```

**A1: Water cycle** (simple concept)

```text
Teach a beginner how the water cycle works.
Draw a simple diagram with four labelled stages: Evaporation, Condensation, Precipitation and Collection.
Arrange them in a loop with directional arrows showing the order: Collection leads to Evaporation, Evaporation to Condensation, Condensation to Precipitation, and Precipitation back to Collection.
Keep the diagram on one canvas with readable labels.
```

**E1: CI/CD pipeline** (complex)

```text
Teach a beginner how a CI/CD pipeline works.
Draw a diagram with these steps: Developer, Git Repository, Build, Unit Tests, Staging, Manual Approval, Production and Notify Developer.
Show the Developer pushing to the Git Repository, the repository triggering the Build, the Build leading to the Unit Tests, and the tests branching: if they pass the change goes to Staging, then Manual Approval, then Production; if they fail, Notify Developer, which leads back to the Developer. Label the two test outcomes "Pass" and "Fail".
Use directional arrows, keep labels readable and avoid unnecessary line crossings. Use one canvas and do not omit any step or connection.
```

**D2: Three database types** (text-heavy)

```text
Teach a beginner how to choose a database.
Draw a heading "Choosing a database" and three cards side by side, each with a title and two lines of text, using exactly this text:

Card 1: "Relational (SQL)"
  "Best for: structured data with clear relationships between tables"
  "Trade-off: changing the schema later takes planning and migrations"
Card 2: "Document (NoSQL)"
  "Best for: flexible records that change shape from one item to the next"
  "Trade-off: joining data across collections is harder and slower"
Card 3: "Graph"
  "Best for: highly connected data such as social networks and recommendations"
  "Trade-off: fewer tools, and a steeper learning curve for most teams"

Keep all the text inside its card and readable, on one canvas.
```

**E2: Photosynthesis with labelled arrows** (complex)

```text
Teach a beginner how photosynthesis works.
Draw a diagram with these parts: Sun, Leaf, Water, Carbon Dioxide, Glucose and Oxygen.
Show the Sun giving energy to the Leaf, Water and Carbon Dioxide going into the Leaf, and the Leaf producing Glucose and Oxygen. Label each arrow with what it carries, using exactly these labels:
Sun to Leaf: "Light energy"
Water to Leaf: "Absorbed by the roots"
Carbon Dioxide to Leaf: "Taken in through tiny pores"
Leaf to Glucose: "Stored as food"
Leaf to Oxygen: "Released into the air"
Use directional arrows, keep every label readable and next to its arrow, and avoid unnecessary line crossings. Use one canvas and do not omit any part, arrow or label.
```

**B2: Bug fix lifecycle** (flowchart)

```text
Teach a beginner how a software bug gets fixed.
Draw a flowchart with these steps:

1. Bug reported
2. Reproduce the bug
3. Write a fix
4. Run the tests (a decision): if the tests fail, go back to "Write a fix"; if they pass, continue
5. Code review
6. Deploy

Label the two outcomes of the decision "Pass" and "Fail". Use directional arrows between the steps and keep everything on one canvas with readable labels.
```

**C3: Load-balanced site with cache** (architecture)

```text
Teach a beginner how a busy website is built.
Draw an architecture diagram with these components: Browser, Load Balancer, Web Server 1, Web Server 2, Cache and Database.
Show the Browser sending requests to the Load Balancer, the Load Balancer sharing them between the two Web Servers, and each Web Server reading from the Cache and falling back to the Database.
Make the arrows connect the right components, keep labels readable and avoid unnecessary line crossings. Use one canvas and do not omit any component or connection.
```

**B3: Login with retry** (flowchart)

```text
Teach a beginner how a website login works.
Draw a flowchart with these steps:

1. The user submits a username and password.
2. The server checks the credentials (a decision).
3. If they are correct, show the dashboard.
4. If they are wrong, show an error message and send the user back to the login form.

Label the two outcomes of the decision "Correct" and "Wrong". Use directional arrows and keep everything on one canvas with readable labels.
```

**A3: Food chain** (simple concept)

```text
Teach a beginner what a food chain is.
Draw a simple diagram with these five living things in order: Grass, Grasshopper, Frog, Snake and Hawk.
Show the energy moving from each one to the next with directional arrows: Grass to Grasshopper, Grasshopper to Frog, Frog to Snake, and Snake to Hawk.
Keep the diagram on one canvas with readable labels.
```


## Decisions needed
1. Override any verdict you disagree with in the review sheet; do the totals change your view?
2. Approve the Argon follow-up (relaxed limits, same 13 prompts, about $1.8 padded)?
3. Is a first-drawing wait of about 55 s acceptable in live teaching? (It decides whether Argon can ever be the default.)
4. ~~Log the renderer's dropped `<line>` arrowheads as its own task~~ Done afterwards: fixed in `roughRenderer.ts` (section 6, update).
