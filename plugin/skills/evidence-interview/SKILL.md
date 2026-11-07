---
name: evidence-interview
description: >
  This skill should be used when a Job Search Kit user wants to add to their
  evidence bank without changing it yet: "evidence interview", "I have a new
  story", "let's capture what I did on <project>", "add evidence for <skill>",
  "a posting asked for X and I've done that", "interview me about my work", or
  after an interview debrief surfaces something new. It captures the story in
  the user's words into a dated proposed-evidence file and the approval queue.
  The bank itself changes only in an approval session.
metadata:
  version: "0.1.0"
---

# Evidence interview

Capture only. The user talks through one or two stories, or fills a gap a posting exposed, and everything they say lands in `Evidence Bank/proposed-evidence-<YYYY-MM-DD>.md` with a row per item in `Evidence Bank/approval-queue.md`. The bank, the Rules File, and the Prep File are not edited here. (Why: when every interview rewrote the bank, the bank never settled. Capture now, approve on purpose later.)

Load `kit-basics` first. Read `${CLAUDE_PLUGIN_ROOT}/skills/kit-basics/references/bullet-format.md` and `confidentiality.md`. Read the bank end to end before the interview so new material lands on the right card and nothing already there gets re-captured; read `Review/bank-issues.md` and the current `approval-queue.md` so open items get asked about.

Suggested rhythm for the user: two short interviews a week (20 to 30 minutes), one approval session a week. Say this once if they haven't set a rhythm.

## Where the material comes from

Ask which, or pick from what's pending:
1. **A new story** the user names.
2. **A gap a posting exposed.** A posting asked for something and nothing in the bank covers it. Suspect the bank before the user's experience: "Have you ever done X, even once, even as part of something else?" The user recalls specifics best by talking them through.
3. **An open question on a card** (each card's "To find out" line). Pick the cards with the most use in recent applications.
4. **A bank issue** logged during drafting (`Review/bank-issues.md`): a bullet that read weak, a missing consequence, a wording the user corrected after delivery.
5. **An interview debrief.** What an interviewer asked that the user answered well, or badly, is new evidence either way.

## The questions

Same as the Start Here story session, one at a time, in the user's words: situation; what they did and who decided; what changed and what could be seen or counted; why it mattered and to whom; every figure sorted (exact to prep, the comfortable rounded shape as the candidate for paper); anything internal; status; open questions.

For a gap: ask for the smallest true instance first, then whether there's a bigger one. A single real instance is a bullet candidate with modest verbs; the absence of one is a confirmed gap to add to Rules File section 11 at approval time. Never stretch an adjacent experience to cover a named requirement.

For an existing card: read the card's current lines aloud first (another session may have changed them), then ask only about what's missing.

## Drafting the proposals

For each item, write in the proposed-evidence file:
- Which card it belongs to (`E07`) or "new card" with a working name.
- The user's words, as said, dated.
- A proposed bullet or card line in three parts, in the user's voice, using only what they said. Where a part is missing, say so instead of filling it.
- Figures: which are proposed for paper (with the rounding) and which are prep only.
- Anything sensitive and the plain-English swap proposed.
- Tag proposal: `[primary]`, `[alternate: angle]`, `[variant: when]`, `[tailor-only]`, or `[interview-only]`.

Read each proposal back. The user can approve in the moment ("yes", "approved", a numbered yes/edit/no list). An approval given in chat is an approval: record it in the queue as approved with the date, and apply it with the `approval-session` skill's steps before ending the session if they want it in the bank today. Otherwise it stays pending for the weekly session.

Add one row per item to `approval-queue.md`: number, the proposed change, the source (session date and the user's words), status pending.

## Also capture

- A rule the user states mid-conversation ("never say X on my resume", "always spell out Y"): queue it for the Rules File or the Retired Claims Log with the date. Don't edit those files here.
- A correction to an existing fact: queue it, marked "correction", so the approval session fixes the bank first and then sweeps the master and every unsent file.

## Close

Read back the queue additions in one numbered list with each item's status. Say when the next approval session is, or offer to run it now if everything was approved in chat.
