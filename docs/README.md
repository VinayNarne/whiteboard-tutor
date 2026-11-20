# docs

Start with **`PROJECT_BRIEF.md`**: the goal, the decisions made and why, the current state, and the ideas parked for later.

## Current

| Document | What it is |
|---|---|
| `PROJECT_BRIEF.md` | The project's memory: decisions, current state, parked ideas. Kept up to date. |
| `lesson_evals/` | Reports of the lesson check (`scripts/lesson_eval.py`): one per run, each ending with a verdict (kept or reverted). |

## History

These record how the project got here: measurements behind decisions, and experiments that were kept or dropped. They describe the
code as it was at the time. The raw run data behind them (`baseline*/`, `benchmark_runs/`, `overlap_runs/`, `shadow_runs/`, about
34 MB) is not in the public repository; code comments that point there refer to it.

| Document | What it is |
|---|---|
| `FEATURES.md` | What the app did on 2026-10-09, before the lesson board (the main README has the current list). |
| `PHASE2_FOUNDATIONS.md` | Groundwork built in October and what would switch it on. |
| `original-plan.md` | The founding design. The lesson board (scene mode) later replaced its "the model draws raw SVG" core. |
| `BASELINE.md`, `baseline*/` | Repeatable quality runs of the older raw-SVG tutor (gpt-4.1-mini, then gpt-4.1). |
| `BENCHMARK_MODELS.md`, `BENCHMARK_CONTROLLED.md`, `benchmark_runs/` | Model comparisons (gpt-4.1 against Gemini) and the scene-mode proof of concept (`benchmark_runs/2026-11-05-scene-poc/`). |
| `OVERLAP_*`, `overlap_runs/`, `CONNECTOR_OVERLAP_EXPERIMENT.md` | Rounds on overlapping drawings in the raw-SVG tutor. |
| `VALIDATOR_DESIGN.md`, `SHADOW_VALIDATOR.md`, `shadow_runs/` | The drawing checks of the raw-SVG tutor. |
| `PROMPT_RULES.md`, `CAPABILITY_INVENTORY.md`, `PHASE1_AUDIT.md` | Audits of the raw-SVG tutor's prompt and capabilities. |
| `WRAP_LIBRARIES.md`, `WRAP_POC.md`, `text_width_offline.json` | Text wrapping research. |
| `GEMINI_MIGRATION_OPTIONS.md` | Options for moving the tutor to Gemini (not done). |
| `PAGE_SUMMARIES_REVIEW.md`, `SCREENSHOT_REVIEW.md`, `SESSION_2026-10-10_headphones.md` | Reviews of single features and sessions. |
