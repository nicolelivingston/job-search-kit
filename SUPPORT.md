# Support and rollback

One page for when something goes wrong.

## If something breaks
1. Open the tracker (Start menu: Job Search Kit, Open my job tracker). A banner at the top says when a daily run failed and why.
2. Press **Send an error report** on the tracker page (or Start menu: Send an error report). A new email opens in your own mail app with a report attached. The report holds the kit's error lines and run facts only: no postings, no resume, no evidence bank, no names, no links. Read it if you like, then press Send. Nothing is sent until you do.
3. Say in the email what you were doing when it went wrong, what happened, and what you expected. That's all that's needed. (If you use GitHub, the repository's "Something went wrong" issue form asks the same things; never paste resumes, postings, or anything personal there, since issues are public.)

## Suggesting an idea
Use **Suggest an idea** in the kit (or the repository's "Suggest an idea" issue form on GitHub). It needs a free GitHub account, and suggestions are public, so leave out anything personal.

## What help looks like
- Daily runs, scoring, the tracker, the wizard, updates, and the Claude plugin: yes, with an error report.
- Your resume content, which jobs to pursue, and what to say in an interview: that's between you and Claude in your folder; the kit's job is to keep every claim traceable to your own bank.
- Your Claude plan, your email, LibreOffice, Windows itself: outside the kit.
- Expect an answer within a few days, not minutes. If a run fails, the kit keeps the last good state; nothing is lost while you wait.

## Going back to the previous version
Updates install quietly from the kit's GitHub releases page and never touch your Job Search folder. A new version waits 72 hours after it comes out before it installs, and the maintainer can pause all updates at once. If an update breaks something:
1. Open https://github.com/nicolelivingston/job-search-kit/releases in a browser.
2. Pick the previous version and download its `JobSearchKit-Setup-<version>.exe`.
3. Run it. It replaces the app's code and bundled Python only. Your folder, settings, bank, applications, and tracker stay exactly as they were.
4. Tell the maintainer which version broke, so the next release fixes it before the kit updates you again. (The daily update check will offer the newest version again; if you want to stay on the older one for a while, turn off automatic updates in the setup wizard under How it runs, or just say so in the email and a release that fixes it will follow.)

## Reinstalling from scratch
Uninstall from Windows Settings, Apps. The uninstaller removes the app only; your Job Search folder stays. Install the newest version again and, at the first step, choose the folder you already have. Nothing is rebuilt.

## Your data
Everything is plain files in the folder you chose (the wizard shows the path). The kit keeps 14 days of daily backups in the data folder, under backups, and Claude can restore one for you. Copy the folder for your own backup. To remove your data, use Delete your data on the Privacy page of the tracker.
