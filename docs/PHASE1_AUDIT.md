# Phase 1 audit: evidence before planning Phase 2

Every number below comes from a run on 2026-10-07 unless a file or test is named. Costs use third-party price lists
(linked at the end), not billing data. "SAD v1" is not in this repository (only `docs/original-plan.md` is), so
section 16 compares against that plan.

> **Update 2026-10-07 (follow-up).** The rule table in section 7 is replaced by `docs/PROMPT_RULES.md` (one numbering, a
> decision per rule, and the background-frame guard proposal). Baseline and factual review: `docs/BASELINE.md`. The 29
> live-server tests that were skipped now run on a free port: 131 passed, 0 skipped. In section 15, the `layout_hint`,
> `tool_call`, `model_usage` and `density_checked` events now exist.

## Close the Phase 1 loose ends

**1. Voice timing in a real browser.**
`tests/test_browser_timing_and_replay.py::test_element_appears_on_screen_at_the_spoken_word`. It reads the second at
which the marked word is spoken from `alignment.json`, then reads the audio clock in the browser two animation frames
after the element enters the DOM (so after it is painted). Five runs, real ElevenLabs voice: **+59, +64, +41, +39,
+39 ms** (mean 48, max 64). Always slightly after the word, never before. About 27 to 32 ms of that is browser paint
lag. The limit in the test is 150 ms. The old version of this file was a script with no `test_` functions (pytest
collected nothing from it) and used selectors from before the redesign, so it had not been running. It is rewritten.

**2. Replay.**
`tests/test_browser_timing_and_replay.py::test_replay_brings_elements_back_in_original_order_with_each_ones_audio`.
Saves a page of 4 drawings (seq 1 to 4, each with an audio file), clicks Replay, and checks: the board clears
(0 elements), elements return as `['rep_a','rep_b','rep_c','rep_d']`, and the audio files played are
`rep_a_audio.mp3 ... rep_d_audio.mp3` in that order. Passes. (The app also plays one silent `data:` clip on click to
unlock audio; the test ignores it.)

## Data and history

**3. Undo deletes rows.**
`backend/main.py: undo_last_drawing` calls `session.delete(e)` on the element's draw and modify events, its
annotations and their remove events, and deletes the audio files from disk. It adds no undo event. Run on SQLite:
before undo the seqs are 1 draw, 2 annotate, 3 draw, 4 modify, 5 remove_annotation; after undoing element `b` they are
1, 2, 5 (gap), and the next draw gets 6. So the audit trail and the audio are lost for good, and seq has holes.
Undo on a saved page is refused with HTTP 400 "saved and locked"
(`tests/test_undo.py::test_undo_refuses_saved_pages_busy_tutor_and_unknown_targets`). Phase 2 change to consider: an
`undo` event plus a hidden flag (soft delete), with audio kept.

**4. Annotations.**
Same table, same stream: `page_events`, one `seq` per page, `kind` in draw / modify / annotate / remove_annotation
(shown above). The `PageEvent` docstring in `backend/models.py` still says only "draw | modify" (stale). There is **no
unique constraint on (page_id, seq)**; REST endpoints compute `max(seq)+1` from a read, so two concurrent writes could
collide. Only indexes exist: `ix_page_events_kind / page_id / seq`.

**5. The learner's pen, highlight and eraser marks.**
They live only in React state (`learnerStrokes` in `WhiteboardCanvas.tsx`), cleared when the page changes. Not stored,
not replayed, not counted in density (density is computed server-side from SVG), and not visible through the
read-page tool. Only the result of a circle gesture is sent: the ids of matched elements, as
`selected_element_ids`, `gesture_type` and `match_score` on the chat request. Sanitising: strokes are never markup;
each is a list of numbers from pointer events turned into a path by `pointsToSvgPath`, with a colour from a fixed
palette, so nothing needs sanitising and nothing is sent to the server.

**6. Postgres vs SQLite.**
`docs/original-plan.md` itself says "set up Postgres schema" (build step 1); the SQLite-first SAD is the webinar
project's and is not in this repo, so I cannot check it. Postgres was chosen in our first session. It still runs on
SQLite: with `DATABASE_URL` unset it uses `learning_platform.db` (`backend/database.py`), and **91 in-process tests pass
on SQLite**, including the Alembic migrations (`TEST_DATABASE_URL=sqlite:///... pytest`). Open-source friction: 
`requirements.txt` always installs `psycopg2-binary`, which should be optional.

## Tutor behaviour and quality

**7. Every rule, HOW it is recorded vs WHAT to draw or say.**
You asked about the webinar lesson (hidden content rules make every output look the same). The founding principle
in `docs/original-plan.md` is "constrain how the agent records its work, never what it chooses to draw ... if you find
yourself handing the model an example, stop". The current prompt breaks it in several places.

| # | Rule (where) | Type | Notes |
|---|---|---|---|
| 1 | Persona: "elite professor", "rich, expressive diagrams", "deep, intuitive narration" on every element (prompt intro) | WHAT | style and depth are forced |
| 2 | Never draw a background frame; wider than 800 or taller than 600 counts as a frame (Rule 0, `author.py:474`) | HOW, but the numbers are wrong | see finding A |
| 3 | First draw must be "a concept box, a diagram, a label, an arrow" (Rule 0) | WHAT (light) | |
| 4 | Every element is a `<g id>` group (Rule 1) | HOW | needed for measuring and annotating |
| 5 | Every element must contain a container shape + a title label + sub-labels; "a shape without text is meaningless"; every concept "must be represented visually" (Rule 1) | **WHAT** | rules out axes, curves, maps, bars, timelines drawn without in-shape text; contradicts "free-form sketch" |
| 6 | "Creative guidance": 10 suggested forms (pipeline of boxes, loop, "a robot, a packet, a stack of plates, a brain", table, timeline, tree, layers, Venn, sketch) | WHAT (examples) | "not rules", but they are examples |
| 7 | Arrowhead markers `#arrow`, `#arrow-dark`, `#arrow-green` | HOW | |
| 8 | Everything inside 1200x800 | HOW | |
| 9 | "MANDATORY: always draw on follow-ups, never reply with plain text alone"; short nudges ("ok") must draw the next concept (Rule 2) | **WHAT** | even "what does X mean?" and "Quiz me" must produce a drawing |
| 10 | Call `get_current_page_state` before drawing (Rule 2, tool text) | HOW | redundant: the state is already in the prompt; costs a model call |
| 11 | Layout zones: header y30-90; 3 columns with roles (left = inputs, client, raw data; centre = processing, server, algorithms; right = outputs, database, results); 2-row split for before/after (Rule 3) | **WHAT (template)** | the "contract template" mistake: a semantic layout for every topic. Every real first element starts in the same top-left cell (see 9) |
| 12 | No overlap, 30 px margin, read `occupied_regions` (Rule 3) | HOW | |
| 13 | Connector routing: no diagonals across cards, align cards, orthogonal routes (Rule 3) | WHAT (aesthetic) | |
| 14 | Card size: height 80-90 px or more, width 180-220 px or more, 20 px padding (Rule 3) | WHAT (aesthetic) | presented as physical, but is a style preference |
| 15 | Text fit: ~0.5 x font-size per character, lines 1.3 x font-size apart (Rule 3) | HOW | a true rendering fact |
| 16 | `[[MARK:id]]` in the first sentence of narration (Rule 4) | HOW | timing protocol |
| 17 | Right/wrong example: "Here we can see the TCP three-way handshake - the client sends a SYN packet" (Rule 4) | **WHAT (example)** | see finding B |
| 18 | MARK only in narration; narration plain text (Rule 4) | HOW | |
| 19 | Six annotation styles and what they are for; tick = verified/passed, cross = invalid/"cache miss" (Rule 5) | HOW, mostly | the meanings are mild WHAT |
| 20 | Note examples "Key step!", "Bottleneck", "O(1) lookup"; ephemeral vs permanent guidance (Rule 5, `annotate_element`) | WHAT (examples, software-flavoured) | |
| 21 | Learner pointer prefix format `[Learner circled ...]` (Rule 6) | HOW | protocol |
| 22 | On a pointer: explain "specific role, responsibility, internal behavior"; for two elements "explain the communication protocol (REST, gRPC, WebSocket, pub/sub), payload flow, sync vs async, failure handling" and MANDATORY arrow (Rule 6) | **WHAT, software-specific** | asking how two elements in a history or biology diagram connect gets networking instructions |
| 23 | Propose a new page and wait for the learner's yes, then `start_new_page` and draw (Rule 7, tool text) | WHAT (product decision) | decision 1 of the plan, so intentional |
| 24 | `draw_new_element`: must be a "complete, self-explanatory component" with "container card rect, title text, labeled sub-boxes, and flow arrows" | **WHAT** | every element must carry sub-boxes and arrows |
| 25 | `draw_new_element`: absolute x/y, no `transform`, fits canvas | HOW | |
| 26 | `narration`: "80-200 words, in-depth, as a professor in office hours"; example "Here you can see the CPU..." | **WHAT** | length drives cost; example is copied (finding B) |
| 27 | `modify_existing_element`: only for corrections, not redesigns | WHAT (light) | |
| 28 | `remove_annotation`, `get_current_page_state` descriptions | HOW | |

Code-side rules that also shape content (not in the prompt):
- **"Unlabeled card" hint** (`validator.find_layout_issues`): any rectangle at least 120x40 px with no child rectangle
  and no text whose centre is inside it. Tested here: three colour bands in a timeline (dates written above them) are
  flagged "has no label inside it", although the drawing is correct.
- **"Mostly empty container" hint**: any rectangle at least 200x200 with children whose lowest child leaves more than
  30% empty at the bottom is told to "shrink it to fit its content or add the missing items". Tested here: a map-like
  region with a few places near the top was flagged "81% empty". It only checks the bottom edge and only rectangles.
  Both are non-blocking, but the tutor is told to fix them with `modify_existing_element`.
- **Overlap rejection** (more than 20% of the smaller box): tested here: a detail diagram drawn inside its own panel
  is rejected as an overlap. The prompt itself suggests Venn diagrams and "zoom-in breakdowns".
- **`transform` ban**: rotated text, such as a graph's y-axis label, cannot be drawn. 2 of 17 rejections in the run.
- **Marker override** (`engine/voice.py`): a marker later than 40% of the audio is forced to time 0.

Findings: **A.** The background-frame guard uses `width > 800 or height > 600`, while the validator's own frame test
is width >= 1100 and height >= 700, and the prompt's header zone is 1100 px wide. In the run, 5 of the 17 rejections
were 1080-1100 px wide boxes of 70 to 400 px height, rejected as "full-canvas background rect"
(`supply_demand_intro`, `newtons_three_laws`, `wwi_causes_overview`, `photosynthesis_overview`, `handshake_diagram`).
**B.** Three of three tutor replies seen in this session begin "Here you see ..." / "Here we see ..."
(pedagogical test, browser render script), which matches the example in rule 17. Small sample, but the pattern is
what the principle predicts.

**8. Density limits against real pages.**
Run of 8 real topics (16 turns), from `density_checked` log events (added today): **8 pages**, final element counts
**1, 2, 2, 2, 2, 2, 3, 7** (median 2), final canvas fill **0.14, 0.26, 0.28, 0.29, 0.30, 0.32, 0.32, 0.35** (median
0.30, max 0.35). **The soft nudge (15 elements or 70% fill) fired 0 times and the hard cap (25) fired 0 times.** The
older log (`logs/app.jsonl`: 695 soft, 69 hard-cap events) is almost entirely my own test fixtures, which fill pages on
purpose, so it says nothing about real use. Conclusion: real pages are tiny, so 15, 25 and 70% have never been
exercised by real tutor behaviour. They are unproven guesses. Also `pages.canvas_coverage` is **always 0.0** in the
database (the model says "updated after every PageEvent insert"; nothing writes it).

**9. What the tutor-quality evaluation measures.**
`tests/eval_tutor.py`. Last run (today): **8 topics** (history, maths, biology, code, economics, physics, language, a
deliberately dense OSI-vs-TCP request), 2 turns each. Hard checks (0 of 8 failed): tutor replied with text and drew
something; every element passes bounds and text checks; no overlaps. Soft checks: "layout variety" 0.88 ("ok"), latency,
and for the dense topic whether it proposed a new page (it did). Retries 17 total (2.1 per topic); an earlier run of
the same eval had 9. One run each, so I cannot say whether that is noise or a regression.
**"Layout variety" is weak.** It compares each topic's whole first-page signature, bounding boxes rounded to 200 px, so
one extra element makes two layouts "different". Stricter, by first element only: history, biology and economics have
the identical first element `[0,1,5,1]` (a wide banner at the top-left); maths and code are identical; **5 distinct
first elements for 8 topics (0.62)**, and all 8 start in the same top-left cell. It does not compare what is drawn
(shape kinds, forms), only boxes.

**10. Factual correctness.**
Nothing checks it. The tutor has no search tool and no grounding (see `docs/FEATURES.md`; the `TAVILY_API_KEY` in
`.env` is unused by this project). If it draws or says something wrong, nothing detects it: the narration is spoken,
stored in `page_events.narration`, replayed and exported as written. The learner has to notice and ask, and the tutor
can then fix a drawing with `modify_existing_element`; there is no flag or confidence marker.

## Learner and quiz (for Phase 2)

**11. Learner identity.**
None. No learner or user table exists (tables: `notebooks`, `pages`, `page_events`, `chat_turns`). Every notebook is
global: `GET /api/notebooks` lists all of them. `session_id` in the logs is the notebook id. One implied person. The
browser remembers only `last_active_notebook_id` in localStorage.

**12. Quiz me and "Ask about a drawing".**
"Quiz me" is a canned chat message (`ChatPanel.tsx`: "Ask me a quick conceptual question or quiz to test my
understanding."). The model asks in text (and by Rule 2 is pushed to draw too); your answer is the next chat message;
the model judges it in free text. Nothing is scored or saved except the chat turns. "Ask about a drawing": the element
ids reach the model only inside `augmented_message` (`main.py:851`); the stored user turn is `req.message` alone
(`main.py:896`), so **the element id and the question are not stored together**. `ChatTurn.tool_calls_made` exists but
nothing writes it.

**13. The "summary of earlier pages".**
Format (`backend/page_state.py: prior_pages_summary`): `Page N: <title> - <summary>` for the 20 most recent pages and
`Page N: <title> (earlier page)` for older ones. **Nobody writes `Page.summary`.** The save call sends no body
(`App.tsx: handleSavePage`), no tool sets it, only a manual PATCH would. Real database: both pages have `summary =
None`, and page 1 also has `title = None`. So what the tutor remembers of earlier pages is page titles (only those set by
`start_new_page`) and "No summary."; beyond the last 15 chat turns it has no memory of what was taught.

## Cost and operations

**14. Model and cost per learner turn.**
Model: Azure OpenAI deployment `gpt-4o-mini` (it serves `gpt-4.1-mini`, see docs/BASELINE.md), API version `2024-08-01-preview`. Measured over the 16 turns (token
usage is now logged as `model_usage`): **3.5 model calls and 20,146 prompt tokens and 1,766 completion tokens per
turn** (each call re-sends the context and tool results; per-call prompt median 5,495). Speech: **524 characters, 35 s
of audio per turn** (`audio_synthesis_completed.chars`). Rough cost per turn, list prices from third-party sources:
LLM about **$0.004-0.005**; ElevenLabs about **$0.03-0.06** (524 chars at roughly $0.05-0.11 per 1,000 characters
depending on plan); Deepgram about **$0.001** per spoken question (assuming about 15 s streamed at $0.005-0.008 per minute).
Total about **$0.03-0.07 per turn, and speech is 85-95% of it.**

**Correction (2026-10-08): the model was `gpt-4.1-mini`, not `gpt-4o-mini`.** Azure upgraded the deployment named `gpt-4o-mini`
to `gpt-4.1-mini` under the same name, before any of the runs in this audit or in baselines A to E. The LLM cost above was
priced as gpt-4o-mini. Recomputed from the same logged tokens (20,146 prompt and 1,766 completion tokens per turn), at list
prices with no cache discount (OpenAI pricing page, https://developers.openai.com/api/docs/pricing, read 2026-10-08):

| | price per 1M tokens (input / output) | prompt tokens | completion tokens | LLM cost per turn |
|---|---|---|---|---|
| old (gpt-4o-mini) | $0.15 / $0.60 | 20,146 = $0.0030 | 1,766 = $0.0011 | **$0.0041** |
| new (gpt-4.1-mini) | $0.40 / $1.60 | 20,146 = $0.0081 | 1,766 = $0.0028 | **$0.0109** |

The LLM is 2.7 times what the audit said. With the audit's own speech and Deepgram estimates unchanged, the total per turn is
about **$0.04-0.07** (was $0.03-0.07) and speech is about 70-85% of it (was 85-95%). The speech estimate itself was from
third-party lists; baseline F prices it from ElevenLabs' own page (docs/BASELINE.md).
Stopping audio when muted: not hard on the server, but a product decision. Today the client mute is cosmetic
(`isAudioMuted` only silences playback) and `_handle_draw_new_element` always calls ElevenLabs. Change: send `voice:
false` on the chat request, skip synthesis, and the player already has a no-audio path (`audio_url` null, short
delay). Roughly 15 lines. The trade-off: those drawings have no audio when replayed or when unmuted later, unless audio
is generated lazily on first replay.

**15. Structured logging.**
Yes, `core/log.py` is used by the backend and engine (JSON lines, daily rotation, 14-day retention). It is copied from
the webinar project: the logger is named `webinar` and the correlation fields are `deck_id` / `slide_id` (here they hold
the page id). The server writes `logs/learning_platform.jsonl`; the pytest runs write `logs/app.jsonl`, so the two are
easy to mix up (this is why the old density counts were misleading). **`scripts/logs_query.py` does not exist in this
project** (there is no `scripts/` folder). I queried the JSONL with short Python scripts. New events today:
`model_usage`, `density_checked`; `audio_synthesis_completed` now carries `chars`.

## Phase 2 and differences from the original plan

**16a. "Phase 2 ideas deferred".** There is no list in the repo. The only source is the plan's out-of-scope paragraph:
no live voice input, no quizzes or "last time we covered" recaps, no multiple simultaneous learners, no real photos or
images, no live two-way barge-in. Two of those are already built (voice input, barge-in). What remains from that list:
quizzes and recaps, multiple learners, images. From this audit, candidates: learner identity; stored quiz results;
"ask about a drawing" stored with its element id; summaries actually written; soft-delete undo; unique `(page_id,
seq)`; optional web search or grounding; skip speech when muted; fix the prompt's content rules (section 7).

**16b. Differences from the plan (`docs/original-plan.md`).**
- **Tools:** the plan had 2 (`get_current_page_state`, `draw_on_page`). Now 6: `draw_new_element` (replaces
  `draw_on_page`), `modify_existing_element`, `annotate_element`, `remove_annotation`, `start_new_page`, plus the
  unchanged `get_current_page_state`.
- **Tables:** the plan's model was notebook, page, chat turns (with `final_svg`, per-page audio and
  `created_from_chat_turns`). Now `notebooks`, `pages` (`current_svg` cache, no `created_from_chat_turns`),
  `page_events` (the event log, audio per event) and `chat_turns`, plus `alembic_version`. No table was added beyond the
  plan's event-log idea. Unused columns: `pages.canvas_coverage`, `chat_turns.tool_calls_made`.
- **Dependencies added:** `alembic`, `psycopg2-binary`, `lxml`; `playwright` moved from runtime to
  `requirements-dev.txt`. Frontend: `roughjs`, `lucide-react`, React 19, Vite.
- **Geometry measurement:** the plan said Playwright-based measurement; the code parses SVG attributes in Python
  (`engine/validator.py`), no browser at runtime.
- **Built although out of scope:** live voice input (Deepgram), barge-in, undo, notebook export, dark theme,
  responsive layout, rate limits, size limits, migrations, restricted CORS/WebSocket origins.
- **Removed or not built:** Playwright at runtime; `created_from_chat_turns`; per-page `narration_audio`.

## Found while auditing (not yet fixed)

- Windows reserved ports 7916-8015 on this machine, which includes 8001 and 8000, so nothing could bind them. This is
  probably the cause of the `WinError 10013` you saw earlier; the README blames "port already taken". Today I made the
  port configurable (`VITE_BACKEND_PORT`, `LP_BACKEND`, `LP_API`) but most older tests still hard-code 8001.
- The background-frame guard threshold (finding A in section 7) and the stale `PageEvent` docstring.
- `requirements.txt` installs `psycopg2-binary` for everyone.

Sources for prices:
[Azure OpenAI pricing](https://azure.microsoft.com/en-ca/pricing/details/cognitive-services/openai-service/),
[ElevenLabs API pricing](https://developer.puter.com/tutorials/elevenlabs-api-pricing/),
[Deepgram Nova-3 pricing](https://convertaudiototext.com/blog/deepgram-nova-3-explained). These are secondary sources;
check your own invoices.
