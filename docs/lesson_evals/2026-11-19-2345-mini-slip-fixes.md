# Lesson check: mini-slip-fixes

2026-11-19 23:45, 10 lessons, 80 tutor turns. Script: question, ok, wrong, vague, right, continue, ok, right2 (`tests/lesson_eval/lessons.json`). Model output varies: compare totals between runs.

## Totals

| Check | Failed turns | Meaning |
|---|---|---|
| turn_failed | 0 | the turn did not return 200 |
| markup_in_chat | 0 | the chat reply shows $, ** or [[ markers |
| no_question | 0 | the reply does not end with a question |
| repeated_question | 0 | the reply ends with (nearly) the same question as the turn before |
| praised_skip | 1 | after 'ok'/'continue' the reply opens with praise |
| praised_wrong | 3 | after a wrong or vague answer the reply opens with praise |
| wrong_not_corrected | 2 | after a wrong answer the reply has no correction wording |
| wrong_not_recorded | 0 | after a wrong or vague answer nothing was recorded as answered_wrong (only once a plan exists) |
| skip_graded | 0 | after a skip an answer was recorded (the code should refuse it) |

- First answer: median 7.8 s, slowest 12.9 s; all turns median 5.6 s.
- Blocks drawn: 70 (draw_graph 2, draw_scene 15, write_notes 53); refused attempts: 38.
- Plans: 10 of 10; final check reached: 2, passed: 0.

## Per lesson

| Lesson | Failed checks | Levels at the end | Blocks |
|---|---|---|---|
| sky | praised_wrong x1 | understood, understood, understood, understood, - | 7 |
| vaccines | none | remembered, taught, taught, understood | 7 |
| hash_table | none | understood, taught, understood, -, - | 8 |
| compound_interest | wrong_not_corrected x1 | remembered, understood, understood, understood, - | 5 |
| photosynthesis | none | understood, understood, understood, understood, - | 5 |
| seasons | wrong_not_corrected x1 | understood, understood, taught, taught | 6 |
| dns | praised_skip x1, praised_wrong x1 | understood, taught, taught, understood, - | 10 |
| supply_demand | praised_wrong x1 | remembered, taught, -, -, - | 8 |
| llm | none | taught, taught, understood, taught, - | 8 |
| quadratics | none | taught, -, -, -, - | 6 |

## Verdict: kept

Against the first mini run: plans 10 of 10 (was 8), no lesson started lesson 2 mid-lesson, praise slips 4 (was 7), refused attempts 38 (was 46), final check reached in 2 lessons (was 0). Of the 4 praise flags, one was a false alarm of the check ("Right after the browser has the IP address ..."; the check now counts "right" only as a word on its own) and three opened a correction with "Right," ("Right, sellers do not just pick any price"). After this run the remover also drops a lone opening "Right," / "Yes," before a correction (unit-tested on these replies; the full check was not re-run). Wrong answers not corrected: 2 (was 1). Facts not judged.
