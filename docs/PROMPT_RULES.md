# Tutor rules: recording vs content, with a decision for each

**Rule of the eval: before blaming the model for what is missing on the board, compare the raw model output with the stored board** (`tests/eval_lossless.py`; the log keeps every drawing as the model wrote it). A silent loss in our own code cost three experiments (F, G and half of C to E) before it was found.

One list, one numbering. Earlier I used two: the prompt's own "HARNESS RULE 0-7" headings in prose, and row numbers
in the audit table (`PHASE1_AUDIT.md`, section 7), and my removal list used the row numbers. The old row numbers
are in the last column ("old #") so the two can be matched: old #9 is Harness Rule 2 (always draw), old #11 is Harness
Rule 3 (zones), old #22 is Harness Rule 6 (how to answer a pointer), old #26 is the 80-200 word narration.

**Type.** RECORDING = how work is stored or measured (ids, coordinates, safety, timing protocol, rendering facts).
CONTENT = what to draw or say (form, style, length, topic examples). MIXED = both in one rule.
**Decision** is my recommendation, nothing has been changed yet: REMOVE / REWRITE (keep the recording part, drop the
content part) / KEEP.

## In the system prompt (`WHITEBOARD_SYSTEM_PROMPT`)

| ID | Where | Quote | Type | Decision | Why | old # |
|---|---|---|---|---|---|---|
| P0 | intro | "an elite, one-on-one AI professor ... drawing rich, expressive diagrams ... deep, intuitive narration — like a master professor in office hours" | CONTENT | REWRITE | keep "one-on-one tutor teaching any topic on a whiteboard"; drop the adjectives, they set a voice and a density | 1 |
| P1 | Rule 0 | "NEVER draw a full-canvas background rect (... anything > 800px wide or > 600px tall)" | RECORDING | REWRITE | the intent is right (the canvas already has a background), the numbers are wrong (see C5); state it from the shared constant | 2 |
| P2 | Rule 0 | "Your very first draw_new_element call ... MUST be a meaningful pedagogical element — a concept box, a diagram, a label, an arrow" | CONTENT | REMOVE | redundant once P1 says no frame; the list is examples | 3 |
| P3 | Rule 1 | "Every element MUST be a `<g id="element_id">` group" | RECORDING | KEEP | ids are what annotation, undo, modify and measuring rely on | 4 |
| P4 | Rule 1 | "NEVER draw a bare, empty geometric shape. A shape without text is meaningless." and the group must contain "a visible container ... A readable title or label ... Any sub-labels, callouts, or connectors" | CONTENT | REMOVE | forces card + title + sub-labels on everything: no bars, curves, maps, timelines, plain sketches. Keep only that things the learner must identify should be identifiable | 5 |
| P5 | Creative guidance | ten forms: "Connected pipeline of boxes", "Circular or triangular loop", "Concrete object metaphor — a robot, a packet, a stack of plates, a brain", "Comparison table", "Timeline", "Tree", "Layered stack", "Venn", "Free-form sketch" | CONTENT (examples) | REMOVE | "not rules" but they are examples, which the principle says the model copies. Keep one sentence: choose the form that fits the concept | 6 |
| P6 | Rule 1 | "Available arrowhead markers: marker-end="url(#arrow)" (blue), (#arrow-dark) (slate), (#arrow-green) (emerald)" | RECORDING | KEEP | these ids exist in the page's defs; the colour words are descriptions | 7 |
| P7 | Rule 1 | "all coordinates must fit inside the 1200 x 800 canvas" | RECORDING | KEEP | | 8 |
| P8 | Rule 2 | "MANDATORY: Call draw_new_element or modify_existing_element. Never reply with plain text alone." | CONTENT | REWRITE | one tutoring-policy rule for all questions, including "what does X mean?" and "quiz me". Suggested: default to drawing when introducing or comparing ideas; plain text is fine for clarifications and quizzes. Your call, it changes the product | 9 |
| P9 | Rule 2 | "Call get_current_page_state() first to find open canvas space." | RECORDING (wasteful) | REMOVE | the state is already in the prompt on every call; costs a model round trip. Measured over 3 baseline runs (48 turns): called 5, 4 and 3 times per run, so the tutor mostly ignores the instruction already | 10 |
| P10 | Rule 2 | "short nudge ('ok', 'next', 'continue'): ... advance the lesson and immediately draw the next concept" | CONTENT | REWRITE | keep "continue means continue"; drop "immediately draw" | 9 |
| P11 | Rule 3 | "organize your elements across these named zones": header y 30-90; LEFT "Inputs, client side, initial state, raw data, or problem statement"; CENTER "Processing, server/engine, algorithms ..."; RIGHT "Outputs, database, results, final state ..."; 2-ROW split | CONTENT (template) | REMOVE | the template with meanings. Replace with the facts the tutor already receives (`occupied_regions`, `available_space`) | 11 |
| P12 | Rule 3 | "NEVER place a new element overlapping an existing one. Maintain at least 30px margin" | RECORDING | KEEP | physical; the margin number should come from the same constant the check uses | 12 |
| P13 | Rule 3 | "CONNECTOR ROUTING: Arrows and lines must NEVER slice diagonally across intermediate cards or text ... align cards on the same vertical level" | CONTENT (aesthetic) | REWRITE | keep "connectors must not run through labels" (readability); drop the alignment advice | 13 |
| P14 | Rule 3 | "CARD BREATHING ROOM: ... at least 80-90px height and 180-220px width ... at least 20px from borders" | CONTENT (aesthetic) | REMOVE | style numbers presented as physics; the text-fit fact (P15) already protects readability | 14 |
| P15 | Rule 3 | "TEXT FIT (rendering fact): a label is about 0.5 x font-size px wide per character ... stacked lines at least 1.3 x font-size apart" | RECORDING | KEEP | a measurable fact, and what the label-overlap check enforces | 15 |
| P16 | Rule 4 | "[[MARK:element_id]] MUST appear in the VERY FIRST SENTENCE of the narration" | RECORDING | KEEP | timing protocol | 16 |
| P17 | Rule 4 | CORRECT: "[[MARK:tcp_handshake]] Here we can see the TCP three-way handshake — the client sends a SYN packet to the server..." / WRONG: "The TCP three-way handshake is how connections are established..." | CONTENT (example) | REWRITE | replace with an abstract format: `[[MARK:<element_id>]] <what you say as it appears>`; the example is where "Here you see ..." comes from | 17 |
| P18 | Rule 4 | "[[MARK:...]] belongs ONLY in the narration ... Narration must be plain text only" | RECORDING | KEEP | | 18 |
| P19 | Rule 5 | six styles: circle "loops an elliptical sketchy ring", underline, tick "emerald-green checkmark (e.g. ... verified, passed, or completed)", cross "rose-red crossmark (e.g. invalid state, rejected path, cache miss)", highlight, arrow | MIXED | REWRITE | keep what each style draws; drop the "e.g." meanings (they suggest when to use it, in software terms) | 19 |
| P20 | Rule 5 | `note`: "(e.g. "Key step!", "Bottleneck", "O(1) lookup")"; lifetime guidance | CONTENT (examples) | REWRITE | keep ephemeral vs permanent definitions; drop the examples | 20 |
| P21 | Rule 6 | "you will receive a spatial grounding prefix": `[Learner circled diagram element(s): 'gateway_node' (Api Gateway) (0.92 match)]` | RECORDING | KEEP (swap the example ids for neutral ones) | the format is a protocol; the example names a networking topic | 21 |
| P22 | Rule 6 | "Direct your explanation to this component's specific role, responsibility, and internal behavior"; two elements: "Deeply explain the communication protocol (REST, gRPC, WebSocket, pub/sub), data payload flow, synchronous vs asynchronous behavior, failure handling"; "MANDATORY: Use annotate_element with style="arrow"" | CONTENT (software-specific) | REWRITE | keep "the learner is pointing at these elements; answer about them; for two elements, about how they relate"; drop the protocol list and MANDATORY | 22 |
| P23 | Rule 7 | "PROPOSE a new page in your chat reply and wait; the learner may decline ... Once the learner agrees ... call start_new_page" | CONTENT (product flow) | KEEP | decision 1 of the original plan, deliberate | 23 |

## In the tool descriptions (`TOOLS`)

| ID | Tool / field | Quote | Type | Decision | Why | old # |
|---|---|---|---|---|---|---|
| T1 | start_new_page | "Call it when the learner agrees to (or asks for) a new page ... or when the current page has no free space left and the learner has agreed" | CONTENT (product flow) | KEEP | goes with P23 | 23 |
| T2 | get_current_page_state | "Always check this before drawing to choose an unoccupied zone and prevent overlaps." | RECORDING (wasteful) | REWRITE | keep what it returns; drop "always check" (see P9) | 28 |
| T3 | draw_new_element | "MUST be a complete, self-explanatory diagram component (e.g. `<g id='element_id'>` with container card rect, title `<text>`, labeled sub-boxes, and flow arrows). NEVER draw bare, unlabeled shapes. Everything spoken in the narration must be visibly labeled." | CONTENT | REWRITE | keep "one `<g id>` group"; drop the card/title/sub-box/arrow recipe and "everything spoken must be labeled" | 24 |
| T4 | draw_new_element.svg_fragment | "Must include container shape, title `<text>`, labeled sub-components, and flow arrows." | CONTENT | REMOVE | every element must contain arrows and sub-components | 24 |
| T5 | draw_new_element.svg_fragment | "Must use absolute x/y coordinates. No transform attributes. Fits within 1200x800 canvas." | RECORDING | KEEP | add that rotation is not supported, so the tutor stops trying it | 25 |
| T6 | draw_new_element.narration | "Write a full, in-depth spoken explanation (80-200 words) as if you are a professor explaining this specific visual to a curious student in office hours." | CONTENT | REWRITE | drop the length range and the persona. Measured over 3 baseline runs: median 52 words, range 16-146, only 21 of 71 narrations inside 80-200, so the rule is mostly ignored already. If you want cost control, cap the maximum in code (about 1,000 characters is a number to discuss) instead of a minimum in the prompt | 26 |
| T7 | draw_new_element.narration | "[[MARK:element_id]] MUST be the very first thing ... Example: '[[MARK:cpu_diagram]] Here you can see the CPU...' ... Plain text only" | RECORDING + example | REWRITE | keep the rule; drop the example (same copy problem as P17) | 17, 26 |
| T8 | modify_existing_element | "Corrects a specific named element you drew earlier ... Touches ONLY the named element ... Use this for immediate corrections, not for redesigning the whole page." | MIXED | KEEP | describes what the tool does (replaces one element) | 27 |
| T9 | annotate_element | style enum, `annotation_id` example 'ann_circle_cache', colour hex examples, note examples 'Bottleneck!', 'O(1) lookup', narration example "Notice how this cache layer intercepts requests before the database..." | MIXED | REWRITE | keep the enum and field meanings; drop the software examples | 19, 20 |
| T10 | remove_annotation | "Removes a specific annotation mark when moving to a new topic or clearing old focus marks." | RECORDING | KEEP | | 28 |

## In code (not shown to the tutor unless noted)

| ID | Where | What it does | Type | Decision | Why |
|---|---|---|---|---|---|
| C1 | `validator.find_layout_issues` | any rectangle at least 120x40 with no child rectangle and no text whose centre lies inside it gets: "The card at x=.., y=.. has no label inside it." | CONTENT | REMOVE (or keep as a log only) | a colour band in a timeline is "unfinished". ADVISORY (non-blocking). Shown 1, 1 and 0 times in the 3 baseline runs, so rare on these 8 topics; the topics do not draw timelines or maps |
| C2 | `validator.find_layout_issues` | any rectangle at least 200x200 with children whose lowest edge leaves more than 30% empty at the bottom gets: "shrink it to fit its content or add the missing items." | CONTENT | REMOVE (or keep as a log only) | a region with a few places near the top is "81% empty". Bottom edge and rectangles only. ADVISORY (non-blocking), same frequency as C1 |
| C3 | `validator.check_overlap` | a new element covering more than 20% of the smaller of the two boxes is rejected (blocking, retry) | MIXED | REWRITE | keep rejecting partial overlaps (they hide labels); allow an element that sits fully inside a larger container. Overlap caused 3, 2 and 4 of the retries in the baseline runs (9 of 33), mostly a detail placed inside its own overview panel |
| C4 | `author._transform_error` | any `transform` attribute is rejected (blocking) | RECORDING | KEEP | measurement reads plain coordinates. Cost: no rotated text, e.g. a graph's y-axis label (2 of 17 rejections) |
| C5 | `author._handle_draw_new_element` step 0 | a `<rect>` with width > 800 or height > 600 is rejected as a "full-canvas background rect" (blocking) | RECORDING | REWRITE | wrong thresholds: it caused 2, 3 and 6 of the retries in the 3 baseline runs (11 of 33 = one third). It also has no test |
| C6 | `engine/voice._calculate_marker_timings` | a marker later than 40% of the audio is moved to time 0 | RECORDING | KEEP | timing safety net for a mis-placed marker |
| C7 | `validator.check_density` | soft nudge at 15 elements or 70% fill (advisory text "consider wrapping up"); hard cap at 25 (blocking) | CONTENT (pacing) | KEEP, re-tune | never reached by real pages in the 8-topic runs (max 7 elements, 0.35 fill) |
| C8 | `validator.validate_geometry`, label overlap, duplicate ids | out of canvas, overlapping labels, duplicate ids rejected (blocking) | RECORDING | KEEP | physical |
| C9 | `validator.validate_geometry`, "Semantic Whiteboard Rule" | any fragment containing a rectangle of at least 120x60 and no `<text>` anywhere in the same fragment is **rejected** (BLOCKING, forces a retry): "Diagram card has no <text> labels. Every whiteboard diagram card must include descriptive <text> labels inside so the student can read the concepts." | CONTENT | REMOVE | **Missed in the first audit** (I listed only the advisory hints C1 and C2). With the prompt no longer demanding labels it caused 243 of the 259 retries in baseline C (see BASELINE.md). Same idea as C1, but blocking and checked per fragment, not per shape |

## Count

| | KEEP | REWRITE | REMOVE |
|---|---|---|---|
| System prompt (24) | 9: P3 P6 P7 P12 P15 P16 P18 P21 P23 | 9: P0 P1 P8 P10 P13 P17 P19 P20 P22 | 6: P2 P4 P5 P9 P11 P14 |
| Tool text (10) | 4: T1 T5 T8 T10 | 5: T2 T3 T6 T7 T9 | 1: T4 |
| Code (9) | 4: C4 C6 C7 C8 | 2: C3 C5 | 3: C1 C2 C9 (C1, C2 or log only) |

Compared with the removal list in my last message (old rows 5, 9, 11, 14, 17, 22, 24, 26): that list lumped REMOVE and
REWRITE together. Here, old 9 (P8), 17 (P17), 22 (P22), 24 (T3) and 26 (T6) are REWRITE, because each has a recording
part worth keeping (the MARK protocol, the pointer format, the `<g id>` group, the spoken-aloud/plain-text rule), and
old 5 (P4), 11 (P11) and 14 (P14) are REMOVE. Rule 3 and Rule 2 are in the table as P8-P14; Rule 6 as P21-P22.

## The background-frame guard (C5 / P1): what it was meant to stop, and one shared constant

**Intent.** Stop the model drawing a full-canvas rectangle as a "slide background". Evidence in the code: the guard's
comment ("reject full-canvas background rects before they pollute the page", `author.py:467`), the prompt's Rule 0
("The canvas background is already set by the frontend. Your job is to draw CONTENT, not frames"), and the validator,
which already skips frames when measuring (`validator.py:251, 334, 391, 444`: width >= 1100 and height >= 700). A frame
painted over the board hides the paper colour and grid, and would count as an element that overlaps everything and fills
the page. The guard arrived in the first commit (`a082f42`, adopted from the earlier code), so git history does not
record a specific incident.

**What went wrong.** There are two definitions of "frame". The guard says width > 800 **or** height > 600; the validator
says width >= 1100 **and** height >= 700. The guard's "or" rejects any wide strip: 5 of the 17 retries in the first
8-topic run and 11 of 33 in the three baseline runs were wide cards of 70-400 px height that were not frames at all
(`supply_demand_intro` 1100x70, `newtons_three_laws` 1100x70, `wwi_causes_overview` 1080x250, `photosynthesis_overview`
1080x400, `handshake_diagram` 1100x300). The error text tells the tutor it drew a "full-canvas background rect" with
`height=70`, which is false. The prompt's own header zone (Rule 3, x 50-1150) is 1100 px wide. No test covers the guard.

**Proposal: one constant, defined by what a frame is (how much of the board it covers).**

```python
# engine/validator.py (next to CANVAS_WIDTH / CANVAS_HEIGHT)
FRAME_CANVAS_FRACTION = 0.6        # a single shape covering at least this share of the canvas is a background frame

def is_background_frame(width, height):
    return width * height >= FRAME_CANVAS_FRACTION * CANVAS_WIDTH * CANVAS_HEIGHT
```

Used in five places that today each have their own numbers: the author guard, the three skips in `validator.py`
(`find_layout_issues`, `validate_geometry`, `extract_element_bboxes` and the label-box filter), and the prompt text,
built with an f-string: `a single shape covering more than {round(FRAME_CANVAS_FRACTION * 100)}% of the canvas`.

| shape | share of canvas | old guard (>800 or >600) | proposal (>= 60%) |
|---|---|---|---|
| 1200x800 background | 100% | reject | reject |
| 1100x700 | 80% | reject | reject |
| 1000x650 | 68% | reject | reject |
| 1080x400 `photosynthesis_overview` | 45% | reject | allow |
| 1100x300 `handshake_diagram` | 34% | reject | allow |
| 1080x250 `wwi_causes_overview` | 28% | reject | allow |
| 1100x70 title strip | 8% | reject | allow |

0.6 is a first guess in the same spirit as the density limits: it should be tuned by watching what the tutor draws. A
test that fixes the table above (frames rejected, strips allowed) should come with the change.

**Implemented (approved 2026-10-07).** `FRAME_CANVAS_FRACTION = 0.6` and `is_background_frame(w, h)` live in
`engine/validator.py` and are used by the author guard, the four frame skips in the validator and the prompt (the prompt
text is built from `FRAME_PERCENT`; the number is not typed in the prompt). The guard's error message now says what was
measured ("a rect of 1200x800 covers 100% of the canvas (the limit for a single shape is 60%)") instead of calling a
1100x70 strip a "full-canvas" rect. Tests: `tests/test_frame_guard.py` (boundary 960x599 passes, 960x600 and 960x601 are
rejected; 1100x70 and 1080x400 pass; a full-board rect over existing elements is rejected and nothing is saved).
`tests/test_density.py::test_coverage_soft_signal_without_many_elements` used a 1100x600 element (69% of the board);
under the new definition that is a frame, so the test now uses two elements that are each under the limit. The guard's
error text still ends with "Draw meaningful content: a concept box, a diagram component, an arrow, a label."; that is
a content example inside a guard message, left as is for now (see section 4 of the plan).

## Applied (Step 4, approved 2026-10-07)

All REMOVE and REWRITE decisions above were applied to the system prompt and the tool descriptions; code guards were not
touched in this step. The prompt went from about 11,100 to 5,800 characters. Specifically:

| ID | What changed |
|---|---|
| P0 | persona is "a one-on-one tutor teaching any topic on a live digital whiteboard ... explains by speaking and drawing together"; no "elite", "rich, expressive", "deep, intuitive" |
| P1 | frame rule states the share from `FRAME_PERCENT` (Step 2) |
| P2, P4, P5 | removed: "first draw must be a concept box...", the container + title + sub-label requirement, the list of ten visual forms. One sentence remains: the tutor chooses the form, colours and layout, and whatever the learner needs to identify should be identifiable |
| P8, P10 | "Drawing is your default way to explain ... A follow-up does not always need a new drawing: when words alone answer it better, answer in text. When the learner signals to continue, move the lesson forward." |
| P9, T2 | "call get_current_page_state first" removed; the tool description only says what it returns |
| P11, P14 | zone template and card-size numbers removed |
| P13 | "Keep connectors from running through labels." |
| P17, T7 | the copied TCP example and the WRONG/CORRECT pair are gone and nothing replaces them; the rule is stated in words (marker in the first sentence, with the element's own id; a later marker makes the visual wait) |
| P19, P20, T9 | each annotation style says what it draws; no "verified / invalid / cache miss" meanings, no note examples, no example ids or narration |
| P21, P22 | pointer prefix shown with neutral placeholders; the tutor is told the learner is asking about those elements (and how two relate); the protocol list and MANDATORY arrow are gone |
| T3, T4 | `draw_new_element` is "a new named element, drawn as one `<g id>` group"; no card / title / sub-box / arrow recipe |
| T5 | kept the recording facts and added "rotation included" to the no-transform rule |
| T6 | narration: "At most 200 words (it is spoken, and speech has a cost)"; the "80-200 / in-depth / professor" wording is gone, so there is a ceiling and no floor |

Kept unchanged: ids, absolute coordinates, no transform, canvas bounds, the 30 px gap, the text-fit fact, the marker
protocol, arrowhead markers, the page-proposal flow, modify/remove tool descriptions. `tests/test_prompt_rules.py` pins
all of this: 17 recording rules must be present, 50+ content rules and examples must stay out.

## C9 applied (approved 2026-10-07)

The blocking label rule is now a log note: `validate_geometry` no longer rejects a card-sized rectangle with no `<text>`
in its drawing; `has_text_less_card` keeps the condition and the draw handler logs `unlabeled_card_note` (not shown to
the tutor). C1 and C2 (the two advisory hints) are unchanged. No page-level check was added: in A, B and C, 35-47% of
final boards have a text-less card-sized rectangle (A and B included, where drawings were fine), so such a check would
flag normal drawings. The eval gets an "elements with no text" metric instead.
