# If something goes wrong

A one-page plan for the maintainer. Act first, explain second, and write it
down the same day.

## What counts
- A release that loses or damages someone's tracker, bank, or settings.
- Anything that sends a user's data somewhere it shouldn't go.
- A release, the signing key, the GitHub account, or a dependency that may be
  compromised.
- Personal data found in the public repository.

## First hour
1. **Stop updates.** Add a file named `UPDATES_PAUSED` to `main` (one line on
   why) and push. Kits stop installing anything on their next check. A new
   release also waits 72 hours, so a bad one caught early reaches no one.
2. **Mark the release.** Edit the GitHub release: say in its first line not to
   install it. Don't delete or move the tag (the ruleset blocks both); fix
   it in the next version number.
3. **Tell people.** Email everyone known to use the kit in plain words: what
   happened, what it means for them, what to do now (usually: nothing, or
   restore yesterday's backup from the data folder's `backups` folder).
4. **Keep the evidence.** Save the error reports, logs, and workflow runs
   before anything rotates them.

## By situation
- **Data damaged.** Each kit keeps 14 days of daily backups, and a restore
  backs up first, so it can be undone. Walk the person through
  `python backup.py restore <file>`. Fix the bug with a test that would
  have caught it, then ship the next version.
- **Signing key exposed or lost.** Generate a new key pair, pin the new
  public key in `app/updater.py`, and ship that as a release signed with the
  old key if it is still in your hands (kits only trust the key they have).
  If the old key is in someone else's hands, keep `UPDATES_PAUSED` on and
  ask every user to reinstall from the release page by hand.
- **GitHub account or a workflow compromised.** Leave `UPDATES_PAUSED` in
  place, change the password and two-factor codes, revoke tokens and app
  access, and check the recent commits, tags, releases, and repository
  settings for anything you didn't do.
- **A dependency has a known problem.** The security job names it. Update the
  pin and its hash, and ship the next version.
- **Personal data in the repository.** Remove it in a new commit, add its
  words to the private leak markers so it can't come back, and decide whether
  the history needs more than that. Force pushes are blocked on purpose; ask
  for help before changing that.

## Afterward
Within a week, a short write-up: what happened, who it reached, why it
wasn't caught, and the test or check that now catches it. Keep it with the
release notes.
