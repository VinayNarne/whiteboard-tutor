# Real learning session: "how noise-cancelling headphones work" (2026-10-10, 11:01 PM to 11:21 PM local)

Notebook `ea3b45f1-d280-4420-af2b-4635d091cc33`. Log times are UTC; local = UTC minus 4 hours (03:02 UTC = 11:02 PM). Sources: `logs/learning_platform.jsonl` (326 records of this notebook, queried with `scripts/logs_query.py`), the database (conversation, pages, drawing events), and the six boards rendered to images
(`board_p1.png` to `board_p6.png`, scratch folder, not in the repo). Nothing was changed.

## Counts
- 13 tutor turns (13 learner messages, 26 chat rows). Turn time: mean 12.0 s, median 9.7 s, slowest 25.7 s (11:02:38 PM, the first turn). No turn over 26 s. Failed turns 0, empty replies 0, iteration limit 0, lost-content notes 0, model timeouts 0, browser errors (`client_error`) 0.
- Model: 38 calls, 180,025 prompt and 11,721 completion tokens, LLM cost $0.091; speech 5,757 characters, $0.230; total $0.32 (about $0.025 per turn).
- Pages: 6 (1 to 5 saved, 6 active); the tutor opened pages 2 to 6 itself (`page_created` 11:04:50, 11:05:57, 11:08:24, 11:14:31, 11:15:39). Drawings stored: 22 (page 1: 6, page 2: 2, page 3: 3, page 4: 8, page 5: 2, page 6: 1).
- Retries (`draw_failed`): 11: 9 overlaps with an existing element (11:02:52 x3, 11:04:38, 11:05:54 x2, 11:13:50, 11:13:54, 11:14:38), 1 canvas bleed (11:08:33), 1 background frame (11:16:24). Plus 1 annotation on an element that did not exist (11:13:50).
- Summaries: 5 written (11:04:50, 11:05:57, 11:08:24, 11:14:31, 11:15:39), none failed; a summary was in the tutor's context in 10 of 13 turns (from the 4th turn on). Three of the five end mid-sentence at the 300-character limit.
- Audio: 22 drawing narrations, 22 audio files, `voice_ok` true in all 22. 334 seconds of speech for 5,757 characters, about 178 words per minute at normal speed.
- Other log events: 32 `group_repaired` and 11 `marker_repaired` (normal repairs), 9 `text_width_note` (a label estimated wider than its space; log only, never shown to the tutor).

## Your notes against the logs
1. **Diagrams are not good.** Looked at the boards. Page 1: the labels "External Microphone", "Speaker Driver", "Internal Microphone" are wider than their circles and cut off; the three circles are drawn twice (a second, smaller row below the box). Pages 4 and 5: a large blue box sits on top of paragraph text (the text runs behind it), the four circles
   run off the right edge (the last circle is cut by the canvas), labels overflow the circles, the text lines run off the right edge on page 5, the same sentence "Sound waves travel through air as vibrations or pressure changes that your ear detects." is drawn twice on page 4, and the wavy lines are decoration with no meaning.
   The logs know only part of this: the 9 `text_width_note` events (labels too wide) and the 11 rejections; no event describes a box covering text or content running past the canvas edge, and those drawings were stored with `draw_completed`. Not explained by an error: the guards did not see it.
2. **Canvas moves to the top when you send a message.** Not explained. No browser error, no failed turn, no server event at the time of every send; the 5 page changes are only 5 of your 13 sends. Needs a look at the page's scrolling in the browser.
3. **Fast speech, can't follow.** Confirmed in part: about 178 words per minute (a slow teaching pace for a non-native listener is nearer 120 to 140). Also in the conversation: you asked for slower and from scratch at 11:04 PM ("take it slowly"), 11:08 PM ("start from scratch ... take it slowly") and 11:11 PM ("I'm not really getting what you're saying, I don't know what is DSP"); the answer to the 11:08 request (turn starting 11:08:19) still opened with the DSP unit and the components overview.
4. **Sometimes no audio, only text in the chat.** Confirmed, and explained: only drawing narrations are spoken; the chat reply is never spoken. Turns with no drawing, or none that was stored, have no audio: 11:04:34 PM (the tutor asked permission for a new page; its one drawing was rejected), 11:16:02 PM (text only, "if I want to develop new earphones" answer),
   11:20:33 PM (text only, "I will explain each step ... in detail"). Every stored drawing had audio.
5, 6, 7. Questions to me (real-time model, a stronger model, a format other than SVG); not log-checkable.

## Problems in the logs you did not mention
- The tutor opened five new pages in 13 turns, three of them (pages 2, 3, 4) for the same "technical deep dive", two with the same title ("Noise Canceling Headphones: Technical Deep Dive"); pages 1 and 6 have no title. Page 2 holds 2 drawings and page 3 holds 3.
- At 11:14 PM (the "concrete real-world example" request, 9 seconds) the tutor drew nothing and proposed a new page, saying there was no free space; page 4 had 8 drawings (the page showed 0 of 15 elements at the end because page 6 was active).
- You replied just "ok" six times (learner messages 3, 4, 7, 8, 10 and 12 of 13); the tutor kept continuing rather than checking understanding.
- Drawings with the same content stored twice on page 4.
- Summaries cut at 300 characters (3 of 5).

## Statements you flagged as doubtful
None: your notes contain no statement flagged as doubtful.
