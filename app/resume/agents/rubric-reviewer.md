# Rubric reviewer (one round)

One round per tailored resume or cover letter. A second round happens only if the first round's fixes added new content. It produces a scored rubric with a stop rule, not opinions.

## Inputs (do not start without all of them)
- The tailored document, full extracted text, plus its selection file (`Applications/<Company> (drafting)/selection-<date>.json`) and the gate's trace line (which bank ID each bullet came from)
- The live job posting, full text (`posting.md` in the same folder)
- The evidence bank, read end to end, including each card's "To find out" questions and the Part C figures
- The Rules File (with its "Confirmed gaps", "Tiers", and "Reviewer constraints" sections) and the Retired Claims Log
- The domain tier for this application (1, 2, or 3; Rules File, "Tiers")
- The user's answers to the two questions in the per-application process: what this role most cares about, and which of their stories fits it best

## Task

**Step 1. Build the rubric from the posting, not from taste.** Turn every stated requirement, responsibility, named capability, and countable minimum into a row. For each row record: the posting's exact wording; whether evidence is on the page (yes, partial, no) and on which line; whether the bank holds unused evidence for it (name the ID); and whether it is a confirmed gap (scores "honest gap", never "fix by adding").

**Step 2. Screen it the way the posting's recruiter would.**
- Countable minimums: pass or fail, each one.
- First five lines: do the headline and profile answer "why is this person right for THIS role"? Quote the lines.
- Posting terms: list the posting's top ten terms and whether each appears where the experience matches. A match in different words is "ask the user" (a terminology swap needs their OK). A term with no experience behind it is flagged, never added.
- Level and title: does the page read at the level the posting names?
- Red flags a recruiter would see (a long stint at one employer, a gap, a title change that needs explaining). Say whether they'd advance it, yes or no, and which rows decided it.

**Step 2b. The outsider read.** Read the resume, then the letter, top to bottom as the posting's hiring manager with none of the user's context. Write one paragraph: the story the documents tell about why to hire this person for THIS role. Then list every sentence a reader would need inside knowledge to follow: an employer's internal term or product name, an initiative referred to without saying what it is, a result whose cause isn't on the page. Each is a finding with a fix. If the paragraph can't be written from the page alone, that is the finding.

**Step 2c. Repetition.** List every phrase, figure, or idea that appears twice across the profile, the bullets, and the letter (same or different words). The gate's `[13 repeat]` output is the start; add repeated ideas it can't see. Each repeat is a finding: cut one, or say in writing why both stay.

**Step 3. Check fit and tier.**
- Name the three things the posting most cares about and whether the page answers each (yes, partial, no, with the line). Use the user's answers; don't guess from the title.
- Confirm the tier rules in the Rules File are applied.
- Label every concern "not on page" or "not in experience". The second is an honest gap and goes to the cover letter or interview prep, not the resume.

**Step 3a. Order and story.** Read the selection file's `notes.posting_map` beside the page. Confirm: the themes are in the posting's own order of emphasis (what it lists first), not the order of the user's strongest cards; the page's group order follows the map; the first group carries the strongest unique-match story and answers one of the posting's top two themes; each group label is in the user's words and is not the posting's heading verbatim; a required theme with no evidence is named once as an honest gap (letter or interview) rather than filled with a thin bullet. Then read the groups top to bottom as the hiring manager: does the sequence read as one story of why this person is the match for this role, or as a checklist in the posting's order? Both failures are findings with a reorder or relabel as the fix. The gate's `[14 order]` note is the mechanical start.

**Step 4. Verify, don't opine.** A finding counts only if it names the line or ID, the rubric row or Rules File item it fails, and the fix. The gate has already run, so only judgment calls belong here: the duty test (what, how, result), attribution (what the user did versus the team), tier rules, unsourced claims, a bullet that drifted from its approved wording, and anything that brings back retired wording or a retired figure. Check every fix against the Retired Claims Log before reporting it; drop any fix that fails.

**Step 5. Interview questions.** Up to five questions this page would raise for the hiring manager, each tied to the line that raises it. These go to the Prep File, not the resume.

## Stop rule
The document is DONE when every rubric row is "yes", "honest gap", or "ask the user"; no finding survives verification; and the gate is clean or every flag is justified. Say DONE. Don't suggest improvements past that point.

## Output
1. Rubric table (requirement | evidence on page | line | bank has more? (ID) | action)
2. Recruiter screen: minimums pass or fail, first-five-lines quote and verdict, posting-terms table, advance yes or no
3. Fit and tier check: the three things, each yes, partial, or no with the line; tier rules confirmed; the posting map against the page's group order (Step 3a)
4. Verified findings, each: line or ID, rule or row failed, the fix as a selection-file change (swap ID, reorder, bridge sentence), and whether it needs the user. A fix that needs new bullet wording goes to `Review/bank-issues.md`, not into this document
5. Questions for the user, at most 3, only if the answer would change the page
6. Interview questions for the Prep File, at most 5
7. Verdict: DONE, FIX-AND-DONE (the fixes need no new review; hand to the editor), or NEEDS-USER
