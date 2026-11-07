# Session 1: North Star, voice, and gaps (about 45 minutes)

Goal: by the end, `Evidence Bank/North Star.md` has no line containing `<fill in` (each one answered, or an Open line where the user wasn't sure), the Rules File has the user's voice (section 2), target level (section 9), and confirmed gaps (section 11), and the user has heard their own pitch read back.

Open by saying what this session is for and that nothing goes on a resume today.

## Part 1. The role (10 minutes)

The setup wizard asks titles, level, work arrangement, pay, and fields, and saves them in `settings/criteria.json`. Read those first. If `agent.TITLE_KEYWORDS` is empty or `agent.SALARY_FLOOR` is 0, the wizard's search questions weren't answered: ask them here for the North Star, and at the close tell the user to run the wizard (Change my settings) so the daily search uses them. Otherwise confirm in a sentence ("You told the wizard: senior product roles, remote, at least X. Still right?") instead of asking again. Check the years settings the same way: `agent.YEARS_CLAIMABLE` (years of experience they can claim in their field; 0 means not set) and `agent.YEARS_RE` (the words for their field in a "5+ years of ..." line). If either is unset or doesn't describe their field, the daily agent can't check years minimums; send them to the wizard with the right answer. If anything they say now differs from the settings, list the differences at the close and send them to the wizard; the plugin never edits search settings. Then ask what the wizard can't:

1. "Why are you looking?" Write their sentences down as said.
2. "If you could only get one of these, which: more pay, staying remote, the field, the level, a better team, learning something new, stability, time back?" Rank what they name.
3. "What would make you turn a job down even if everything else fit?" These become the North Star's rules. (Gaps come only from question 11.)

## Part 2. The pitch (15 minutes)

4. "Tell me what you do, as you'd tell a friend who doesn't work in your field." Let them talk. Don't interrupt to tidy.
5. "What do you own? Who is it for?"
6. "How do you work? What do people come to you for?"
7. "What are you good at that your title doesn't say?"

Draft the one-paragraph pitch from their words only. Read it back. Edit until they say it sounds like them. This paragraph is the seed of the resume profile in session 4, so it must be theirs. It is revisited in session 4 once the stories exist, and anything that criticizes another company or team comes out then (confidentiality rule on other parties).

## Part 3. Voice (10 minutes)

8. Ask for two or three things they wrote themselves (an email they were happy with, a note to their team, a message to a friend). They can paste them in. If they have none to hand, read their voice from how they've talked in this session and write an Open line for punctuation. Read for: sentence length, punctuation habits, words they use and words they'd never use, whether they use contractions, how they join clauses.
9. Say what you noticed in three to five plain phrases and ask if that's right ("long sentences, lots of dashes, you'd never say 'synergy'").
10. "Any words or phrases you can't stand on a resume?" These go in Rules File section 2 as "not my voice".
11a. Note any habit they name or you hear that drafts should correct ("I round my numbers down"). It goes in section 2's habits line, and every later session asks "who did it?" when it shows up.

Write Rules File section 2 from this: the three-to-five-word description, punctuation they prefer or avoid, phrases that aren't their voice, habits to correct. Keep the template's default lines below theirs.

## Part 4. Gaps (5 minutes)

11. "What do postings in your field ask for that you don't have?" Take each one as a plain statement ("no Spanish", "never owned a budget", "no enterprise sales"). These are confirmed gaps: Rules File section 11 and the North Star's gaps list. Say plainly that gaps go in a cover letter or an interview answer when relevant and are never fixed by adding to the resume.
12. "What level are you aiming for, and what do you think a hiring manager at that level looks for first?" Rules File section 9. If they don't know the second part, write "keep the reviewer's default rows".

## File edits

- `Evidence Bank/North Star.md`: every section, in their words, or an Open line. Add a dated "Decided on" line: "Session 1 done; pitch and gaps agreed." Session 1 doesn't touch the bank, so no Part D line.
- `Evidence Bank/Rules File.md`: sections 2, 9, and 11. Leave every other `<fill in` line for session 3.

## Close

Read back the pitch and the gaps. Say session 2 is the stories (four to six of them, about 45 minutes) and ask them to think of the work they're proudest of and the time something went wrong and they fixed it.
