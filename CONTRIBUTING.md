# Contributing

Thanks for wanting to help. This is a small project with one maintainer, so
the process is short.

## The easiest ways to help
- **Something broke:** open a "Something went wrong" issue, or press **Send an
  error report** inside the kit (see `SUPPORT.md`).
- **You have an idea:** open a "Suggest an idea" issue. Say what you were
  trying to do, since that helps more than a proposed fix.
- **A security problem:** don't open an issue. Follow `SECURITY.md`.

## One rule above the rest: nothing personal
Issues and pull requests are public. Never include a real resume, a saved
posting, tracker data, names, emails, or phone numbers, in text, screenshots,
test files, or code comments. Tests use made-up people only.

## Changing the code
1. Open an issue first for anything bigger than a small fix, so nobody builds
   something that won't be merged.
2. Fork the repository and make your change on a side branch.
3. Keep the pull request small and about one thing. Fill in the template: what
   changed and why.
4. If you fix a bug, add a test that would have caught it.
5. Wait for the checks. Every pull request runs the tests, a security scan, a
   secret scan, and an install on a clean Windows machine. All of them need to
   be green.

Nothing merges straight to `main`. The maintainer reviews every pull request
and usually answers within a few days.

## What fits and what doesn't
- **Fits:** bug fixes, clearer wording, new job-board sources, accessibility
  fixes, and settings that let people make the kit their own.
- **Doesn't fit:** anything that sends a person's data off their computer,
  applies to jobs or sends email without the person doing it themselves, or
  writes claims into a resume that don't trace back to their own evidence.

Settings are described in `SETTINGS.md` and job-board sources in `SOURCES.md`.

## Conduct and license
Everyone taking part follows the `CODE_OF_CONDUCT.md`. Contributions are
released under the project's MIT license (see `LICENSE`).
