# Rules File

One place for every rule that governs your job-search materials. Where anything else disagrees with this file, this file wins. Edit it only in an evidence session, never while drafting an application.

Lines marked "fill in" are set during the Start Here sessions. The rest are defaults; change any of them.

# 1. Standing principles

- **Never fabricate.** No accomplishment, metric, scope, or experience that isn't in the evidence bank. Flag gaps instead of papering over them.
- **Every claim traces.** Each resume bullet carries an evidence bank ID. No ID, no bullet.
- **Your words stay your words.** When you've supplied wording, keep it. Shortening a bullet is not license to rename what you described.
- **Conservative wins.** When two safe wordings exist, take the more general one.
- **Exact detail stays in prep.** Exact figures, dates, names, and internal detail live in the Prep File and nowhere else.
- **Corrections spread.** Fix the bank first, then the master, then every unsent document, in the same pass. Sent documents are never edited; add an interview note instead.
- **AI drafts are input only.** Bullets, titles, dates, or figures from any AI tool go through the bank like anything else.

# 2. Voice

- <fill in: three to five words for how you write, e.g. warm, precise, upbeat>
- <fill in: punctuation you prefer or avoid>
- <fill in: phrases that are not your voice>
- <fill in: habits drafts should correct, e.g. "I round my numbers down; ask for the real figure">
- Bullets have no "I", "my", or "we"; the verb carries the action. Cover letters use "I" sparingly.
- No abbreviations on resumes or cover letters unless the posting uses them; credential names stay as issued.
- Modest verbs carry attribution ("helped define", "partnered with") when the work was shared.

# 3. Bullet format

- Three parts, in order: what you did, what it caused, why it mattered.
- <fill in: how long bullets run and how clauses join>
- Every bullet finishes its own thought, so it can be picked on its own for a tailored page.
- One scope line per role may skip parts two and three ("Lead ... for ...").
- A scale figure appears once per resume. One story gets at most three bullets on a tailored page.
- Bullet-group labels are sentence case, three or four words, ending in a colon. Drop them for portals that re-parse your resume field by field.
- Finished-work verbs only for shipped work; "leading", "developing" for work in progress.
- Never count access as use: people who could use something are not people who use it.

# 4. Numbers

- **Cleared for paper:** only the figures in evidence bank Part C marked "paper", written exactly as listed.
- **Prep only:** every exact count behind those, every date, every figure not in Part C.
- **Retired figures:** see the Retired Claims Log. Never on paper again.
- **Money:** <fill in: whether dollar figures may appear>
- **Estimates:** say "could" and keep them directional. Never present an estimate as a measurement.

# 5. Confidentiality and tiers

**Never on paper**
- Your employer's internal system, product, and vendor names; internal links, tickets, or access groups.
- Unannounced plans, roadmaps, and dates.
- Client names, coworker names, and quotes from feedback.
- Criticism of another team or a failed effort as anyone's failure.
- <fill in: anything else specific to your employer or field>

**Tiers** (how much to translate for a given employer)
- **Tier 1, same field as your current employer:** generalize counts, no timing, no internal terms.
- **Tier 2, adjacent field:** scale numbers fine; translate vocabulary.
- **Tier 3, outside your field:** plain-English translation is the main job.

**Outsider wording** (your internal term to what an outsider would say)
- <fill in: internal term> to <plain term>

The sentence test: cut the internal detail and read it again. If it still proves you can do the job, the detail was never doing the work.

# 6. Document rules

- Word documents, versioned (_v2, _v3), never overwriting anything that may have been sent.
- Tailored resumes stay at <fill in: one or two> pages; render and check before delivering. The master may run longer.
- Format comes from settings/resume.json (font, sizes, margins, spacing). One column, real bullets, no tables or text boxes.
- Headline: see the bank's A.headline (set in Start Here session 4). The profile doesn't repeat the title.
- Cover letters: one page, same font and size as the resume, addressed to a person when possible, examples tied to the posting, limited "I", honest about gaps.

# 7. Per-application process

The bank, the master, this file, and the Retired Claims Log are read-only while drafting.

1. Save the live posting as `posting.md` in `Applications/<Company> (drafting)/`.
2. Check countable minimums, pass or fail.
3. Assign the tier (section 5).
4. Check for a live application at the same company.
5. Answer two questions before drafting: what this role most cares about, and which of your stories fits it best.
6. Keyword table: the posting's term, your term, where on the page. A swap to different words needs your OK; a term with no experience behind it is flagged, never added.
7. Select, don't rewrite: write `selection-<date>.json` from the template, then build with `app/resume/build_resume.py`.
8. Run the pre-send gate on every file; fix flags in the selection file, never the document.
9. One rubric review round. Stop at done.
10. Deliver versioned Word files; the version count per application is a measure to watch.
11. Log the outcome in the tracker.

# 8. Pre-send gate

Run by `app/resume/presend_gate.py`. It traces every bullet to an approved bank ID, flags drift and untraced bullets, reads retired wording from the Retired Claims Log, checks terms and format, counts pages, and flags repetition. It flags; it doesn't clear. Still checked by hand:
- Tier rules applied for this employer.
- Titles and dates match your records; credentials as issued; contact block complete.
- The outsider read: can a reader with none of your context follow why to hire you for THIS role?
- No unnecessary repetition of a phrase, figure, or idea.

# 9. Target level

- Level you're targeting: <fill in, e.g. Lead Designer, Principal Engineer, Head of Sales>
- What a reader at that level looks for first: <fill in: what they look for, or "keep the reviewer's default rows" (the target-level reviewer's prompt holds them)>

# 10. Reviewer constraints

Lines every reviewer must hold. Breaking one is a defect in the review.
- <fill in, e.g. "Never call me a generalist.">
- <fill in, e.g. "Keep my license on the first page.">

# 11. Confirmed gaps

Things you don't have. They score "honest gap", go in the cover letter or interview prep when relevant, and are never fixed by adding.
- <fill in>

# 12. Approved exceptions

Dated rulings that override a rule above for a stated case.
- <date>: <the exception and why>
