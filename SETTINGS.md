# Settings catalog

Every choice in the kit is a setting the user owns. Nothing personal lives in
the code. The setup wizard asks the **Setup** questions in plain words and
writes the files; **Advanced** settings have sensible defaults and sit on the
wizard's Advanced page; **Builder** settings are tuning for the person
maintaining the kit and rarely change.

Files are in the user's settings folder: `criteria.json`, `companies.json`,
`resume.json`, `app.json`, `paths.json`, `preferences.json`, plus `keyword-groups.json` next to the
evidence bank. Keys below are `section.NAME` as the code reads them
(`app/kit_settings.py`). A test fails if the code reads a setting that isn't
listed here.

## Setup questions

### 1. The work you want
| Question | Settings | Notes |
|---|---|---|
| What job titles are you looking for? | `agent.TITLE_KEYWORDS`, `agent.ROLE_TITLE_RE`, `agent.ROLE_FAMILY_LABEL` | Whole-word, case-insensitive |
| Which titles are never right? | `agent.ROLE_REJECT_KEYWORDS`, `agent.ROLE_BAD_RE`, `fit_scoring.TITLE_SKIP`, `fit_scoring.TITLE_SKIP_LABEL` | |
| Which titles should ask you first? | `fit_scoring.TITLE_ASK` | |
| What level are you aiming for? | `agent.LEVEL_TIERS`, `fit_scoring.LEVEL_RULES` | |
| How many years of experience in your field can you claim, and what's the field called in postings? | `fit_scoring.YEARS_CLAIMABLE`, `fit_scoring.YEARS_RE`, `fit_scoring.YEARS_LABEL` | Postings asking for more than your years plus `fit_scoring.YEARS_GRACE` (default 1) count as a missed requirement |

### 2. Where and how you work
| Question | Settings | Notes |
|---|---|---|
| Remote only, remote or hybrid, or any (including onsite)? | `fit_scoring.WORK_ARRANGEMENT.mode` (`remote`, `remote_or_hybrid`, `any`) | `remote` keeps the strict fully-remote rules |
| Where do you live, and which cities or areas could you commute to? | `fit_scoring.WORK_ARRANGEMENT.home`, `.commute_areas` | Hybrid and onsite only |
| Most office days a week you'd accept? | `fit_scoring.WORK_ARRANGEMENT.max_office_days` | Blank means no limit |
| Would you work fully onsite? | `fit_scoring.WORK_ARRANGEMENT.onsite_ok` | Only with mode `any` |
| Would you relocate? | `fit_scoring.WORK_ARRANGEMENT.relocation_ok` | |
| Which countries or regions can you work from? | `agent.US_LOCATION_KEYWORDS`, `agent.LOCATION_REJECT_KEYWORDS`, `agent.NON_US_REGION_KEYWORDS`, `agent.REMOTE_KEYWORDS`, `fit_scoring.POSTING_REMOTE_RE` | Defaults are US-remote |
| How much do you care that a company is remote by design? | `fit_scoring.POSTURE_POINTS` | Remote-only users weight it higher |

### 3. Rules that rule a job out
| Question | Settings | Notes |
|---|---|---|
| Are you open to managing people (direct reports)? | `fit_scoring.HARD_RULES` (include or leave out `people-manager`) | Yes leaves the rule out |
| On-call or after-hours duty? Contract roles? | `fit_scoring.HARD_RULES` (`on-call`, `contract`) | Each can be turned off |
| Most travel you'd accept? | `fit_scoring.TRAVEL_SKIP_PCT` | Lower amounts ask instead of skip |
| Industries you won't work in, and any exceptions? | `agent.EXCLUDE_KEYWORDS`, `agent.DOMAIN_REJECT_KEYWORDS`, `fit_scoring.EXCLUDED_INDUSTRY_RE`, `fit_scoring.EXCLUDED_COMPANIES`, `agent.INDUSTRY_EXCEPTION_KEYWORDS`, `fit_scoring.INDUSTRY_EXCEPTION_RE`, `fit_scoring.EXCLUDED_INDUSTRY_LABEL`, `agent.ASK_FLAG_LABEL` | The lists hold any excluded industry; the label is the reason shown on a skip |
| Skip companies weak on both time off and health benefits? | `fit_scoring.BENEFITS_RULES` | On by default |

### 4. Pay
| Question | Settings | Notes |
|---|---|---|
| Lowest base pay you'd take? | `agent.SALARY_FLOOR`, `fit_scoring.PAY_HARD_FLOOR` | One answer writes both |
| Pay you're aiming for? | `fit_scoring.PAY_TARGET` | |
| Rank postings with no posted pay lower? | `fit_scoring.NO_PAY_CAP` | |

### 5. Fields and companies
| Question | Settings | Notes |
|---|---|---|
| Which fields interest you most, and which least? | `fit_scoring.DOMAIN_SCORES`, `fit_scoring.DOMAIN_KEYWORDS`, `fit_scoring.DOMAIN_UNKNOWN` | A company with no field set scores 0 field points (never a keyword guess) |
| Industries outside your field (a posting that requires years or experience in one counts it as a missed requirement) | `fit_scoring.OUT_OF_DOMAIN_INDUSTRIES`, `fit_scoring.OUT_OF_DOMAIN_LABEL` | Empty list turns the rule off |
| Which of your fields is the developer-tooling or infrastructure one, and which is the planning or workflow one? | `fit_scoring.INFRA_DOMAIN`, `fit_scoring.PLANNING_DOMAIN` | Optional, both names from `DOMAIN_SCORES`. A planning or workflow role at an infrastructure company then scores as the planning field, and a data, platform, API, or developer title there is Possible fit at most |
| Does AI work built for business or operations users (not engineers) deserve extra points? | `fit_scoring.AI_BUSINESS_BONUS` | `{"points": 4, "cards": "E01", "label": "..."}`; absent or 0 points means off |
| Staffing agencies or reposters to ignore as the hiring company | `agent.REJECT_POSTERS` | Names, added as they turn up |
| Companies you'd love to work for (paste careers page links) | `ats_tools.CONFIRMED_COMPANIES`, `ats_tools.CUSTOM_SITE_COMPANIES` | The wizard detects the job board. A Workday board is read only when its entry has `"workday_ok": true` (a box in the wizard; see SOURCES.md) |
| Companies you already rank highly | `fit_scoring.TIER_PRECEDENTS` | |
| Which remote job feeds fit your field? | `board_feeds.WWR_FEEDS`, `board_feeds.REMOTE_CO_FEEDS` | Category feeds |

### 6. Your evidence and your resume
| Question | Settings | Notes |
|---|---|---|
| (Built in the Start Here interviews) your story cards' keyword groups, gaps, and requirements you can't claim | `fit_scoring.WORK_FAMILIES`, `fit_scoring.GAP_FAMILIES`, `fit_scoring.MINIMUM_FAMILIES` (in `keyword-groups.json`) | Ties fit scoring to the user's own bank |
| Gaps that count only inside a posting's required section (the same words in Responsibilities describe the work) | `fit_scoring.REQUIRED_BLOCK_FAMILIES` (in `keyword-groups.json`) | Same shape as `MINIMUM_FAMILIES`; empty by default |
| Words your evidence bank can vouch for when a required item is read on its own | `fit_scoring.VOUCH_WORDS` (in `keyword-groups.json`), `fit_scoring.VOUCH_FIELD_WORDS`, `fit_scoring.VOUCH_GENERIC`, `fit_scoring.REQUIRED_COVERAGE` | `VOUCH_WORDS` defaults to every phrase in your keyword groups, titles, and field keywords; `VOUCH_FIELD_WORDS` are the everyday nouns of your field; `VOUCH_GENERIC` has a field-neutral default (soft skills, logistics). Two required items none of them vouch for cap a posting at Possible fit, four (or half) at Poor fit, each quoted in the breakdown. `REQUIRED_COVERAGE: false` turns the pass off |
| What you're good at and what you're not, for the market report | `market_report.LEXICON`, `market_report.LEVEL_BUCKETS` | |
| Resume font, sizes, margins, spacing | `build_resume.FONT`, `build_resume.BODY_PT`, `build_resume.NAME_PT`, `build_resume.HEADING_PT`, `build_resume.MARGIN_IN`, `build_resume.LINE_SPACING`, `presend_gate.SPEC_FONT`, `presend_gate.SPEC_BODY_PT`, `presend_gate.SPEC_NAME_PT`, `presend_gate.SPEC_HEADING_PT` | One answer writes both |
| Words and abbreviations to keep off your resume; wording you've retired (the words list is asked in step 8 as "Words to never use") | `presend_gate.VOCAB_TERMS`, `presend_gate.ABBREVIATIONS`, `presend_gate.RETIRED_PHRASES`, `presend_gate.TIMING_TERMS`, `presend_gate.SANCTIONED_RETIRE`, `presend_gate.CREDENTIAL_OK` | Longer retired phrases can live in the Retired Claims Log instead |
| Figures that may appear only once per resume | `presend_gate.ONCE_PER_RESUME` | |
| Tailored resume page limit, and how full its last page may be | `presend_gate.PAGE_LIMIT`, `presend_gate.LAST_PAGE_FILL` | Step 8's resume length writes the page limit when it's 1 or 2 pages; with "Let Claude decide by experience", Start Here session 3 (Rules File section 6) writes it. The fill limit stays 0.75 |

### 7. How it runs
| Question | Settings | Notes |
|---|---|---|
| When should it check for new jobs? | `app.schedule.full`, `app.schedule.quick`, `app.schedule.update` | Defaults: 8am full run, quick checks at 11, 2, 5, and 8, update check at 9:30 |
| Built-in tracker or Notion? | `app.tracker`, `agent.NOTION_DATABASE_ID`, `agent.NOTION_COMPANIES_DATABASE_ID` | Built-in by default |
| Should it install updates by itself? | `app.auto_update` | Default on: a daily check of this project's GitHub releases installs signed updates. Off: no daily check; Check for updates in the Start menu still works |
| (Set by the privacy page) did you confirm the beta terms? | `app.acknowledged` | `{"terms", "date"}`, written when you tick the box on the privacy page; setup asks again if the terms change |
| Who gets your error reports? | `app.support_email` | The address the Send an error report button and the Help page's Email it button write to (the page never shows it); blank means you type it in. Set it in `settings/app.json` (the builder sets it during setup) |
| Light or dark pages? | `app.theme` | `auto` (match the computer), `light`, or `dark`; the Theme menu at the top of every page sets it |
| Status colors | `app.status_colors` | One color per status (gray, blue, teal, green, yellow, orange, red, purple, or pink); the Colors button on Applications sets it |
| (Written by the kit) settings format version | `app.settings_version` | Missing means a folder made by v0.1.0. After an update the kit brings older settings forward on its next run (taking a backup first) and never changes a folder saved by a newer kit |
| Where your evidence bank and data live | `paths.bank_dir`, `paths.bank_file`, `paths.data_dir`, `paths.keyword_groups` | The installer sets these |
| (Written by the wizard) where the kit's code lives | `paths.kit_dir` | Read by the Claude plugin, not the code, so it can run the builder, gate, and tracker |

### 8. How Claude works for you
These live in `preferences.json`. The Claude plugin reads them every session (the code reads only the two noted). Where the user's Rules File says something more specific, the Rules File wins.

| Question | Settings | Notes |
|---|---|---|
| Tools you use | `tools` | Start Here session 4 builds the bank's `A.tools` from this list; each application picks the ones that match the posting. A tool added later goes to the next evidence session |
| Resume and letter format rules | `format_rules.*` (`action_verbs`, `no_pronouns`, `spell_out_abbreviations`, `show_results`, `posting_words`, `posting_order`, `explain_jargon`, `letter_one_page`, `letter_named_person`, `letter_tie_to_posting`, `letter_light_on_i`), `own_rules` | All on by default (common university career-office guidance, plus tailoring). The builder always orders experience newest first and uses one format for both documents |
| Resume length | `resume_pages` (`auto`, `one`, `two`) | `one` or `two` also writes `presend_gate.PAGE_LIMIT` |
| Bullet length | `bullet_length` (`short`, `medium`, `detailed`) | Used when bullets are written into the bank (evidence mode) |
| What bugged you about AI drafts, habits to avoid, punctuation, tone | `voice.what_bugged_you`, `voice.avoid_habits`, `voice.oxford_comma`, `voice.contractions`, `voice.keep_my_wording`, `voice.tone` | Habits are suggestions, none picked by default. Picking em dashes also turns on `presend_gate.FLAG_EM_DASH`. Start Here session 1 seeds Rules File section 2 from these |
| Fixes you've saved | `saved_fixes` | Added by Claude when the user says yes to saving a fix; the user can delete any line |
| Feedback, drafts, decisions, obvious calls | `feedback` (`blunt`, `balanced`, `gentle`), `drafts` (`one`, `options`), `decisions` (`list`, `conversation`), `obvious_calls` (`decide_and_tell`, `ask_first`) | `drafts` applies to cover letters and written answers; a resume is always one version built from the bank |
| File format | `file_format` (`word`, `pdf`) | PDF is made from the gated Word file, which stays in the folder |
| What Claude can do | `permissions.update_tracker`, `permissions.draft_messages`, `permissions.draft_form_answers`, `permissions.save_fixes` | Each `can`, `ask`, or `never`. Always on, not settings: never invent, flag gaps, fix a correction everywhere it appears, never send, never submit |
| What stays general on paper | `keep_general` | Start Here session 3 seeds Rules File section 5 ("Never on paper") from it |
| Talk it through | `talk_it_through`, `talked_through` | Up to three questions about blank sections, once. Claude writes the date to `talked_through` afterwards |

## Advanced
| Setting | Default | What it does |
|---|---|---|
| `agent.FRESH_DAYS` | 14 | Postings this many days old or newer count as fresh |
| `fit_scoring.FRESHNESS_BANDS` | this week +5 ... over two months -10 | Score points by posting age |
| `fit_scoring.DOMAIN_GUESS` | true | When a posting's company has no field set, guess the field from the posting's words. Turn it off once your Companies rows carry fields: benefits text ("401(k)") can make a guess land on a finance field |
| `fit_scoring.ONE_MISS_STRONG_MIN` | 80 | A posting missing one requirement is still Strong fit when its score before the cap is at least this |
| `fit_scoring.SAME_DOMAINS`, `fit_scoring.ADJACENT_DOMAINS` | empty | Field names (from `DOMAIN_SCORES`) whose companies get the tightest confidentiality tier when tailoring (Tier 1, same field as your employer) or the next one (Tier 2, an adjacent field). Companies in `TIER_PRECEDENTS` are tiered by name first; everything else is Tier 3 |
| `presend_gate.FLAG_EM_DASH` | false | Flag em dashes on a resume or letter, for users who avoid them |
| `fit_scoring.INDUSTRY_RULE_CODES` | `["industry"]` | Hard-rule codes in `HARD_RULES` whose match becomes a "your call" instead of a Poor fit when one of your exception words is in the posting |
| `ats_tools.PORTFOLIO_BRAND_SUFFIXES` | empty | `{"Parent name": ["Brand", ...]}` for one job board shared by several brands whose titles end in " \| Brand"; each brand is then tracked as its own company |
| `fit_scoring.DRAG_DOMAINS` | empty | Field names that pull a mixed company's field points down by 6 when it also carries a better field |
| `agent.NETCHECK_URLS` | three public job-board hosts | Probed before a run; when none answers, the run is skipped and the next scheduled run retries |
| `agent.FRESH_ALERT_DAYS` | 2 | How new a top-tier posting must be to send an alert |
| `agent.EVERGREEN_AGE_DAYS` | 150 | Postings open this long are flagged as likely evergreen |
| `agent.AGE_NOTE_DAYS` | 60 | Postings open this long get an age note |
| `agent.REPOST_WINDOW_DAYS` | 90 | How far back reposts are detected |
| `agent.GHOST_FLAG_IDS`, `agent.GHOST_FLAG_LOCATIONS`, `agent.GHOST_SKIP_IDS` | 2, 4, 4 | Thresholds for postings sprayed across many locations or reposted under new IDs |
| `invariants.TRACKING_STARTS` | setup date | Revision and cycle-time tracking starts here |
| `presend_gate.REPEAT_SKIP_RE`, `presend_gate.REPEAT_STOPWORDS` | name, contact, section titles; common words | Left out of the repetition check |
| `LINKEDIN_ALERT_DAYS` (environment) | 3 | Days of LinkedIn alert emails to read, when that optional reader is on |

## Builder
| Setting | What it does |
|---|---|
| `fit_scoring.WORK_CAP`, `fit_scoring.GAP_CAP` | Maximum points from evidence matches and gap penalties |
| `fit_scoring.MIN_CAP_ONE`, `fit_scoring.MIN_CAP_TWO` | Score caps for one or two missed requirements (also the Possible fit and Poor fit coverage caps) |
| `fit_scoring.UNRESEARCHED_COMPANY_PTS` | Company points before any research |
| `agent.OPEN_STATUSES` | Tracker statuses that count as open (must match the tracker) |

## Retired
| Setting | Since | Replaced by |
|---|---|---|
| `agent.ASK_EXPIRY_DAYS`, `agent.NO_DECISION_VERDICT` | settings version 2 | Every posting gets a fit label (Strong fit, Possible fit, Poor fit) on every run; the 48-hour rule and the Watch (no decision) label are gone. The kit removes the two settings from an older folder on its next run |
