# Session 4: The master resume (about 30 minutes)

Goal: the bank's Part A filled, `master-selection.json` at the root of the Job Search folder, the master resume built from it and gated, one target-level review round, and the user holding a Word file that is every approved bullet on one document. Tailored resumes later select down from this; the master itself may run longer than the tailored page limit.

## Part 0. Open items first (5 minutes)

1. Read back every `Open (asked ...)` line in the North Star and the Rules File and ask each once more. An answer replaces the line; "still not sure" keeps it.
2. Read back every Part C figure not marked "paper" yet ("not yet cleared" or similar). Ask: paper, prep only, or drop. Update Part C. A figure the Money rule rules out is prep only.
3. Work the approval queue: each pending row (internal terms and retired wording queued in session 3, bullets the user wanted to think about) gets yes, edit, or no from the user, the same way an approval session does. Apply the approved edits to the bank, add a Part D line, and rebuild the index. The master is built only after the queue has no pending row that touches a bullet going on it.

## Part 1. Part A: profile and fixed facts (10 minutes)

Fill these lines in `Evidence Bank/Evidence Bank.md`, Part A, keeping the exact `- ID [primary]: text` shape:

- `A.headline`: their title plus a theme, agreed in session 3 (the North Star's "Decided on" line). Then set Rules File section 6's headline line to "Headline: see the bank's A.headline". The theme is what their stories add up to, in three to six words. AI tools don't lead the headline unless the role is an AI role.
- `A.profile`: two or three sentences from the session 1 pitch. Lead with what they own and for whom, then how they work, then the differentiating skill. Never repeat a bullet's words; never open by naming a tool. Read it back; it must sound like them. Put the user's main scale figure in the profile or in the scope line, not both.
- `A.core`: six skill areas, separated by " • ", named for the work in the cards (not tools). Ask the user to confirm each; a skill area with no card behind it comes off.
- `A.scope.t1`: one scope line for the current role ("Own ... for ..."), written for a same-field reader. Don't repeat the headline's theme words. Add `A.scope.t23` if the plain-English version for outside readers differs.
- `A.role.t1`: the current job as `Employer | Title | Location | Mon YYYY - Present` (location optional). One `A.role.t2`, `A.role.t3` per earlier job that gets bullets, and one `A.earlier.1`, `A.earlier.2` per older job shown as a single line (`Employer | Title | YYYY - YYYY`). Titles and dates exactly as their records show. (These lines print on the page; the daily agent's years check uses the settings `YEARS_CLAIMABLE` and `YEARS_RE`, which session 1 confirms.)
- `A.education`, `A.credentials`: as issued, exactly. Ask for the institution and degree as they'd want it printed; credentials by their official names. No credentials: delete the `A.credentials` line (the resume then has no Credentials section).
- `A.tools`: the tools they use, comma separated. Ask which ones they value. A tool goes on only if they've used it in work they could describe in an interview; a course or a trial isn't enough. A tailored page shows these or a subset, never a tool that isn't here.

Rebuild the index.

## Part 2. The selection file (5 minutes)

Copy `<kit>/templates/Applications/selection-template.json` to `<Job Search>/master-selection.json` and fill it:
- `output`: `<First>_<Last>_Master_Resume.docx`.
- `name`, `contact` (city, state, "(Remote)" if they work remotely, phone, email, LinkedIn). Ask for these once; they stay in this file.
- `master`: `true`. This is how the builder and the gate know it's the master (no tier, no page limit).
- `headline`, `profile`, `education`, `credentials`: the Part A IDs. No credentials: delete the `credentials` key. Delete the profile `bridge` key (the master has no bridge).
- `core_expertise`: the six areas from A.core, as a list.
- `roles`: every role with bullets, each as `{"id": "A.role.t1", ...}`. Current role first with `scope` set to `A.scope.t1`, groups labeled for the work (sentence case, three or four words, colon), every `[primary]` bullet by ID in the order that reads best. Alternates and variants stay off the master; tailor-only, interview-only, and proposed never go on it.
- `earlier`: older roles as `{"id": "A.earlier.1"}`; a bullet only if a card exists for it.
- `tools`: the plain string `"A.tools"` (not inside `{"text": ...}`, which prints whatever is typed).
- `tier`: leave null (the master has no tier).
- Delete the `notes`, `letter_sources`, and `timeline` blocks; they're for tailored files.

## Part 3. Build and gate (5 minutes)

1. `build_resume.py master-selection.json`. It prints the IDs used and renders the page count. If it refuses an ID, the tag is wrong in the bank; fix the bank line, rebuild the index, build again.
2. `presend_gate.py <the master .docx>`. Read every flag. Fix a flag in the bank (a figure not in Part C, retired wording, an abbreviation) or the selection file (a duplicate scale figure: swap in the variant without the figure, or drop one; if both copies are Part A lines, take it out of the scope line in the bank). A flag is justified in writing or fixed; silence is not a pass.
3. Open the result with the user: read the profile and the first group of bullets aloud in the chat. Fix wording only by editing the bank line (this is evidence mode, so that's allowed), then rebuild the index and the file.

## Part 4. Target-level review (10 minutes)

Run the `target-level-reviewer` agent as a fresh subagent with the bank, the Rules File, the Retired Claims Log, the master's text, and the gate's full output (it has no shell). It has no posting. It returns findings against what a reader at the user's target level looks for first, each tied to a bullet ID, or an ASK for the user. If subagents aren't available, run its prompt in this session after re-reading only the master's text, the gate output, and the files it lists, and write "same session" in the review log's Reviewer column. Bring the ASKs to the user as one numbered list. Apply what they approve in the bank or the selection file, rebuild, re-gate. One round; stop at the reviewer's stop rule.

Log the round in `Review/review-log.md`: date, "Master", "target-level", findings raised, accepted, rejected and why, 0 corrections after delivery (fill the last column later if the user corrects the master after this session). Count each ASK as a finding: answered and applied is accepted; declined or still open at the end of the session is rejected, with "ASK open" as the reason. This row is what tells the next session that Start Here is complete.

## File edits

- `Evidence Bank/Evidence Bank.md`: Part A; a dated Part D line.
- `master-selection.json` and the master `.docx` at the root.
- `Evidence Bank/bank-index.json`: rebuilt.
- `Review/review-log.md`: one row.
- `Evidence Bank/approval-queue.md`: every row worked in Part 0 marked approved, edited, or declined.
- `Evidence Bank/North Star.md`, `Rules File.md`: Open lines answered in Part 0; section 6 headline line.
- `Evidence Bank/North Star.md`: dated "Decided on" line: "Start Here complete; master v1 built."

## Close

Say what they have now: a bank with N cards, the rules in one file, a master resume that every tailored resume will select from, and a daily agent that scores postings against their stories. Say the next step is their first application with the `application-materials` skill when a posting they want to pursue lands in the tracker, and that new stories go through `evidence-interview`.
