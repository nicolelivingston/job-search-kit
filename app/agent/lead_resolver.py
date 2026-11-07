#!/usr/bin/env python3
"""
Lead resolver: title-only leads -> the company's own posting (added 2026-10-21).
------------------------------------------------------------------------------
LinkedIn alert cards carry a title, a company, and a location, nothing else,
so they score 34 to 48 and sit in Tier C where nothing reads them. This module
is the zero-token first pass the user asked for: before a lead is scored, look
for the same role on the company's own ATS board and, when it is there, use
that posting (full text, salary, real publish date, the board's URL) instead.
Leads that still have no posting text after this are stamped in Notes
("Board lookup: none found") and the daily research step does the second
pass with one web search each.

Where boards come from, in order, all cached for the run:
  1. postings already fetched this run (CONFIRMED_COMPANIES, feeds), by company
  2. CONFIRMED_COMPANIES entries, matched by normalised company name
  3. candidate_results.json (the zero-token probe of new companies)
  4. board_lookup_cache.json (boards this module found or ruled out before;
     a miss is retried after 14 days)
  5. slug guesses from the company name on greenhouse / ashby / lever

Title matching is deliberately strict, because a wrong swap is worse than no
swap: level words (senior, staff, principal...) and role nouns (manager,
owner, designer...) must agree exactly; after that, one title containing the
other, or sharing most of its words, counts. Several plausible matches is
"ambiguous" and the row gets the candidate URLs in Notes instead of a swap.
The slug trap from ats_tools applies to source 5: a guessed slug can be a
different company's board, so swaps from a guessed slug say so in Notes.
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import data_dir as _ks_data_dir  # agent state lives in the data folder

from ats_tools import CONFIRMED_COMPANIES, FETCHERS, STATIC_PATTERNS

CANDIDATE_RESULTS_FILE = _ks_data_dir() / "candidate_results.json"
BOARD_CACHE_FILE = _ks_data_dir() / "board_lookup_cache.json"
MISS_RETRY_DAYS = 14
PROBE_PLATFORMS = ("greenhouse", "ashby", "lever")

BOARD_STAMP = "Board lookup"          # Notes stamp prefix the agent and the refresh filter on
WEB_STAMP = "Web lookup"              # the daily research step's stamp (second pass)

# Suffixes that never help identify a company (dropped for both matching and slugs)...
_LEGAL_RE = re.compile(r"[,.]?\s*\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|gmbh)\b\.?", re.I)
# ...and descriptive tails that vary between a board and an alert ("Chainlink
# Labs" vs "Chainlink"), dropped for matching only; slugs try both forms.
_TAIL_RE = re.compile(r"\b(holdings|group|technologies|technology|labs)\b\.?", re.I)
_STOP = {"the", "of", "and", "a", "an", "for", "to", "in", "at", "on", "with", "our", "team", "remote", "us", "usa"}
_SYNONYM = {"sr": "senior", "jr": "junior", "mgr": "manager", "mgmt": "management", "assoc": "associate",
            "2": "ii", "3": "iii", "4": "iv", "1": "i"}
# Words that must agree exactly between two titles for them to be the same role.
PROTECTED = {"senior", "staff", "principal", "lead", "director", "head", "vp", "svp", "evp", "cpo", "chief",
             "associate", "junior", "group", "ii", "iii", "iv", "i", "intern", "fellow",
             "manager", "management", "owner", "designer", "marketing", "engineer", "analyst", "architect",
             "researcher", "scientist", "specialist", "coordinator", "consultant", "operations"}

_RUN_CACHE = {}  # (platform, slug) -> list of job dicts ([] when the board failed or is empty)


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------

def _clean_company(name, drop_tails):
    s = re.sub(r"\(.*?\)", " ", (name or "").lower())
    s = _LEGAL_RE.sub(" ", s)
    if drop_tails:
        s = _TAIL_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_company(name):
    """'Harborline, Inc' -> 'harborline'; "Moody's Corporation" -> 'moodys';
    'Chainlink Labs' -> 'chainlink'. A tail-less result falls back to the
    full name so 'Labs' alone never becomes an empty key."""
    return _clean_company(name, True) or _clean_company(name, False)


# Job aggregators and reposters that show up as the "company" on a LinkedIn
# card or run their own ATS board. Never a target: the agent should find the
# company's own posting instead, and the daily research step never uses an
# aggregator's copy. An aggregator's Lever board was once cached as a
# company and reposted another company's roles as new rows.
AGGREGATORS = {"jobgether", "himalayas", "lensa", "ziprecruiter", "built in", "builtin", "indeed",
               "glassdoor", "wellfound", "remotive", "remoteok", "remote ok", "we work remotely",
               "working nomads", "jobright", "adzuna", "talent", "dice", "monster", "careerbuilder",
               "simplyhired", "jobot", "cybercoders", "get on board", "getonboard", "jobleads",
               "remote rocketship", "remoterocketship", "jobs via dice", "jobs via efinancialcareers"}
# Staffing agencies that post client roles under their own name arrive the
# same way (v3.7: a three-person agency arrived as a Strong fit with no client
# named). The user adds them in settings as they turn up.
from kit_settings import setting as _ks_setting
AGGREGATORS |= {str(x).strip().lower() for x in (_ks_setting("agent.REJECT_POSTERS", default=[]) or [])}


def is_aggregator(company):
    """True for a job board or reposter standing in for the hiring company."""
    key = norm_company(company or "")
    raw = (company or "").strip().lower()
    return key in AGGREGATORS or raw in AGGREGATORS or raw.startswith("jobs via ")


def title_tokens(title):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (title or "").lower()).replace("&", " and ")
    words = re.split(r"[^a-z0-9]+", t)
    out = set()
    for w in words:
        if not w or w in _STOP:
            continue
        out.add(_SYNONYM.get(w, w))
    return out


def title_match(lead_title, board_title):
    """0 = different role; 1.0 = same words; 0.9 = one title inside the other;
    0.6..0.99 = most words shared. Level words and role nouns must agree."""
    a, b = title_tokens(lead_title), title_tokens(board_title)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if (a & PROTECTED) != (b & PROTECTED):
        return 0.0
    if a <= b or b <= a:
        return 0.9
    j = len(a & b) / len(a | b)
    return j if j >= 0.6 else 0.0


def company_slug_guesses(name, website=None):
    """Slugs worth probing for a company: 'Chainlink Labs' -> chainlinklabs,
    chainlink-labs, chainlink. The website's domain is tried too when known."""
    guesses = []
    for form in (_clean_company(name, False), norm_company(name)):
        words = form.split()
        if words:
            guesses += ["".join(words), "-".join(words)]
            if len(words) > 1 and len(words[0]) >= 4:
                guesses.append(words[0])
    raw = re.sub(r"[^a-z0-9]+", "", (name or "").lower())  # 'Harborline, Inc' -> harborlineinc
    if raw:
        guesses.append(raw)
    if website:
        from ats_tools import guess_slugs
        guesses += guess_slugs(website if "://" in website else f"https://{website}")
    seen, out = set(), []
    for g in guesses:
        if g and len(g) >= 3 and g not in seen:
            seen.add(g)
            out.append(g)
    return out[:5]


def board_from_url(url):
    """(platform, slug) from a greenhouse / lever / ashby board URL, else None."""
    for platform in PROBE_PLATFORMS:
        m = re.search(STATIC_PATTERNS[platform], url or "")
        if m:
            return platform, m.group(1)
    return None


# ---------------------------------------------------------------------------
# board sources
# ---------------------------------------------------------------------------

def _load_json(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except (OSError, ValueError):
        return default


def load_board_cache():
    return _load_json(BOARD_CACHE_FILE, {})


def save_board_cache(cache):
    try:
        BOARD_CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))
    except OSError as e:
        print(f"[warn] could not save {BOARD_CACHE_FILE.name}: {e}", file=sys.stderr)


def fetch_board(platform, slug):
    """Jobs on one board, fetched once per run. [] on any failure."""
    key = (platform, json.dumps(slug, sort_keys=True) if isinstance(slug, dict) else slug)
    if key in _RUN_CACHE:
        return _RUN_CACHE[key]
    if platform == "workday":
        from ats_tools import workday_allowed
        if not workday_allowed(slug):   # opt-in per company only (SOURCES.md)
            _RUN_CACHE[key] = []
            return []
    try:
        jobs = FETCHERS[platform](slug) or []
    except Exception:
        jobs = []
    _RUN_CACHE[key] = jobs
    return jobs


def known_boards(company, job_board_url=None):
    """(platform, slug, origin, display_name) for boards we already know
    belong to this company, without probing anything."""
    key = norm_company(company)
    out = []
    for entry in CONFIRMED_COMPANIES:
        if norm_company(entry["name"]) == key:
            out.append((entry["platform"], entry["slug"], "confirmed", entry["name"]))
    for name, rec in _load_json(CANDIDATE_RESULTS_FILE, {}).items():
        if rec.get("ats") and rec.get("slug") and norm_company(name) == key:
            out.append((rec["ats"], rec["slug"], "candidate probe", name))
    if job_board_url:
        found = board_from_url(job_board_url)
        if found:
            out.append((found[0], found[1], "Companies row", company))
    return out


def board_label(platform, slug):
    if isinstance(slug, dict):
        return f"{platform} / {slug.get('tenant')}"
    return f"{platform} / {slug}"


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def best_match(lead_title, jobs, prefer=None):
    """-> (status, job, candidates). status: exact | unique | ambiguous | none.
    `prefer(job) -> bool` breaks ties between same-title postings (e.g. the
    one whose location passes the agent's filter)."""
    scored = [(title_match(lead_title, j.get("title", "")), j) for j in jobs]
    exact = [j for s, j in scored if s == 1.0]
    close = [j for s, j in scored if 0 < s < 1.0]
    if exact:
        if len(exact) > 1 and prefer:
            preferred = [j for j in exact if prefer(j)]
            if preferred:
                exact = preferred
        return "exact", exact[0], exact
    if len(close) == 1:
        return "unique", close[0], close
    if len(close) > 1:
        return "ambiguous", None, close
    return "none", None, []


def build_index(jobs):
    """norm company -> jobs, for postings already in hand this run."""
    index = {}
    for j in jobs:
        c = norm_company(j.get("company", ""))
        if c:
            index.setdefault(c, []).append(j)
    return index


def resolve(company, title, index=None, job_board_url=None, website=None, today=None,
            prefer=None, cache=None, probe=True):
    """Find the company's own posting for a title-only lead.

    Returns a dict:
      status   in_run | swapped | ambiguous | none | no_board
      job      the matching posting (in_run / swapped), else None
      board    'ashby / harborline' or '' ; origin: how the board was known
      company  the board's canonical company name when one is known
      candidates  up to 4 near-miss URLs (ambiguous)
      note     one line for the row's Notes
    `cache` is the persistent board cache dict (mutated); `probe=False`
    skips slug guessing (used in tests and when the network is down)."""
    today = today or date.today()
    key = norm_company(company)
    result = {"status": "none", "job": None, "board": "", "origin": "", "company": None,
              "candidates": [], "note": ""}
    if not key or not title:
        result["note"] = f"{BOARD_STAMP}: skipped (no company name) {today}."
        return result
    if is_aggregator(company):
        result["note"] = f"{BOARD_STAMP}: skipped ({company} is a job aggregator, not the employer) {today}."
        return result

    # 1. postings already fetched this run
    if index and key in index:
        status, job, cands = best_match(title, index[key], prefer)
        if status in ("exact", "unique"):
            result.update(status="in_run", job=job, board=job.get("source", ""),
                          note=f"{BOARD_STAMP}: same role already in today's fetch from {job.get('source', '')}.")
            return result
        from_board = [j for j in index[key] if j.get("ats_platform")]
        if from_board:
            # The company's own board was fetched today (CONFIRMED_COMPANIES),
            # so there is nothing more to probe.
            label = from_board[0].get("source", "company board")
            if status == "ambiguous":
                urls = [c.get("url", "") for c in cands[:4]]
                result.update(status="ambiguous", board=label, origin="confirmed", candidates=urls,
                              note=f"{BOARD_STAMP}: {len(cands)} similar titles on {label} {today}, pick one: " + " ; ".join(urls))
            else:
                result.update(status="none", board=label, origin="confirmed",
                              note=f"{BOARD_STAMP}: none found on {label} {today} (role not on the board).")
            return result

    # 2-4. boards we already know for this company
    boards = known_boards(company, job_board_url)
    cache = cache if cache is not None else {}
    cached = cache.get(key)
    if cached and cached.get("platform") and not any(b[0] == cached["platform"] and b[1] == cached["slug"] for b in boards):
        boards.append((cached["platform"], cached["slug"], "cache", cached.get("name") or company))

    tried = []
    for platform, slug, origin, name in boards:
        jobs = fetch_board(platform, slug)
        label = board_label(platform, slug)
        tried.append(label)
        if not jobs:
            continue
        status, job, cands = best_match(title, jobs, prefer)
        if status in ("exact", "unique"):
            result.update(status="swapped", job=job, board=label, origin=origin, company=name,
                          note=f"{BOARD_STAMP}: matched {label} ({origin}) {today}.")
            return result
        if status == "ambiguous":
            urls = [c.get("url", "") for c in cands[:4]]
            result.update(status="ambiguous", board=label, origin=origin, company=name, candidates=urls,
                          note=f"{BOARD_STAMP}: {len(cands)} similar titles on {label} {today}, pick one: " + " ; ".join(urls))
            return result
        # board is real but the role is not on it
        result.update(status="none", board=label, origin=origin, company=name,
                      note=f"{BOARD_STAMP}: none found on {label} {today} (role not on the board).")
        return result

    # 5. slug guesses (the probe), unless a recent miss is cached
    if cached and not cached.get("platform"):
        checked = cached.get("checked", "")
        try:
            if (today - datetime.strptime(checked, "%Y-%m-%d").date()).days < MISS_RETRY_DAYS:
                result.update(status="no_board",
                              note=f"{BOARD_STAMP}: no greenhouse/ashby/lever board (checked {checked}).")
                return result
        except ValueError:
            pass
    if not probe:
        result.update(status="no_board", note=f"{BOARD_STAMP}: no known board {today}.")
        return result
    for slug in company_slug_guesses(company, website):
        for platform in PROBE_PLATFORMS:
            jobs = fetch_board(platform, slug)
            if not jobs:
                continue
            label = board_label(platform, slug)
            status, job, cands = best_match(title, jobs, prefer)
            if status in ("exact", "unique"):
                cache[key] = {"platform": platform, "slug": slug, "name": company, "checked": today.isoformat()}
                result.update(status="swapped", job=job, board=label, origin="slug guess", company=None,
                              note=f"{BOARD_STAMP}: matched {label} (slug guess, verify it is {company}) {today}.")
                return result
            if status == "ambiguous":
                cache[key] = {"platform": platform, "slug": slug, "name": company, "checked": today.isoformat()}
                urls = [c.get("url", "") for c in cands[:4]]
                result.update(status="ambiguous", board=label, origin="slug guess", candidates=urls,
                              note=f"{BOARD_STAMP}: {len(cands)} similar titles on {label} (slug guess) {today}, pick one: " + " ; ".join(urls))
                return result
            # A live board under this slug with no such role: could be the
            # wrong company entirely, so keep probing other guesses.
    cache[key] = {"platform": None, "slug": None, "name": company, "checked": today.isoformat()}
    result.update(status="no_board",
                  note=f"{BOARD_STAMP}: none found {today} (no greenhouse/ashby/lever board under "
                       f"{', '.join(company_slug_guesses(company, website))}).")
    return result


def apply_match(lead, job, keep_source=True):
    """Overwrite a title-only lead with the board posting's facts, keeping the
    lead's id (so seen_jobs still tracks the LinkedIn card) and remembering
    the LinkedIn URL."""
    lead["linkedin_url"] = lead.get("url", "")
    for k in ("title", "url", "location", "description", "salary_text", "published"):
        if job.get(k):
            lead[k] = job[k]
    lead["published_approx"] = False if job.get("published") else lead.get("published_approx", True)
    for k in ("ats_platform", "ats_slug", "notion_page_id", "posted_text"):
        if job.get(k) is not None:
            lead[k] = job[k]
    if not keep_source:
        lead["source"] = job.get("source", lead.get("source"))
    return lead


if __name__ == "__main__":
    # python3 lead_resolver.py "Harborline, Inc" "Principal Product Manager"
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cache = load_board_cache()
    r = resolve(sys.argv[1], sys.argv[2], cache=cache)
    save_board_cache(cache)
    print(json.dumps({k: v for k, v in r.items() if k != "job"}, indent=2))
    if r["job"]:
        print(f"-> {r['job'].get('title')} ({r['job'].get('location')}) {r['job'].get('url')}")
