# Lesson check: refactor-chat-graph

2026-11-21 21:31, 2 lessons, 16 tutor turns. Script: question, ok, wrong, vague, right, continue, ok, right2 (`tests/lesson_eval/lessons.json`). Model output varies: compare totals between runs.

## Totals

| Check | Failed turns | Meaning |
|---|---|---|
| turn_failed | 0 | the turn did not return 200 |
| markup_in_chat | 0 | the chat reply shows $, ** or [[ markers |
| no_question | 0 | the reply does not end with a question |
| repeated_question | 0 | the reply ends with (nearly) the same question as the turn before |
| praised_skip | 0 | after 'ok'/'continue' the reply opens with praise |
| praised_wrong | 1 | after a wrong or vague answer the reply opens with praise |
| wrong_not_corrected | 0 | after a wrong answer the reply has no correction wording |
| wrong_not_recorded | 3 | after a wrong or vague answer nothing was recorded as answered_wrong (only once a plan exists) |
| skip_graded | 0 | after a skip an answer was recorded (the code should refuse it) |

- First answer: median 9.0 s, slowest 9.0 s; all turns median 5.7 s.
- Blocks drawn: 16 (draw_graph 2, draw_scene 5, write_notes 9); refused attempts: 5.
- Plans: 2 of 2; final check reached: 0, passed: 0.

## Per lesson

| Lesson | Failed checks | Levels at the end | Blocks |
|---|---|---|---|
| compound_interest | wrong_not_recorded x1 | remembered, taught, -, -, - | 7 |
| quadratics | praised_wrong x1, wrong_not_recorded x2 | remembered, understood, taught, -, - | 9 |
