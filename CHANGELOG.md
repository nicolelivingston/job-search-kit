# What's new

Plain-words notes for each release, newest first. A kit that's already installed updates itself; your Job Search folder, settings, evidence bank, and tracker are never changed by an update, except where a note below says a setting is updated (after a backup).

## 0.2.0

**New**
- **Health page.** One screen on the tracker that shows how the search is going: applications in progress, interviews, applications sent by week against your own weekly target, what needs you today, and whether drafts are taking fewer rounds over time.
- **Skills watch.** Once a week the kit ranks the skills the postings in your search ask for, with your own status on each (Skilled, Partial gap, or Gap) and the change since last week. You edit the list on the Skills page.
- **Tailoring table.** Every resume draft from the Claude plugin comes with a table: each requirement in the posting, the resume line that answers it or "honest gap", and a count.
- **Work column.** The tracker shows Hybrid or Onsite when a posting clearly says so. Before, it only ever showed Fully Remote.

**Fixed**
- Benefits, time off, and equal-opportunity lines are no longer read as requirements, or as a reason to rule a job out. The first full run after this update reads closed postings again and reopens any that were closed for that reason; the digest lists them.
- A requirements heading with more words on its line ("What You Bring To The Team") is read as a heading, so its items count.
- Remote with a catch also covers wording like "not remote-only" and required in-person sessions.
- A posting that drops off a company's public list but still opens stays open, marked Unlisted.
- The weekly skills report runs. Before, the daily run looked for it in the wrong folder.

**Changed**
- Setup assumes no field. Job titles, experience wording, and the rule about managing people come from your own answers.
- Finished resumes and cover letters are Word files (Word can save a PDF copy).
- Two optional scoring rules and one job feed that never worked are gone. Your settings are backed up, then updated on the next run.
- Open postings are rescored on the first full run (fit scoring 4.2).
- The installer is named `JobSearchKit-Setup.exe` in every release, and the README starts with how to install it.

**Behind the scenes**
- The tests run as three made-up people, every pull request builds the installer and installs it on a clean Windows machine, and a beta release can be tried by hand before anyone's kit updates to it.
- Bundled packages are up to date.
