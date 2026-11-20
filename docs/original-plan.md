<USER_REQUEST>
Yes — let's write it properly, same rigor as day one of the webinar project. Here's the full Phase 1 build plan, ready to hand to the new Gemini Antigravity session.

---

# Build Plan: Learning Agent — Phase 1 (Draw & Explain)

## What we're building

A one-on-one AI tutor. A whiteboard sits center-screen; a chat panel sits on the right. The learner asks a question or names a topic; the agent explains by **drawing live on the whiteboard while speaking**, one concept per page, in a notebook that keeps growing and can always be reopened later.

## Explicitly out of scope for Phase 1 — do not build these yet

State this to avoid scope creep: no live voice input (learner types back, doesn't speak), no quizzes or "last time we covered" recaps, no multiple simultaneous learners, no bringing in real photos/images (drawing only, for now), no live two-way barge-in conversation.

## Founding principle, carried over from the webinar project — read this first

> Constrain how the agent records its work, never what it chooses to draw. A rule belongs in the system prompt only if it's true for every topic and every audience — a physical/rendering constraint, not a stylistic preference. If you find yourself handing the model an example instead of a requirement, stop — it will copy the example forever.

This exact mistake (a contract template with real hex values baked in) caused every deck in the webinar project to look identical for weeks before it was caught. Don't rediscover this the hard way a second time.

---

## Five core decisions (already made, build to these exactly)

1. **Page transitions**: the agent proposes moving to a new page at a natural pause; the learner can always override — "keep going" or "let's switch topics" — at any time.
2. **Crowding within a page**: the agent proactively splits into a continuation page when a page is getting dense, guided by a soft signal; a hard automatic limit forces a split regardless, as a backstop. (Concrete starting thresholds below — tune after real testing, don't treat these as final.)
3. **Chat vs. buttons**: simple, frequent, unambiguous actions (back a page, replay this page, jump to a saved page) are real UI buttons, not chat messages. Open-ended requests (explain differently, go deeper, connect this to something else) go through chat.
4. **Voice**: the agent speaks aloud, reusing the proven ElevenLabs + word-alignment system from the webinar project. The learner types back. No voice input in Phase 1.
5. **Saved pages default to instant, silent view** — the finished drawing, fully visible, no replay — with an optional "replay this" action that re-plays the original drawing-and-narration sequence from scratch.

---

## Reuse from the webinar project — copy these files as a starting point, do not rebuild

- `rough.min.js` (self-hosted Rough.js)
- `useAnnotationOverlay.ts` — the shared highlight/pointing hook (getBBox + getCTM measurement, 8px padding, Rough.js draw)
- `sanitize_svg` — the safety pass on any AI-generated SVG (strip scripts, event handlers, disallowed tags)
- `inject_trusted_font` — server-side font handling, never model-authored
- The TTS + word-alignment pipeline (ElevenLabs call + alignment.json generation)
- The core architectural rule: **absolute x/y coordinates only, no `transform` attributes** — same reason as before (breaks measurement and overlay registration)
- The general pattern: **cheap model generates, a deterministic Playwright-based measurement pass checks the geometry** — don't trust the model's own claims about size or position

## New pieces this project actually needs — build these fresh

### 1. The WhiteboardAuthor (the core new agent, reusing the webinar's "second way to invoke the Author" pattern)

Every learner chat message is a request to the same underlying author, not a separate agent. It gets:
- The full conversation history for this notebook (capped to recent turns, same pattern as the slide-chat feature; full history persisted regardless)
- A summary of prior pages in this notebook (so it has continuity of what's already been taught)
- The current page's live SVG state, freshly read every time, never cached

Two tools, same shape as the slide-chat feature:
- `get_current_page_state()` — always re-reads fresh
- `draw_on_page(change_description, new_svg_fragment)` — adds to the current page; goes through the full pipeline: sanitize → validate geometry → measure → (if narration changed) regenerate audio + alignment

### 2. Page density check (new validator rule, same measurement technique as before)

Using the same Playwright-based bounding-box measurement approach:
- **Soft signal** (nudges the agent to consider wrapping up): element count or canvas-coverage ratio crosses a first-guess threshold — start with **15 elements** or **70% canvas coverage**, whichever comes first
- **Hard cap** (forces a split regardless of what the agent wants): **25 elements**, non-negotiable

State these as first estimates to the build agent — they should be tuned after watching real generated pages, not treated as correct on day one.

### 3. Page lifecycle & notebook data model

```
Notebook (one per topic)
  └── Page (one per concept/idea)
        ├── final_svg (the finished drawing)
        ├── narration_audio + alignment.json
        ├── created_from_chat_turns (which messages produced this page)
        └── status: active | saved
  └── chat_turns (full conversation, spans all pages, persisted like slide_chat_turns)
```

Use the same event-log + replay pattern already proven in the webinar's live runtime — each page's drawing is a sequence of timestamped add-events, which is also exactly what makes the optional "replay this page" feature possible for free, since replaying is just re-emitting the same events against the audio again.

### 4. Additional annotation styles (small addition to `useAnnotationOverlay`)

Add underline, circle, and strike-through as mark styles alongside the existing box, using Rough.js primitives already available (`.ellipse()`, `.line()`) — no new dependency.

### 5. Diagonal-label fix (from the Rough.js spike)

Any text label sitting on a diagonal connector line gets a small solid background box behind it first, so the sketchy stroke passes behind the text instead of through it.

### 6. Locked Rough.js defaults

`roughness: 1.0–1.2`, confirmed clean across every diagram type tested in the spike. Do not exceed this without a reason.

---

## Build sequence

1. **Foundation**: copy reused files into the new project; set up Postgres schema for Notebook/Page/chat_turns
2. **WhiteboardAuthor core**: the two-tool chat loop, page state reading, drawing pipeline (sanitize → validate → measure)
3. **Density check**: implement soft + hard thresholds, test with a deliberately dense request to confirm the hard cap actually triggers
4. **Page lifecycle**: page-end proposal logic, learner override, save-on-transition
5. **Voice**: wire in TTS + alignment for narration; confirm audio and drawing stay in sync using the same word-by-word approach as before
6. **Frontend**: whiteboard viewport + chat panel + navigation buttons (back/forward/replay)
7. **Save & reopen**: instant silent view by default, full replay on request

## Verification plan

- Reuse the same "must catch / must pass" discipline for the density check: one fixture that should trigger the hard cap, one that should clearly not
- Generate at least 3 pages on different topics; confirm each produces genuinely different layouts (same audit we ran on the webinar project — don't let a template sneak back in)
- Confirm a saved page reopens correctly in both silent and replay modes
- Confirm the chat correctly distinguishes "explain more" (adds to current page) from "new topic" (proposes/starts a new page)
</USER_REQUEST>
