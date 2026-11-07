# Evidence Bank

The only source for resumes, cover letters, and application answers. One card per story. Exact figures and internal detail live in the Prep File, rules in the Rules File, and retired wording in the Retired Claims Log. Where this file and the Rules File disagree, the Rules File wins.

**Edit this file only in an evidence session**, never while drafting an application. If a bullet looks wrong mid-application, log it in `Review/bank-issues.md` and keep going. After any edit, rebuild the index (Claude runs the kit's `bank_index.py` for you; the kit-basics skill has the command). Lines whose text still starts with `<` are placeholders: the index marks them and they never reach paper.

## How to read a card

- **Status** sets the tense: shipped (past tense), in progress or ongoing (present). The same line's **Tier** says which applications may use the card: `all`, or the tier numbers, for example `2, 3`. Nothing else: any other wording is an error when the index is rebuilt. The Tier must be on the Status line. The builder refuses the card's bullets on any other tier.
- **Role** sets the verb: your call (decision verbs), shared or helped (modest verbs).
- **Bullets** carry an ID and a tag:
  - `[primary]` the default for the master and tailored pages.
  - `[alternate: angle]` used instead of the primary when a posting calls for that angle; never on the same page as that primary.
  - `[variant: when]` a wording swap for one named situation.
  - `[tailor-only]` off the master; on a tailored page only when the posting calls for that work.
  - `[interview-only]` never on paper.
  - `[proposed]` not approved yet. The gate flags it.
  - `[superseded]` kept for the record; never on paper.
- **Cleared** lists the figures and phrases allowed on paper for that story. Anything else is prep only. A figure on paper must also be in Part C; one on a Cleared line but missing from Part C isn't usable until an evidence session adds it.
- **To find out** is what would make the story stronger, as questions. Answer them in an evidence session.

A bullet line is machine-read. Keep the exact shape: `- ID [tag]: text`. IDs look like `E01.1` (card 1, bullet 1), `P-E01.2` (proposed), or `A.profile` (Part A).

---

# Part A. Profile and fixed facts

- A.headline [primary]: <Your Title> | <Theme>
- A.profile [primary]: <Two or three sentences: what you own, for whom, and how you work. Built in the Start Here sessions.>
- A.core [primary]: <Skill area> • <Skill area> • <Skill area> • <Skill area> • <Skill area> • <Skill area>
- A.scope.t1 [primary]: <One scope line for your current role, e.g. "Lead ... for ...">
- A.role.t1 [primary]: <Employer> | <Title> | <City, ST, or Remote> | <Mon YYYY> - Present
- A.earlier.1 [primary]: <Employer> | <Title> | <YYYY> - <YYYY>
- A.education [primary]: <Degree, School>
- A.credentials [primary]: <Certifications as issued. No credentials: delete this line.>
- A.tools [primary]: <Tool>, <Tool>, <Tool>

Role lines are machine-read: `Employer | Title | Location | Dates` (location optional). Add `A.role.t2` and so on for earlier titles you want shown with bullets, and `A.earlier.2` and so on for one-line earlier jobs. Tailored resumes show a subset of the tools line, never a tool that isn't on it.

# Part B. Story cards

## E01 <Short name for the story>

Status: <shipped | in progress | ongoing>, <year> | Role: <your call | shared (who did what) | helped> | Tier: <all | 2, 3>

- Situation: <what was going on and why it mattered>
- What changed: <what you did and what happened>
- Why it mattered: <the result for users, the business, or the team>
- Cleared: <figures and phrases allowed on paper>
- To find out: <questions that would make this stronger>

- E01.1 [primary]: <What you did; what it caused, why it mattered.>

# Part C. Figures: what goes on paper

The whole list. A figure not here is prep only. Every figure on paper matches this list exactly, including rounding.

| Figure | Status | Story |
|---|---|---|
| <figure> | paper | E01 |

# Part D. Change log

- <date>: <what changed and why>
