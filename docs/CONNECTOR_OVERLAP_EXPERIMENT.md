# Why connectors are rejected: the six-box architecture diagram (isolated experiment, 2026-10-14)
Geometry: the six boxes, 11 connectors and 2 label pills that the agent itself wrote in Test 2 (taken from the log, notebook `1715375a...`). Method: the REAL draw handler (`engine.author._handle_draw_new_element`: sanitiser, geometry, overlap, density) with the audio faked and output in the scratchpad; no production file, rule or prompt changed. Script: scratchpad `connector_variants.py`.

## Results
- **A, one call (boxes, labels, 11 connectors, 2 pills): ACCEPTED.** One element on an empty page; nothing to compare with.
- **B, boxes, then connectors and pills together: boxes accepted; `connectors` REJECTED** ("overlaps existing 'boxes' (x:60-1040, y:120-300)", the new element is 790 x 190).
- **B' (the agent's own three calls: boxes, arrows, labels): boxes accepted; `arrows` REJECTED (790 x 140) and `labels` REJECTED (130 x 106).** Identical to the log of Test 2.
- **C, boxes, then each connector in its own call, then each pill in its own call: boxes accepted; all 11 connectors ACCEPTED; both pills REJECTED (130 x 36 each, against `boxes`).**
- D (diagnostic, not asked): each box as its own element, then each connector alone: all 6 boxes and all 11 connectors ACCEPTED.
- E (diagnostic): two identical boxes drawn on top of each other (labels apart): ONE call = ACCEPTED; the same two in TWO calls = the second REJECTED. (With the two labels at the same spot the one-call version is rejected too, by the label-overlap check, which does work inside a call.)

## Why (read from the code and checked on this geometry)
- The overlap check compares ELEMENT boxes: a new element's box against the box of each existing element, where an element's box is the union of all its shapes. The six boxes are one element whose box is x 60-1040, y 120-300 (980 x 180), so every gap between the boxes counts as occupied. The 11 connectors are one element with box 790 x 140 lying completely inside it (100 percent of the smaller box, limit 20 percent).
- A shape thinner than 20 px is ignored on either side. Each connector alone has a zero-height or zero-width box, so at connector level the check never fires: 66 of 66 connector/box pairs are "ignored (thin)". That is why C passes.
- The two pills are a real overlap even at shape level: the Request pill lies 72 percent over the User box, the Response pill 56 percent over it (the agent put them on top of the first box). Their rejection is correct.

## Genuine collision or wrong rejection?
- Variant B and B' (connectors rejected): mostly the wrong reason. The block comes from the union box of the diagram, not from any box or label. But the agent's connectors also do collide in fact: measured on the geometry, 8 of the 11 run through a box interior and through label text (they start inside the boxes, e.g. at x 140 inside the User box, and run at y 160 through the "User" label), 1 runs along the bottom edges of two boxes, and 2 short vertical ones sit in the gaps. So the rejection is right in effect and wrong in cause.
- Variant C and D (connectors accepted): the check lets through connectors that do cross labels, because thin shapes are exempt. No protection there.
- Variant A: accepted although 8 connectors cross box interiors and label text.

## Does one call just bypass the checks between its own parts?
Yes. The overlap check never compares shapes inside one element (E: two boxes on top of each other pass in one call and fail in two). Inside one call only two things are checked: canvas bounds per shape and label against label (30 percent of the smaller estimated text box). So A passing says nothing about whether its shapes collide.

## Limits of each approach
- **A (one call).** All or nothing: one error rejects or redraws the whole diagram (about 1,450 output tokens and 10 s for a call like this); one narration and one reveal moment for everything; no incremental build while speaking; a change to one box means replacing the whole group with `modify` (which is not overlap-checked); annotation or the learner's circle gesture resolves to the whole group, not one box; no check inside the group.
- **B (connectors in a second call).** Fails structurally whenever the boxes are one element: any connector between them lies inside their union box. Only passes if the connectors lie outside that box (not between the boxes).
- **C (one call per connector).** Works for thin connectors, and a failed connector can be redrawn alone, but: 11 to 13 extra calls (each with its own narration, marker and speech synthesis), it uses the page's element budget (17 elements here; soft nudge at 15, hard cap 25), connectors are not tied to the boxes (moving or redrawing a box leaves them behind), and thin connectors still get no collision check against labels.
- **D (each box its own element).** Best granularity (annotation, modify and recovery per box) and the box-on-box protection stays; the cost is 17 elements and many calls.

## Smallest change that lets intentional connectors attach without weakening protection (not implemented)
Compare shapes, not whole elements: for an existing element use its individual child shapes (not their union box), and for a new thin connector test its actual segments against those shapes instead of ignoring it. In practice two small changes inside the validator, no prompt change and no new tool:
1. Existing elements are compared child by child, so the gaps between boxes stay free. (Alone this is not enough: the new element's union box 790 x 140 would still cover 32 percent of the User box; the comparison must also be shape against shape, which at connector level means every thin shape is ignored.)
2. Thin shapes (connectors) get a segment test against existing child boxes and text: allowed to END on or near a box edge (an attach tolerance of a few pixels), rejected when a segment runs through a box interior or a label. The thin-line detector tested in `docs/WRAP_LIBRARIES.md` (segment against rectangle, arrow heads) is the same geometry.
Effect: box-on-box overlaps stay rejected (unchanged rule), connectors in the gaps and ending on edges are accepted in one call or many, and connectors that cross label text become rejected (a protection that does not exist today). Declaring `from` and `to` element ids in the draw call would be a larger change (a new tool parameter) and is not needed for this.
