# Lesson check: scene-token-cap

2026-11-19 22:55, 10 lessons, 80 tutor turns. Script: question, ok, wrong, vague, right, continue, ok, right2 (`tests/lesson_eval/lessons.json`). Model output varies: compare totals between runs.

## Totals

| Check | Failed turns | Meaning |
|---|---|---|
| turn_failed | 9 | the turn did not return 200 |
| markup_in_chat | 0 | the chat reply shows $, ** or [[ markers |
| no_question | 1 | the reply does not end with a question |
| repeated_question | 0 | the reply ends with (nearly) the same question as the turn before |
| praised_skip | 0 | after 'ok'/'continue' the reply opens with praise |
| praised_wrong | 0 | after a wrong or vague answer the reply opens with praise |
| wrong_not_corrected | 1 | after a wrong answer the reply has no correction wording |
| wrong_not_recorded | 1 | after a wrong or vague answer nothing was recorded as answered_wrong (only once a plan exists) |
| skip_graded | 0 | after a skip an answer was recorded (the code should refuse it) |

- First answer: median 11.7 s, slowest 27.5 s; all turns median 14.0 s.
- Blocks drawn: 78 (draw_graph 1, draw_scene 14, write_notes 63); refused attempts: 22.
- Plans: 10 of 10; final check reached: 2, passed: 0.

## Per lesson

| Lesson | Failed checks | Levels at the end | Blocks |
|---|---|---|---|
| sky | none | taught, taught, taught, taught | 9 |
| vaccines | turn_failed x1, wrong_not_recorded x1 | understood, taught, understood, - | 6 |
| hash_table | turn_failed x1 | understood, understood, - | 6 |
| compound_interest | turn_failed x1 | understood, -, -, -, understood | 9 |
| photosynthesis | turn_failed x1 | taught, taught, taught | 10 |
| seasons | no_question x1, turn_failed x1, wrong_not_corrected x1 | understood, understood, -, - | 8 |
| dns | turn_failed x1 | understood, -, taught, - | 7 |
| supply_demand | turn_failed x1 | understood, understood, taught, - | 8 |
| llm | turn_failed x1 | understood, taught, taught, -, - | 7 |
| quadratics | turn_failed x1 | understood, taught, taught, - | 8 |

## Verdict: reverted

Tried: the tutor's scene-mode calls reserved 2,000 output tokens instead of 6,000 (1,207 logged scene calls used at most 923). Idea: Azure counts the reservation against the gpt-4.1 token rate limit, so lower reservations would stop the 429s on first answers. Result: 7 of 10 first answers still got a 429 (8 of 10 before), so the reservation is not the cause; the change was reverted.

What the log shows: every 429 is on a new lesson's first answer, a second after the previous lesson's back-to-back turns (this script sends the next message the moment a reply arrives). Tokens in the minute before a failure ranged from about 49,000 to 102,000, and a 102,000-token minute also passed, so a plain tokens-per-minute count does not explain it either. Real lessons with a learner reading between turns (the owner's three on 2026-11-19, two live course runs) had no 429.
