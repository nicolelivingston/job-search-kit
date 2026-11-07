# Releasing

The go or no-go checklist for every release. A release that fails any
"stop" line is not published; fix it and ship the next version number (tags
can't be moved or deleted).

## Before tagging
- [ ] Every Checks and CodeQL run on `main` is green, including the security job
      (bandit, pip-audit, gitleaks).
- [ ] The maintainer's private checks pass on their own computer: the full
      test suite with their own settings, the scoring equivalence check, the
      full-history leak scan, and the pending-ports check.
- [ ] No open bug report says the current release lost or damaged data.
- [ ] `UPDATES_PAUSED` is not on `main` (unless this release is the fix and
      the pause stays until it has been checked).
- [ ] What changed is written down for the release notes, in plain words.

## Test before it reaches anyone
Three places to catch a problem, each before the next:
1. **Every pull request**: the full test suite runs as the made-up test
   people (Priya, Dana, and Marcus, in `examples/`), never real data, and a
   fresh Windows machine builds the installer and installs it
   (`installer/smoke_test_windows.ps1`). Merge only on a green check.
2. **Merging to main ships nothing.** Kits only ever install a published,
   signed release.
3. **Beta first.** Tag `vX.Y.Z-beta.1` (any tag with a dash). It builds and
   runs every release check, then publishes as a GitHub pre-release, which
   automatic updates never see. Install it by hand on a test computer from
   the releases page and use it for a day. If it's wrong, fix it and tag
   `-beta.2`. When it's right, tag the plain `vX.Y.Z` from the same commit.

- [ ] A beta of this exact commit was installed by hand and used for a day.

## Tag and build
- [ ] `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] The Release workflow passes every job: tests, Windows installer with
      the Defender scan, VirusTotal, clean install on a fresh Windows runner,
      publish.
- [ ] **Stop** if Microsoft flags the installer on VirusTotal, or three or
      more engines do. Submit a false-positive report and wait.
- [ ] The publish job waits for approval (the `release` environment). Approve
      it on GitHub only after every line above is checked.
- [ ] The release has the installer, `job-search-kit.plugin`,
      `SHA256SUMS.txt`, and `job-search-kit-sbom.cdx.json`.

## Sign
- [ ] On the maintainer's computer only: sign `SHA256SUMS.txt` and attach
      `SHA256SUMS.txt.sig`. Kits install nothing unsigned.
- [ ] Check the signature against the public key pinned in `app/updater.py`,
      and that the installer's hash is on the signed list.

## After publishing
- [ ] Kits install the release 72 hours after it was published. Watch for
      error reports in that window.
- [ ] **Stop** everything if a problem turns up: add an `UPDATES_PAUSED`
      file to `main` (say why in it) and push. Every kit stops installing
      updates until it's removed.
- [ ] Install it by hand on one Windows computer: the folder is kept, the
      tracker opens, a daily run finishes, Send an error report works.

## Never
- Never move, delete, or re-use a tag.
- Never put the signing key on GitHub, in CI, or in this repository.
- Never publish a release the leak scan hasn't passed.
- Never ship a release that renames or removes a setting without bumping
  `SETTINGS_VERSION` and adding a step to `MIGRATIONS` in `app/kit_settings.py`.
