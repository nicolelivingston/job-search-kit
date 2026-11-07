# Filing and timekeeping

## Claude keeps the clock

The user does not track time; never ask them to. Every selection file carries a `timeline` block of local-time timestamps:
- `drafting_started`: the first selection file for this posting.
- `v1_delivered`, `v2_delivered`, ...: each version handed to the user.
- `correction_v1`, `correction_v2`, ...: each correction message, at the time it arrived.
- `submitted`: when the user says they applied, or the time they state.

When the user says they submitted, compute and write to the tracker:
- **Hours Spent**: an estimate of the user's active time. Sum the gaps between each delivery and their next reply where the gap is under two hours, plus 20 minutes for the application form unless they say otherwise. Note it with `--append-notes "Hours Spent is an estimate"` (append, so earlier notes stay).
- **Cycle time**: days from Drafting Started to Date Applied. Compute it and write `--set "Cycle Days=N"`.
Report both in one line and ask the user to correct the estimate if it's off.

## When the user says they applied

In one pass:
1. Rename the folder to `Applications/<Company> (sent YYYY-MM-DD)/`. Move earlier versions to `Archive/Superseded drafts/` (create it if needed), keeping the version that was sent and its selection file.
2. Tracker row (`tracker_cli.py update <id> ...`): `--status Applied` (sets Date Applied today; pass `--set "Date Applied=YYYY-MM-DD"` if it was another day), `--set "Resume Versions=N"`, `--set "Cover Letter Versions=N"` (every version drafted, restarts included), `--set "Resume Version Used=v3"`, `--set "Hours Spent=1.5"`, `--set "Posting Age At Send=12"` (days since the posting's first-published date, or first seen), `--set "Contact Before Applying=<yes | tried, no answer | after applying | none>"`.
3. `timeline.submitted` and `notes.posting_age_at_send` and `notes.contact_before_applying` in the selection file.
4. `Review/review-log.md`: the row's last column, corrections the user made after delivery (a number first, then a note).
5. The Prep File: the rubric reviewer's interview questions under the company, if not already there.

If the application is dropped instead: `(on hold)` or leave as drafting with a tracker note, and still fill the version counts so the cost of unsent drafts is visible.

## Later state changes

- **Screen or interview scheduled**: status "Interviewing", `--set "Interview Stage=<stage>"`, `--set "Interview Stage Date=YYYY-MM-DD"`. Before the call, a company prep page in `Interview Prep/<Company>/` from the bank cards and the Prep File. Within a day after, a short debrief in the same folder; anything it surfaces goes to `bank-issues.md` and the Prep File.
- **Rejection**: folder to `(sent YYYY-MM-DD, rejected)`, `--status Rejected --outcome Rejected` (sets Outcome Date today; the row moves to Complete on the tracker page and drops out of `list --open`), review log unchanged.
- **Offer, withdrawal, no response after 30 days**: `--outcome <Offer | Withdrew | No response>`.
- **Networking only**: `(networking, not applied)`.

After any state change, check every other `Applications/` folder name against the tracker's open rows (`tracker_cli.py list --open`) and fix any mismatch in the same pass.

## Session close-out

Commit nothing (the user's folder isn't a git repository unless they made it one). Confirm every file is saved, the review log row is complete, the tracker matches the folders (`tracker_cli.py show <id>` prints every field of a row), and name the next thing that needs the user: a note to send, a version to review, a form to submit.
