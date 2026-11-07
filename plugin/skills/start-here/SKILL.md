---
name: start-here
description: >
  This skill should be used when a new Job Search Kit user says "start here",
  "/start-here", "set up my evidence bank", "build my master resume", "let's do
  the first session", "continue my setup", or asks where to begin after
  installing the kit. It runs four short interview sessions that build the
  user's North Star, evidence bank, Rules File, keyword groups, and master
  resume from the kit's templates, in the user's own words.
metadata:
  version: "0.1.0"
---

# Start Here

Four short sessions, about 45 minutes each, that turn a new user's experience into the files the kit runs on. The user talks; Claude asks one question at a time, writes down what they said in their words, reads it back, and only then files it. Nothing goes into the evidence bank that the user didn't say and didn't confirm.

Load `kit-basics` first (folder map, how to run scripts). Read `${CLAUDE_PLUGIN_ROOT}/skills/kit-basics/references/bullet-format.md` and `confidentiality.md` before session 2.

## Which session is next

Check the Job Search folder and say in one line where the user is:
1. `Evidence Bank/North Star.md` still has a line containing `<fill in`: **session 1**.
2. `Evidence Bank/Evidence Bank.md` has no story card past the template's `E01 <Short name>`: **session 2**.
3. `Rules File.md` still has a line containing `<fill in`, or `keyword-groups.json` has empty `WORK_FAMILIES`: **session 3**.
4. No `master-selection.json` at the root, no master resume built from it, or no "Master" row in `Review/review-log.md` (the review round didn't happen): **session 4**.
5. All done: offer the next step (a first application with `application-materials`, or another story with `evidence-interview`). If `approval-queue.md` has any row still "pending", offer the `approval-session` first.

Every placeholder a session fills starts `<fill in`. A line the user answered "not sure" is replaced with `Open (asked YYYY-MM-DD): <the question>`; that counts as answered for the check above, and the next session starts by reading the Open lines back and asking once more. (These Open lines are different from a story card's "To find out:" field, which an evidence session answers, not Start Here.)

A session can stop early. Save what's done, add a line to the North Star's "Decided on" list saying where to pick up, and close out.

## How to interview

- One question at a time. Plain words. No forms to fill; the user talks and Claude writes.
- Capture the user's words. Read each item back before filing it. If they change a word, take theirs.
- When a figure comes up, ask three things: is it exact or rough, could an outsider do anything with it, and would their employer mind seeing it in print. Exact goes to the Prep File; the rounded shape they're comfortable with goes on paper, listed in the bank's Part C.
- When the user says "we", ask who decided and who did the work. Their answer sets the card's Role line (my call, shared, helped) and the verbs.
- When evidence seems missing, suspect the questions, not the user. Ask about the time something went wrong, the thing they argued for and won, the decision they'd defend, the number they watched.
- Never suggest a result the user didn't state. If a story has no measurable result, say so and keep it; "Why it mattered" can be a decision someone made or a problem that stopped recurring.
- Keep the user's confidentiality instincts. If they hesitate over a detail, ask: "Prep File only, or nowhere at all?" Nowhere means nowhere: not the Prep File, not Part C, not the transcript of the session.
- When the user says "not sure", don't fill the gap with a guess. Write the Open line (above) and move on.
- Until session 4, evidence mode is lighter: rebuild the index after a bank edit, but there is no master to rebuild or review yet.

## The four sessions

Each session's questions, outputs, and file edits are in `references/`:
- `references/session-1-north-star.md`: what they want and why, how they write, confirmed gaps. Writes `North Star.md`, Rules File sections 2, 9, and 11.
- `references/session-2-stories.md`: four to six story cards with bullets, figures, and prep detail. Writes the bank's Part B, Part C, and Part D, and the Prep File.
- `references/session-3-rules-and-keywords.md`: employer specifics, outsider wording, retired wording, keyword groups. Writes Rules File sections 4 to 6, 10, and 12, the Retired Claims Log, `keyword-groups.json`, four lists in `settings/resume.json`, and pending edits in `approval-queue.md`.
- `references/session-4-master.md`: open items and the approval queue, profile and fixed facts, the master selection, build, gate, target-level review. Writes the bank's Part A and `master-selection.json`, builds the master.

## Every session ends the same way

1. Read back what was filed, in one short list.
2. Rebuild the bank index if the bank changed (`bank_index.py`).
3. Add a dated line to `North Star.md` under "Decided on" (the first one replaces the template's example line) and, if the bank changed (sessions 2 and 4), to the bank's Part D.
4. Say what the next session covers and roughly how long it takes.
5. A bullet the user wants to think about goes in `approval-queue.md` as pending, not into the bank. Anything else they want to think about (pay, level, a rule) stays as an Open line where it belongs.
