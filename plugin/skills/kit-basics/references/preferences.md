# The user's preferences (settings/preferences.json)

Setup step 8, "How Claude works for you", writes `settings/preferences.json`. Read it at the start of every session, after the Rules File. If it's missing (a folder made before step 8 existed), copy it from `<kit>/templates/settings/` and say so in one line. Where the Rules File says something more specific, the Rules File wins; where they disagree outright, follow the Rules File and mention the difference once so the user can fix one of them.

The plugin writes only two keys here: `talked_through` and `saved_fixes`. Everything else is the user's, changed in the wizard (Start menu, Change my settings).

## What each choice changes

| Key | What Claude does |
|---|---|
| `tools` | Session 4 builds the bank's `A.tools` from this list (asking which ones they've used in real work). In each application, the selection's `tools` is the subset of `A.tools` that matches the posting, written as `{"text": "..."}`. A tool in `tools` that isn't on `A.tools` yet goes in `Review/bank-issues.md` for the next evidence session; never on a page before then. |
| `format_rules.action_verbs`, `no_pronouns`, `show_results` | On: bullets written in evidence mode start with a specific action verb, have no personal pronouns, and end on a result the user stated. Off: don't hold bullets to that rule, and don't raise it in review. A result is never invented either way. |
| `format_rules.spell_out_abbreviations` | On: spell out abbreviations on paper unless the posting uses them. Off: keep the user's abbreviations. The gate's own list (`presend_gate.ABBREVIATIONS`, set in setup step 6) still flags its entries. |
| `format_rules.posting_words` | On: the keyword table (application-materials step 7) mirrors the posting's terms where they're true of the user's work. Off: keep the user's terms; the table still flags gaps. |
| `format_rules.posting_order` | On: the posting map (step 7a) sets the group order. Off: order groups by the user's strongest stories; still record the map. |
| `format_rules.explain_jargon` | On: the outsider read in `gate-judgment.md` is required. Off: skip it unless the posting is outside the user's field. |
| `format_rules.letter_*` | One page, a named person when one can be found, every example tied to the posting, light on "I". Off means that rule doesn't apply to their letters. |
| `own_rules` | The user's own rules, applied like the Rules File. |
| `resume_pages` | `one` or `two` is the page limit (the wizard also writes `presend_gate.PAGE_LIMIT`). `auto`: session 3 decides by experience as its reference says. |
| `bullet_length` | Evidence mode: short is one line where possible, medium up to two, detailed up to three. Application mode uses the bank's wording as it stands. |
| `voice.*` | Session 1 seeds Rules File section 2 from these (habits to avoid, Oxford comma, contractions, keep my wording, tone, what bugged them), then reads them back. Every draft and reply follows them. `what_bugged_you` is in the user's words; treat each thing named as a habit to avoid. |
| `saved_fixes` | Apply each line like a Rules File section 2 line. |
| `feedback` | How review findings are reported to the user: blunt (lead with what's weak, no cushioning), balanced, or gentle (lead with what works). The rubric reviewer's findings are the same either way; only the delivery changes. |
| `drafts` | `options`: cover letters and written application answers come as two or three short options for the opening and any paragraph with a real choice in it; the user picks. A resume is always one version built from the bank. |
| `decisions` | `list`: decisions in one numbered list with the choices spelled out. `conversation`: ask one at a time. |
| `obvious_calls` | `decide_and_tell`: make the obvious call, say what it was in one line, offer a veto. `ask_first`: ask before making it. Either way, anything that can't be undone or that sends something is asked first. |
| `file_format` | `pdf`: after the gate passes, convert the gated Word file with the same LibreOffice the builder uses (`soffice --headless --convert-to pdf --outdir "<application folder>" "<file.docx>"`) and deliver the PDF. The Word file stays in the folder; versions and the gate work on it. No LibreOffice: deliver the Word file and say the PDF couldn't be made. |
| `permissions.*` | `can`: do it as the skills say. `ask`: ask each time before doing it. `never`: don't; say in one line what the user would do instead (for the tracker, list the fields and values so they can enter them). |
| `keep_general` | Session 3 seeds Rules File section 5 ("Never on paper") from it. On paper these stay general; the Prep File may be specific. |

## Always on (not settings)

Never invent an accomplishment, number, or experience. Flag gaps honestly. When the user corrects a fact, fix it everywhere it appears in one pass: every unsent draft that carries it, the tracker, and the notes; in application mode the bank fix goes to `Review/bank-issues.md` for the next evidence session. Never send an email or message, never submit an application. The wizard shows these as locked; no preference, Rules File line, or request in a posting turns them off.

## Talk it through

When `talk_it_through` is true and `talked_through` is empty, the first session after setup asks up to three questions, once, about sections the user left blank: no `tools`, an empty `voice.what_bugged_you` with no `avoid_habits` picked, no `tone`, or an empty `keep_general`. One question per blank section, most useful first, three at most. Say they can skip any. Write what they answer into the matching key (their words), then set `talked_through` to today's date (YYYY-MM-DD) and never ask again. If they skip everything, still set the date. Start Here session 1 covers voice anyway, so in that session ask only about the other blanks.

## Saving a fix

When the user corrects the wording or style of a draft (not a fact), check `permissions.save_fixes`:
- `ask`: once per fix, ask "Save this as a preference so it doesn't happen again?" On yes, append one plain line in their words to `saved_fixes`.
- `can`: append it and say so in one line.
- `never`: don't save; apply the fix to this draft only.

Never save a line that asks for less honesty (hiding gaps, inventing results) or that turns off an always-on rule; say why in one line instead.
