# Overlap plan (agreed with the owner and Claude Desktop; updated 2026-10-10)

Order: baseline first, then the change, then the checks. Prompt and tool text stay frozen (digests unchanged). Show exact wording before editing.

1. **Overlap rejection message** (tool-result text in `engine/author.py`, not the prompt). Show the current wording; propose a new one that names the element it overlaps and gives one free region (x, y, width, height) computed in code from the existing elements where the drawing would fit; if none fits, say so plainly and say how much room is left. No code that moves the drawing.
2. **Repeat cap:** after 2 identical rejections of the same element in one turn, stop repeating the same message and send the free-region hint only; log `overlap_cap_reached` (element, count). Tests both ways.
3. **Measure, baseline FIRST on gpt-4.1.** 3 replays before the change, 3 after, of (a) the 8 eval topics and (b) the GPS session replay. A result counts only if outside the run-to-run range. Points added by the owner:
   - the old baselines are gpt-4.1-mini, so they cannot be used; the "before" runs are new;
   - the replay uses only NEUTRAL learner messages and the list is recorded (`docs/OVERLAP_MEASURE.md`);
   - a "permission ask" counts only a question asking whether to start or move to a new page (not "would you like to know more?");
   - the real GPS session (12 rejections, 7 pages created, 3 permission asks) is shown as one reference point, not as the range.
4. **Read only:** for every rejection in the headphones and GPS sessions: how much the shapes overlap and how full the page was (the page 3 case: one drawing on the page, still rejected).
5. **Scroll jump:** find why the canvas moves to the top when a message is sent. VERIFY IN THE BROWSER before naming a cause; name the code line and the trigger. Do not fix yet.
6. **Speech rate:** show where it is set, the provider's allowed range, whether 0.85 works without a prompt change, and what it does to the drawing sync. Do not change yet.
7. **Summaries:** confirm the 300-character mid-sentence cut still happens; propose a sentence-end cut. Do not change yet.
8. **Live suite and browser tests**, counts and commit list.

Open question for the owner (not part of this plan): the permission asking is prescribed by the frozen prompt ("PROPOSE a new page in your chat reply and wait") and by the current rejection text ("tell the learner and propose a new page"). A better rejection message reduces asks on pages that are not full; it cannot remove asks on pages that are full unless the prompt is changed.
