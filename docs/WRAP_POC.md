# Text wrapping proof of concept (isolated experiment, 2026-10-11; nothing in the app changed)
Test page (not in the repo): scratchpad `wrap_poc/index.html`; it copies `roughifySvgFragment` (same options, plus a fixed seed so both sides draw the same rectangle), embeds the app's Inter font, and measures with the browser (`getComputedTextLength`, `getBBox`), not the backend estimate.
Subject: stored `gps_signal_content`: one `rect` 240x110 at (850,250), rx 18, and three centred `text` lines (21 px title, two 16 px lines). Padding kept free: 12 px each side (216 px usable). Wrap: at spaces, greedy, one `<tspan x=anchor dy=1.2em>` per extra line. The rectangle and other elements are not moved.
## Case A: the stored card (real data)
- The title is really 280 px wide (backend estimate 323): it sticks out 20 px on each side of the 240 px card. The other two lines (128 and 188 px) fit.
- After wrapping: 2 lines (widest 205 px), inside the card. Rough rectangle paths identical; font size, colour, anchor and x/y of every text identical.
- But the second title line lands on "1. The exact time": 128 x 16 px of overlap, because the lines below were not moved.
## Case B: same card, deliberately long labels (temporary)
- Widths 636, 443 and 429 px in a 216 px usable width. Each wraps to 3 lines (widest 216, 176, 208), all inside the card's left and right edges.
- Text runs 22 px past the bottom of the card (card not resized) and the three groups of lines overlap each other (176x41, 208x16, 176x33 px), since each starts at its original baseline.
## What it cannot handle (as built)
- Neighbouring text below a wrapped label is not moved down, so it collides; the card is not made taller. Both are needed for a correct result, and both change the model's layout (a decision for the owner).
- It needs the browser (real font): the backend cannot know the width, so the check and the wrap have to run in the front end; the stored SVG would keep the long single line unless the result is saved back.
- Only text whose anchor lies inside a `rect`; circles/ellipses (the headphones labels) need an inscribed-width rule; a text sticking out of a shape from outside is untouched.
- Rough.js draws `rect` without `rx` (the rounded corners are not in the app today either; same on both sides).
- A single long word wider than the line cannot be split; it still overflows. Newlines inside one `<text>` are collapsed to a space by SVG and are not treated as breaks here.
- Line height 1.2em is assumed; modify events and the validator's 80 px text box are not touched.
