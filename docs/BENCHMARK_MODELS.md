# Model benchmark: gpt-4.1 against Gemini text models, and two realtime voice models (2026-10-15)

> **Follow-up (2026-10-15):** the larger controlled benchmark of the production model, Gemini 3.8 Flash and Gemini 4 Argon is in `docs/BENCHMARK_CONTROLLED.md`. It uses a stricter rubric, so its numbers are not comparable with the 4-of-6 counts below, and it found that the production baseline is the full `gpt-4.1`.

An isolated benchmark. Nothing in production changed: no prompt, tool text, validator rule, live shadow hook, default model or deployment was touched, and no production data was read or written (see section 1). Numbers are from 2 runs per cell, so they are indicative, not proof. Every board was rendered with the real frontend and reviewed by eye by me (the owner can override any verdict in `review_sheet.html`, section 8). No vision model judged anything.

## 0. Bottom line
- **Text drawing (Test 1).** gpt-4.1 was the fastest and cheapest but made 0 usable diagrams out of 6. `gemini-3.8-flash` made 4 of 6 usable and `gemini-4-argon` 4 of 6, but both are far slower to start (first drawing about 23 s and 51 s against 9 s) and cost about 4.5 and 6 times more per attempt. Argon failed both architecture attempts (app error 503) and never finished them.
- **Realtime voice (Test 2).** Neither Azure `gpt-realtime` nor Gemini Live `gemini-3.8-live` produced a usable board in any of the 6 runs. With the unchanged production tool loop, Azure kept calling the draw tool until my 10-turn cap and made invalid or rejected calls; Gemini Live drew one element and stopped. Realtime is a design project, not a model swap.
- **Offline shadow validator.** It flagged all 4 boards I judged to have major overlap, and also flagged 3 boards I judged clean (connector or axis lines crossing label boxes). It did not flag 7 of the 9 boards with only minor overlap (text touching a border).
- **Spend (padded estimates).** Azure/OpenAI about $1.69 of the $4 hard cap (target $3); Gemini about $2.5 plus about $0.03 for the speech clips.
- **Recommendation.** A larger test is worth it for the text path with `gemini-4-argon` and `gemini-3.8-flash`, not for either realtime model yet (section 7).

## 1. What was run, and how it was kept isolated
- **Production code, unchanged, run in a separate process.** `engine/author.py: run_whiteboard_author` ran through the normal backend routes (TestClient, no lifespan) with `DATABASE_URL` pointed at scratch SQLite files, `LP_SHADOW_VALIDATOR=0`, the log redirected to a scratch file, text-to-speech faked, and only the model client, the deployment name, `MODEL_CEILING_S` and `OUTPUT_DIR` swapped inside that process. Production settings held: `temperature=0.7`, `max_tokens=6000`, `tool_choice="auto"`, same system prompt and tool definitions, same canvas, renderer and existing overlap validator.
- **Natural data untouched.** `logs/learning_platform.jsonl` was fingerprinted before and after (27751 bytes, last written 14 Oct); it did not change. Benchmark sessions live only in the scratchpad databases, so they cannot enter the natural-use shadow review.
- **Models.** gpt-4.1 (the existing deployment; no gpt-4.1-mini), `gemini-3.8-flash` and `gemini-4-argon` through Google's OpenAI-compatible endpoint (thinking left at the provider default), Azure `gpt-realtime` (not 2.1) and Gemini Live `gemini-3.8-live` (not the Argon one). No paid deployment was created.
- **Prompts** (same three for everything): P1 the browser-opens-a-website flowchart (5 steps, cached and uncached paths); P2 the six-component architecture (User, Frontend, API Gateway, Authentication Service, Backend Service, Database; requests forward, response back); P3 the approved y = x² graph (axes with tick labels, the curve, points (-2,4), (0,0), (2,4), labelled vertex). Test 2 used three synthetic speech clips of the same three prompts (Gemini speech generation), the identical audio file for both models.
- **Test 2 setup.** Headless. A small adapter (`harness/rt.py`) presents each realtime model to the unchanged production loop as if it were the chat client: first call sends instructions, tool definitions and the clip (streamed in 100 ms chunks, then end of turn); later calls return tool results as function outputs; for draw and annotate tools the narration text is filled from the speech transcript. Benchmark-only copies of the spoken prompt (Rule 4 rewritten to "speak first, then call the tool") and the tool wording (narration optional) were used; production text is not edited. Limits: 10 model turns and 150 s of audio per scenario.
- **Budget guard.** Every paid call was checked before it was made (`harness/common.py: guard`) against the $4 Azure/OpenAI hard cap and a separate $5 Gemini guard I set for myself; estimates are padded by 25% and Azure realtime was priced conservatively (no cached-token discount), so real spend is likely lower. Failures were recorded, never silently retried.

## 2. Test 1: text drawing quality (18 attempts)
| | gpt-4.1 | gemini-3.8-flash | gemini-4-argon |
|---|---|---|---|
| attempts / finished without app error | 6 / 6 | 6 / 6 | 6 / 4 |
| all required parts present (my review) | 2 | 5 | 4 |
| **usable** (complete and no unintended overlap) | **0** | **4** | **4** |
| usable with no overlap at all | 0 | 2 | 3 |
| draw calls / rejected by the existing validator | 9 / 2 | 36 / 8 | 28 / 5 |
| model calls | 15 | 59 | 17 |
| first drawing, median | 9.1 s | 23.3 s | 51.4 s |
| finished, median | 12.7 s | 137.7 s | 128.2 s |
| tokens in / out | 49k / 10k | 817k / 122k | 130k / 54k |
| estimated cost (padded), total | $0.22 | $1.34 | $1.00 |
| per attempt | $0.037 | $0.223 | $0.166 |
| per usable diagram | none usable | $0.334 | $0.249 |
| offline shadow validator would reject (drawings) | 3 of 7 | 5 of 28 | 2 of 23 |

Per attempt (r1/r2 = first/second run; "complete" = every required component and connection present; cost is padded):

| attempt | HTTP | first drawing s | total s | model calls | draws ok / rejected | cost | complete | overlap | usable | shadow would-reject |
|---|---|---|---|---|---|---|---|---|---|---|
| gpt-4.1 P1 r1 | 200 | 9.1 | 11 | 2 | 1 / 0 | $0.031 | no | major | no | 1 of 1 |
| gpt-4.1 P1 r2 | 200 | 9.1 | 11 | 2 | 1 / 0 | $0.028 | yes | major | no | 1 of 1 |
| gpt-4.1 P2 r1 | 200 | 11.9 | 14 | 2 | 1 / 0 | $0.029 | yes | major | no | 1 of 1 |
| gpt-4.1 P2 r2 | 200 | 4.6 | 19 | 4 | 2 / 1 | $0.059 | no | minor | no | 0 of 2 |
| gpt-4.1 P3 r1 | 200 | 14.4 | 16 | 3 | 1 / 1 | $0.049 | no | minor | no | 0 of 1 |
| gpt-4.1 P3 r2 | 200 | 9.0 | 11 | 2 | 1 / 0 | $0.027 | no | minor | no | 0 of 1 |
| 3.8-flash P1 r1 | 200 | 23.1 | 73 | 9 | 7 / 0 | $0.111 | yes | none | yes | 2 of 7 |
| 3.8-flash P1 r2 | 200 | 20.8 | 140 | 9 | 5 / 2 | $0.138 | no | none | no | 1 of 5 |
| 3.8-flash P2 r1 | 200 | 19.3 | 267 | 17 | 5 / 2 | $0.490 | yes | minor | yes | 0 of 5 |
| 3.8-flash P2 r2 | 200 | 23.4 | 185 | 12 | 5 / 2 | $0.298 | yes | minor | no | 1 of 5 |
| 3.8-flash P3 r1 | 200 | 26.6 | 129 | 6 | 3 / 1 | $0.150 | yes | none | yes | 1 of 3 |
| 3.8-flash P3 r2 | 200 | 25.7 | 135 | 6 | 3 / 1 | $0.151 | yes | minor | yes | 0 of 3 |
| argon P1 r1 | 200 | 48.7 | 56 | 2 | 6 / 0 | $0.085 | yes | minor | yes | 0 of 6 |
| argon P1 r2 | 200 | 55.3 | 86 | 3 | 7 / 2 | $0.152 | yes | none | yes | 2 of 7 |
| argon P2 r1 | **503** | 51.3 | 175 | 3 | 2 / 0 | $0.114 | no | none | no | 0 of 2 |
| argon P2 r2 | **503** | none | 119 | 1 | 0 / 0 | $0.079 | no | none | no | 0 of 0 |
| argon P3 r1 | 200 | 53.3 | 210 | 4 | 4 / 1 | $0.310 | yes | none | yes | 0 of 4 |
| argon P3 r2 | 200 | 51.4 | 138 | 4 | 4 / 2 | $0.255 | yes | none | yes | 0 of 4 |

What the numbers say, and do not say:
- **gpt-4.1 draws one big SVG element and stops.** Within seconds it produced a single element per attempt (1 to 2 drawings). The P1/P2 boards had connectors striking through box text, no arrowheads, or detached arrow strips; the P3 curve was upside down or a sine-like wave through the origin, with points off the curve. Its speed and cost are real, but none of the six boards teaches anything correctly.
- **The Gemini models build boards in several elements** (Flash 3 to 7, Argon 4 to 7 per board) with titles, arrows and labels, which is why they take much longer. Flash used many more model calls (59 against Argon's 17) and was the more expensive per usable board on the hardest prompt (P2: $0.49 and $0.30).
- **Argon failures (recorded, not retried).** P2 r2: the first model call hit the 6000-token output cap (`finish_reason=length`, 5 draw calls cut off, 118 s), so nothing was drawn and the app returned `model_unreachable` (503). P2 r1: after two good elements out of six, a further model call failed with an empty error text after about 175 s and the app returned 503 (probably the 90 s per-call ceiling; not confirmed). Argon on P1 and P3 finished in 56 to 210 s. With the production `max_tokens=6000` and default thinking, a six-component board is at the edge of what Argon can emit; raising the cap would be a separate, untested change.
- **Rejections.** The existing validator rejected 22% (gpt-4.1), 22% (Flash) and 18% (Argon) of draw calls; the models re-drew after rejections within the production loop (no extra retries by me).
- **A stray clipped badge at the board corner** appears on some Flash boards. It comes from the production annotation placement, not from the model's drawing.
- **My automatic completeness checker agrees with my manual completeness call on only 10 of 18 boards** (tolerance problems), so the manual review is the authoritative column and the checker is only a first pass.

## 3. Offline shadow validator column
The shadow validator (`engine/shape_model.shadow_check`, offline, no effect on any outcome) re-checked every saved drawing. Counted against my visual review:
- All 4 boards I judged to have **major** overlap were flagged (gpt-4.1 P1 r1, P1 r2, P2 r1 and Gemini Live scenario 1).
- 3 boards I judged **clean** were flagged: Flash P1 r1 and Flash P3 r1 (`connector_through_node`: axis or flow lines passing through label boxes) and Argon P1 r2 (`connector_through_node` and `arrowhead_in_node`). These are the known advisory-class crossings (connector or label crossings), so they are not evidence the validator is wrong, but they are a false-alarm risk if such crossings were ever enforced.
- The **minor** overlaps (a title touching a box border, curve tips touching header text) were mostly not flagged, as expected from its thresholds.
Per-model counts are in the table in section 2. This is an offline column only; it is a decision input for the shadow review, not an approval for enforcement.

## 4. Test 2: realtime voice (6 runs, one scenario per prompt, headless)
Timings are from the end of the speech clip. "Turns" are model responses in one scenario. Cost is padded.

| run | app result | speech end to first drawing | to completion | turns | draws ok / rejected | invalid tool calls | spoken words (audio s) | cost | complete | overlap | usable |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Azure gpt-realtime P1 | stopped at my 10-turn cap (shown as 503) | 11.4 s | 30.0 s | 10 | 5 / 5 (all 5 invalid calls) | 5 | 73 (21.1) | $0.355 | no | minor | no |
| Azure gpt-realtime P2 | stopped at my 10-turn cap (503) | 6.8 s | 28.8 s | 10 | 6 / 4 | 0 | 45 (16.2) | $0.413 | no | none | no |
| Azure gpt-realtime P3 | 200 | 10.2 s | 19.9 s | 4 | 1 / 1 | 0 | 101 (28.9) | $0.164 | no | none | no |
| Gemini Live P1 | 200 | 10.9 s | 13.8 s | 2 | 1 / 0 | 0 | 26 (6.6) | $0.020 | yes | major | no |
| Gemini Live P2 | 200 | 11.3 s | 15.3 s | 2 | 1 / 0 | 0 | 24 (5.9) | $0.016 | no | minor | no |
| Gemini Live P3 | 200 | 26.8 s | 38.5 s | 2 | 1 / 0 | 0 | 75 (22.2) | $0.065 | no | none | no |

- **Azure `gpt-realtime`:** first drawing 6.8 to 11.4 s after the speech ended, and it speaks while drawing. But it never wrapped up: in P1 and P2 it kept drawing until my 10-turn cap. P1: 5 of the 10 draw calls failed with invalid arguments (the other 5 were accepted); the board had 3 shapes and 2 short connectors without arrowheads. P2: six boxes drawn, no connectors (4 draw calls were rejected; the ones I read were its connector `request_flow` overlapping the boxes, the known union-box limitation). P3: axes only; the curve was rejected as overlapping the axes element, and the model then asked the student to open a new page. Only after I rewrote Rule 4 in the benchmark-only prompt to "speak first" did it speak at all; the first attempt with the unchanged wording never spoke and looped to a 14-turn cap (kept in `out/test2_v1_prompt_azure_s3.json`, $0.54 padded).
- **Gemini Live `gemini-3.8-live`:** every run made exactly one accepted draw call and then ended its turn, so boards were never complete. P1 had two overlapping boxes hiding text; P2 had only User and Frontend and one arrow, with one box cut at the left edge; P3 had a wrong curve (vertex above the origin, missing the three points). The wait before the first drawing was 10.9 to 26.8 s (thinking time shows up in the billing as thought tokens). It is the cheapest option by far ($0.016 to $0.065 per run).
- **Narration quality:** measured by volume only (23 to 101 spoken words per run, one narrated draw per drawn element); I did not listen to or rate the audio, so there is no narration-quality verdict.
- **Tool-call correctness:** Azure 5 of 10 invalid calls in P1; 0 in P2 and P3. Gemini Live 0 invalid calls (1 call each). Calls that were rejected were rejected by the existing overlap validator, not by the adapter.
- **Adapter work (inspection, not a rebuild).** The production loop was reused unchanged through a facade: `harness/rt.py` is about 370 lines (event loop thread, benchmark-only prompt/tool copies, tool and schema converters, the facade, one class per provider) and `harness/test2.py` about 140. Still missing for a real product path, none built here: browser microphone and audio playback over a socket, barge-in handling, session length and reconnect (Gemini audio sessions last about 10 minutes unless resumption is on), reveal timing from the model's own audio (no word timestamps from either model), and moving the production prompt and tool text to a speak-first design (frozen today).

## 5. Spend (padded estimates, from `ledger.jsonl`)
- Azure/OpenAI: $1.693 of the $4 hard cap (target $3): gpt-4.1 Test 1 $0.222; gpt-realtime final runs $0.932; the aborted first P3 run with the old prompt $0.538 (the biggest avoidable waste). No cap breach; no paid deployment created.
- Gemini (personal key, tracked separately): Flash $1.338, Argon $0.995, Live $0.113 (includes one early P3 run kept in `out/test2_gemini_s3_harness_v1_no_toolresults.json`), plus about $0.03 for generating the three speech clips (`audio/tts_ledger.json`). Total about $2.5 against my own $5 guard.
- Cost figures are conservative upper bounds; Azure realtime was billed at full price with no cached discount in the estimate.

## 6. Limits of this evidence
- 2 runs per text cell and 1 run per realtime cell: a single lucky or unlucky run can move a result. By the standing rule a result counts only if all runs fall outside the reference run-to-run range; none of these were compared with a repeated reference for the same models, so treat differences as leads.
- The realtime models were run through an adapter and benchmark-only prompt copies; a different prompt design could change the result (that is the point of the finding, not a defect of it).
- Rendering was the real frontend, but the review is a human-by-eye call on 24 screenshots by me; the automatic completeness checker is a first pass only.
- Thinking level, cached tokens and Argon's output cap were left at defaults, so Flash and Argon cost and latency could move if tuned.

## 7. Recommendation
- **Worth a larger test: the text path with `gemini-4-argon` and `gemini-3.8-flash`.** Both beat gpt-4.1 where it matters (usable boards, correct curve, clean arrows) at a price per usable diagram of $0.25 to $0.33, with the cost of 25 to 50 s before the first drawing (and 2 minutes to finish). Argon needs its architecture failures understood first (output cap and call ceiling), and Flash's high number of model calls on the six-component board needs watching.
- **Not yet: either realtime model.** Neither produced a usable board even with a benchmark-only prompt; the gap is in prompt and tool design for a speaking model, not in the model alone.
- gpt-4.1 stays the default; nothing here changes it.

## 8. Where the evidence is
`docs/benchmark_runs/2026-10-15/`: `review_sheet.html` (all 24 boards, my verdicts, automatic checks, override boxes with a JSON export), `summary.json` and `results.json`, `manual_review.json`, `test1/` and `test2/` (every attempt: events, tool log, metrics, per-call trace, rejection messages), `shots/` (JPEG copies of the screenshots), `ledger.jsonl`, `audio/` (prompt texts, speech clip ledger), `harness/` (all scripts, including the Test 2 adapter) and the three superseded Test 2 runs. Full-size PNGs and the scratch databases stay in the scratchpad.

## Decisions needed
1. Open `review_sheet.html` and override any "usable" verdict you disagree with; say if the totals change your view.
2. Approve a larger text test of Argon and Flash? Suggested scope: 5 runs per model on P1 to P3 with the same pipeline, plus one Argon variant with a higher output cap (benchmark-only), within a new budget you set.
3. Should the realtime question wait for a design step (speak-first prompt and tool wording for a speaking model) before any further test?
4. The stray clipped annotation badge at the board corner is a production annotation-placement issue; do you want it logged as a separate task?
