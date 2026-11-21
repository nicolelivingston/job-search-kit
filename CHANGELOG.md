# What's new

Plain-words notes for each release, newest first. A kit that's already installed updates itself; your Job Search folder, settings, evidence bank, and tracker are never changed by an update, except where a note below says a setting is updated (after a backup).

## Next release
(Rename this heading to the version number when you tag the release.)

**Changed**
- **Capital words on your never list count only in capitals.** In setup, "Never show me titles with these words" now treats a short word typed in capitals, such as IT or QA, as that word only. "IT Data Analyst" is left out; "Data Analyst, Make It Count" isn't. Every other word on the list matches in any capitalization, as before. The Try a title box follows the same rule.

**Fixed**
- **A hiring or benefits line about military service no longer hides a posting.** If your list of industries you won't work in has "military" or "defense", lines such as "including military members and their spouses", "military leave", or "military service" no longer drop a posting or close it. Postings about defense work still do.

**Behind the scenes**
- When the daily check leaves out a posting with one of your job titles, its log says why, including the word that left it out.
- Company names are tidied up in a way that can't stall on a very long, odd name typed into setup. Which names match each other is unchanged.

## 0.3.0

**New**
- **Start from the resume you have.** Setup step 6 keeps a copy of your current resume in your Job Search folder. In Start Here, Claude reads it, checks every bullet against the kit's guidelines (what you did, what it caused, why it mattered), suggests a tighter wording where everything is already there, and asks you a question where a result or a reason is missing. Your stories and fixed facts (jobs, dates, education) start from it instead of a blank page. Nothing is added to your evidence bank until you approve it.
- **The kit follows companies on its own.** When a job site turns up a posting that fits you, the daily check finds that company's own job board and reads it every day from then on. It only follows a board it can confirm is that company's, and you can stop any of them on the Companies page or turn this off in setup.
- **Companies to follow closely.** In setup, type the names of the companies you'd most like to work for. The kit finds each one's job board (no careers link needed), and every new opening there on your title list is called out, whatever its fit score.
- **Company research.** Say "research my companies" to Claude. It looks up the companies you follow closely and the ones with a top-fit posting, shows you what it found with links, and saves only what you approve. It never opens Glassdoor or other review sites.
- **SmartRecruiters boards** are read alongside Greenhouse, Lever, Ashby, and Workday.
- **A board that goes quiet is called out.** If a company you follow stops listing jobs on its board for three days after listing five or more (it has usually moved to another job site), or its board fails on every check, you get one notification and a banner on your tracker.
- **Workday postings come with their details.** For a Workday board you turned on, each posting on your title list is read in full: the description, the pay range in it, and the real posted date. A Workday careers link now gives the kit the board's full address, so the board can be read once you turn it on.
- **A cover letter that repeats the resume is flagged.** The checker compares a letter with the resume beside it and flags any run of four or more words they share. The letter says why; the resume says what.

**Changed**
- **Setup explains itself.** Step 1 says how job titles are matched, with examples, and has a Try a title box that shows what the daily check would do with any title. Step 3 explains what "industries you won't work in" means, with examples, and says it's optional. Step 5 lists every place the kit looks.
- The privacy page says what's new in what goes out (boards the kit finds, and company research), so setup asks you to confirm it once more.
- In Claude Code, a web search in your Job Search folder now asks you first instead of being refused, so company research can run. Opening web pages there is still off.
- **Old postings sink.** A posting open more than 60 days loses 10 points, and one open more than 90 days loses 15, even when its score is capped. Its fit label doesn't change because of age. Your settings are backed up, then updated on the next run, and open postings are rescored on the first full run (fit scoring 4.3).
- **An abbreviation the posting uses is fine.** The checker keeps an abbreviation on your spell-out list when the saved posting uses it too.

**Fixed**
- **Reposters are not employers.** More reposter sites are on the kit's list, a posting from a job site that never names the employer ("for our client, we are seeking") is left out, and copies like that already open in your tracker are closed unless you marked them Applying or Passed.

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
