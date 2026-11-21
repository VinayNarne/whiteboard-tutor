# Learning Platform

A one-on-one AI tutor that **teaches out loud while it draws on a whiteboard**. Name a concept, or a whole goal ("I want to become a
full stack engineer"), and the tutor plans a course, explains each idea with handwritten notes, diagrams, graphs and tables that
appear step by step in time with its voice, asks you questions, and tracks what you have understood. Everything lives in a notebook
you can reopen, replay and export.

> **Status: early version.** It works end to end and is tested (about 590 automated tests and a repeatable lesson check), but
> it is built for one person on one machine (no login), and it has been tried as a learner only by its author. The
> older tutor that drew raw SVG was retired; it is kept in the git tag `pre-raw-svg-retirement`.

## What it does

- **Teaches on a lesson board.** Notes, flow diagrams, graphs, tables, bar charts and Venn diagrams appear one step at a time while
  the tutor speaks; a camera follows the step being explained.
- **Plans before it teaches.** Your first message becomes a course: your goal and a roadmap of lessons. Each page gets a private
  lesson plan (checked facts, steps, check questions, common misconceptions) that the tutor follows.
- **Keeps you on track.** Your own questions are answered first, on the board too; questions far from your goal are answered briefly
  and kept for later. "Next concept" moves on to the next lesson of the course.
- **Checks understanding.** Each step of "Today's path" earns a level from your answers: taught, understood, remembered (after a
  surprise review). A lesson ends with a short final check.
- **Talks and listens.** Spoken explanations with word timings (ElevenLabs) and voice input (Deepgram); both are optional.
- **Runs locally for one person.** FastAPI + React, SQLite by default or Postgres.

## How it works

```
Browser (React + Vite)  ──HTTP /api──►  FastAPI backend  ──►  Postgres / SQLite
   board, chat, path      ◄──WebSocket──   │      │
                                           │      └─►  ElevenLabs (speech + word timings)
                                           └─►  Azure OpenAI (the tutor, with tools)
```

**The model says what to show; code decides where.** Each learner message goes to one agent (`engine/author.py`) that calls tools
such as `write_notes`, `draw_scene` (a diagram), `draw_graph`, `draw_table`, `annotate_element`, `start_new_page` and `record_step`.
Code lays every block out (`engine/scene.py`, diagrams by ELK.js), renders it as SVG, makes the narration for each step, stores it,
and streams it to the board. Code also refuses what would hurt the lesson, such as a block that repeats the board or a second recap
card, and sends the reason back to the model as a tool error so it can do better. Numbers come from a `calculate` tool, not the
model's head.

Data model: `Notebook` (with its course) → `Page` (with its lesson plan) → `PageEvent` (an append-only log of every step: the SVG
picture, its narration, and for a block's first step the block as data), plus `ChatTurn`. Audio files live in
`generated_notebooks/<notebook>/<page>/`.

The older tutor that wrote raw SVG itself was retired and now lives only in the git tag `pre-raw-svg-retirement`.

## Run it

Prerequisites: Python 3.11+, Node 20+, an Azure OpenAI deployment (the project is tuned on `gpt-4.1-mini`; `gpt-4.1` works too).
The database is **SQLite by default** (leave `DATABASE_URL` unset: a `learning_platform.db` file is created next to the code).

```bash
# 1. configure
cp .env.example .env                          # then fill in your keys (see the comments inside)

# 2. backend  (http://127.0.0.1:8001, API docs at /docs, health at /health)
pip install -r requirements.txt
cd engine/scene_layout && npm install && cd ../..   # diagram layout (elkjs), formulas (MathJax), handwriting font; all pinned
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001

# 3. frontend  (Vite prints the address, normally http://localhost:5173)
cd frontend
npm install
npm run dev
```

At startup the server logs a warning naming anything that is missing. Without an ElevenLabs key the tutor still works, silently;
`LP_VOICE=0` turns voice off on purpose (useful for test runs, so no credits are spent).

## Using Postgres (optional)

The default install does not include the Postgres driver. To use Postgres: install it, create the database once, and set `DATABASE_URL` in `.env`
(the app creates and migrates its own tables on start):

```bash
pip install -r requirements-postgres.txt          # adds psycopg2-binary
psql -U postgres -c "CREATE DATABASE learning_platform;"
# .env:  DATABASE_URL=postgresql://user:password@127.0.0.1:5432/learning_platform
```

If `DATABASE_URL` points at Postgres and the driver is missing, the app stops at start with a message saying exactly this.

## Changing the database

The schema is managed with Alembic (`alembic/`, applied automatically on every start by `backend/migrate.py`).
A database created before migrations existed is adopted in place: marked as the baseline, data untouched.

```bash
# after editing backend/models.py:
alembic revision --autogenerate -m "describe the change"   # review the generated file
alembic upgrade head                                       # or just restart the backend
alembic check                                              # exits non-zero if models and migrations differ
```

`tests/test_migrations.py` fails if a model changes without a matching migration.

## Tests and the lesson check

```bash
pip install -r requirements-dev.txt && python -m playwright install chromium
python -m pytest                      # about 950 tests; browser tests run only when the backend and Vite are running
```

- `pytest` uses an isolated database (`<your db>_test`, wiped each run, or a temporary SQLite file) and never calls a real model.
- **The lesson check** (`scripts/lesson_eval.py`) teaches 10 fixed lessons to a scripted learner (a question, "ok", a wrong answer,
  a vague one, a right one...) against a running backend and counts teaching slips: praise after a wrong answer, a repeated question,
  a wrong answer not corrected or not recorded, a skip graded as an answer. `--judge` also asks a model whether any reply states
  something false (set `JUDGE_AZURE_OPENAI_*` to judge a cheap tutor with a stronger model). Reports go to `docs/lesson_evals/`;
  run it before and after any change to the tutor's behaviour and compare the totals.

```bash
LP_VOICE=0 python -m uvicorn backend.main:app --host 127.0.0.1 --port 8102
python scripts/lesson_eval.py --url http://127.0.0.1:8102 --label my-change [--only sky,dns] [--judge]
```

## Project layout

| Path | What lives there |
|---|---|
| `backend/` | FastAPI app (`main.py`), models, DB setup, WebSocket hub, request limits, notebook export |
| `engine/` | The tutor: `author.py` (agent loop, tools, prompts), `scene.py` (lesson board layout), `lesson_plan.py` (course, plans, checklist), `graph.py`, `blocks.py`, `validator.py`, `sanitiser.py`, `voice.py` |
| `core/` | Event names and structured logging |
| `frontend/src/` | `App.tsx` (screens), `components/` (whiteboard, chat, sidebar, menus), `hooks/`, `utils/` |
| `tests/` | Pytest suite, browser smoke tests, the lesson check's lessons (`tests/lesson_eval/`) |
| `scripts/` | `lesson_eval.py` (the lesson check) and development helpers |
| `docs/` | `PROJECT_BRIEF.md` (decisions, current state, parked ideas), lesson check reports, research history (see `docs/README.md`) |

## Design rules worth knowing

- **The model says what, code says where.** Never ask the model for coordinates on the lesson board; add layout to `engine/scene.py`.
- **Generic agent, checks in code.** Prefer a check in code that refuses with a clear reason over another rule in the prompt.
- **Measure behaviour changes.** Run the lesson check before and after; keep a change only if the totals say so.
- **Colours come from tokens** in `frontend/src/index.css` (a light set and a `data-theme="dark"` set). Do not hard-code
  hex values in components; `tests/test_themes.py` checks contrast in both themes. Switch themes from the **Notebook** menu
  (or **Appearance** on the home page): Light, Dark, or Match system.
- **Responsive:** above 1200px three columns; up to 1200px the page list becomes a thin rail and the chat narrows; up to
  820px (tablets, phones) one pane at a time with Board / Chat / Pages tabs and a dot when something new arrives in the
  hidden pane. All panes stay mounted, so audio and typed text survive tab switches (`tests/test_responsive.py`).
- **Secondary actions live in menus** (`components/Menu.tsx`); keep the whiteboard and the conversation in front.

## Security and cost controls

Only pages served from this machine (any `localhost` / `127.0.0.1` port) may call the API or open the WebSocket.
Chat messages are capped at 4,000 characters, chat is limited to 20 requests per minute per notebook, voice to 30 per
minute per client (`RATE_LIMIT_*` in `.env`). One live-dictation session ends after 5 minutes (`MAX_VOICE_SECONDS`). There is no user login: this is built to run locally for one person.
Add authentication before exposing it on a network.

## Long sessions

What the tutor is sent on each question stays the same size however long the notebook gets: the last 15 chat turns,
the 20 most recent page summaries (older pages are listed by title only), and the current page without its embedded
font data. `tests/test_long_session.py` builds a 60-page, 400-turn notebook and checks these limits and the load times.

## Troubleshooting

- **`[WinError 10013]` when starting the backend:** either another copy is using port 8001 (find it with
  `Get-NetTCPConnection -LocalPort 8001 -State Listen`), or Windows has reserved the port (check
  `netsh int ipv4 show excludedportrange protocol=tcp`; ranges such as 7916-8015 block 8001 and move after reboots).
  In the second case use another port: start the backend with `--port 8100`, put `VITE_BACKEND_PORT=8100` in
  `frontend/.env.local`, and run the live tests with `LP_BACKEND=http://127.0.0.1:8100`.
- **Live updates do not appear / WebSocket 403:** the page is being served from a non-local address. Add it to
  `CORS_ORIGINS` in `.env`.
- **Voice is silent:** the ElevenLabs key is missing or out of quota; the app shows a notice and falls back to text.
- **The mic does nothing / "Live transcription stopped":** `DEEPGRAM_API_KEY` is missing, or the browser blocked the
  microphone (allow it in the address bar). If live transcription drops, press Done and the recording is transcribed instead.

Two separate controls: the **mic button** (next to the chat box, Alt+M) is you speaking to the tutor; **Tutor's voice**
(top of the chat) is the tutor speaking to you. The Tutor's voice settings and "Send when I pause" are remembered between visits.

## Licence

MIT, see `LICENSE`. Bundled third-party code and fonts keep their own licences (elkjs: EPL-2.0; MathJax: Apache-2.0; the Caveat font: SIL Open Font License).
