# Proposed validator design: shape-level checks for boxes, labels and connectors (design review only, 2026-10-14)

Status: a proposal. Nothing is implemented; no code, rule, prompt or behaviour was changed. Basis: `docs/CONNECTOR_OVERLAP_EXPERIMENT.md` (variants A to D and the diagnostics), `docs/WRAP_LIBRARIES.md` (thin-line and arrow-head detectors), `docs/CAPABILITY_INVENTORY.md`, and the current `engine/validator.py`.
Tags used below: **DEMONSTRATED** = shown by an experiment or by reading the code, **HYPOTHESIS** = my reasoning, not yet tested, **CHOICE** = a design decision for the owner.

## 0. What is demonstrated today (the three problems)
1. **Union boxes.** An element's box is the union of its shapes, so the gaps between boxes count as occupied. The six-box diagram is one element (x 60-1040, y 120-300); the connector element (790 x 140) lies fully inside it. DEMONSTRATED (variants B, B').
2. **Thin shapes are ignored.** A shape thinner than 20 px is skipped on either side. 66 of 66 connector/box pairs were "ignored (thin)"; connectors that cross box interiors and label text (8 of 11 in the agent's own geometry) were accepted in variants A, C and D. DEMONSTRATED.
3. **No shape-to-shape check inside one call.** Two identical boxes pass in one call and fail in two (E). Inside a call only canvas bounds per shape and label against label are checked. DEMONSTRATED.
Also DEMONSTRATED: the pill labels (72 and 56 percent over the User box) are a genuine overlap; the connector rejections were mostly for the wrong reason (union box) and, where the reason was right (crossing a box or label), it was not what the validator measured.

## 1. The design in plain words
Today the validator asks "does this whole new element overlap any whole existing element?" The proposal asks the question one level down: "do the individual **shapes** collide, and does it matter?" It gives every shape a **role** and applies different rules per role, in the same way for a new call, for shapes inside the same call, and for existing page content:
- **Node** (a box or circle with a label inside it) and **container** (a frame that holds other shapes, or a shape with no fill): regions.
- **Label** (text): a box estimated from its text and font size.
- **Connector** (a line, polyline or path with no fill, with or without an arrow head): drawn as a thick line, curved ones cut into short straight pieces, plus the head triangle.
Rules by role: boxes may not overlap other boxes; labels may not sit on other labels or on someone else's box; a connector may touch the **edge** of a box (within a small band) but may not run through a node's interior or through a label; connectors may cross containers and each other. Intentional overlaps stay legal: a label inside its own box, a box inside a frame, and the shapes of one picture that overlap by design (a Venn diagram, an icon).
The unit of intent stays the `<g id>` element: it is still what is drawn, annotated, edited and undone. Only the question the validator asks about it changes.

## 2. Rules and their order (cheap first; all run on the shapes of the new call against the page, then among the new call's own shapes)
0. **Unchanged rules first:** transform, background frame, id uniqueness, sanitiser, canvas bounds per shape, hard cap. (The canvas check must also cover text width, a separate gap.)
1. **Extract shapes** from the sanitised XML (ElementTree, not regexes; this also fixes nested `<g>` being cut at the first `</g>`). Per shape: role, geometry (rect or ellipse bounds exact; polygon; connector as a flattened polyline with half stroke width; arrow head triangle at the end, from the board's three known markers, 8 x stroke width), owner element id. HYPOTHESIS: roles are decided by simple tests: text is a label; no fill and open, or `marker-*` present, means connector; a closed shape that contains the centre of a label is a node; a closed shape that fully contains another region, or has no fill, is a container; the rest are decorations (nodes without labels).
2. **Region against region, across elements** (replaces the union-box comparison): the present rule (more than 20 percent of the smaller box covered, shapes under 20 px skipped), but between individual shapes of different elements. Nesting (smaller fully inside larger, at most 80 percent of its area) is allowed; this is what lets a card sit in a frame.
3. **Label against label and label against region, across elements:** the 30 percent label rule extended to labels already on the page, and a label may not sit on another element's node (more than 30 percent of its estimated box).
4. **Connector against nodes and labels (new, everywhere, including inside one call):** let the "interior" of a node be the node shrunk by an attach band of max(4 px, stroke width) on every side. Reject when the centre line (plus half stroke width) has more than 8 px of length inside the interior of any node, or crosses a label box (more than 6 px). Allowed: touching or ending on the edge band; running along an edge; crossing containers and other connectors. The arrow head triangle is checked the same way: the tip may be in the band, its body may not enter the interior deeper than the band. HYPOTHESIS: 4 px, 8 px and 6 px are starting values to be tuned in shadow mode.
5. **Inside one call, region against region (narrow):** reject only near-duplicates (the smaller shape at least 90 percent inside the larger and the areas within 20 percent: a stacked box). Partial overlaps inside one element stay legal because intersecting circles and icons are drawn that way (the stored GPS drawings have intersecting spheres). CHOICE: this deliberately leaves the case "a pill straddling a box inside one call" legal while the same geometry across two calls stays rejected; the principle is that one element is the unit of intent, and rules 4 and the near-duplicate rule apply to intent that is never legitimate.
6. **Connector against connector:** crossings allowed; reject two connectors that run on top of each other (same line, more than 20 px shared, as the request and response arrows the agent drew on identical coordinates). HYPOTHESIS, lowest priority, could be a hint.
7. **Density and everything after:** unchanged.
Order reason: bounds and roles are cheap and exact; region rules before connector rules because connector rules need the classified regions; the narrow intra-call rule last because it only ever rejects obvious duplicates.
The same function is applied to `modify_existing_element` (today it skips the overlap check), with the old shapes of that element removed from the page first. HYPOTHESIS, phase 4.

## 3. Cases that should be accepted or rejected (expected results by reasoning, NOT run; the experiment results for today are DEMONSTRATED)
Regression set from the experiment (the agent's geometry as drawn):
| Case | Today | Proposed |
|---|---|---|
| A one call, as drawn | accepted | REJECTED: 8 connectors run through a box interior and label text (names the connector, the box and the length); 3 pass (2 short gap arrows, 1 along the bottom edges). Intentional change |
| B and B' connectors call, as drawn | rejected (union box) | REJECTED for the true reasons above; pills rejected (72 and 56 percent over User) |
| C each connector alone | all 11 accepted, pills rejected | 8 REJECTED, 3 accepted, pills rejected |
| D each box its own element, connectors alone | all accepted | 8 REJECTED, 3 accepted |
Same four with the geometry corrected (each connector starts and ends on a box edge in the gaps, labels in free space): A accepted, B accepted, C accepted, D accepted. The gaps are free because the union box no longer exists. Expected, HYPOTHESIS.
Additional cases:
- Connector crossing text only (in a gap, over a caption): REJECTED (rule 4, label).
- Connector ending on a box edge, head tip within the band: ACCEPTED. Connector ending 10 px inside the box: REJECTED with the nearest edge point in the message.
- Two overlapping boxes in one call: identical stack REJECTED (rule 5); 30 percent partial overlap ACCEPTED (CHOICE); the same two in two calls REJECTED (rule 2, unchanged).
- Curved connector from one box edge to another through free space: ACCEPTED. The same curve with its bow through a third box: REJECTED. A curve whose control point lies in a box but whose curve does not: ACCEPTED (a box test on control points would reject it; shown in the thin-line experiment, case 9).
- Label inside its own box: ACCEPTED. Label inside another element's box: REJECTED.
- Connector inside a container frame (headphones overview style): ACCEPTED; across a node inside the frame: REJECTED.
- Venn circles in one element: ACCEPTED; as two elements: REJECTED (unchanged).
- Modify: a box resized over an existing connector: REJECTED (phase 4).

## 4. False positives, false negatives, cost
False positives (a good drawing rejected): HYPOTHESIS, all untested on real data.
- Role mistakes: a container taken for a node (an outlined panel that holds only text) would reject connectors that cross it; a node taken for a container lets them through.
- Text width is an estimate (0.5 to 0.55 em per character); a connector close to a label can be rejected wrongly or accepted wrongly. Browser measurement is not available in the backend.
- Rough.js redraws shapes with a wobble of about 2 to 3 px; the band of 4 px covers it, a thinner band would not.
- The model's present habit (arrows that start inside a box, centre to centre) will be rejected: correct, but the number of rejections will rise at first and the messages must teach "start at the edge". In the real sessions 21 percent of draws were already rejected, and the overlap message round did not reduce rejections.
- Intentional overlaps inside one picture (decorations, shadows) are kept legal by rule 5 being narrow.
False negatives (a bad drawing accepted):
- Partial overlaps inside one call (rule 5 is narrow by choice); a connector hidden under a filled node of a LATER element is caught only when that node is drawn (rule 2 treats it as a region overlap with a thin shape: ignored; a node drawn over an existing connector is not caught today and would need the connector to count as an occupant of its own line).
- Connector against connector crossings (allowed by design); labels outside the band but touching strokes; dashed or round-capped ends; curves flattened coarsely; arcs (today only the end point is read: needs a proper flattening).
- Nothing guards the arrowhead of markers other than the board's three.
Performance (HYPOTHESIS): pages have at most 25 elements and the sanitiser caps a fragment at 500 elements; typical 20 to 250 shapes. Connector pieces about 100, nodes plus labels about 150: about 15,000 segment-against-box tests per call, a few milliseconds in Python; parsing a 20 KB fragment with ElementTree is a few milliseconds and replaces regexes. Not measured.

## 5. Geometry only, or explicit connector references?
Geometry only (the design above): no change to the frozen prompt or tool text, works for any connector the model writes, and the attach band recovers the intent "this touches the box". It still infers intent from positions, so it cannot say that an arrow points at nothing or at the wrong box, and cannot check "do not omit any connection" (a Test 2 requirement). That is the weakness.
Explicit references (`from` and `to` element ids on each connector, for example as `data-from` and `data-to` attributes, which the sanitiser would have to allow, or as tool parameters): the validator could confirm that each end lies on the named box, report missing links, move or reroute connectors when a box moves, and the learner could circle a link. Costs: it needs the frozen tool text or prompt to tell the model (owner decision), more tokens, a new failure mode (wrong or missing ids), and the founding principle limits what code may do with it (it may check that an end touches the named box, but must not place the connector for the model). HYPOTHESIS: references improve long-term reliability, mainly for completeness checks and editing; this is not demonstrated and is not needed for the three problems. Recommendation: build the geometry-only design first; keep the connector role and owner id in the shape model so references can be added later without redoing it; decide on references after shadow-mode data show how often geometry alone misreads intent.

## 6. Incremental implementation and regression-testing plan (each step reversible, one flag)
0. **Corpus and golden outcomes, no behaviour change.** Fixtures: the 41 stored drawings, the six-box variants A to D (as drawn and with corrected geometry), the thin-line and card cases, the new cases of section 3. Record today's outcome per case.
1. **Shape model as pure functions:** extraction, roles, flattening, arrow-head triangle, segment-against-region. Property tests like the free-region tests (random layouts: the brute-force answer equals the function's answer) and the experiments' cases as unit tests. No wiring.
2. **Shadow mode:** run the new rules beside the old on every draw and offline on the corpus and the GPS replay; log `would_reject` with the reason; outcomes unchanged. Decide thresholds from the false-positive rate on the stored drawings and the screenshot-review labels. Owner approves the exact new message wording first (tool results are not frozen).
3. **Enforce the smallest part first: rule 2 at shape level** (problem 1: the gaps become free, no new rejection of anything that was legal). Then rules 3 and 4 for connectors against nodes and labels (problem 2), after the shadow data. Messages name the connector, the box or label, the length and the nearest edge point; repeat cap as for overlaps.
4. **Intra-call rules** (problem 3: rule 5 and rule 4 inside one call), then the check on modify.
5. **Optional:** connector-on-connector, and references (section 5), only with the owner's decision.
Live check at each enforced step: the two prompts from Tests 1 and 2, three runs before and three after on gpt-4.1, under the standing rule that a change counts only when all runs are outside the before-range; count rejections by reason, retries, connectors present (completeness), failed turns, seconds per turn, and the unit tests (in-process suite) green. Keep the old behaviour behind a switch until two clean rounds.

## 7. Demonstrated versus not yet known
DEMONSTRATED: the three problems and their causes; per-variant outcomes today; that a segment test with half stroke width and an arrow-head box classifies thin lines, diagonals, curves and arrow heads correctly on 13 hand-made cases (thin-line experiment); that the card preflight reasoning works on 29 new cases; the agent's geometry crosses boxes and labels (8 of 11 connectors).
HYPOTHESIS: every threshold and the role rules; that no legitimate drawing in the stored data would be rejected; the cost figures; that the rejection messages will lead the model to attach connectors at box edges; that references would pay off; that enforcing the connector rules raises rejections first and lowers broken diagrams later.
