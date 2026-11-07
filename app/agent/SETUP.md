# How the job board agent works

This is the builder's guide. A new user never edits these files; the setup
wizard writes their settings and installs the schedule.

## Where things live
- Code: `app/agent/` (this folder). Updates replace it; it holds no personal data.
- Settings: the user's settings folder (`settings/` in the kit by default, or
  `KIT_SETTINGS_DIR`). See `app/kit_settings.py` for every file:
  - `criteria.json`: title keywords, reject lists, pay floor and target, hard
    Skip rules, domain scores, company tiers, level rules, freshness bands
  - `companies.json`: target company job boards (Greenhouse, Lever, Ashby,
    Workday, custom sites)
  - `app.json`: `"tracker": "local"` (built-in tracker, the default) or
    `"notion"`, and the run `"schedule"`
  - `paths.json`: the evidence bank folder, bank file name, and data folder
  - `keyword-groups.json` (next to the evidence bank): the keyword groups that
    tie fit scoring to the user's own story cards
- Data: the data folder (`data/` by default): the built-in tracker
  (`tracker/applications.json`, `tracker/companies.json`), `seen_jobs.json`,
  `posting_history.json`, `agent.log`, `alerts.jsonl`, the daily digest, and
  `tracker_snapshot.md`.

## What a run does
1. Fetches postings from the user's company boards (`ats_tools.py`), the remote
   job feeds (`board_feeds.py`), Remotive, and RemoteOK. The LinkedIn alert
   reader (`linkedin_alerts.py`) is off unless an email account is set up.
2. Filters and scores each posting (`fit_scoring.py`): hard rules quote the
   rule they broke; the score is 0 to 100 from the user's keyword groups,
   domain, level, pay, company, and freshness; the required section is read
   item by item against the user's evidence; the research tier (A, B, C)
   decides how much follow-up each row gets, and every row gets a fit label
   (Strong fit, Possible fit, Poor fit) with the reason.
3. Writes new matches to the tracker and never sets Applying or Passed; those
   decisions are the user's and are never overwritten.
4. Full runs only: rescores open rows, re-checks that postings are still live,
   and closes a posting after it's gone from its board on two runs.
5. Writes the digest and the tracker snapshot, and records run stats.

## Schedule
`python3 app/schedule.py install` registers the 8am full run and the daytime
quick runs (Task Scheduler on Windows, launchd on macOS). A computer that was
asleep runs the job when it wakes. `show` prints the plan; `remove` undoes it.

## By hand
- One run: `python3 app/agent/job_search_agent.py` (add `--quick` for a quick run)
- A dry run that writes nothing: `AGENT_DRY_RUN=1 python3 app/agent/job_search_agent.py`
- Find a company's job board: `python3 app/agent/ats_tools.py detect "https://example.com/careers"`
- Look up a title-only lead on its company's board:
  `python3 app/agent/lead_resolver.py "Company" "Senior Product Manager"`

## Optional: LinkedIn job alert emails
Off by default. To turn it on, create a Gmail app password and put
`GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `app/agent/.env`. The reader checks
All Mail and Trash read-only, never visits linkedin.com, and looks each lead
up on the company's own board first.

## Optional: Notion instead of the built-in tracker
Set `"tracker": "notion"` in `app.json`, put `NOTION_TOKEN` in `app/agent/.env`,
and add the Applications and Companies database IDs to `criteria.json`
(`agent.NOTION_DATABASE_ID`, `agent.NOTION_COMPANIES_DATABASE_ID`).
