---
name: approval-session
description: >
  This skill should be used when a Job Search Kit user wants to change their
  evidence bank on purpose: "approval session", "let's go through the queue",
  "approve my pending evidence", "that bullet is wrong, fix it", "retire that
  phrase", "update my rules file", "I corrected a fact, sweep everything", or
  whenever a correction or approved wording has to land in the bank. It works
  through the approval queue item by item (yes, edit, or no), applies the
  changes in the bank, rebuilds the index and the master, re-gates every unsent
  tailored file, and runs the target-level review on the master.
metadata:
  version: "0.1.0"
---

# Approval session

Evidence mode. This is the only time `Evidence Bank.md`, `Rules File.md`, `Retired Claims Log.md`, and `Prep File.md` change. Everything pending is in `Evidence Bank/approval-queue.md`; the user says yes, edit, or no to each item, and the bank changes accordingly. Then every file that depends on the bank is rebuilt in the same session, so nothing drifts.

Load `kit-basics` first. Read `${CLAUDE_PLUGIN_ROOT}/skills/kit-basics/references/bullet-format.md`, `confidentiality.md`, and `voice-and-letters.md`.

## Before the first change

1. Read the bank end to end, the Rules File, the Retired Claims Log, the queue, the proposed-evidence files it points at, and `Review/bank-issues.md`.
2. Fold any bank-issues rows not yet in the queue into it (dated, status pending), so the user rules on everything in one list.
3. Present the queue as one numbered list: each item with its proposed text, the card it touches, and the choices (yes, edit, no). Items that are corrections to existing facts go first, since they sweep the widest.

## Ruling, item by item

- **Yes**: apply exactly the queued wording.
- **Edit**: take the user's words. Read the final line back before writing it.
- **No**: mark the row rejected with their reason in a few words. A rejected figure or phrase the user never wants on paper again goes to the Retired Claims Log.
- **Think about it**: stays pending with today's date.

Before editing any bullet, read its current line in the bank and print it. Never replace from an earlier read; another session may have changed it.

## Applying changes to the bank

- A new bullet gets the next ID on its card (`E07.4`) and its tag. A new card gets the next card number; never renumber existing cards.
- A reworded bullet: the old line becomes `[superseded]` (kept for the record) and the new wording gets a new ID, unless the change is a correction of fact, in which case the line changes in place and Part D says so. The builder refuses superseded IDs, so any selection file using the old ID will fail its next build; that is the signal to update it.
- A changed figure: Part C first (status paper, prep only, or retired), then every bullet that carries it. A retired figure goes to the Retired Claims Log with the date and what to say instead.
- A retired phrase: append to the Retired Claims Log in double quotes if 18 characters or longer; shorter phrases also go in `settings/resume.json` under `presend_gate.RETIRED_PHRASES`. The gate reads both.
- A new rule: the right section of the Rules File, dated where the section dates things. If it supersedes a rule, reword the old rule rather than deleting it, and move retired wording to the log.
- A new confirmed gap: Rules File section 11 and, if postings ask for it by name, a `GAP_FAMILIES` or `MINIMUM_FAMILIES` entry in `keyword-groups.json`.
- A new story that postings ask for: a `WORK_FAMILIES` entry or an added card ID on an existing one.
- Exact figures, dates, names, and internal detail: Prep File.
- Part D gets one dated line per session summarizing what changed; a card's "To find out" line gets updated where a question was answered.

Mark each queue row approved or rejected with the date.

## After any bank change, in this order

1. `bank_index.py`. If it reports a line it couldn't read, fix the line shape and run again.
2. Rebuild the master: `build_resume.py master-selection.json`, then `presend_gate.py` on it. If a bullet was superseded, update `master-selection.json` to the new ID. If the new wording changed the page count or a figure now appears twice, fix the selection file.
3. Rebuild every unsent tailored file: for each `Applications/<Company> (drafting)/` or `(on hold)` folder, build from its selection file (rebuilding an unsent file in place is fine) and re-gate. Report which were rebuilt. Sent files are never edited; if a correction affects a sent document, add an interview-prep note under that company in the Prep File instead.
4. Re-check the tags of every ID those selection files use: a primary can have become an alternate, an ID superseded, a figure moved to prep only.
5. Run the `target-level-reviewer` agent on the master as a fresh subagent (bank, Rules File, Retired Claims Log, the master's text, the gate's full output; no posting, no shell). One round. Bring its ASKs to the user as one numbered list; apply what they approve; rebuild and re-gate. Log the round in `Review/review-log.md`.
6. Update the Prep File and any interview prep pages that quote old wording.

## When the user corrects something outside a session

A correction is an approval with the user's own words. Apply it here the same way, the same day: bank first, then the list above. Ask whether that's the only place it's off or whether to sweep everything, and report plainly which documents were touched and which were left alone, and why. If the correction shows a rule was wrong, supersede the rule in the Rules File, append the retired wording to the log, and make sure the gate catches it next time (a phrase in the log or in `RETIRED_PHRASES`). If the user pushes back on a flag or a rewrite, take it seriously, own the miss in one plain sentence, and fix it.

## Close

Read back: items approved, edited, rejected, still pending; what was rebuilt; what the target-level review changed; anything that needs the user next. Clear nothing from the queue; approved and rejected rows stay as the record.
