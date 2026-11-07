# Voice, attribution, and cover letters

## Voice

The user's voice lives in their Rules File, section 2, built from their own writing in the Start Here sessions and their setup step 8 choices (`settings/preferences.json`: habits to avoid, punctuation, tone, saved fixes). Apply it everywhere: resume bullets, letters, application answers, and replies to the user. General defaults until their section or preferences say otherwise (each format rule here can be turned off in `format_rules`):

- Plain and concrete. No buzzwords.
- When the user supplies wording, keep it exactly. Don't upgrade it.
- No abbreviations on paper unless the posting uses them; credential names as issued.
- Specific active verbs, no personal pronouns in bullets, fact-based with results, consistent and easy to skim.

## Attribution

Users correct attribution more than anything else. Before writing any bullet about shared work, ask who directed and who facilitated, and default to the softer version. Modest verbs carry attribution: "helped define", "put team capacity toward", "partnered with". Never list collaborators inside a bullet. Each bank card's Role line (my call, shared, helped) sets the verb; if the card doesn't say, ask.

## Positioning

- Lead the profile with what the user owns and for whom, then how they work, then the differentiating skill. Never open by defining them as the tool they use.
- Name a real gap once, compactly, after a strength has landed. Don't overstate equivalence between the user's work and the employer's domain.
- Tools get one mention, in the bullet where they earned it, plus the tools line. AI tools the user works with belong on the tools line, not in the headline, unless the role is an AI role.
- Old experience: a title line with no bullet is fine; never invent a bullet to fill a role.
- Cut unverifiable self-praise. Outside reviews the user brings in (another AI tool, a friend, a coach) are evidence-session input, never application input.

## Audience translation

Most employers are outside the user's current field. Define a thing once in plain words, then say what the user did with it. Run every term against two vocabularies: does the posting use it, and does the user? If neither, replace it.

## Cover letters

- One page, same font and size as the resume, addressed to a named person when possible; a plain "Dear <Company> Hiring Team" beats a guessed name.
- Every body paragraph is sourced: fill `letter_sources` in the selection file, one entry per paragraph naming the bank card ID(s) it rests on or the user's dated statement in their words. The gate flags a letter with fewer sources than paragraphs. A paragraph with no source is cut, not softened.
- Drafted from the bank cards (situation, what changed, why it mattered), in the user's voice. When the user supplies a sentence, use it verbatim.
- Lead with qualifications, never with gaps. Two or three real stories beat a checklist. Don't count matches, don't open consecutive paragraphs with the same formula, don't explain the company's values back to them. End on the employer's actual problem.
- Cover letters are where confidentiality slips happen. Gate them hardest.
- If the application form has no cover letter field and no free text, the letter goes into the resume file as page three (resume first), and the selection notes say so.
