# Job Search Kit plugin

Claude skills for the Job Search Kit. Install it in the Claude desktop app, open your Job Search folder in the Code tab, and say "start here".

## What's in it

| Skill | Say | What it does |
|---|---|---|
| `start-here` | "start here", "continue my setup" | Four short interview sessions that build your North Star, evidence bank, Rules File, keyword groups, and master resume, in your words |
| `application-materials` | "tailor my resume for this posting", "I applied" | Selects approved bullets into a tailored resume and cover letter, builds the Word files, runs the pre-send gate and one independent review, keeps the clock, files the outcome in your tracker |
| `evidence-interview` | "I have a new story", "a posting asked for X" | Captures new evidence in your words into a proposed-evidence file and the approval queue; the bank doesn't change yet |
| `approval-session` | "approval session", "that bullet is wrong" | Works through the queue (yes, edit, no), changes the bank, rebuilds the index, the master, and every unsent resume, runs the target-level review |
| `kit-basics` | (loaded by the others) | The folder map, the two modes, how Claude runs the kit's scripts, the session close-out |

Two reviewer agents (`rubric-reviewer`, `target-level-reviewer`) run as fresh subagents with the kit's reviewer prompts, so the review never grades its own drafting.

## How it finds things

The plugin works in the Job Search folder you have open. It finds the kit's code through `kit_dir` in `settings/paths.json` (written the first time), or the installer's default location, and runs the kit's scripts with your settings. Nothing in the plugin stores your data; everything lives in your folder.

## Two rules the plugin never breaks

- Nothing goes on a page that isn't in your evidence bank, in the bank's wording. The gate checks every bullet.
- The bank changes only in an approval session, and only with your yes.

## Installing

From a release: the installer puts the plugin folder in the kit (`plugin/`). In the Claude desktop app, add it as a local plugin from that folder, or install the packaged `job-search-kit.plugin` file attached to the release.

For development: `claude plugin validate plugin/.claude-plugin/plugin.json` from the kit folder.
