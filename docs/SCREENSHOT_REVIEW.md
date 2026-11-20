# Look of the real sessions (screenshots of the stored notebooks, 2026-10-11)
Method: stored GPS (8 pages) and headphones notebooks opened in the app's browser pane (narrow pane, 100% zoom, so only part of the board is visible; the whole board was not checked).
Seen on the pages looked at (GPS pages 2-8, headphones page 2):
- GPS p.2-3: a tiny Satellite ellipse and Phone circle in a corner of the board; a connector line runs through the "Satellite" and "Phone" text; labels are very small.
- GPS p.4: the most crowded page; "Possible locations" is hidden behind the Sat 1 circle, "Possible locations from Sat 1" and "...Sat 2" overprint each other, "Satellite" and "Phone" overprint.
- GPS p.5-8: clearer (circles with labels), but text inside circles is tiny, "Phone" is a dot, and a few labels sit on circle outlines.
- Headphones p.2: text is wider than its circle ("ternal Microphone" is cut), and the last circle crosses the right edge of its frame.
Not seen: the audio, the reveal timing, the pages not opened (GPS p.1, headphones p.3-6).
Reading: the diagrams are drawable and understandable; the visible faults are small text, labels overprinting and text wider than its shape.

## Remaining pages (checked 2026-10-11; the board fits the pane at 100%, so these are whole boards)
- Headphones p.1: three circles sit below the frame with their labels cut; the three circles inside the frame are cut too ("External Microphone" wider than the circle); a long arrow row is half outside.
- Headphones p.3: a text box overflows its rectangle; the last circle crosses the right edge of the frame; a stray dot.
- Headphones p.4: the diagram frame covers the intro paragraph; three stacked text blocks and two wavy lines overlap each other and run off the bottom of the page.
- Headphones p.5: the diagram frame sits on top of the paragraph, whose lines run off the right edge; the last circle is cut by the frame.
- Headphones p.6: a plain numbered list, clean (the only page with no fault).
- GPS p.1: "Orbits Earth" sits on top of "GPS Satellite", "Receives Signals" prints over "Your Phone", and the arrow ends inside the phone circle; otherwise readable.
Count over all 14 pages: 1 clean (headphones p.6); about 9 with overprinted or cut text; 4 with a drawing on top of other content (headphones p.3, 4, 5 and GPS p.4). Headphones pages repeat the same four-circle diagram with the same cut labels.

## Why the guard lets these through (read-only; stored events replayed through the validator in draw order, 2026-10-11; script: scratchpad `why_pass.py`)
1. **A text element is measured as a fixed 80 x 20 px box, however long it is** (`extract_element_bboxes`, `engine/validator.py:623`). Headphones p.4 `basic_concept_intro` is stored as box (60,114,80,110) but its lines are about 540-940 px long (estimate). The diagram frame drawn next (`overview_components`, x 420-1210) does not touch an 80 px box at x 60-140, so `check_overlap` says pass. Same on p.5. Replayed result: overlap_check = pass for every draw event on headphones p.3, 4, 5.
2. **The canvas-bounds check only looks at where a text starts** (`validate_geometry`, line 477: x and y-14, width 0). A paragraph that starts at x=60 and runs to x=1300 (estimate) is valid. Headphones p.5 draws two lines estimated 78 and 117 px past the right edge; geometry = ok.
3. **The text-width check exists and finds them, but only advises** (`find_text_width_issues`: kinds canvas, card, neighbour; the hint is log-only by an earlier decision). Replay: it flags the paragraph lines past the card edge (p.3: 247-278 px, p.4: 44-158 px), the last circle label past the canvas (24 px), and the GPS p.4 labels running into the circle. Nothing is blocked.
4. **The width check looks only at rectangles ("cards")**, not at circles and ellipses: a label wider than its circle ("External Microphone" in a 90 px circle) is never compared with the circle, only with the canvas edge.
5. **The overlap check is 20 percent of the smaller box between two whole elements**, and ignores shapes thinner than 20 px. GPS p.4: the two circle groups overlap by about 7 percent, so pass; the overprinted labels inside one group are never compared with the shapes of that group, and a modify event is not overlap-checked at all (gps_circle_demo was widened by a modify).
6. **Text against other existing text:** `find_text_overlap` compares labels inside ONE fragment only, so a label drawn later on top of an earlier label on the page is not seen (GPS p.4 labels), except when it also meets rule 5.
Caveat: the 0.55 em width factor is an estimate (the screenshots show real lines shorter than the estimate on p.4/p.5), so the exact overflow amounts are approximate; the direction (text reaches under the frame / past the edge) matches the screenshots.
Founding rule applies to any change: constrain how the tutor records the drawing (measure and report honestly), not what it draws.

## Label that does not fit its box: overflow or shrink? (stored draw events of all 3 notebooks; script: scratchpad `fit_stats.py`)
109 labels sit inside a rectangle, circle or ellipse. By the 0.55 em width estimate 39 do not fit (they run past the shape) and 70 fit. Font sizes used: 14 to 24 only; NONE below 12. Labels that do not fit use the same sizes as those that fit (14-22 against 14-24): the tutor does not shrink text to make it fit, it keeps the size and the text extends outside the shape (e.g. 18 px "External Microphone", about 188 px, in a 140 px circle; 16 px lines of about 500-600 px in a 460 px card). The "tiny" text in the screenshots comes from the board being scaled down to the pane (14 px at about 60 percent), not from small font sizes. Caveats: width is an estimate; a font-size set on a parent group (not on the text) is counted as 16; modify events not included.
