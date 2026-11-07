# Session 3: Rules and keyword groups (about 30 minutes)

Goal: no `<fill in>` lines left in the Rules File, a seeded Retired Claims Log, `keyword-groups.json` tied to the story cards, and the gate's word lists in `settings/resume.json` matching. After this session the daily job agent scores postings against the user's own stories, and the gate knows their retired wording.

## Part 1. Employer specifics (10 minutes)

Rules File section 5 has three `<fill in>` spots. Ask:

1. "What at your employer must never show up in print? System names, project names, vendors, a plan that isn't announced, anything a lawyer or your manager would wince at." Start from `keep_general` in `settings/preferences.json` (what they said in setup should stay general) and read it back. List them under "Never on paper". Internal names also go in the Prep File if they aren't already there, except a detail the user marked "nowhere at all": for that one, write only a generic description ("an unannounced vendor change") under "Never on paper", and remove the detail itself from the Prep File, the cards, and Part C if an earlier session filed it.
2. "For each internal term in your stories, what would you say to someone outside the company?" Build the "Outsider wording" list from the cards: the internal term to the plain term. Reuse the swaps already made on the cards in session 2. Then search the bank (every card and bullet, and Part C) for each internal term and each "Never on paper" name. Each hit goes in `approval-queue.md` as a pending edit ("E02.1: 'Cabinet' to 'leadership team'"); session 4 works the queue before it builds anything. The bank itself doesn't change in this session.
3. "May a dollar figure ever appear on your resume?" Section 4, Money. If the user isn't sure, write the Open line (`Open (asked YYYY-MM-DD): may a dollar figure appear?`) and treat it as no until it's answered.
4. "Which field is your current employer in? Which fields are adjacent?" This settles how tier 1 and tier 2 get assigned per application. Write one line under Tiers naming the user's field.

## Part 2. Document rules (5 minutes)

5. Section 6: one or two pages for tailored resumes (if `resume_pages` in `settings/preferences.json` is `one` or `two`, use it and say so; for `auto`, default two for ten or more years of experience, one otherwise; write the same number to `presend_gate.PAGE_LIMIT` in `settings/resume.json`, which the builder and the gate read), the headline (their title plus a theme, in words from the session 1 pitch). Write it once, as `A.headline` in session 4; section 6 says "Headline: see the bank's A.headline" so the two can't drift. Until then, note the agreed headline in the North Star's "Decided on" line. The format itself (font, sizes, margins) comes from `settings/resume.json`, which the wizard set.

## Part 3. Reviewer constraints and exceptions (5 minutes)

6. Section 10: "What should a reviewer never suggest for you?" Two or three lines from the user, such as "Never call me a generalist" or "Keep my license on the first page". These bind every reviewer.
7. Section 12: replace the template's example line with a dated ruling if one came up in sessions 1 or 2 (for example, the user allowed a dollar figure for nonprofit employers), or with "None yet." Date it.

## Part 4. Retired wording (3 minutes)

8. "Any phrase or figure you've used on a resume before that you never want to use again?" Append each to `Retired Claims Log.md` with the date, the reason, and what to say instead; the first row replaces the template's example row. Phrases of 18 characters or more go in double quotes in the "Retired wording" column so the gate reads them. The gate reads quotes only from that column, so quotes in "Say instead" are safe. Shorter ones also go in `settings/resume.json` under `presend_gate.RETIRED_PHRASES`.
9. Search the bank (every bullet, every Cleared line, and Part C) for each retired phrase or figure. Each hit goes in `approval-queue.md` as a pending edit with the replacement wording; session 4 fixes it before the build. The gate flags retired wording even inside approved bullets, so a hit left in the bank will stop the master.

## Part 5. Keyword groups (10 minutes)

`Evidence Bank/keyword-groups.json` tells the daily agent which posting words match which stories. Build it from the cards, confirming each group with the user. The file shape (see the kit's `templates/Evidence Bank/keyword-groups.json` and the examples) is:

```json
{"fit_scoring": {
  "WORK_FAMILIES":    [{"$tuple": ["<group name>", "E01 E02", 10, {"$rx": ["word", "phrase"]}]}],
  "GAP_FAMILIES":     [{"$tuple": ["<gap name>", 6, {"$rx": ["word"]}]}],
  "MINIMUM_FAMILIES": [{"$tuple": ["<requirement>", {"$rx": ["word", "phrase"]}]}]
}}
```

- **WORK_FAMILIES**: three to six groups. Each names a kind of work the cards prove, lists the card IDs that prove it, carries points (10 for their strongest and most-asked-for work, down to 6), and lists the words a posting would use for it. Ask: "When a posting is asking for this kind of work, what words does it use?" Lowercase, plain words and short phrases, letters, spaces, and hyphens only. The kit adds word boundaries and escapes symbols for you, so a phrase ending in "+" or "%" will never match; write "10 plus years" as "years" instead.
- **GAP_FAMILIES**: one group per confirmed gap from Rules File section 11 that postings ask for by name, with points (4 to 8, higher for gaps that would sink an application) and the words postings use.
- **MINIMUM_FAMILIES**: requirements the user cannot claim at all (a certification, a language, a hard skill). A posting that lists one counts it as a missed minimum. A requirement can be both a gap and a minimum (a certification the user lacks): put it in both. GAP_FAMILIES lowers the fit score; MINIMUM_FAMILIES counts it toward the "missing two or more minimums" stop.

Write the file with two-space indentation. Then confirm it loads: `tracker_cli.py check-groups`. It reads the file, checks every group's shape, and scores a sample posting. It prints "groups OK" or a plain message naming the group that's wrong (exit code 1); fix that group and run it again. Don't close the session until it passes.

## Part 6. Gate lists (2 minutes)

In `settings/resume.json`, edit only these four keys under `presend_gate`, keeping everything else as the wizard wrote it:
- `ONCE_PER_RESUME`: every scale figure marked paper in the bank's Part C, written exactly as it appears in the bullets (the gate counts each at most once per resume). A scale figure sizes the thing the user worked on (people served, records, sites, budget); a result figure (a rate that rose, time saved) is not one. If unsure, ask: "Does this number say how big it was, or what changed?"
- `VOCAB_TERMS`: every "Never on paper" name and every internal term from the "Outsider wording" list, so the gate flags them on any page. For a "nowhere at all" item, add only a word that can't identify it (or nothing).
- `RETIRED_PHRASES`: retired phrases shorter than 18 characters.
- `ABBREVIATIONS`: add any abbreviation from the user's field they want kept off paper.

## File edits

- `Evidence Bank/Rules File.md`: sections 4, 5, 6, 10, and 12. Section 11 isn't edited here; if a new gap came up, add it and note it in the "Decided on" line.
- `Evidence Bank/Retired Claims Log.md`: appended rows.
- `Evidence Bank/keyword-groups.json`: written.
- `settings/resume.json`: the four lists above and `presend_gate.PAGE_LIMIT`.
- `Evidence Bank/approval-queue.md`: pending edits for internal terms and retired wording found in the bank.
- `Evidence Bank/North Star.md`: dated "Decided on" line.

## Close

Read back the keyword groups in one list ("the agent will now score postings for: ..."). Say session 4 builds the master resume, about 30 minutes, and that it's the first time they'll see a page.
