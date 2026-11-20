# Lesson check: point-not-rewrite

2026-11-15 11:12, 10 lessons, 80 tutor turns. Script: question, ok, wrong, vague, right, continue, ok, right2 (`tests/lesson_eval/lessons.json`). Model output varies: compare totals between runs.

## Totals

| Check | Failed turns | Meaning |
|---|---|---|
| turn_failed | 0 | the turn did not return 200 |
| markup_in_chat | 0 | the chat reply shows $, ** or [[ markers |
| no_question | 1 | the reply does not end with a question |
| repeated_question | 1 | the reply ends with (nearly) the same question as the turn before |
| praised_skip | 0 | after 'ok'/'continue' the reply opens with praise |
| praised_wrong | 0 | after a wrong or vague answer the reply opens with praise |
| wrong_not_corrected | 1 | after a wrong answer the reply has no correction wording |
| wrong_not_recorded | 4 | after a wrong or vague answer nothing was recorded as answered_wrong (only once a plan exists) |
| skip_graded | 0 | after a skip an answer was recorded (the code should refuse it) |

- First answer: median 10.6 s, slowest 18.2 s; all turns median 7.8 s.
- Blocks drawn: 48 (draw_graph 3, draw_scene 12, write_notes 33); refused attempts: 34.
- Plans: 10 of 10; final check reached: 5, passed: 0.
- Fact judge: 2 of 80 replies flagged (0 not judged).
  - hash_table (right2): Error: The reply explains collision handling (chaining), but does not answer how hash tables find keys quickly (hash function directs lookup).
  - quadratics (right2): The tutor answered for x² - 4x + 4 = 0, not x² - 5x + 6 = 0.

## Per lesson

| Lesson | Failed checks | Levels at the end | Blocks |
|---|---|---|---|
| sky | none | taught, understood, understood, taught | 6 |
| vaccines | wrong_not_corrected x1 | taught, taught, understood, understood | 6 |
| hash_table | none | understood, -, understood, - | 2 |
| compound_interest | none | taught, understood, understood, - | 5 |
| photosynthesis | wrong_not_recorded x1 | taught, understood, taught, taught | 4 |
| seasons | wrong_not_recorded x1 | remembered, -, -, - | 5 |
| dns | none | taught, understood, taught, taught | 6 |
| supply_demand | repeated_question x1 | understood, understood, understood, - | 5 |
| llm | wrong_not_recorded x1 | understood, taught, taught, -, - | 4 |
| quadratics | no_question x1, wrong_not_recorded x1 | taught, understood, taught | 5 |

## Verdict

Reverted. Labelling the board words "point at these, do not rewrite" left refusals at 34 and cut blocks drawn from 69 to 48: the tutor drew less instead of repeating less. The plain `already_written` field (run board-words) is kept.
