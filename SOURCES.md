# Job sources: how the kit reads them

The kit reads public job boards on the user's own computer, a few times a day, for one person's job search. It identifies itself on every request with a descriptive User-Agent (`JobSearchKit/<version> (+https://github.com/nicolelivingston/job-search-kit; personal job search, a few polite runs a day)`), fetches each feed once per run, retries with a wait on errors, and keeps only what the user needs (title, company, link, pay, location, posting date, and a snapshot of the text for scoring). Every tracker row and digest line keeps the posting's original link and names its source.

| Source | What is read | Terms the kit follows | Re-check |
|---|---|---|---|
| Remotive | public jobs API (`remotive.com/api/remote-jobs`), every listing unless `agent.REMOTIVE_SEARCH` names search words; your title filter keeps the ones on your list | Remotive asks that listings link back to the Remotive job page; the kit keeps the original link on every row and never republishes listings | their API page |
| Remote OK | public jobs API (`remoteok.com/api`) | Remote OK asks for a link back to Remote OK and credit as the source on anything shown; rows carry the link and "Source: Remote OK"; no republishing | the terms at the top of the API response |
| We Work Remotely | public RSS feeds by category | personal use of the public feed; links kept | their site terms |
| Himalayas | public jobs API | personal use; links kept | their API page |
| Working Nomads | public exposed-jobs API | personal use; links kept | their API page |
| Greenhouse, Lever, Ashby, Workday | each target company's own public job board API or careers page, for companies the user chose | one request per company per run; the user chose each company; links point at the company's own page. Greenhouse and Lever only: when a posting already in the user's tracker has left the board's public list on two full runs, one more request asks the same public API about that single posting before its row is closed (at most once per full run for that posting) | each board's public API terms |
| LinkedIn | nothing is fetched; the user pastes a link or text into Add a Posting | the kit never scrapes LinkedIn or reads a LinkedIn account | n/a |

Before each release the maintainer re-reads the terms of any source whose fetch code changed. If a source objects, it is removed from the defaults.

## Workday (checked November 1, 2026)
Workday's site terms (workday.com/legal/site-terms) forbid "data mining, robots or similar data gathering or extraction methods designed to scrape" their Sites and say "you may not use any Workday APIs without authorization under a separate agreement with Workday". Those terms define their Sites as workday.com and pages that reference the terms; they don't name the career sites companies host on myworkdayjobs.com. The kit reads those career sites through the same data feed the career page itself loads in a browser, once per run, only for companies the user added. No company in the kit's defaults uses Workday. Decision (November 1, 2026): Workday is opt-in per company. A Workday board the wizard finds stays off until the user ticks a box under it that explains the above; until then the kit neither reads it daily nor uses it to look up leads, and the company is one to check by hand.
