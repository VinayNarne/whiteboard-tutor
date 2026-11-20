# Learning Platform: what it does today

A one-on-one AI tutor that teaches by talking and drawing on a whiteboard at the same time. This list describes the
current state of the code.

## The tutor (the agent)

**What it is.** An AI professor for any topic. Nothing in the agent is specific to one subject.

**What it can do.** It works through six tools:

| Tool | What it does |
|---|---|
| Draw a new element | Boxes, arrows, labels and diagrams, each with its own spoken narration |
| Modify an element | Corrects or improves something it drew earlier |
| Annotate | Circle, underline, tick, cross, highlight or arrow on an existing element; temporary (fades) or permanent |
| Remove an annotation | Takes one of its annotations away |
| Read the current page | Looks at what is on the board before deciding where to draw |
| Start a new page | Moves on when a concept is finished or the page is getting full |

**How it behaves.**
- It decides what to draw and in what order; code checks every drawing before it appears (see the next section).
- When a drawing breaks a rule, the tutor is told why and retries.
- It sees the last 15 chat messages, short summaries of the 20 most recent pages, and the current page.
- It has no internet access. What it knows comes from the model it runs on.
- A learner can interrupt it by speaking, and it stops.

## Quality checks on every drawing

- **Safety:** scripts and other unsafe content in the SVG are stripped.
- **Layout:** drawings must stay inside the canvas and not overlap other elements; text must not overlap other text.
- **Density:** a nudge to start a new page at 15 elements, and a hard stop at 25.
- **Unfinished drawings:** hints when a card has no label or a container is mostly empty.
- **Other rules:** drawings with `transform` attributes or duplicate ids are rejected with a clear reason.

## The whiteboard

- **Live drawing:** elements appear in step with the spoken narration, in a hand-drawn (Rough.js) or clean style.
- **Learner tools:** pan and zoom; pen, highlight and eraser; and circle or select a drawing to ask the tutor about it.
- **Replay:** replays a whole page step by step at 1x, 1.25x or 1.5x.
- **Undo:** removes the tutor's last drawing, its edits, its annotations and its audio (Edit menu, or Ctrl/Cmd+Z).
- **Export:** SVG, PNG, or copy as SVG.
- **Board colour:** stays paper-coloured in both light and dark themes.

## Voice

- **Tutor's voice** (top of the chat): the tutor reads its explanations aloud (ElevenLabs). You can turn it off or change
  the speed (1x, 1.25x, 1.5x). If speech fails, the app falls back to text and says so.
- **Speak your question** (mic button next to the chat box, Alt+M): your speech becomes text as you talk (Deepgram).
  - *Send when I pause:* optional; sends your message after a real pause.
  - *Interrupting:* speaking over the tutor stops it.
  - *Fallback:* if live transcription drops, pressing Done transcribes the recording instead.
- The Tutor's voice settings and "Send when I pause" are remembered between visits.

## Notebooks and pages

- **Notebooks:** one per topic. Create, rename and delete them; a landing page lists recent ones.
- **Pages:** several per notebook; add, rename and delete. *Save and lock* freezes a page so the tutor cannot change it.
  A fullness meter shows how full the current page is.
- **Chat:** beside the board, with formatted text, copyable code blocks, and quick follow-ups: Simpler analogy, Real
  example, Step by step, Quiz me, Next concept.
- **Notebook export:** a print-ready HTML file with all drawings, narration and the conversation.

## Look, feel and reach

- **Design:** calm academic palette; the whiteboard is the main focus, secondary actions live in menus.
- **Themes:** light, dark or match system; remembered between visits, no flash on load.
- **Screen sizes:** laptops get a thin page rail; tablets and phones get Board / Chat / Pages tabs, with a dot when
  something new happens in a hidden tab.
- **Accessibility:** works by keyboard throughout; AA contrast in both themes; dialogs trap focus; reduced motion is
  respected; the conversation is announced to screen readers; tap targets are at least 28px. Not yet tested with a real
  screen reader.

## Under the hood

- **Stack:** FastAPI, React/Vite and Postgres (SQLite fallback). Database changes are migrations that apply at startup.
- **Event log:** every drawing and edit is stored as an event, so pages can be replayed, undone and rebuilt.
- **Security and cost controls:** only pages served from your own machine can use the API; message sizes are limited;
  chat is limited to 20 requests a minute per notebook and voice to 30; one dictation session ends after 5 minutes.
- **Long sessions:** what the tutor is sent per question stays the same size however long the notebook gets.
- **Tests:** 129 automated tests, plus live scripts and a tutor-quality evaluation that use real credits.

## Not built yet

- Internet search for the tutor.
- User accounts or login (local-only on purpose).
- Skipping speech generation while the tutor is muted (it still uses ElevenLabs credits).
- Testing with a real screen reader and a real phone.
- Phase 2 ideas.
