# Capability inventory of the drawing system (read-only map, 2026-10-14)

Nothing was changed to make this. Sources read: `engine/sanitiser.py`, `engine/author.py` (tools, handlers, system prompt), `engine/validator.py`, `backend/page_state.py`, `frontend/src/services/roughRenderer.ts`, `frontend/src/utils/roughAnnotations.ts`, `frontend/src/components/WhiteboardCanvas.tsx`, `frontend/src/utils/narrationPlayback.ts`, the stored drawings (41 draw calls and 1 modify, 3 notebooks, 15 pages) and the structured log (`logs/`, 30 Sep to 11 Oct 2026, including test and evaluation runs: 3,396 completed and 912 rejected draws, 1,173 chats).

Tags: **CODE** = confirmed by reading the code. **DATA** = observed in the stored drawings or the log. **NONE** = not implemented (no code path). **UNKNOWN** = not tested, or code present but never seen to work or fail.
A supported SVG tag is not a reliable diagram: where the code allows something but the data shows it is never used, that is said.

## 1. Primitive drawing
| What | Status | Evidence |
|---|---|---|
| `rect` (with `rx`/`ry`), `circle`, `ellipse`, `line`, `path`, `polygon`, `polyline`, `text`, `tspan`, `g`, `defs`, `marker`, `title`, `desc` | CODE (sanitiser allowlist) | `sanitiser.py:29` |
| Used in the 41 stored drawings | DATA | 162 `text`, 42 `circle`, 31 `ellipse`, 28 `rect` (22 rounded), 24 `path`; 0 `line`, `polyline`, `polygon`, `tspan`, gradient, filter |
| Curves: path commands C/Q/S/T/A | CODE (bounds parser reads them; arcs use only the end point) | `validator.py:224-251`; DATA: 10 of 24 stored paths are curves or arcs |
| Arrowheads: `marker-end="url(#arrow\|arrow-dark\|arrow-green)"`, markers are defined once by the board | CODE (prompt rule 1, `WhiteboardCanvas.tsx:867`) | DATA: 15 path uses carry a marker. The model cannot define its own marker size units (`markerUnits` is not allowed) |
| Gradients (`linearGradient`, `radialGradient`, `stop`) | CODE allowed; DATA never used; UNKNOWN how they render: the Rough renderer passes a rect's `fill` straight to Rough.js as a colour, and `url(#id)` is not a colour (not tested) |
| Filters (`feGaussianBlur`, `feMerge`, `feMergeNode`, max 10, blur capped at 30) | CODE; DATA never used. No `feOffset`/`feDropShadow`/`feColorMatrix`, so no drop shadow can be built |
| Dashes, opacity, caps/joins, fill and stroke opacity | CODE allowed; DATA dashes 3 fragments, opacity 2 |
| Rotation, scale, skew (`transform`) | NONE: rejected with a message (`find_transform`), 25 rejections in the log; the sanitiser also strips it |
| `style` attribute, `clip-path`, `mask`, `pattern`, `use`, `image`, `foreignObject`, animation tags, `fill-rule`, `font-style` (italics), `text-decoration`, `letter-spacing`, `textLength`, `marker-mid`, `markerUnits`, `fx`/`fy`, `gradientTransform`, `spreadMethod` | NONE: not in the allowlist, removed silently (the lost-content check tells the tutor only when text is lost) |
| Images, icons, LaTeX, emoji fonts | NONE (no `image`/`use`); emoji and symbols as plain text characters: UNKNOWN glyph coverage (the font is a subset of Inter) |
| Limits | CODE: 500 elements, path 10,000 chars, fragment 500,000 chars, 25 named elements per page (hard cap), soft nudge at 15 elements or 70% coverage |
| Text and shape styling by the model: colours, sizes, weights | DATA: `font-weight` in 32 of 41 fragments, `text-anchor` in 28 |

## 2. Text layout
| What | Status | Evidence |
|---|---|---|
| Measuring text width in the backend | NONE exact: an estimate of 0.55 em per character (`estimate_text_width`) for the advisory check; a fixed 80x20 px box for the blocking checks (`extract_element_bboxes`); 0.5 em in `_text_boxes` | `validator.py:268-286, 355, 623` |
| Measuring with the browser's font | CODE only for annotations (`svgBounds.getElementBounds` uses `getBBox`); not used for validation or layout |
| Wrapping | NONE. DATA: 0 `tspan` in 162 texts; the model writes one `<text>` per line (a paragraph is stacked texts about 30 px apart); a newline inside one `<text>` collapses to a space and is not a line break (DATA: "External\nMicrophone" in the headphones circles) |
| Anchoring (`text-anchor`, `dominant-baseline`, `dx`, `dy`) | CODE allowed; DATA `text-anchor` middle in 97 of 162 texts, start 65; `dominant-baseline` never |
| Fit of a label in its shape | CODE advisory only, log-only by an earlier decision (`find_text_width_issues`: canvas, card (rects only), neighbour). DATA: 39 of 109 labels inside a shape do not fit by the estimate (font sizes 14-24 only, none below 12: the tutor overflows, it does not shrink) |
| Text bounds against the canvas | CODE only the start point (x, y-14) is checked; a long line may run off the right edge (`validate_geometry`) |
| Label against label | CODE only inside one fragment, 30 percent of the smaller estimated box (`find_text_overlap`); not against labels already on the page |
| Fonts | CODE: Inter 400 and 700 are injected after sanitising (subset woff2 inlined, about 16 KB per page, stripped from what the model reads); the model's `font-family="Arial"` is overridden by the page style (DATA) |
| Text on curves (`textPath`) | NONE |

## 3. Spatial layout
| What | Status | Evidence |
|---|---|---|
| Coordinates | CODE: the model writes every x, y, width, height itself (absolute, 1200 x 800); nothing places or sizes anything for it. DATA: all 41 drawings |
| Canvas bounds | CODE: tolerance 10 px; checks rect, circle, ellipse, line, polyline/polygon, path (control points included), and text start. 81 rejections in the log |
| Background frame | CODE: one shape of 60 percent of the canvas or more is rejected (43 rejections) |
| Overlap | CODE: a new element is rejected when it covers more than 20 percent of the smaller of two element boxes; shapes thinner than 20 px are ignored on either side; text is a fixed 80 x 20 box; only the largest top-level shape of the new fragment is compared; an element drawn later by `modify_existing_element` is not overlap-checked. 351 rejections in the log (38 percent of all) |
| Containment | NONE as a rule: no check that a label is inside its box. DATA: 77 percent of labels in shape drawings are inside a shape by their anchor (109 of 141); the association is measured offline only |
| Free-space reporting | CODE: `occupied_regions` (one box per named element, regex based; a nested `<g>` would be cut at the first `</g>`) and `available_space` (three fixed columns reported open or not: it says "all main columns have content" as soon as one wide element spans them) with every request. New: an overlap rejection names one free rectangle computed on a 10 px grid (`find_free_region`) |
| Automatic positioning, snapping, alignment, distribution | NONE |
| Page capacity | CODE: soft and hard counts; the tutor is told to propose a new page, which the frozen prompt turns into asking the learner |
| Stored drawings | DATA: the drawings fill about a third of the board; labels overprint on 9 of 15 pages; a diagram frame was drawn over an earlier paragraph on 3 headphones pages (`docs/SCREENSHOT_REVIEW.md`) |

## 4. Connectors
| What | Status | Evidence |
|---|---|---|
| Straight connector | DATA: `path` with `M x y L x y` (14 of 24 paths); never `line` | CODE allows both |
| Curved connector | DATA: 10 of 24 paths; bounds use the control points, so a curve's box is larger than the curve |
| Arrowhead | CODE/DATA: `marker-end` with the board's three markers; the head is 8 x stroke-width wide (about 17 px for a 3 px stroke) and is not part of any box |
| Anchoring a connector to shapes, routing around obstacles, keeping ends on box edges | NONE: the model computes both end points |
| Collision of connectors with labels | CODE: prompt rule 3 asks for it; no check exists. A straight horizontal or vertical connector has a zero-width or zero-height box, so the overlap and growth checks cannot see it (verified in the preflight experiments) |
| Annotation arrow (`annotate_element` style `arrow`) | CODE: a fixed curve from the centre of the source box to the centre of the target box, head drawn by hand; no routing (`roughAnnotations.ts:171`); used 57 times completed, 43 failed in the log |

## 5. Complex diagrams
| What | Status | Evidence |
|---|---|---|
| Flowcharts, process chains, comparison cards, concept cards, lists, labelled objects, circles and spheres (GPS), timelines of boxes | DATA: stored drawings are cards, circles and ellipses with text, arrows between them |
| Hierarchies/trees, cycles, networks, sequence diagrams, Venn, charts and plots with axes, number lines, geometry with angles, equations | CODE: nothing forbids them (any shapes and text); DATA: none present in the 41 drawings (the GPS "spheres" are circles and an ellipse); UNKNOWN how reliable they would be |
| Structured diagram helpers (node-link layout, chart from data, graph layout, math typesetting) | NONE: no diagram templates or layout engine |
| Learner drawing on the board (pen, highlighter, eraser, circle/relationship gestures grounded to element ids) | CODE (`learnerGrounding.ts`, prompt rule 6) |

## 6. Live teaching
| What | Status | Evidence |
|---|---|---|
| Incremental drawing, one element per call with narration | CODE/DATA: 2,828 draw calls in the log |
| Reveal timed to speech | CODE: an element appears at its `[[MARK:id]]` time from the character timings of the audio (`narrationPlayback.ts`); the element appears all at once: no progressive stroke drawing, no fade-in (fade is used only for temporary annotations) |
| Stable ids | CODE: one `<g id>` per element, ids unique per page (3 duplicate-id rejections); the id is the handle for annotate, modify, undo, replay |
| Modify one element | CODE: `modify_existing_element` replaces the whole group; geometry and sanitiser checks only (no overlap, no density, no free-region help); not allowed on a saved page. DATA: 155 calls in the log (5 percent of tool calls), 1 stored modify |
| Delete an element | NONE as a tutor tool (the learner has Undo for the last drawing: `/undo`, `element_removed`); the tutor cannot remove or move an element except by replacing it with `modify` |
| Move/resize/reflow a neighbour after an edit | NONE |
| Annotations: circle, underline, tick, cross, highlight, arrow; ephemeral (fades after 3 s, 1-10 s) or permanent; remove by id | CODE; DATA 57 completed in the log |
| Replay with speed, export SVG/PNG/copy, zoom and pan, themes, hand-drawn toggle | CODE (`WhiteboardCanvas.tsx`) |
| Rough.js appearance | CODE: rect, circle, ellipse, line, polygon are redrawn rough (rounded corners `rx` are dropped; the same in both ways); `path`, `polyline`, `text` stay crisp; the roughness is 1.1; NO seed, and the whole page is rebuilt (`composedSvgContent`, every element roughified again) whenever the element map changes, so earlier shapes may re-wobble when a new element arrives: UNKNOWN whether this is visible (not seen in screenshots, which are static) |
| Rendering performance | CODE: the whole page is replaced through `dangerouslySetInnerHTML` on every change; UNKNOWN cost on a page of 25 elements (not measured). Per turn: 8 to 15 s on gpt-4.1 (measured earlier) |

## 7. Reliability
| What | Status | Evidence |
|---|---|---|
| Rejections (log, all history) | DATA: 912 of 4,308 draw attempts (21 percent): overlap 351, labels overlap each other 145, bleeds the canvas 81, background frame 43, transform 25, duplicate id 3, token cap 5, and 244 (27 percent) from an older rule that has since been removed (a drawing with a card and no text of its own was rejected); the rest are model or call failures |
| Recovery | CODE: the tutor gets the reason and may redraw; overlap messages name the element, the size and one free rectangle, and are capped at two full messages per element per turn; lost-content notes capped at two |
| Silent repairs | CODE/DATA: missing group wrapper (1,022 logged), marker not first in narration (954), `font-size"20"` missing equals (2), control characters replaced by a visible placeholder (64), HTML entities, stray `<` and `&` |
| Sanitiser limits | CODE: removes disallowed tags and attributes without telling the tutor unless text is lost (`engine/lossless.py`); malformed XML is recovered by `lxml`; 44 sanitise failures in the log |
| Failure of the turn | CODE: typed 503 for model failure or empty reply, 90 s model ceiling, 20 model calls per turn (iteration limit hit 3 times); browser errors are logged (`client_error`, 11) |
| Voice failure | CODE: the drawing still appears (silent); 7 audio failures in the log |
| Page-level quality check (does the finished board look right?) | NONE: no check after the whole board is drawn; the only automatic look at quality is hints that are log-only |

## The five capability gaps to investigate next (in order of evidence)
1. **Real text measurement.** The backend measures text by a guess (an 80 px box for the blocking checks, 0.55 em for the advisory ones), the tutor does not wrap, and 36 percent of labels in shapes do not fit. The check that would catch it is advisory and the bounds check reads only where text starts. (Investigated in `docs/WRAP_LIBRARIES.md`; not applied.)
2. **Placement and spacing.** The model computes every coordinate; free space is told in coarse columns or one rectangle after a rejection; 38 percent of all rejections are overlaps and 16 percent are labels on labels. Where drawings sit and how large they are (about a third of the board) is unmanaged.
3. **Connectors.** Plain paths with the model's own end points: no anchoring, no routing, and the collision checks cannot see straight horizontal or vertical lines or arrow heads (verified; a fix was only tested in an experiment).
4. **Diagram variety.** The stored drawings are cards, circles and arrows; trees, cycles, sequence diagrams, charts and plots, geometry and equations have no evidence of working and no helper code; gradients and filters are allowed but never used and their rendering under Rough.js is unknown.
5. **Editing a drawing that is already on the board.** The tutor can only replace a whole element, cannot delete one, gets none of the overlap or free-space help on a replacement, and nothing reflows the neighbours; add the unseeded whole-page re-roughening (possible visible wobble, not tested) and the instant (not progressive) reveal.
