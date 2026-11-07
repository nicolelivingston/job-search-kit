# Session 2: Story cards (about 45 minutes, repeatable)

Goal: four to six story cards in `Evidence Bank/Evidence Bank.md`, each with one to three approved bullets, its figures sorted into paper and prep, and its exact detail in `Evidence Bank/Prep File.md`. More stories come later through the `evidence-interview` skill; this session establishes the shape.

Read `bullet-format.md` and `confidentiality.md` (in the kit-basics skill's references) before starting. Write bullets to the user's `bullet_length` and `format_rules` in `settings/preferences.json`. Read the bank template's "How to read a card" section so the card shape and the `- ID [tag]: text` bullet line are exact; the index builder reads them by machine.

## Picking the stories

Ask for the list first, then go deep one at a time:

1. "Name the four to six pieces of work from the last few years you'd want a hiring manager to know about. One line each." Write them as a numbered list and read it back.
2. Steer toward range: one thing they shipped, one decision they made under constraint, one time they changed what leaders decided, one time something went wrong and what they did, one thing that shows how they work with other teams. If the list is all one kind, ask for the missing kind.
3. Order them as the user likes. Card numbers never change, and session 3's keyword groups decide which stories the daily matches lean on.

## One card at a time (about 7 minutes each)

For each story, ask in this order and write their answers as said:

- **Situation.** "What was going on, and why did it matter?"
- **What you did.** "What did you do, specifically? What did you decide?" Then: "Who decided, and who did the work?" The answer sets Role: my call, shared, or helped. When parts differ, write shared and say who did what ("shared: requirements and rollout mine, vendor contract my manager's"); the verbs follow each part.
- **What changed.** "What happened because of that? What could you see or count afterward?" If nothing countable: "What did someone decide, or stop doing, because of it?"
- **Why it mattered.** "Who was better off, and how?"
- **Figures.** For every number: exact or rough? Could an outsider do anything with it? Would your employer mind it in print? Exact goes to the Prep File. The rounded shape they're comfortable with is "Cleared" on the card and goes in Part C as paper. A figure they're unsure about goes in Part C as "not yet cleared". A figure they don't want written anywhere goes nowhere: the card and Part C say "(amount withheld by the user)" in its place, the Prep File doesn't get it, and it is never asked for again.
- **Sensitivity.** "Anything in this story that's internal: a system name, a plan that isn't public, a customer, a coworker?" Internal names go to the Prep File; the card uses the plain-English swap (what the thing does, for whom). Unannounced plans and dates never leave the Prep File.
- **Status.** Shipped, in progress, or ongoing. Sets the tense.
- **To find out.** "What would make this stronger if you could find it out?" One or two questions, saved on the card.

Then draft the bullets:

- One to three bullets per card, three parts each (what, what it caused, why it mattered), in the user's voice from Rules File section 2, using only what they said. Read each one back. Yes, edit, or no.
- Approved bullets get `[primary]`. A second angle on the same story gets `[alternate: <angle>]`. A wording that fits only one situation gets `[variant: <when>]`. Something they want to keep but not put on a resume gets `[interview-only]`.
- A bullet they want to think about gets a `P-` ID and the `[proposed]` tag (`- P-E01.2 [proposed]: ...`) and a row in `approval-queue.md`. On approval the approval session gives it the next free `E01.N` ID and its real tag. The gate refuses proposed bullets on anything that may be sent, so there is no harm in parking one.
- Never write a result the user didn't say. If part 2 or 3 is missing, ask once more; if it's still missing, write the bullet with the parts they have and put the missing part in the card's "To find out" line.

## Numbering

Cards are `E01`, `E02`, ... in the order agreed. Bullets are `E01.1`, `E01.2`. Never renumber a card later; new cards append.

## File edits

- `Evidence Bank/Evidence Bank.md`: replace the template card with the real cards in Part B, keep the exact line shapes. Fill Part C with every figure the user allowed to be written (paper, prep only, or not yet cleared, with the story); a withheld one appears only as "(amount withheld by the user)". Leave Part A's placeholders for session 4; the index marks them as placeholders, never paper. Add a dated Part D line: "Session 2: cards E01 to E0N added."
- `Evidence Bank/Prep File.md`: one section per card with exact figures, dates, people and teams, internal names, and the likely interview questions the story raises. Answers to those questions come from the user, in a later session if not now; never draft them.
- `Evidence Bank/approval-queue.md`: any proposed bullets.
- Rebuild the index: `bank_index.py`. If it reports a line it couldn't read, fix the line shape and run it again.

## Close

Read back the card names and bullet counts. Say session 3 is the rules (employer specifics, words to keep off paper, and the keyword groups that tie the daily job matches to these stories), about 30 minutes.
