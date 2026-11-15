#!/usr/bin/env python3
"""
Company follow: the daily check finds and follows company job boards on its own.
--------------------------------------------------------------------------------
The job sites (Remotive, Remote OK, We Work Remotely, Himalayas, Working
Nomads) carry postings from many companies, but only the ones those sites
happen to list. When one of them turns up a posting that fits the user's
search, this module looks for that company's own job board (Greenhouse, Ashby,
Lever, or SmartRecruiters) and, when it is sure the board is that company's,
follows it: from the next run on, the daily check reads the board directly, so
every later opening there is seen on the day it is posted. No AI, no tokens.

How a board is confirmed (a guessed address can be another company's board):
  1. the posting's own link is on a board site (certain), or
  2. the same role is on the board under an address guessed from the company's
     name (the same title at a same-named company is the proof).
A board that exists but doesn't list the role is never followed on a guess.
Workday is never followed here: it is opt-in per company (SOURCES.md).

What is kept, in found_boards.json in the data folder (never in the user's
settings, which stay the user's own answers):
  boards  [{name, platform, slug, found, how, last_match, status}]
          status "on" is read daily; "off" is one the user stopped (never
          followed again); a board with no posting on the user's title list
          for AUTO_FOLLOW_STALE_DAYS is dropped and can be found again later
  queue   [{company, title, url, added}] postings waiting for a board lookup

Settings (all optional, see SETTINGS.md):
  agent.AUTO_FOLLOW             true; false turns the whole thing off
  agent.AUTO_FOLLOW_MAX         60 boards followed this way at most
  agent.AUTO_FOLLOW_PER_RUN     8 lookups per full run
  agent.AUTO_FOLLOW_STALE_DAYS  90
"""
import json
import sys
from datetime import date, datetime

import ats_tools
import lead_resolver
from ats_tools import _S

AUTO_FOLLOW = _S("agent.AUTO_FOLLOW", default=True) is not False
AUTO_FOLLOW_MAX = int(_S("agent.AUTO_FOLLOW_MAX", default=60))
AUTO_FOLLOW_PER_RUN = int(_S("agent.AUTO_FOLLOW_PER_RUN", default=8))
AUTO_FOLLOW_STALE_DAYS = int(_S("agent.AUTO_FOLLOW_STALE_DAYS", default=90))
FOLLOW_PLATFORMS = ("greenhouse", "ashby", "lever", "smartrecruiters")
QUEUE_MAX = 200
HOW_LINK = "the posting's own link"
HOW_ROLE = "the same role on its board"


def load():
    return ats_tools.load_found_boards()


def save(data):
    try:
        ats_tools.FOUND_BOARDS_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError as e:
        print(f"[warn] could not save {ats_tools.FOUND_BOARDS_FILE.name}: {e}", file=sys.stderr)
        return False


def _key(name):
    return lead_resolver.norm_company(name or "")


def _board_key(platform, slug):
    return (platform, str(slug).lower())


def is_watched(company, watched=None):
    """True when the user follows this company closely (setup or the Companies page)."""
    names = ats_tools.WATCHED_COMPANIES if watched is None else watched
    key = _key(company)
    return bool(key) and any(_key(n) == key for n in names)


def _known(data):
    """Company keys and boards that need no lookup: the user's own picks
    (boards and check-by-hand sites) and every found board, on or off."""
    names, boards = set(), set()
    for c in list(ats_tools.CONFIRMED_COMPANIES) + list(ats_tools.CUSTOM_SITE_COMPANIES):
        names.add(_key(c.get("name")))
        if c.get("platform") in FOLLOW_PLATFORMS:
            boards.add(_board_key(c["platform"], c.get("slug")))
    for b in data["boards"]:
        names.add(_key(b.get("name")))
        boards.add(_board_key(b.get("platform"), b.get("slug")))
    names.discard("")
    return names, boards


def wants(job, result):
    """A written posting worth a board lookup: it fits (anything but Poor fit,
    or the company is one the user follows closely), it names a real employer,
    and it didn't come from a board the kit already reads."""
    if not AUTO_FOLLOW:
        return False
    company = (job.get("company") or "").strip()
    if not company or lead_resolver.is_aggregator(company):
        return False
    if job.get("ats_platform"):
        return False   # fetched from a followed board
    if result.get("hard_skip"):
        return False
    return result.get("verdict") != "Poor fit" or is_watched(company)


def enqueue(matches, today=None, data=None):
    """Queue written matches for a board lookup at the next full run.
    `matches` is the run's written list: (job, result, flag, salary_min).
    Returns how many were added."""
    if not AUTO_FOLLOW or not matches:
        return 0
    today = today or date.today()
    own = data is None
    data = load() if own else data
    names, _ = _known(data)
    queued = {_key(q.get("company")) for q in data["queue"]}
    added = 0
    for job, result, *_rest in matches:
        key = _key(job.get("company"))
        if not key or key in names or key in queued or not wants(job, result):
            continue
        data["queue"].append({"company": job["company"].strip(), "title": job.get("title", ""),
                              "url": job.get("url", ""), "added": today.isoformat()})
        queued.add(key)
        added += 1
    data["queue"] = data["queue"][-QUEUE_MAX:]
    if own and added:
        save(data)
    return added


def find_board(company, title, url="", cache=None, today=None, fetch=None):
    """-> (platform, slug, how) for a board that is this company's, else None.
    `fetch(platform, slug) -> jobs` is lead_resolver.fetch_board unless a test
    passes its own; `cache` is the board lookup cache (mutated)."""
    today = today or date.today()
    fetch = fetch or lead_resolver.fetch_board
    cache = cache if cache is not None else {}
    key = _key(company)
    if not key:
        return None
    found = lead_resolver.board_from_url(url)
    if found and found[0] in FOLLOW_PLATFORMS:
        return found[0], found[1], HOW_LINK
    cached = cache.get(key)
    if cached and cached.get("platform") in FOLLOW_PLATFORMS:
        # the lead matcher already matched a role on this board
        return cached["platform"], cached["slug"], HOW_ROLE
    if cached and not cached.get("platform"):
        try:
            if (today - datetime.strptime(cached.get("checked", ""), "%Y-%m-%d").date()).days < lead_resolver.MISS_RETRY_DAYS:
                return None
        except ValueError:
            pass
    for slug in lead_resolver.company_slug_guesses(company):
        for platform in FOLLOW_PLATFORMS:
            jobs = fetch(platform, slug)
            if not jobs:
                continue
            status, _job, _ = lead_resolver.best_match(title, jobs)
            if status in ("exact", "unique"):
                cache[key] = {"platform": platform, "slug": slug, "name": company, "checked": today.isoformat()}
                return platform, slug, HOW_ROLE
            # A live board under this address without the role could be another
            # company's; keep looking and never follow it on a guess.
    cache[key] = {"platform": None, "slug": None, "name": company, "checked": today.isoformat()}
    return None


def process_queue(today=None, limit=None, fetch=None, cache=None):
    """Look up a board for up to `limit` queued postings and follow the ones
    confirmed. Returns the names newly followed (for the digest)."""
    if not AUTO_FOLLOW:
        return []
    today = today or date.today()
    limit = AUTO_FOLLOW_PER_RUN if limit is None else limit
    data = load()
    if not data["queue"]:
        return []
    own_cache = cache is None
    cache = lead_resolver.load_board_cache() if own_cache else cache
    names, boards = _known(data)
    on = sum(1 for b in data["boards"] if b.get("status", "on") == "on")
    followed, left, looked = [], [], 0
    for q in data["queue"]:
        key = _key(q.get("company"))
        if not key or key in names:
            continue   # followed (or stopped) since it was queued
        if looked >= limit or on >= AUTO_FOLLOW_MAX:
            left.append(q)
            continue
        looked += 1
        hit = find_board(q["company"], q.get("title", ""), q.get("url", ""), cache=cache, today=today, fetch=fetch)
        if not hit:
            continue   # no board found; the miss is cached and retried when the company turns up again later
        platform, slug, how = hit
        if _board_key(platform, slug) in boards:
            continue
        data["boards"].append({"name": q["company"], "platform": platform, "slug": slug, "found": today.isoformat(),
                               "how": how, "last_match": today.isoformat(), "status": "on"})
        names.add(key)
        boards.add(_board_key(platform, slug))
        on += 1
        followed.append(q["company"])
    data["queue"] = left
    save(data)
    if own_cache:
        lead_resolver.save_board_cache(cache)
    return followed


def note_matches(all_jobs, title_ok, today=None):
    """After a fetch: stamp last_match on each found board that returned a
    posting on the user's title list today, and drop the ones that have had
    none for AUTO_FOLLOW_STALE_DAYS. Returns the names dropped."""
    today = today or date.today()
    data = load()
    if not data["boards"]:
        return []
    live = {_key(j.get("company")) for j in all_jobs if j.get("ats_platform") and title_ok(j.get("title", ""))}
    keep, dropped, changed = [], [], False
    for b in data["boards"]:
        if b.get("status", "on") != "on":
            keep.append(b)
            continue
        if _key(b["name"]) in live:
            if b.get("last_match") != today.isoformat():
                b["last_match"] = today.isoformat()
                changed = True
            keep.append(b)
            continue
        try:
            idle = (today - date.fromisoformat(b.get("last_match") or b.get("found") or today.isoformat())).days
        except ValueError:
            idle = 0
        if idle >= AUTO_FOLLOW_STALE_DAYS:
            dropped.append(b["name"])
            changed = True
        else:
            keep.append(b)
    if changed:
        data["boards"] = keep
        save(data)
    return dropped


def set_status(name, on):
    """The Companies page: stop or resume reading a found board. A stopped
    board stays in the file so the daily check never follows it again."""
    data = load()
    hit = False
    for b in data["boards"]:
        if _key(b["name"]) == _key(name):
            b["status"] = "on" if on else "off"
            hit = True
    return hit and save(data)


def digest_section(followed, dropped=()):
    """Plain lines for the daily digest, or None."""
    if not followed and not dropped:
        return None
    lines = ["## Companies the daily check follows now"]
    if followed:
        lines.append("A fitting posting turned up at each of these, and the kit found the company's own job board. "
                     "Their new openings are read every day from here on. Stop following any of them on the Companies page.")
        lines += [f"- {n}" for n in followed]
    if dropped:
        lines.append(f"No longer followed (no opening on your title list in {AUTO_FOLLOW_STALE_DAYS} days): " + ", ".join(dropped) + ".")
    return "\n".join(lines)


if __name__ == "__main__":
    d = load()
    print(json.dumps({"following": [b["name"] for b in d["boards"] if b.get("status", "on") == "on"],
                      "stopped": [b["name"] for b in d["boards"] if b.get("status") == "off"],
                      "waiting": len(d["queue"])}, indent=1))
