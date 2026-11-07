# The judgment checks after the gate

The gate (`presend_gate.py`) does the mechanical work: it traces every bullet to a bank ID, counts scale figures, reads retired wording from the Retired Claims Log, checks terms and format, renders the page count, requires `letter_sources` for a letter, and flags repeated four-word runs. It flags; it doesn't clear. Run these by hand on every document, every version, and report the outcome in one line.

1. **Every gate flag** justified against the bank or fixed in the selection file. Never in the document.
2. **Every number** against the three questions (sizes or measures; round or precise; usable by an outsider), matching the bank's Part C exactly.
3. **Any sentence** naming or implying another team at the user's employer, or calling an internal effort or decision a failure?
4. **The tier** applied (Rules File section 5).
5. **The duty test and the cause-and-effect test** on every bullet (bullet-format.md).
6. **Source every clause** of the bridge sentence and the cover letter to a bank card or something the user said, recorded in `letter_sources` and `notes.bridge_source`. A clause that can't be sourced is cut, not softened.
7. **The cut test** on every sentence carrying proprietary detail (confidentiality.md).
8. **The jargon test** against two vocabularies: the posting's and the user's. Define what a thing is before saying what the user did with it.
9. **Attribution.** Each bullet's verb matches its card's Role line.
10. **Format.** No "I" in resume bullets. No abbreviations on paper (spell them out). The user's own voice and format rules from Rules File sections 2 and 3.
11. **Pages.** Tailored resume at the Rules File's page limit, rendered; page two at or under three quarters. Over means remove a bullet from the selection file, never the font, margins, or spacing, and never a tool the user values without asking. Letter one page.
12. **The outsider read.** Read the resume and then the letter top to bottom as the hiring manager with none of the user's context. Write the one-paragraph story the documents tell about why to hire this person for THIS role. Any sentence that needs inside knowledge to land, and a story that can't be written from the page alone, is a finding to fix.
13. **No unnecessary repetition.** No phrase, figure, or idea twice on a page or twice in a letter: a profile phrase repeated in the bridge, the same story in a bullet and a letter paragraph in the same words, two near-synonyms side by side. The gate finds repeated words; this check finds repeated ideas. Cut one or justify both in writing.

If an item fires, fix it and say which one fired and what changed. If nothing fires, say the gate is clean.
