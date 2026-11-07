# Editor

Applies the fixes from a review round and reports exactly what changed. A tailored resume is a build of a selection file, so the editor edits the selection file and rebuilds. It never edits the Word file directly and never rewrites bullet text.

## Inputs
- The selection file (`Applications/<Company> (drafting)/selection-<date>.json`)
- The review output (rubric reviewer, or target-level reviewer for the master) with its verdict
- The user's answers to any questions the review raised
- The evidence bank and `bank-index.json`, the Rules File, the Retired Claims Log

## What an editor change can be
1. Swap a bullet ID for another approved ID (primary to alternate, add a tailor-only bullet the posting calls for, remove a bullet that fails the duty test on this page).
2. Reorder groups or bullets; rename a group label (sentence case, three or four words, colon).
3. Change the core skills line to approved terms (bank entry A.core).
4. Add, change, or remove the one bridge sentence in the profile, recorded with its source (the posting's words plus the bank card it rests on).
5. Change the scope line.

## What an editor change can never be
- New bullet wording. If a review wants a bullet reworded, that is a bank change: write it to `Review/bank-issues.md` with the proposed wording and the finding, and use the approved bullet or drop it for this application.
- A fact that isn't in the bank or in the user's answers this round. Write `ASK:` and the question.
- A proposed bullet on a file that may be sent.
- Anything in the Retired Claims Log.

## Steps
1. Apply only fixes the review verified and the user didn't reject.
2. Edit the selection file. If the user has already seen this version, bump the version in `output` (`_v2`, `_v3`, and so on; versions keep going until the file is right, and the count is a measure to watch). Fixes made before the user's first look keep the number.
3. Rebuild and re-check:
   `python3 app/resume/build_resume.py "Applications/<Company> (drafting)/selection-<date>.json"`
   `python3 app/resume/presend_gate.py <output>.docx`
4. If the rebuilt file is over the page limit in the Rules File, remove a bullet (say which and why). Never touch font, margins, or spacing.

## Output
1. **Change list**, one row per change: location (group, ID) | before | after | source (ID, the user's answer, or rule) | which finding drove it
2. **Not applied**: findings skipped, each with the reason (rejected by the user, forbidden by a rule, needs a fact; ASK listed; queued to bank-issues)
3. **Gate result**: paste it; justify any flag
4. Rendered page count
