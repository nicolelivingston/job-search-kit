# Testing

Bugs are cheaper to catch with a script than by poking around. Four pieces:

1. **Regression tests**, `agent_tests/`. Plain `unittest` scripts, no extra
   tools. Run everything:
   `cd app/agent && KIT_SETTINGS_DIR=../../dev-settings python3 agent_tests/run_all.py`
   Rule: a bug found by hand isn't fixed until a test here would have caught
   it. Write the test from the real case, then fix the code.
2. **Invariants**, `invariants.py`: rules every run must leave true, checked
   at the end of the full run. A new failure raises an alert; warnings go to
   `invariants_last.md` in the data folder.
3. **Profiler and dry run**, `run_stats.py`: every run prints a `Profile:`
   line and appends to `run_stats.jsonl`. `AGENT_DRY_RUN=1` runs the whole
   pipeline with tracker writes recorded to `dry_run_writes.jsonl` instead of
   made.
4. **Equivalence check** (builders only), `dev/equivalence_check.py`: runs
   thousands of real postings through scoring and filtering and prints a hash.
   It proves a refactor changed nothing.

## The invariants (FAIL unless marked WARN)
- one open row per company and normalized title
- hard-rule Poor fit and Passed rows are closed; a soft Poor fit (label "Poor fit (...)": no pay, two or more missing requirements, weak fit) stays open by design
- every rescored open row has a fit label (Strong fit, Possible fit, Poor fit) and never a retired one (Watch, Watch (no decision), Ask me first)
- Strong fit only on Tier A rows
- no posted pay means Tier C, except rows the user marked Applying
- WARN: a Tier C row that got paid research
- WARN: no Posted Date two days after the row was created
- WARN: Applying under 7 with no override reason; Applying older than 14 days with no application
- WARN: a row on a fetched board not verified in 7 or more days
- a row stamped Last Verified today is in today's fetch
- a row closed today isn't live in today's fetch
- the agent never writes Applying or Passed
- fetched postings under 60% of the 7-day median
- WARN: tracker calls over twice the 7-day median
- WARN: a board that returned 0 postings after returning some last run

Add one whenever a bug shows a rule the system was quietly assuming.

## Tracker discipline for chat sessions
- Orient from `tracker_snapshot.md` in the data folder, which is rewritten
  after every run.
- With Notion as the tracker: verify a row with one page fetch before writing
  to it, batch every change to a row into one update, and leave bulk reads to
  the agent.
