# Mindprint: the tutor's memory of each learner

Mindprint gives the tutor a lasting picture of each learner: what they know, what they get wrong, how they like to be taught, and what
the tutor has already taught them. It works across notebooks and long courses. This document is the design, decided from research and
small experiments run on this project's own lessons (2026-11-22).

## Principles (each backed by a measurement below)

1. **Code holds the learner's state; the model reads a short instruction.** A per-turn instruction placed right before the learner's
   message changed behaviour reliably; the same facts as a profile inside the big context block barely did.
2. **Only graded answers change mastery, and a separate grader decides.** The tutor's own grading is not enough on its own.
3. **A summary model never writes the learner model.** Summaries of what was *taught* are reliable; summaries of what the *learner*
   said, believed or answered are mostly invented.
4. **When unsure whether two lessons teach the same concept, keep them apart.** False mastery is worse than split mastery.
5. **Everything lives in our own database.** No memory framework fits: they add infrastructure, store contradicting facts side by
   side, take over the agent loop, or are not maintained, and none models learning.

## Evidence (experiments on this project, gpt-4.1-mini)

| Question | Result | Decision |
|---|---|---|
| Does a learner instruction change teaching? | "Already knows DNS basics": re-teaching 4.0 -> 0 lines, 5/5 went deeper. "Correct the distance myth first": 0/5 -> 5/5 in the first two lines. Rewriting the lesson plan in code added nothing. | Per-turn instruction right before the learner's message. |
| Same instruction inside the context block | "Example first" in 1/5 runs (4/5 as a per-turn instruction). | Never as a profile label in the context block. |
| How reliable is the tutor's own grading? (86 lesson checks) | Vague -> right 6%; wrong -> right 0-9%; correct answers missed 10-23%; it tried to grade "ok"/"continue" in ~2/3 of skips (code refused all). | Do not use the tutor's grading for mastery. |
| A separate grader with the expected answer and a short checklist (80 cases) | 0 false accepts of 60 non-correct answers; 20/20 correct answers graded right. | Separate grader call; only "right" counts. |
| Page digest written by the model | Taught side 1-2% wrong; learner side: answers 45-54% wrong, misconceptions 71% wrong (copied from the plan's myths list). | Taught side only, built from board records in code; the model labels only *how* each idea was explained (quotes checked in code). ~68 words per page. |
| Mapping a new lesson's steps onto known concepts | Model alone: 20% of reuses wrong (e.g. photosynthesis -> "LLM text prediction"). With top-15 candidates by embedding, reuse accepted only when the model's choice is in the embedding top-3 and similarity >= 0.70, recap steps skipped: wrong merges 0.8% of steps, duplicates 17-23%, 35/35 stable. | Use the gated pipeline; accept duplicates. |

Research (in `research_notes/`, kept locally): plain-text learner state in the prompt raised next-item correctness by about 6% at Khan
Academy (raw logs/JSON: no effect); simple per-concept mastery works as well as deep models on small data; "learning styles" matching has
no evidence; LLM-simulated students are too compliant, so the evaluation uses a scripted learner.

## Data model (new tables, one migration)

- `concepts`: per learner. id, name, description, embedding, aliases, created_from (page and step).
- `concept_state`: per learner and concept. mastery level (new, taught, understood, remembered), right-answer count and the turns they
  came from, last wrong answer, open misconception (text, from the lesson plan's check, confirmed by a graded wrong answer), next review
  date (later: spaced review).
- `teaching_log`: per concept. Where it was taught (notebook, page, block ids), how (analogy / worked example / diagram, short label),
  the board text excerpt. Built from `page_events.block` in code; the "how" label is the only model-written field.
- `learner_prefs`: explicit preferences the learner stated or chose ("simpler", "more examples", "slower"), with the date. Never inferred
  styles.
- `page_digest`: per page, the taught-only digest (code fields plus the checked "how" labels).

## Phase 0 result: the ceiling with a perfect learner note (2026-11-22)

`scripts/memory_eval.py`, course in `tests/memory_eval/course.json`, 5 runs per cell, three later lessons in new notebooks.

- **The note must reach the lesson-plan writer too.** With the note only in the tutor's turn (v1), the plan, written without it,
  steered the tutor back to the basics and little changed.
- With the note in both places (v2): the known misconception was corrected in 8/10 lessons (0/10 without memory); examples-first
  rose from 8/15 to 11/15; the earlier analogy came back in 2/6 (0/6); no new contradictions.
- **Re-teaching did not drop** (9/10 both ways): the tutor still asks "why does your browser need DNS?" even when the plan dropped that
  step. Telling the model is not enough here; phase 1 should mark known steps in code (for example, as already understood in the checklist).

## How a turn uses it

1. **When a lesson plan is written** (already one model call): map each step to a concept with the gated pipeline (one extra call per
   plan, plus embeddings).
2. **Before each tutor turn, code builds a short instruction** (a few lines, plain text, placed right before the learner's message):
   - concepts in today's step the learner already mastered: "do not re-teach X (checked by the grader); go deeper into Y";
   - an open misconception for today's concept: "address the belief that ... first";
   - how X was taught before: "earlier you explained X with the water-pipe analogy; reuse it, do not contradict it";
   - stated preferences: "the learner asked for worked examples first".
3. **After the learner answers a check question**, a separate grader call compares the answer with the plan's expected answer and a short
   checklist. Only "right" counts; mastery: the first right answer from the grader means understood, a right answer in a later turn means remembered (the grader had 0 false accepts in 60 answers, and the tutor rarely re-asks a step, so waiting for two never happened); "ok"/"continue" are never answers. A misconception is not cleared by the right answer that follows its correction: it is marked corrected and kept (with a hash of the lesson plan) until a right answer in a later lesson; the note then asks for a brief check. Why: misconceptions often return after one correction (measured: the next right answer erased it in 3 of 4 runs).
4. **When a page ends**, code writes its digest and teaching-log rows (one small model call for the "how" labels).
5. **Context over long courses**: recent turns verbatim, earlier pages as digests (~70 words each), and teaching-log lines retrieved by
   concept for today's step. Stable content first in the prompt so caching works.

## What the learner sees

A "What I know about you" card: mastered concepts, open misconceptions, stated preferences, each editable or removable by the learner.
It keeps the memory honest and private.

## Phases

0. **Evaluation first.** A multi-lesson scripted course (2-3 topics, 4 short lessons each) with a scripted learner who has a known
   misconception and a stated preference, run with memory on and with memory wiped. Measures: re-teaching mastered content, addressing
   the known misconception, honouring the preference, contradicting earlier explanations, reusing earlier analogies, false mastery from a
   vague answer.
1. **Learner memory:** the tables, the concept mapping, the separate grader, the per-turn instruction, page digests and the teaching log.
2. **The learner card** and explicit feedback (typed or quick choices like "simpler", "more examples").
3. **Spaced review across days**, once the tutor is used across days.

## Known limits

- Duplicates (17-23% of new concepts) mean a concept learned in one notebook can be re-checked in another. Acceptable; never the reverse.
- One kind of wrong merge survives the gate: an overview step mapped to a narrow concept (e.g. "the DNS query process" to "TLD to
  authoritative"). The grader must still judge the answer right before mastery, which limits the damage.
- Experiments were small (5 runs per cell, 28 plans, 80 grading cases). Phase 0's evaluation is the real test.
