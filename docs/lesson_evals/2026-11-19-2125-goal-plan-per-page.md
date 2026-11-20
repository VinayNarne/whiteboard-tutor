# Lesson check: goal-plan-per-page

2026-11-19 21:25, 10 lessons, 80 tutor turns. Script: question, ok, wrong, vague, right, continue, ok, right2 (`tests/lesson_eval/lessons.json`). Model output varies: compare totals between runs.

## Totals

| Check | Failed turns | Meaning |
|---|---|---|
| turn_failed | 8 | the turn did not return 200 |
| markup_in_chat | 0 | the chat reply shows $, ** or [[ markers |
| no_question | 0 | the reply does not end with a question |
| repeated_question | 1 | the reply ends with (nearly) the same question as the turn before |
| praised_skip | 0 | after 'ok'/'continue' the reply opens with praise |
| praised_wrong | 1 | after a wrong or vague answer the reply opens with praise |
| wrong_not_corrected | 1 | after a wrong answer the reply has no correction wording |
| wrong_not_recorded | 1 | after a wrong or vague answer nothing was recorded as answered_wrong (only once a plan exists) |
| skip_graded | 0 | after a skip an answer was recorded (the code should refuse it) |

- First answer: median 12.7 s, slowest 14.7 s; all turns median 14.4 s.
- Blocks drawn: 80 (draw_scene 14, draw_table 2, write_notes 64); refused attempts: 28.
- Plans: 10 of 10; final check reached: 3, passed: 0.

## Per lesson

| Lesson | Failed checks | Levels at the end | Blocks |
|---|---|---|---|
| sky | none | taught, -, -, - | 7 |
| vaccines | turn_failed x1 | understood, -, understood, - | 7 |
| hash_table | repeated_question x1 | understood, taught, understood, - | 5 |
| compound_interest | praised_wrong x1, turn_failed x1, wrong_not_corrected x1, wrong_not_recorded x1 | understood, understood, understood | 9 |
| photosynthesis | turn_failed x1 | taught, understood, understood, taught | 7 |
| seasons | turn_failed x1 | remembered, -, -, - | 9 |
| dns | turn_failed x1 | taught, remembered, understood, taught, taught, taught | 9 |
| supply_demand | turn_failed x1 | taught, remembered, -, - | 10 |
| llm | turn_failed x1 | understood, taught, understood, - | 11 |
| quadratics | turn_failed x1 | understood, understood, -, - | 6 |

## Verdict: kept

- The 8 failed turns are all first turns refused by Azure (429, gpt-4.1 token rate limit) while the plan and the tutor's first call ran together. The same two lessons on the code before this change failed the same way on the same evening (sky passed, dns got a 429), so it is the deployment's limit that day, not this change. It is still a product risk: a learner's very first answer can fail with "couldn't reach the tutor model".
- Other checks: 4 failed turns against 5 in the last full run (board-words, 2026-11-15). Final check reached in 3 lessons against 1 (step 1 is now recorded after the first answer).
- Turns were slower (median 14.4 s against 8.6 s); the deployment was throttling that evening, so this run cannot say whether the change costs time.
- Not covered by this script: off-plan questions and "next concept" pages. Checked live instead (a full stack course: Docker answered and set aside for later, the new page continued with lesson 2, no repeat).
