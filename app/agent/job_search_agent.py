#!/usr/bin/env python3
"""
Job Search Kit: job board agent
-------------------------------
Checks the user's target company job boards and remote job feeds, filters
and scores postings against the user's criteria (settings folder), and
writes new matches into the tracker (built-in by default, or Notion).

This is a FIRST-PASS FILTER, not a decision-maker. Always review matches
before applying -- salary and remote-status data from these APIs
is sometimes missing or wrong.

Run manually to test:  python3 job_search_agent.py
Then schedule it (see SETUP.md) to run automatically once a day.
"""

import html
import json
import logging
import os
import re
from collections import Counter
from urllib.parse import urlparse
import smtplib
import subprocess
import sys
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
import requests

from ats_tools import fetch_all_confirmed, request_with_retry, run_concurrently, FETCHERS
from board_feeds import fetch_board_feeds, FEED_HOSTS
from linkedin_alerts import fetch_linkedin_alerts
import lead_resolver
import fit_scoring
import run_stats
from run_stats import STATS

load_dotenv(Path(__file__).parent / ".env")

# Rejections are logged at DEBUG so they're silent by default -- run with
# LOG_LEVEL=DEBUG to see why individual postings were filtered out.
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                     format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)
# optional tokens in .env are readable only by this user account and never land in logs
import platform_support as _ps  # noqa: E402
_ps.protect_secrets(Path(__file__).parent / ".env", logger_names=("", __name__))

# ---------------------------------------------------------------------------
# CONFIG -- fill these in via environment variables (see SETUP.md), or edit
# the defaults below directly. Never commit real credentials to a public repo.
# ---------------------------------------------------------------------------

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S, user_agent as _ks_user_agent  # personal settings live in the settings folder, not the code

# Notion is optional in the kit. With "tracker": "local" (the default) every
# Notion API call is answered by local_tracker from files in the data folder.
from kit_settings import tracker_mode as _ks_tracker_mode, data_dir as _ks_data_dir
TRACKER_MODE = _ks_tracker_mode()
DATA_DIR = _ks_data_dir()
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", _S("agent.NOTION_DATABASE_ID", default=""))
NOTION_COMPANIES_DATABASE_ID = os.environ.get(
    "NOTION_COMPANIES_DATABASE_ID", _S("agent.NOTION_COMPANIES_DATABASE_ID", default=""))
if TRACKER_MODE == "local":
    import local_tracker
    NOTION_TOKEN = "local-tracker"
    NOTION_DATABASE_ID = NOTION_DATABASE_ID or "applications"
    NOTION_COMPANIES_DATABASE_ID = NOTION_COMPANIES_DATABASE_ID or "companies"
    local_tracker.configure(DATA_DIR, NOTION_DATABASE_ID, NOTION_COMPANIES_DATABASE_ID)

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
PHONE_GATEWAY_EMAIL = os.environ.get("PHONE_GATEWAY_EMAIL", "")  # e.g. 5555551234@vtext.com

SEEN_JOBS_FILE = DATA_DIR / "seen_jobs.json"
STALE_MISS_FILE = DATA_DIR / "stale_posting_misses.json"

# Only these phrases count as a PM-level title -- matched as whole-word
# phrases (see _phrase_pattern) so "Productivity"/"Production" etc. can't
# match on "product" the way naive substring matching would.
TITLE_KEYWORDS = _S("agent.TITLE_KEYWORDS")

# Titles containing any of these are rejected outright, even if they also
# contain one of the TITLE_KEYWORDS phrases above (e.g. "Head of Product
# Design" is rejected for "design").
ROLE_REJECT_KEYWORDS = _S("agent.ROLE_REJECT_KEYWORDS")

# Reject unless the location clearly means US/Americas, or "remote" with no
# other country attached. Named US cities with no "remote" qualifier are
# rejected too (they read as on-site), which falls out of has_us/has_remote
# both being false below rather than needing an explicit city list.
LOCATION_REJECT_KEYWORDS = _S("agent.LOCATION_REJECT_KEYWORDS")
US_LOCATION_KEYWORDS = _S("agent.US_LOCATION_KEYWORDS")
# "Remote" alone isn't enough if it's paired with a non-US region restriction
# (e.g. "Remote-EMEA", "Remote-Iberia") -- that's still a country restriction.
NON_US_REGION_KEYWORDS = _S("agent.NON_US_REGION_KEYWORDS")

# Reject if the title or description prominently features these -- signals
# the role is really an infra/security/observability role wearing a PM title.
DOMAIN_REJECT_KEYWORDS = _S("agent.DOMAIN_REJECT_KEYWORDS")

# Keywords that auto-exclude a posting, UNLESS one of the user's exception
# words (INDUSTRY_EXCEPTION_KEYWORDS) is also present
EXCLUDE_KEYWORDS = _S("agent.EXCLUDE_KEYWORDS")
INDUSTRY_EXCEPTION_KEYWORDS = _S("agent.INDUSTRY_EXCEPTION_KEYWORDS")

# Level tiers for scoring (highest matching tier wins) -- edit freely
LEVEL_TIERS = _S("agent.LEVEL_TIERS")

REMOTE_KEYWORDS = _S("agent.REMOTE_KEYWORDS")

SALARY_FLOOR = _S("agent.SALARY_FLOOR")
_WORK = _S("fit_scoring.WORK_ARRANGEMENT", default={"mode": "remote"})
_WORK_MODE = _WORK.get("mode", "remote")
_COMMUTE = [c.lower() for c in _WORK.get("commute_areas", [])]
ROLE_FAMILY_LABEL = _S("agent.ROLE_FAMILY_LABEL", default="")   # e.g. "Product " in the title-mismatch reason
ASK_FLAG_LABEL = _S("agent.ASK_FLAG_LABEL", default="Ask Me First")   # Industry Flag value when an excluded industry meets the exception list


# ---------------------------------------------------------------------------
# FETCHING
# ---------------------------------------------------------------------------

def fetch_remotive():
    """Free, public API. No key required. https://remotive.com/api-documentation"""
    jobs = []
    try:
        resp = request_with_retry(
            requests.get,
            "https://remotive.com/api/remote-jobs",
            params={"search": "product manager"},
            timeout=60,
        )
        resp.raise_for_status()
        for job in resp.json().get("jobs", []):
            jobs.append({
                "source": "Remotive",
                "id": f"remotive-{job['id']}",
                "title": job.get("title", ""),
                "company": job.get("company_name", ""),
                "url": job.get("url", ""),
                "location": job.get("candidate_required_location", ""),
                "salary_text": job.get("salary", "") or "",
                "description": job.get("description", ""),
            })
    except requests.RequestException as e:
        logger.warning(f"Remotive fetch failed: {e}")
    return jobs


def fetch_remoteok():
    """Free, public API. No key required. https://remoteok.com/api"""
    jobs = []
    try:
        resp = request_with_retry(
            requests.get,
            "https://remoteok.com/api",
            headers={"User-Agent": _ks_user_agent()},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        for job in data:
            if "position" not in job:
                continue  # first element is a legal-notice blob, not a job
            jobs.append({
                "source": "RemoteOK",
                "id": f"remoteok-{job.get('id', job.get('slug', job.get('position', '')))}",
                "title": job.get("position", ""),
                "company": job.get("company", ""),
                "url": job.get("url", ""),
                "location": job.get("location", ""),
                "salary_text": (
                    f"${job['salary_min']:,}-${job['salary_max']:,}"
                    if job.get("salary_min") and job.get("salary_max")
                    else ""
                ),
                "description": job.get("description", "") or "",
            })
    except requests.RequestException as e:
        logger.warning(f"RemoteOK fetch failed: {e}")
    return jobs


# ---------------------------------------------------------------------------
# FILTERING & SCORING
# ---------------------------------------------------------------------------

def _phrase_pattern(phrase):
    """Case-insensitive, whole-word regex for a (possibly multi-word) phrase.
    Word boundaries mean "product" only matches the standalone word -- not
    "Productivity" or "Production", which naive substring matching missed."""
    escaped = re.escape(phrase).replace(r"\ ", r"\s+")
    return re.compile(rf"\b{escaped}\b", re.I)


TITLE_PATTERNS = [_phrase_pattern(p) for p in TITLE_KEYWORDS]
ROLE_REJECT_PATTERNS = [(kw, _phrase_pattern(kw)) for kw in ROLE_REJECT_KEYWORDS]
LOCATION_REJECT_PATTERNS = [(kw, _phrase_pattern(kw)) for kw in LOCATION_REJECT_KEYWORDS]
US_LOCATION_PATTERNS = [_phrase_pattern(kw) for kw in US_LOCATION_KEYWORDS]
NON_US_REGION_PATTERNS = [(kw, _phrase_pattern(kw)) for kw in NON_US_REGION_KEYWORDS]
DOMAIN_REJECT_PATTERNS = [(kw, _phrase_pattern(kw)) for kw in DOMAIN_REJECT_KEYWORDS]
REMOTE_PATTERN = _phrase_pattern("remote")
CANADA_PATTERN = _phrase_pattern("canada")


def matches_title(title):
    return any(p.search(title) for p in TITLE_PATTERNS)


def location_rejection_reason(location):
    """None if the location is acceptable, else a string reason. Accepts
    US/Americas mentions, or "remote" with no other country attached;
    rejects named non-US countries/cities, Canada-only postings, and named
    US cities/offices that don't say "remote"."""
    loc = (location or "").strip()
    if not loc:
        return "no location listed"

    for kw, pattern in LOCATION_REJECT_PATTERNS:
        if pattern.search(loc):
            return f"excluded location {loc!r} (matched {kw!r})"

    has_us = any(p.search(loc) for p in US_LOCATION_PATTERNS)
    has_canada = bool(CANADA_PATTERN.search(loc))
    has_remote = bool(REMOTE_PATTERN.search(loc))
    non_us_region = next((kw for kw, pattern in NON_US_REGION_PATTERNS if pattern.search(loc)), None)

    if has_canada and not has_us:
        return f"Canada-only location {loc!r}"
    if has_us:
        return None
    if has_remote and non_us_region:
        return f"remote but restricted to non-US region {loc!r} (matched {non_us_region!r})"
    if has_remote:
        return None
    if _WORK_MODE != "remote" and _COMMUTE and any(c in loc.lower() for c in _COMMUTE):
        return None   # hybrid or onsite inside the user's commute area
    if _WORK_MODE != "remote" and _COMMUTE:
        return f"location {loc!r} is outside your commute area"
    return f"location {loc!r} has no US/Remote indicator"


def role_type_rejection_reason(title):
    """None if the title is an acceptable PM-level role, else a reason."""
    for kw, pattern in ROLE_REJECT_PATTERNS:
        if pattern.search(title):
            return f"title {title!r} contains rejected role keyword {kw!r}"
    if not matches_title(title):
        return f"title {title!r} doesn't match an approved {ROLE_FAMILY_LABEL}role phrase"
    return None


def domain_rejection_reason(title, description):
    """None if the posting is clear of rejected technical domains, else a
    reason. Checked across title + description since these terms show up
    more in the body than the title."""
    # Equal-opportunity sentences ("... military or veteran status ...") say
    # nothing about the domain, so their words never reject a posting.
    combined = f"{title} {fit_scoring.strip_eeo(description or '')}"
    for kw, pattern in DOMAIN_REJECT_PATTERNS:
        if pattern.search(combined):
            return f"domain keyword {kw!r} found in title/description"
    return None


def get_rejection_reason(job):
    """Runs all filters in order, returning the first rejection reason found,
    or None if the job clears every filter."""
    reason = role_type_rejection_reason(job["title"])
    if reason:
        return reason
    if lead_resolver.is_aggregator(job.get("company", "")):
        return f"aggregator repost ({job.get('company', '')}); the employer's own posting is the target"
    reason = location_rejection_reason(job["location"])
    if reason:
        return reason
    reason = domain_rejection_reason(job["title"], job.get("description", ""))
    if reason:
        return reason
    return None


def industry_flag(text):
    t = fit_scoring.strip_eeo(text).lower()   # EEO wording is not the industry
    has_exclude = any(kw in t for kw in EXCLUDE_KEYWORDS)
    has_exception = any(kw in t for kw in INDUSTRY_EXCEPTION_KEYWORDS)
    if has_exclude and not has_exception:
        return "Excluded"
    if has_exclude and has_exception:
        return ASK_FLAG_LABEL
    return "Clear"


# Words that make a nearby dollar figure more likely to be an actual salary
# mention, vs. funding raised / revenue / customer savings elsewhere in a JD.
SALARY_CONTEXT_KEYWORDS = [
    "salary", "compensation", "base", "range", "pay", "total target cash",
]
SALARY_CONTEXT_PATTERNS = [_phrase_pattern(kw) for kw in SALARY_CONTEXT_KEYWORDS]

# Plausible individual-contributor/manager base salary band -- filters out
# dollar figures that are clearly something else (funding rounds, revenue,
# ARR, customer savings claims, etc.) rather than a salary.
SALARY_PLAUSIBLE_MIN = 50_000
SALARY_PLAUSIBLE_MAX = 600_000

# One dollar amount: "$198,500.00 to $320,000.00", "$143,800 - $231,900",
# "$150k-$200k", "USD 150,000". Always requires a "$"/"USD" marker -- a bare
# number with a "k" suffix and no currency marker (e.g. "401k") is far too
# likely to be something else (a 401(k) retirement plan mention is extremely
# common boilerplate in US postings and would otherwise misread as $401,000).
# The "$" must not be preceded by a letter, so per-country pay bands quoted
# as "S$246,500" (Singapore) or "C$210,700" (Canada) aren't misread as USD.
_SALARY_AMOUNT_RE = re.compile(
    r"(?:USD\s*|(?<![A-Za-z])\$\s*)(?P<amt>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)(?P<k>[kK])?"
)


def _salary_amount_value(match):
    value = float(match.group("amt").replace(",", ""))
    if match.group("k"):
        value *= 1000
    return int(value)


def extract_salary_min(salary_text, description=""):
    """Best-effort parse of the low end of a salary range. Uses salary_text
    when present; otherwise falls back to the free-text description, since
    the Greenhouse/Lever/Ashby fetchers don't populate salary_text at all.
    Only considers amounts within SALARY_PLAUSIBLE_MIN/MAX, and prefers ones
    that appear near a salary-ish context word when the text has more than
    one dollar figure in range (e.g. a JD that also mentions funding raised).
    Still a heuristic -- not reliable, and many postings list no salary."""
    text = salary_text or description or ""
    if not text:
        return None

    candidates = []  # (value, match_start, match_end)
    for m in _SALARY_AMOUNT_RE.finditer(text):
        try:
            value = _salary_amount_value(m)
        except ValueError:
            continue
        if SALARY_PLAUSIBLE_MIN <= value <= SALARY_PLAUSIBLE_MAX:
            candidates.append((value, m.start(), m.end()))

    if not candidates:
        return None

    def near_context(start, end):
        # Bound the window to the current sentence so an unrelated dollar
        # figure two sentences away (e.g. a funding number) doesn't borrow
        # context from a "base salary" mention nowhere near it.
        left = max(text.rfind(".", 0, start), text.rfind("!", 0, start),
                   text.rfind("?", 0, start), text.rfind("\n", 0, start), start - 80)
        right_candidates = [i for i in
                             (text.find(c, end) for c in ".!?\n") if i != -1]
        right = min(right_candidates + [end + 80]) if right_candidates else end + 80
        window = text[max(0, left):min(len(text), right)]
        return any(p.search(window) for p in SALARY_CONTEXT_PATTERNS)

    near = [value for value, start, end in candidates if near_context(start, end)]
    pool = near if near else [value for value, _, _ in candidates]
    return min(pool)


def score_level(title):
    """0-3: how senior the title reads, highest matching tier wins."""
    t = re.sub(r"\bsr\.?(?=\s|$)", "senior", title.lower())
    for points, keywords in LEVEL_TIERS:
        if any(kw in t for kw in keywords):
            return points
    return 0


def score_domain(text):
    """0-3: industry fit, reusing the same exclude/exception keyword logic as industry_flag."""
    t = fit_scoring.strip_eeo(text).lower()
    has_exclude = any(kw in t for kw in EXCLUDE_KEYWORDS)
    has_exception = any(kw in t for kw in INDUSTRY_EXCEPTION_KEYWORDS)
    if has_exclude and not has_exception:
        return 0
    if has_exclude and has_exception:
        return 1
    return 3 if has_exception else 2


def score_remote(job):
    """0-2: 2 if location itself says remote, 1 if only title/description mention it."""
    if any(kw in job["location"].lower() for kw in REMOTE_KEYWORDS):
        return 2
    combined = f"{job['title']} {job['description']}".lower()
    if any(kw in combined for kw in REMOTE_KEYWORDS):
        return 1
    return 0


def score_salary(salary_min):
    """0-2: 2 if at/above floor, 1 if listed but below floor, 0 if not listed."""
    if salary_min is None:
        return 0
    return 2 if salary_min >= SALARY_FLOOR else 1


def score_job(job):
    """Returns (fit_score 0-10, industry_flag, salary_min_or_None).
    Rubric: level (0-3) + domain (0-3) + remote quality (0-2) + salary (0-2)."""
    combined_text = f"{job['title']} {job['company']} {job['description']}"
    flag = industry_flag(combined_text)
    salary_min = extract_salary_min(job["salary_text"], job.get("description", ""))
    source = "salary_text" if job["salary_text"] else "description"
    logger.debug("Salary extract for %r @ %r: %s (from %s, raw=%r)",
                 job["title"], job["company"], salary_min, source,
                 (job["salary_text"] or job.get("description", ""))[:100])

    score = (score_level(job["title"]) + score_domain(combined_text)
             + score_remote(job) + score_salary(salary_min))

    return score, flag, salary_min


# ---------------------------------------------------------------------------
# DEDUPE (local memory across runs)
# ---------------------------------------------------------------------------

def load_seen():
    if SEEN_JOBS_FILE.exists():
        return set(json.loads(SEEN_JOBS_FILE.read_text()))
    return set()


def save_seen(seen_ids):
    SEEN_JOBS_FILE.write_text(json.dumps(sorted(seen_ids)))


# ---------------------------------------------------------------------------
# NOTION
# ---------------------------------------------------------------------------

# company name -> Companies-database page id, populated as we go so a run
# with many postings from the same company only looks it up/creates it once.
COMPANY_PROFILE_CACHE = {}


def _company_ats_text(job):
    """Best-effort "platform / slug" description for a new Company page's ATS
    field, matching the style already used on existing pages (e.g.
    "greenhouse / mozilla"). Falls back to the posting's source (e.g.
    "Remotive") for jobs that aren't from a tracked ATS at all."""
    platform = job.get("ats_platform")
    slug = job.get("ats_slug")
    if platform and slug:
        return f"{platform} / {slug}"
    if platform:
        return platform
    return job.get("source", "")


def find_company_page(company_name):
    """Query the Companies database for a page whose Company title exactly
    matches company_name. Returns a page id, or None if not found or the
    query fails. Exact-match only -- a company already tracked under a
    slightly different name/casing won't be found and a new page will be
    created for it (documented tradeoff, not a bug)."""
    url = f"https://api.notion.com/v1/databases/{NOTION_COMPANIES_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {"filter": {"property": "Company", "title": {"equals": company_name}}}
    try:
        resp = request_with_retry(requests.post, url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        logger.warning(f"Companies lookup failed for {company_name!r} after retries: {e}")
        return None
    if resp.status_code >= 300:
        logger.warning(f"Companies lookup failed for {company_name!r}: {resp.status_code} {resp.text}")
        return None
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None


def create_company_page(company_name, ats_text):
    """Creates a stub Company page for a company we've never tracked before,
    flagged for manual follow-up via Monitoring/Risk Level/Verdict."""
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    properties = {
        "Company": {"title": [{"text": {"content": company_name[:200]}}]},
        "ATS": {"rich_text": [{"text": {"content": ats_text[:200]}}]},
        "Monitoring": {"select": {"name": "Auto (in agent feed)"}},
        "Risk Level": {"select": {"name": "Not researched"}},
        "Verdict": {"select": {"name": "Needs research"}},
    }
    payload = {"parent": {"database_id": NOTION_COMPANIES_DATABASE_ID}, "properties": properties}
    try:
        resp = request_with_retry(requests.post, url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        logger.warning(f"Failed to create Companies page for {company_name!r} after retries: {e}")
        return None
    if resp.status_code >= 300:
        logger.warning(f"Failed to create Companies page for {company_name!r}: {resp.status_code} {resp.text}")
        return None
    return resp.json()["id"]


def get_or_create_company_page(job):
    """Returns the Companies-database page id for job's company, looking it
    up (or creating a stub page for it) on first use and caching the result
    for the rest of the run. A cached None (lookup/create failed) is kept
    too, so a persistent failure doesn't get retried on every single job
    from that company within the same run."""
    company_name = job["company"].strip()
    if not company_name:
        return None
    if company_name in COMPANY_PROFILE_CACHE:
        return COMPANY_PROFILE_CACHE[company_name]

    page_id = find_company_page(company_name)
    if not page_id:
        page_id = create_company_page(company_name, _company_ats_text(job))
    COMPANY_PROFILE_CACHE[company_name] = page_id
    return page_id


# ---------------------------------------------------------------------------
# COMPANY PROFILE READ (feeds fit scoring v2)
# One GET per company per run, cached. Returns the handful of fields the
# scorer needs; anything missing reads as Unknown / Not researched.
# ---------------------------------------------------------------------------

COMPANY_FIELDS_CACHE = {}
NOTION_HEADERS = {"Authorization": f"Bearer {NOTION_TOKEN}",
                  "Notion-Version": "2022-06-28",
                  "Content-Type": "application/json"}


def _sel(props, name):
    v = props.get(name, {}).get("select")
    return v["name"] if v else None


def _rt(props, name):
    return "".join(t.get("plain_text", "") for t in props.get(name, {}).get("rich_text", []))


def _title(props, name):
    return "".join(t.get("plain_text", "") for t in props.get(name, {}).get("title", []))


def _date(props, name):
    v = props.get(name, {}).get("date")
    return v["start"] if v else None


def fetch_company_profile(page_id):
    """Companies row -> dict for fit_scoring (remote_posture, risk, pto,
    health, verdict, domains, website, name, has_icon, last_researched)."""
    if not page_id or not NOTION_TOKEN:
        return {}
    if page_id in COMPANY_FIELDS_CACHE:
        return COMPANY_FIELDS_CACHE[page_id]
    try:
        resp = request_with_retry(requests.get, f"https://api.notion.com/v1/pages/{page_id}",
                                  headers=NOTION_HEADERS, timeout=60)
    except requests.RequestException as e:
        logger.warning(f"Company profile read failed for {page_id}: {e}")
        COMPANY_FIELDS_CACHE[page_id] = {}
        return {}
    if resp.status_code >= 300:
        COMPANY_FIELDS_CACHE[page_id] = {}
        return {}
    page = resp.json()
    p = page.get("properties", {})
    profile = {
        "name": _title(p, "Company"),
        "remote_posture": _sel(p, "Remote Posture"),
        "risk": _sel(p, "Risk Level"),
        "pto": _sel(p, "PTO"),
        "health": _sel(p, "Health Benefits"),
        "verdict": _sel(p, "Verdict"),
        "domains": [d["name"] for d in p.get("Domain", {}).get("multi_select", [])],
        "website": p.get("Website", {}).get("url"),
        "job_board_url": p.get("Job Board URL", {}).get("url"),
        "research_tier": _sel(p, "Research Tier"),
        "last_researched": _date(p, "Last Researched"),
        "has_icon": bool(page.get("icon")),
    }
    COMPANY_FIELDS_CACHE[page_id] = profile
    return profile


def patch_page(page_id, properties=None, icon_url=None):
    """PATCH a page's properties and/or icon. Returns True on success."""
    payload = {}
    if properties:
        payload["properties"] = properties
    if icon_url:
        payload["icon"] = {"type": "external", "external": {"url": icon_url}}
    if not payload:
        return True
    try:
        resp = request_with_retry(requests.patch, f"https://api.notion.com/v1/pages/{page_id}",
                                  headers=NOTION_HEADERS, json=payload, timeout=60)
    except requests.RequestException as e:
        logger.warning(f"Patch failed for {page_id}: {e}")
        return False
    if resp.status_code >= 300:
        logger.warning(f"Patch failed for {page_id}: {resp.status_code} {resp.text[:300]}")
        return False
    _cache_apply_patch(page_id, properties)
    return True


def favicon_url(website):
    """Google's favicon service, which works for any public domain and needs no key."""
    host = urlparse(website if "://" in website else f"https://{website}").netloc
    return f"https://www.google.com/s2/favicons?domain={host}&sz=128" if host else None


def ensure_company_icon(page_id, profile):
    """Set the company page icon from its Website once, when known."""
    if not page_id or profile.get("has_icon") or not profile.get("website"):
        return False
    url = favicon_url(profile["website"])
    if url and patch_page(page_id, icon_url=url):
        profile["has_icon"] = True
        return True
    return False


def company_tier_update(page_id, profile, posting_tier):
    """Companies carry the best tier of their open postings, so the research
    routine can pick companies by the same rule as postings."""
    if not page_id:
        return
    rank = {"A": 3, "B": 2, "C": 1}
    current = (profile.get("research_tier") or "")[:1]
    if rank.get(posting_tier, 0) > rank.get(current, 0):
        if patch_page(page_id, {"Research Tier": {"select": {"name": fit_scoring.TIER_NAMES[posting_tier]}}}):
            profile["research_tier"] = fit_scoring.TIER_NAMES[posting_tier]


# Maps the classification score_remote() already computes onto the
# Applications "Remote Status" select (options: Fully Remote / Hybrid /
# Onsite). Only 2 -- the posting's own location field says remote -- is a
# positive remote classification. 1 (remote mentioned only in the title or
# description) and 0 (no remote mention) don't tell hybrid from onsite, so
# Remote Status is left empty for those rather than guessed.
REMOTE_STATUS_BY_REMOTE_SCORE = {2: "Fully Remote"}


def remote_status_for(job):
    """Remote Status select value for job, or None to leave it unset."""
    return REMOTE_STATUS_BY_REMOTE_SCORE.get(score_remote(job))


# Postings lead with long company blurbs; the qualifications section is what
# the weekly triage screens against, so the snapshot anchors on it.
SNAP_MARKERS = re.compile(
    r"(what (we.re|we are|we’re) looking for|minimum qualifications|basic qualifications|"
    r"required qualifications|requirements:?|what you.ll need|what you need to succeed|"
    r"about you\b|who you are|what you.ll bring|what you bring|qualifications:?|"
    r"your background|must.have|ideal candidate|"
    r"you should have|we.d love|looking for someone|skills (and|&) experience|"
    r"your experience|experience required|what it takes|what you.ll do|responsibilities:?|"
    r"about the role|the role:?|what you will do)", re.I)
# 2026-10-20: dropped "you (have|are|bring|will bring)" from the markers. It
# matched "you have read Northwind's Global Candidate Privacy Notice" in the
# consent boilerplate and produced 522-character snapshots of legal text.

SNAPSHOT_MAX = 9000  # stored as 1,900-char rich_text chunks (Notion allows many)


def clean_posting_text(desc):
    """Greenhouse (and some Lever) descriptions arrive HTML-entity-encoded
    (&lt;p&gt;...), so unescape before stripping tags or the tags survive as
    text and the snapshot anchors land on boilerplate. Found when most
    open-row snapshots still carried &lt; and &amp;."""
    # v4.0 (Nov 7, 2026): one cleaner for the scorer and the snapshot, which
    # keeps bullet and paragraph boundaries as " • " so the required block can
    # be read item by item (fit_scoring._clean).
    return fit_scoring._clean(desc)


def make_snapshot(desc):
    """A snapshot of the posting: short intro plus the text from the first
    qualifications-style heading onward, so stated minimums survive the cut."""
    text = clean_posting_text(desc)
    if not text:
        return ""
    m = SNAP_MARKERS.search(text)
    if m and m.start() > 250:
        return (text[:230] + " [...] " + text[m.start():m.start() + SNAPSHOT_MAX - 240])[:SNAPSHOT_MAX]
    return text[:SNAPSHOT_MAX]


def snapshot_is_stale(stored, fresh):
    """True when a stored Posting Snapshot should be replaced by a fresh capture.

    Rows captured before the Oct 20 unescape fix hold HTML-escaped text
    (&lt;p&gt;...), and some captured only the company intro, so the scorer
    never saw the requirements (one posting scored work 0/30 on a
    1,732-character intro, Oct 21, 2026). Replace when the stored text is
    escaped or raw HTML, or when it has no qualifications-style heading and
    the fresh capture is meaningfully longer."""
    if not fresh:
        return False
    if not stored:
        return True
    if "&lt;" in stored or "&amp;" in stored or re.search(r"<\s*(p|li|ul|div|br|strong)\b", stored, re.I):
        return True
    if not SNAP_MARKERS.search(stored) and len(fresh) > len(stored) * 1.2:
        return True
    return False


SNAPSHOT_REFRESHED_TAG = "SNAPSHOT REFRESHED"


def snapshot_rich_text(snapshot):
    return [{"text": {"content": snapshot[i:i + 1900]}} for i in range(0, len(snapshot), 1900)]


def evaluate_job(job, company_page_id, evergreen=False, today=None):
    """Fit scoring v2 for a fetched posting. Returns the fit_scoring result."""
    profile = fetch_company_profile(company_page_id) if company_page_id else {}
    salary_min = extract_salary_min(job.get("salary_text", ""), job.get("description", ""))
    return fit_scoring.score_posting(
        job["title"], job.get("description", ""), salary_min=salary_min,
        company=profile, company_name=job.get("company", ""), evergreen=evergreen, today=today,
        remote_hint=score_remote(job) == 2, age_days=posting_age_days(job, None, today),
        salary_text=job.get("salary_text", "") or "")


def scoring_properties(result, today=None):
    """The Notion properties fit scoring v2 owns, shared by new writes and
    the rescoring pass so the two can never drift."""
    today = today or datetime.now().date()
    props = {
        "Role Fit Score": {"number": result["fit_10"]},
        "Research Tier": {"select": {"name": fit_scoring.TIER_NAMES[result["tier"]]}},
        "Score Breakdown": {"rich_text": [{"text": {"content": result["breakdown"][:1900]}}]},
        "Fit Evidence": {"rich_text": [{"text": {"content": result["evidence"][:1900]}}]},
        "Domain Tier": {"select": {"name": result["domain_tier"]}},
        "Label Reason": {"rich_text": [{"text": {"content": fit_scoring.label_reason(result, today)[:1900]}}]},
    }
    if result["verdict"]:
        props["Overall Verdict"] = {"select": {"name": result["verdict"]}}
    if result["schedule"]:
        props["Schedule Intensity"] = {"select": {"name": result["schedule"]}}
    return props


def posted_date_properties(job, history=None, today=None):
    """Posted Date + its source from the board's own publish date, a Workday
    'Posted N Days Ago' string, or the first day this agent saw the posting."""
    today = today or datetime.now().date()
    published = (job.get("published") or "")[:10]
    if re.match(r"\d{4}-\d{2}-\d{2}$", published):
        src = "Board approximate" if job.get("published_approx") else "Board publish date"
        return {"Posted Date": {"date": {"start": published}},
                "Posted Date Source": {"select": {"name": src}}}
    d, approx = fit_scoring.workday_posted_to_date(job.get("posted_text", ""), today)
    if d:
        return {"Posted Date": {"date": {"start": d}},
                "Posted Date Source": {"select": {"name": "Board approximate" if approx else "Board publish date"}}}
    if history is not None:
        key = history_key(job)
        ids = history.get(key, {}).get("ids", {})
        seen = [v for k, v in ids.items() if not k.startswith("tracker-")]
        if seen:
            return {"Posted Date": {"date": {"start": min(seen)}},
                    "Posted Date Source": {"select": {"name": "First seen by agent"}}}
    return {}


def lead_notes(job):
    """The Notes line for a new row. LinkedIn leads also record the alert link
    and the board-lookup outcome, which is what the daily research step
    filters on for its web-lookup pass."""
    notes = f"Auto-found by job search agent. Location: {job['location']}"
    if job.get("linkedin_url"):
        notes += f" Found via LinkedIn alert: {job['linkedin_url']}"
    if job.get("notes_extra"):
        notes += " " + job["notes_extra"]
    return notes


def write_to_notion(job, result, flag, salary_min, ghost_note=None, evergreen=False,
                    company_page_id=None, history=None):
    if not NOTION_TOKEN:
        logger.warning("NOTION_TOKEN not set -- skipping Notion write.")
        return False
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    today = datetime.now().date()
    properties = {
        "Role": {"title": [{"text": {"content": job["title"][:200]}}]},
        "Company": {"rich_text": [{"text": {"content": job["company"][:200]}}]},
        "Job Posting": {"url": job["url"] or None},
        # Hard-rule fails are decided on arrival: they land Closed (still in
        # the tracker for dedupe and the funnel, out of every open view).
        "Status": {"status": {"name": "Closed" if result.get("hard_skip") else "Interested"}},
        "Industry Flag": {"select": {"name": flag}},
        "Source": {"select": {"name": job["source"] if job["source"] in
                    ("LinkedIn", "Indeed", "We Work Remotely", "Built In", "FlexJobs",
                     "Referral", "Company Site", "Other") else "Other"}},
        "Notes": {"rich_text": [{"text": {"content": lead_notes(job)[:1900]}}]},
        "Last Verified": {"date": {"start": today.isoformat()}},
    }
    properties.update(scoring_properties(result, today))
    properties.update(posted_date_properties(job, history, today))
    if salary_min:
        properties["Base Salary"] = {"number": salary_min}
        properties["Pay Basis"] = {"select": {"name": "Base"}}
    else:
        properties["Pay Basis"] = {"select": {"name": "Not posted"}}
    if evergreen:
        properties["Posting Health"] = {"select": {"name": "Suspected evergreen"}}
    if ghost_note:
        properties["Role Red Flags"] = {"rich_text": [{"text": {"content": ghost_note[:1900]}}]}
    snapshot = make_snapshot(job.get("description", ""))
    if snapshot:
        properties["Posting Snapshot"] = {"rich_text": snapshot_rich_text(snapshot)}
    else:
        # Title-only (a LinkedIn card, say): tag the breakdown the same way
        # rescore_tracker does, so the row is rescored once text arrives.
        properties["Score Breakdown"]["rich_text"][0]["text"]["content"] = (
            NO_SNAPSHOT_TAG + " (title-only score; refresh fills it). " + result["breakdown"])[:1900]
    remote_status = remote_status_for(job)
    if remote_status:
        properties["Remote Status"] = {"select": {"name": remote_status}}
    if company_page_id is None:
        company_page_id = job.get("notion_page_id") or get_or_create_company_page(job)
    if company_page_id:
        properties["Company Profile"] = {"relation": [{"id": company_page_id}]}
        profile = fetch_company_profile(company_page_id)
        company_tier_update(company_page_id, profile, result["tier"])
        ensure_company_icon(company_page_id, profile)

    payload = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}
    try:
        resp = request_with_retry(requests.post, url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        logger.warning(f"Notion write failed for '{job['title']}' after retries: {e}")
        return False
    if resp.status_code >= 300:
        logger.warning(f"Notion write failed for '{job['title']}': {resp.status_code} {resp.text}")
        return False
    return True


# ---------------------------------------------------------------------------
# ALREADY-TRACKED CHECK
# Before writing a row, skip any posting whose ID is already in the tracker
# under ANY status (Closed, Rejected, Applied...). seen_jobs.json only knows
# what this agent wrote, so rows added by hand or by another routine used to
# come back as fresh "Interested" duplicates.
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_GH_JID_RE = re.compile(r"[?&]gh_jid=(\d+)")
_WORKDAY_REQ_RE = re.compile(r"_([A-Za-z]*\d{4,})(?:-\d+)?(?:[/?#]|$)")
_LONG_NUM_RE = re.compile(r"(\d{6,})")


def posting_key(url):
    """A stable ID for a posting that survives different URL shapes for the
    same job (careers-site wrapper vs. board URL, jobs.boxco.com vs
    boxco.jobs). Workday re-post suffixes collapse to the base requisition."""
    if not url:
        return None
    u = url.strip().lower()
    for rx in (_UUID_RE, _GH_JID_RE, _WORKDAY_REQ_RE):
        m = rx.search(u)
        if m:
            return m.group(1) if rx.groups else m.group(0)
    nums = _LONG_NUM_RE.findall(u.split("?")[0])
    if nums:
        return nums[-1]
    return u.split("?")[0].rstrip("/")


TRACKED_TITLE_PAIRS = set()


def fetch_tracked_posting_keys():
    """posting_key() of every Job Posting URL in the tracker, any status.
    Returns None if Notion can't be read, so callers skip the check rather
    than treat the tracker as empty."""
    if not NOTION_TOKEN:
        return None
    base_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    url = _filter_properties_url(base_url, ("Job Posting", "Company", "Role"))
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}",
               "Notion-Version": "2022-06-28",
               "Content-Type": "application/json"}
    payload, keys = {"page_size": 100}, set()
    while True:
        try:
            resp = request_with_retry(requests.post, url, headers=headers,
                                      json=payload, timeout=60)
        except requests.RequestException as e:
            logger.warning(f"Tracked-posting lookup failed (skipping check): {e}")
            return None
        if resp.status_code == 400 and url != base_url:
            # The property-id filter was refused (ids changed?); fall back to full rows.
            logger.warning("filter_properties refused; tracked-posting scan reading full rows.")
            url = base_url
            continue
        if resp.status_code >= 300:
            logger.warning(f"Tracked-posting lookup failed: {resp.status_code}")
            return None
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            k = posting_key(props.get("Job Posting", {}).get("url"))
            if k:
                keys.add(k)
            # Company + normalized title, so the same role arriving from a job
            # board feed under a different URL (weworkremotely.com vs the
            # company's own board) doesn't become a second row. Found when
            # one posting came in twice from two sources.
            company = _rt(props, "Company").strip().lower()
            title = norm_title(_title(props, "Role"))
            if company and title:
                TRACKED_TITLE_PAIRS.add((company, title))
        if not data.get("has_more"):
            return keys
        payload["start_cursor"] = data["next_cursor"]


# ---------------------------------------------------------------------------
# STALE POSTING CLEANUP
# Marks a Notion row "Closed" once its Job Posting URL has been missing from
# the fetch for two consecutive runs. Only ever touches rows currently in
# Status "Interested" -- Applied/Interviewing/Offer/Rejected are never queried
# and so can never be modified here.
# ---------------------------------------------------------------------------

def load_miss_counts():
    if STALE_MISS_FILE.exists():
        return json.loads(STALE_MISS_FILE.read_text())
    return {}


def save_miss_counts(miss_counts):
    STALE_MISS_FILE.write_text(json.dumps(miss_counts, indent=2))


def fetch_interested_rows():
    """Returns [(page_id, job_posting_url), ...] for every Notion row with Status == Interested."""
    if not NOTION_TOKEN:
        return []
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {"filter": {"property": "Status", "status": {"equals": "Interested"}}}
    rows = []
    while True:
        try:
            resp = request_with_retry(requests.post, url, headers=headers, json=payload, timeout=60)
        except requests.RequestException as e:
            logger.warning(f"Notion query for Interested rows failed after retries: {e}")
            break
        if resp.status_code >= 300:
            logger.warning(f"Notion query for Interested rows failed: {resp.status_code} {resp.text}")
            break
        data = resp.json()
        for page in data.get("results", []):
            posting_url = page.get("properties", {}).get("Job Posting", {}).get("url")
            if posting_url:
                rows.append((page["id"], posting_url))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return rows


def update_status(page_id, status_name):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    try:
        resp = request_with_retry(
            requests.patch, url, headers=headers, timeout=60,
            json={"properties": {"Status": {"status": {"name": status_name}}}},
        )
    except requests.RequestException as e:
        logger.warning(f"Failed to close page {page_id} after retries: {e}")
        return False
    if resp.status_code >= 300:
        logger.warning(f"Failed to close page {page_id}: {resp.status_code} {resp.text}")
        return False
    _cache_apply_patch(page_id, {"Status": {"status": {"name": status_name}}})
    return True


def _board_scope(url):
    """(host, first path segment) for a posting URL, e.g.
    ("job-boards.greenhouse.io", "exampleco") or ("jobs.lever.co", "paylane").
    Two postings share a scope when they come from the same board, which is
    the unit the fetchers cover. For careers-site wrappers (quillco.careers,
    careers.harborview.com) the host alone is the scope."""
    if not url:
        return None
    try:
        parts = urlparse(url.strip().lower())
    except ValueError:
        return None
    host = parts.netloc
    if not host:
        return None
    segs = [seg for seg in parts.path.split("/") if seg]
    board_hosts = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com")
    if host.endswith(board_hosts) and segs:
        return (host, segs[0])
    return (host, "")


def close_stale_postings(all_jobs):
    """Returns the number of rows newly marked Closed this run."""
    if not NOTION_TOKEN:
        return 0

    current_urls = {job["url"] for job in all_jobs if job["url"]}
    # 2026-10-29 fix: match on posting_key(), the same normalized ID that
    # refresh_open_rows uses to stamp Last Verified. Matching on the exact URL
    # string meant a row whose stored URL had a different shape from the
    # fetched one (job-boards vs boards.greenhouse.io, a ?gh_jid= query, a
    # careers-site wrapper) was stamped live AND counted as a miss in the same
    # run, then closed two runs later, while the postings were still open.
    current_keys = {posting_key(u) for u in current_urls}
    current_keys.discard(None)
    # 2026-10-17 fix: only judge staleness for postings on a board this run
    # actually fetched. Rows added another way or by hand (Built In,
    # dailyremote, LinkedIn, Jobvite, company sites not in CONFIRMED_COMPANIES)
    # were never in all_jobs, so they were being closed as "stale" after two
    # runs regardless of whether the posting was still open.
    covered_boards = {_board_scope(u) for u in current_urls}
    covered_boards.discard(None)
    miss_counts = load_miss_counts()
    new_miss_counts = {}
    closed_count = 0

    for page_id, posting_url in fetch_interested_rows():
        key = posting_key(posting_url)
        if posting_url in current_urls or (key and key in current_keys):
            continue  # still live in today's fetch -- nothing to track
        scope = _board_scope(posting_url)
        if scope not in covered_boards:
            continue  # not a board we fetch; can't tell if it's stale
        if scope and scope[0].endswith(FEED_HOSTS + ("linkedin.com",)):
            # Feed boards (We Work Remotely, Himalayas, Working Nomads,
            # remote.co) only list recent postings, so dropping out of the
            # feed says nothing about whether the job is still open. Last
            # Verified stops moving instead, which the user can see.
            continue

        miss_id = key or posting_url
        count = miss_counts.get(miss_id, 0) + 1
        if count >= 2:
            if update_status(page_id, "Closed"):
                closed_count += 1
            # resolved either way -- don't carry it forward in the miss file
        else:
            new_miss_counts[miss_id] = count

    save_miss_counts(new_miss_counts)
    return closed_count


# ---------------------------------------------------------------------------
# TEXT DIGEST
# ---------------------------------------------------------------------------

def send_text_digest(new_matches):
    if not PHONE_GATEWAY_EMAIL:
        return  # optional feature, not configured; nothing to warn about every morning
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        logger.warning("PHONE_GATEWAY_EMAIL is set but GMAIL_ADDRESS/GMAIL_APP_PASSWORD are not; text digest skipped.")
        return
    actionable = [m for m in new_matches if m[1]["tier"] in ("A", "B")]
    if not actionable:
        body = "Job search agent ran: no new Tier A or B matches today."
    else:
        top = sorted(actionable, key=lambda x: -x[1]["score"])[:5]
        lines = [f"{len(actionable)} new Tier A/B match(es). Top ones:"]
        for job, result, flag, salary_min in top:
            salary_str = f"${salary_min:,}+" if salary_min else "salary n/a"
            lines.append(f"- [{result['tier']} {result['score']}] {job['title']} @ {job['company']} ({salary_str})")
        lines.append("Full list in your Notion tracker.")
        body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = "Job Search Agent Digest"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = PHONE_GATEWAY_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)


# ---------------------------------------------------------------------------
# FRESH TIER A EMAIL ALERTS
# Truly new roles fast, not ones that have sat open for months. After any run
# (the daily full run or a --quick daytime run), every newly written Tier A
# row posted FRESH_ALERT_DAYS or fewer days ago is emailed to the user's own
# mailbox, from the user's own mailbox. It never emails anyone else.
# fresh_alerts_sent.json keeps one alert per posting even across runs.
# ---------------------------------------------------------------------------

FRESH_ALERT_DAYS = int(os.environ.get("FRESH_ALERT_DAYS", _S("agent.FRESH_ALERT_DAYS", default=2)))
FRESH_ALERTS_SENT_FILE = DATA_DIR / "fresh_alerts_sent.json"
FRESH_ALERTS_PENDING_FILE = DATA_DIR / "fresh_alerts_pending.json"   # v4.0: failed alerts, retried next run


NEAR_MISS_UNCAPPED_MIN = fit_scoring.ONE_MISS_STRONG_MIN   # 80 before any cap, by default


def is_near_miss(result):
    """v4.0: a Possible fit whose score before the caps was Strong-fit
    territory, held back by at most one named minimum and at most two required
    items the bank can't vouch for. Alerts like a Tier A row, labeled, so a
    real fit isn't lost among the Possible fits."""
    if result.get("verdict") != "Possible fit" or result.get("hard_skip"):
        return False
    if result.get("score_uncapped", result["score"]) < NEAR_MISS_UNCAPPED_MIN:
        return False
    if len(result.get("missing_minimums") or []) > 1 or len(result.get("unvouched") or []) > 2:
        return False
    return True


def fresh_alert_candidates(written, history=None, today=None):
    """Written matches that earn an alert: Tier A (not Poor fit) or a near miss
    (is_near_miss), posted within FRESH_ALERT_DAYS, and not flagged evergreen.
    Unknown age never alerts."""
    today = today or datetime.now().date()
    out = []
    for job, result, flag, salary_min in written:
        strong = result["tier"] == "A" and result.get("verdict") != "Poor fit"
        if not strong and not is_near_miss(result):
            continue
        age = posting_age_days(job, history, today)
        if age is None or age > FRESH_ALERT_DAYS:
            continue
        out.append((job, result, salary_min, age))
    return sorted(out, key=lambda m: (m[3], -m[1].get("score_uncapped", m[1]["score"])))


def _near_miss_why(result):
    why = [m.split(" (")[0] for m in (result.get("missing_minimums") or [])[:1]]
    why += ["can't vouch: " + u[:60].rstrip(" .") for u in (result.get("unvouched") or [])[:2]]
    return "; ".join(why) or "capped"


def _age_words(age):
    return "posted today" if age == 0 else f"posted {age} day{'s' if age != 1 else ''} ago"


def fresh_alert_message(fresh):
    """(subject, body) for one email covering every fresh Tier A row."""
    job, result, _, age = fresh[0]
    near = is_near_miss(result) and result["tier"] != "A"
    tag = "[Fresh near-miss]" if near else "[Fresh Tier A]"
    shown = result.get("score_uncapped", result["score"]) if near else result["score"]
    subject = f"{tag} {job['company']} – {job['title']}, {shown} fit, {_age_words(age)}"
    if len(fresh) > 1:
        subject += f" (+{len(fresh) - 1} more)"
    lines = []
    for job, result, salary_min, age in fresh:
        salary = f"${salary_min:,.0f}+" if salary_min else "no range posted"
        verdict = f", {result['verdict']}" if result.get("verdict") else ""
        near = is_near_miss(result) and result["tier"] != "A"
        score_line = (f"near miss: {result.get('score_uncapped', result['score'])}/100 before the cap "
                      f"({_near_miss_why(result)}), {_age_words(age)}, {salary}{verdict}") if near else \
                     f"{result['score']}/100 fit, {_age_words(age)}, {salary}{verdict}"
        lines += [f"{job['company']} – {job['title']}", score_line,
                  result.get("evidence", "")[:200],
                  job["url"], ""]
    lines.append("Rows are in your Notion Applications tracker.")
    return subject[:200], "\n".join(lines)


def send_fresh_alerts(written, history=None, today=None):
    """Email fresh Tier A rows to the user. Best effort: never breaks the run."""
    fresh = fresh_alert_candidates(written, history, today)
    if not fresh and not FRESH_ALERTS_PENDING_FILE.exists():
        return 0
    try:
        sent = set(json.loads(FRESH_ALERTS_SENT_FILE.read_text()))
    except (OSError, json.JSONDecodeError):
        sent = set()
    fresh = [m for m in fresh if m[0]["id"] not in sent]
    # v4.0: an alert that failed to send last run ("Fresh Tier A alert email
    # failed" with 5 matches, never resent) goes out with this one. The
    # pending file keeps the finished message text and the row ids only.
    try:
        pending = json.loads(FRESH_ALERTS_PENDING_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        pending = {}
    pending_ids = [i for i in pending.get("ids", []) if i not in sent and i not in {m[0]["id"] for m in fresh}]
    if not fresh and not pending_ids:
        return 0
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        logger.warning("GMAIL_ADDRESS/GMAIL_APP_PASSWORD not set; fresh Tier A alert skipped.")
        return 0
    if fresh:
        subject, body = fresh_alert_message(fresh)
        if pending_ids:
            body += "\n\nStill unsent from the last run:\n" + pending.get("body", "")
    else:
        subject, body = pending.get("subject", "[Fresh Tier A] unsent alert"), pending.get("body", "")
    all_ids = [m[0]["id"] for m in fresh] + pending_ids
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS   # the user's own inbox only
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        logger.warning(f"Fresh Tier A alert email failed: {e}; will retry next run")
        notify("Job agent: fresh Tier A", subject)   # at least a Mac notification
        try:
            FRESH_ALERTS_PENDING_FILE.write_text(json.dumps({"ids": all_ids[-50:], "subject": subject, "body": body[-6000:]}, indent=1))
        except (OSError, TypeError) as e2:
            print(f"[warn] could not save pending alerts: {e2}", file=sys.stderr)
        return 0
    sent.update(all_ids)
    try:
        if FRESH_ALERTS_PENDING_FILE.exists():
            FRESH_ALERTS_PENDING_FILE.unlink()
    except OSError:
        pass
    try:
        FRESH_ALERTS_SENT_FILE.write_text(json.dumps(sorted(sent)[-2000:], indent=1))
    except OSError:
        pass
    fresh = all_ids
    print(f"Fresh Tier A alert emailed: {len(fresh)} posting(s).")
    return len(fresh)


# ---------------------------------------------------------------------------
# HEALTH: never fail silently again.
# In Sept-Oct 2026 the tracker's "Fit Score" property was renamed to
# "Role Fit Score" and every Notion write failed quietly for three weeks.
# These helpers make that class of failure loud and immediate.
# ---------------------------------------------------------------------------

DIGEST_FILE = DATA_DIR / "Latest_Agent_Digest.md"

# Every property write_to_notion() sends. If the tracker renames or deletes
# one, abort the run and notify instead of failing 21 writes one by one.
REQUIRED_APP_PROPERTIES = (
    "Role", "Company", "Job Posting", "Status", "Industry Flag",
    "Role Fit Score", "Source", "Notes", "Base Salary", "Remote Status",
    "Company Profile", "Posting Health", "Role Red Flags",
    # fit scoring v2 (added 2026-10-20)
    "Research Tier", "Score Breakdown", "Fit Evidence", "Domain Tier",
    "Label Reason", "Overall Verdict", "Schedule Intensity", "Pay Basis",
    "Posted Date", "Posted Date Source", "Last Verified",
)

# ---------------------------------------------------------------------------
# GHOST / EVERGREEN POSTING DETECTION
# Signals, any one of which flags a posting "Suspected evergreen":
#   1. True repost: the same company+title under a new posting ID in the SAME
#      location within the window. A role posted once as "Remote US" and once
#      as "Remote Canada" is a normal country twin (Northwind, Quillco and
#      others do this for every role) and is not counted as a repost.
#   2. Age: the board's original publish date is EVERGREEN_AGE_DAYS+ old.
#      Uses first_published / publishedAt / createdAt, never updated_at,
#      which boards bump in bulk.
#   3. City spray: the role listed in GHOST_FLAG_LOCATIONS+ distinct
#      non-country locations.
#   4. Workday requisition re-post suffix (e.g. _P100001-2).
#   5. Pipeline titles: open calls, talent communities, or several levels in
#      one title ("Senior/Staff/Principal").
# Postings 60+ days old get an age note in Role Red Flags without the flag.
# Rows seeded from the tracker ("tracker-" ids) are history, not posting IDs,
# and never count toward a repost.
# ---------------------------------------------------------------------------

POSTING_HISTORY_FILE = DATA_DIR / "posting_history.json"
HISTORY_WINDOW_DAYS = 30      # sightings inside this window count toward the city-spray flag
# Reposts look further back (Oct 25, 2026): companies often close a role and
# reopen it under a new ID a month or two later, which a 30-day window missed.
REPOST_WINDOW_DAYS = int(os.environ.get("REPOST_WINDOW_DAYS", _S("agent.REPOST_WINDOW_DAYS", default=90)))
HISTORY_RETENTION_DAYS = 120  # sightings older than this are pruned (must cover REPOST_WINDOW_DAYS)
# IDs for the same title in the same location before it counts as a repost.
GHOST_FLAG_IDS = int(os.environ.get("GHOST_FLAG_IDS", _S("agent.GHOST_FLAG_IDS", default=2)))
GHOST_FLAG_LOCATIONS = int(os.environ.get("GHOST_FLAG_LOCATIONS", _S("agent.GHOST_FLAG_LOCATIONS", default=4)))
GHOST_SKIP_IDS = int(os.environ.get("GHOST_SKIP_IDS", _S("agent.GHOST_SKIP_IDS", default=4)))
EVERGREEN_AGE_DAYS = int(os.environ.get("EVERGREEN_AGE_DAYS", _S("agent.EVERGREEN_AGE_DAYS", default=150)))
AGE_NOTE_DAYS = int(os.environ.get("AGE_NOTE_DAYS", _S("agent.AGE_NOTE_DAYS", default=60)))

# A location that only names a country/region for a remote role, e.g.
# "Remote US", "Remote - Canada", "Canada (Remote)". Not a city spray.
_COUNTRY_REMOTE_RE = re.compile(
    r"^\W*(remote\W+)?(us|usa|u\.s\.|united states|canada|ca|uk|united kingdom|"
    r"mexico|americas|global|anywhere|worldwide)(\W+remote)?\W*$")
_WORKDAY_REPOST_RE = re.compile(r"_[A-Za-z]*\d+-(\d+)(?:[/?#]|$)")
_PIPELINE_TITLE_RE = re.compile(
    r"open call|talent (community|pool|network)|general application|"
    r"future opportunit|"
    r"\b(associate|senior|sr\.?|staff|principal|lead)\s*/\s*"
    r"(senior|sr\.?|staff|principal|lead|group)\b", re.I)


def norm_title(title):
    """Collapse cosmetic variants so reposts map to one history key."""
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip(" -–—|•")


def history_key(job):
    return f"{job['company'].strip().lower()}::{norm_title(job['title'])}"


def load_history():
    if POSTING_HISTORY_FILE.exists():
        try:
            return json.loads(POSTING_HISTORY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("posting_history.json unreadable; starting fresh.")
    return {}


def save_history(history, today):
    pruned = {}
    for key, entry in history.items():
        ids = {i: d for i, d in entry.get("ids", {}).items()
               if _within_days(d, today, HISTORY_RETENTION_DAYS)}
        locs = {l: d for l, d in entry.get("locations", {}).items()
                if _within_days(d, today, HISTORY_RETENTION_DAYS)}
        id_locs = {i: l for i, l in entry.get("id_locs", {}).items() if i in ids}
        lw = entry.get("last_written")
        if ids or locs or (lw and _within_days(lw, today, HISTORY_RETENTION_DAYS)):
            pruned[key] = {"ids": ids, "locations": locs}
            if id_locs:
                pruned[key]["id_locs"] = id_locs
            if lw:
                pruned[key]["last_written"] = lw
    POSTING_HISTORY_FILE.write_text(json.dumps(pruned, indent=1, sort_keys=True))


def _within_days(datestr, today, days):
    try:
        return (today - datetime.strptime(datestr, "%Y-%m-%d").date()).days <= days
    except (ValueError, TypeError):
        return False


def record_sighting(history, job, today_str):
    key = history_key(job)
    entry = history.setdefault(key, {"ids": {}, "locations": {}})
    entry["ids"].setdefault(job["id"], today_str)
    loc = (job.get("location") or "").strip().lower() or "unspecified"
    entry["locations"].setdefault(loc, today_str)
    # Remember which location each ID was posted in, so a US + Canada twin
    # isn't mistaken for a repost. Filled in for every live ID on each run.
    entry.setdefault("id_locs", {})[job["id"]] = loc
    return key


def _days_since(datestr, today):
    try:
        return (today - datetime.strptime(datestr[:10], "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def _is_country_remote(loc):
    return bool(_COUNTRY_REMOTE_RE.match(loc or ""))


def assess_posting_health(history, key, today, job=None):
    """Returns (note_or_None, flag_evergreen, skip_entirely, repost_of_tracked_role).

    note can be set without flag_evergreen (an age heads-up for a posting
    open AGE_NOTE_DAYS+ days); flag_evergreen means set Posting Health."""
    job = job or {}
    entry = history.get(key, {}) if key else {}
    recent_ids = {i for i, d in entry.get("ids", {}).items()
                  if _within_days(d, today, REPOST_WINDOW_DAYS)
                  and not i.startswith("tracker-")}
    id_locs = entry.get("id_locs", {})
    per_loc = {}
    for i in recent_ids:
        if i in id_locs:  # IDs seen before this field existed can't be placed
            per_loc.setdefault(id_locs[i], set()).add(i)
    repost_ids = max((len(v) for v in per_loc.values()), default=0)
    spray_locs = sum(1 for l, d in entry.get("locations", {}).items()
                     if _within_days(d, today, HISTORY_WINDOW_DAYS)
                     and l != "unspecified" and not _is_country_remote(l))
    recently_written = _within_days(entry.get("last_written"), today, HISTORY_WINDOW_DAYS)

    reasons, flag = [], False
    if repost_ids >= GHOST_FLAG_IDS:
        flag = True
        reasons.append(f"reposted: {repost_ids} posting IDs for this title in the same "
                       f"location in the last {REPOST_WINDOW_DAYS} days")
    if spray_locs >= GHOST_FLAG_LOCATIONS:
        flag = True
        reasons.append(f"listed in {spray_locs} different locations")
    age = _days_since(job.get("published") or "", today)
    if age is not None and age >= EVERGREEN_AGE_DAYS:
        flag = True
        reasons.append(f"open {age} days (first published {job['published'][:10]})")
    m = _WORKDAY_REPOST_RE.search(job.get("url") or "")
    if m and int(m.group(1)) >= 2:
        flag = True
        reasons.append(f"Workday requisition re-posted (suffix -{m.group(1)})")
    if _PIPELINE_TITLE_RE.search(job.get("title") or ""):
        flag = True
        reasons.append("pipeline-style title (open call or several levels in one title)")

    note = None
    if flag:
        note = ("Evergreen pattern: " + "; ".join(reasons)
                + ". Often a resume-collector / pipeline posting; verify before investing time.")
    elif age is not None and age >= AGE_NOTE_DAYS:
        note = (f"Posting age: open {age} days (first published {job['published'][:10]}). "
                "Not flagged yet; worth confirming it's actively hiring.")
    return note, flag, repost_ids >= GHOST_SKIP_IDS, recently_written


def notify(title, message):
    """Desktop notification (macOS or Windows) plus a line in the data
    folder's alerts.jsonl for the tracker banner. Best effort -- never breaks the run."""
    import platform_support
    platform_support.notify(title, message, DATA_DIR)


APP_PROPERTY_IDS = {}   # name -> Notion property id, filled by check_notion_schema each run


def _filter_properties_url(url, names):
    """Append ?filter_properties=<id> for each named property, so a query
    returns only those (Oct 30, 2026: the tracked-posting scan used to pull
    every property of every row, snapshots included, five times a day)."""
    ids = [APP_PROPERTY_IDS.get(n) for n in names]
    if not all(ids):
        return url
    return url + "?" + "&".join(f"filter_properties={i}" for i in ids)


def check_notion_schema():
    """Confirm the Applications tracker still has every property we write.
    Returns False (and notifies) on drift; returns True on transient API
    trouble so a flaky network can't block the run."""
    if not NOTION_TOKEN:
        return True
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}",
               "Notion-Version": "2022-06-28"}
    try:
        resp = request_with_retry(
            requests.get, f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}",
            headers=headers, timeout=60)
    except requests.RequestException as e:
        logger.warning(f"Could not verify Notion schema (continuing): {e}")
        return True
    if resp.status_code >= 300:
        logger.warning(f"Schema check got {resp.status_code} (continuing).")
        return True
    schema_props = resp.json().get("properties", {})
    APP_PROPERTY_IDS.clear()
    APP_PROPERTY_IDS.update({name: prop.get("id") for name, prop in schema_props.items() if prop.get("id")})
    have = set(schema_props.keys())
    missing = [p for p in REQUIRED_APP_PROPERTIES if p not in have]
    if missing:
        msg = (f"Applications tracker is missing: {', '.join(missing)}. "
               "A property was likely renamed. Run aborted; nothing marked seen.")
        print(f"[error] {msg}", file=sys.stderr)
        notify("Job agent needs attention", msg)
        return False
    return True


FRESH_DAYS = _S("agent.FRESH_DAYS")   # the Three-Month Plan's freshness rule: apply to postings 14 days old or newer


def posting_age_days(job, history=None, today=None):
    """Days since the posting appeared, from the same source Posted Date uses;
    None when nothing is known."""
    today = today or datetime.now().date()
    posted = posted_date_properties(job, history, today).get("Posted Date", {}).get("date", {}).get("start")
    if not posted:
        return None
    try:
        return (today - date.fromisoformat(posted[:10])).days
    except ValueError:
        return None


def write_digest(new_matches, written_count, closed_count, ghost_skipped=(), extra_sections=None,
                 history=None, today=None):
    """Overwrite a small skimmable summary of the latest run. Tier C rows
    (hard-rule fails) are counted but not listed, so digests carry only
    actionable items. Freshest Tier A first, so new postings get seen early."""
    today = today or datetime.now().date()
    actionable = [m for m in new_matches if m[1]["tier"] in ("A", "B")]
    skipped_c = len(new_matches) - len(actionable)

    def age_label(job):
        age = posting_age_days(job, history, today)
        if age is None:
            return "posted date unknown"
        return f"posted {age} day{'s' if age != 1 else ''} ago" + (" (FRESH)" if age <= FRESH_DAYS else "")

    def sort_key(m):
        age = posting_age_days(m[0], history, today)
        return (m[1]["tier"], age if age is not None else 10_000, -m[1]["score"])
    lines = [f"# Latest job agent run - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             "",
             f"{len(new_matches)} new match(es), {written_count} written to Notion, "
             f"{closed_count} stale posting(s) closed, "
             f"{len(ghost_skipped)} skipped as likely ghost posting(s), "
             f"{skipped_c} auto-marked Skip or Tier C.", ""]
    for job, result, flag, salary_min in sorted(actionable, key=sort_key):
        salary = f" | ${salary_min:,.0f}+" if salary_min else " | no range posted"
        verdict = f" | {result['verdict']}" if result["verdict"] else ""
        lines.append(f"- **{job['title']}** at {job['company']} - Tier {result['tier']}, "
                     f"{result['score']}/100{salary}{verdict} | {age_label(job)}\n  {result['evidence'][:160]}\n  {job['url']}")
    if not actionable:
        lines.append("_No new Tier A or B matches this run._")
    if ghost_skipped:
        lines.append("\n## Skipped as likely ghost postings (not written to Notion)")
        for job, note in ghost_skipped:
            lines.append(f"- **{job['title']}** at {job['company']} - {note}\n  {job['url']}")
    for section in extra_sections or []:
        lines.append("")
        lines.append(section)
    lines.append("\nFull history: agent.log. Review in Notion: Applications → Triage queue view.")
    try:
        DIGEST_FILE.write_text("\n".join(lines))
    except OSError as e:
        logger.warning(f"Could not write digest file: {e}")


# ---------------------------------------------------------------------------
# TRACKER MAINTENANCE (fit scoring v2, 2026-10-20)
# Three passes that run after the fetch, all zero-token:
#   rescore_tracker     open rows not yet scored by RUBRIC_VERSION
#   refresh_open_rows   Last Verified + Posted Date on open rows
#   screen_candidates   probe ATS boards for companies in candidates.json
# Open = Status in OPEN_STATUSES. v3.3: the agent writes a fit label (Strong
# fit / Possible fit / Poor fit) on every open row; Applying and Passed are the
# user's and are never overwritten. A Label Reason the user wrote is kept as is.
# ---------------------------------------------------------------------------

OPEN_STATUSES = _S("agent.OPEN_STATUSES")
CANDIDATES_FILE = DATA_DIR / "candidates.json"
CANDIDATE_RESULTS_FILE = DATA_DIR / "candidate_results.json"
MACHINE_LABEL = re.compile(r"by (weekly triage|agent v\d|daily check-in|daily refresh)", re.I)
# Labels the daily research step (or this agent's own 48-hour rule) has
# already judged. A rescore keeps the verdict and the text and only refreshes
# the "Scored <date> by agent vX.Y." stamp inside it. Earlier the agent
# treated these as machine-written and replaced them, so the refresh
# re-screened the same rows every day and verdicts flip-flopped.
# Labels an earlier, retired capture process wrote: "<Verdict>: reason" with
# no machine stamp, on rows whose Notes say "Captured by recurring job
# search". Without this they read as the user's own call and their Ask
# survived every rescore.
LEGACY_NOTES = re.compile(r"Captured by recurring job search", re.I)
LEGACY_LABEL = re.compile(r"^\s*(Ask me first|Watch|Skip|Pursue later|Needs your OK)\s*:", re.I)


def is_legacy_machine_label(label, notes):
    return bool(label and LEGACY_LABEL.search(label) and LEGACY_NOTES.search(notes or ""))


SOFT_SKIP_LABEL = re.compile(r"^\s*(Skip|Poor fit) \(", re.I)   # v3.3: Skip for no pay, 2+ missing, or weak fit; stays open
SCREENED_LABEL = re.compile(r"Qualifications screened \d{4}-\d{2}-\d{2}|by daily refresh", re.I)   # v3.3: "No decision in 48 hours" labels are retired and get replaced
AGENT_STAMP = re.compile(r"\s*Scored \d{4}-\d{2}-\d{2} by agent v[\d.]+\.?", re.I)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def merge_label(existing_label, fresh_label):
    """Keep a screened label's text; replace the agent's own score stamp with
    the one from the fresh label (or append it)."""
    stamp = AGENT_STAMP.search(fresh_label)
    kept = AGENT_STAMP.sub("", existing_label or "").strip()
    return (kept + (stamp.group(0) if stamp else ""))[:1900]


OPEN_ROWS_CACHE = None   # list of open-row pages, fetched once per run (Oct 30, 2026)


def _prop_text(prop):
    t = prop.get("type")
    if t in ("rich_text", "title"):
        return "".join(x.get("plain_text", "") for x in (prop.get(t) or []))
    if t in ("select", "status"):
        return ((prop.get(t) or {}).get("name")) or ""
    if t == "url":
        return prop.get("url") or ""
    if t == "date":
        return ((prop.get("date") or {}).get("start")) or ""
    if t == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    return ""


def _matches_filter(page, flt):
    """Evaluate the subset of Notion's filter language the agent uses
    (and / or; select, status, rich_text, title, url, date with equals,
    does_not_equal, contains, does_not_contain, is_empty, is_not_empty)
    against a page payload. Anything else raises, so a new filter shape is
    noticed in tests rather than silently matching nothing."""
    if "and" in flt:
        return all(_matches_filter(page, f) for f in flt["and"])
    if "or" in flt:
        return any(_matches_filter(page, f) for f in flt["or"])
    name = flt["property"]
    kind = next(k for k in flt if k != "property")
    cond = flt[kind]
    prop = page.get("properties", {}).get(name, {"type": kind})
    value = _prop_text(prop)
    if "equals" in cond:
        return value == cond["equals"]
    if "does_not_equal" in cond:
        return value != cond["does_not_equal"]
    if "contains" in cond:
        return cond["contains"] in value
    if "does_not_contain" in cond:
        return cond["does_not_contain"] not in value
    if "is_empty" in cond:
        return (value == "") == bool(cond["is_empty"])
    if "is_not_empty" in cond:
        return (value != "") == bool(cond["is_not_empty"])
    raise ValueError(f"unsupported filter: {flt}")


def _write_to_read_shape(name, wprop):
    """Turn a property in write shape into the read shape the cache holds."""
    if "rich_text" in wprop:
        return {"type": "rich_text", "rich_text": [{"plain_text": x.get("text", {}).get("content", "")} for x in wprop["rich_text"]]}
    if "title" in wprop:
        return {"type": "title", "title": [{"plain_text": x.get("text", {}).get("content", "")} for x in wprop["title"]]}
    for t in ("select", "status", "date", "number", "url", "relation", "multi_select"):
        if t in wprop:
            return {"type": t, t: wprop[t]}
    return None


def _cache_apply_patch(page_id, properties):
    """Keep the open-row cache in step with a successful patch."""
    if not OPEN_ROWS_CACHE or not properties:
        return
    for page in OPEN_ROWS_CACHE:
        if page.get("id") == page_id:
            for name, wprop in properties.items():
                shaped = _write_to_read_shape(name, wprop)
                if shaped is not None:
                    page.setdefault("properties", {})[name] = shaped
            status = _prop_text(page.get("properties", {}).get("Status", {}))
            if status and status not in OPEN_STATUSES:
                OPEN_ROWS_CACHE.remove(page)
            return


def query_open_rows(extra_filter=None):
    """All Applications rows in an open status, full property payloads.
    Fetched from Notion once per run; later calls filter the cached rows
    locally, and patch_page / update_status keep the cache current."""
    global OPEN_ROWS_CACHE
    if not NOTION_TOKEN:
        return []
    if OPEN_ROWS_CACHE is not None:
        rows = OPEN_ROWS_CACHE
        return [p for p in rows if _matches_filter(p, extra_filter)] if extra_filter else list(rows)
    rows = _fetch_open_rows()
    if rows is not None:
        OPEN_ROWS_CACHE = rows
        return query_open_rows(extra_filter)
    return []


def _fetch_open_rows():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    flt = {"or": [{"property": "Status", "status": {"equals": s}} for s in OPEN_STATUSES]}
    payload, rows = {"filter": flt, "page_size": 100}, []
    while True:
        try:
            resp = request_with_retry(requests.post, url, headers=NOTION_HEADERS, json=payload, timeout=60)
        except requests.RequestException as e:
            logger.warning(f"Open-row query failed: {e}")
            return None   # partial results are not cached
        if resp.status_code >= 300:
            logger.warning(f"Open-row query failed: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        payload["start_cursor"] = data["next_cursor"]


def _row_company_page(props):
    rel = props.get("Company Profile", {}).get("relation", [])
    return rel[0]["id"] if rel else None


NO_SNAPSHOT_TAG = "NO SNAPSHOT"


def freshness_edge_days():
    """Ages (in days) at which a row's freshness points change, plus the day
    after as slack for a missed run. Rows at these ages get rescored even
    when their rubric version is current (v3.0)."""
    edges = [limit + 1 for limit, _, _ in fit_scoring.FRESHNESS_BANDS if limit is not None]
    return sorted({d for e in edges for d in (e, e + 1)})


def freshness_edge_filters(today):
    today = today or datetime.now().date()
    return [{"property": "Posted Date", "date": {"equals": (today - timedelta(days=d)).isoformat()}}
            for d in freshness_edge_days()]


def rescore_tracker(today, limit=150):
    """Score every open row whose Score Breakdown isn't from RUBRIC_VERSION,
    plus rows scored title-only that have since received a snapshot.
    Returns the number of rows updated."""
    rows = query_open_rows({"or": [
        {"property": "Score Breakdown", "rich_text": {"does_not_contain": fit_scoring.RUBRIC_VERSION}},
        {"property": "Score Breakdown", "rich_text": {"contains": NO_SNAPSHOT_TAG}},
        # Rows waiting on company research: rescored every run, so the score
        # moves the morning after the daily research step researches it (v3.2).
        {"property": "Score Breakdown", "rich_text": {"contains": fit_scoring.UNRESEARCHED_NOTE}},
    ] + freshness_edge_filters(today)})
    updated = 0
    for page in rows[:limit]:
        p = page.get("properties", {})
        snapshot = _rt(p, "Posting Snapshot")
        breakdown_now = _rt(p, "Score Breakdown")
        if NO_SNAPSHOT_TAG in breakdown_now and fit_scoring.RUBRIC_VERSION in breakdown_now and not snapshot:
            continue  # already scored title-only and still no text; nothing new
        updated += rescore_page(page, today)
    return updated


def _row_age_days(props, today=None):
    """Days since the row's Posted Date; None when blank or unparseable."""
    posted = _date(props, "Posted Date")
    if not posted:
        return None
    try:
        return ((today or datetime.now().date()) - date.fromisoformat(posted[:10])).days
    except ValueError:
        return None


def cap_kept_poor_fit(props, result):
    """v3.8: when the daily refresh screen's Poor fit
    stands, the written score and tier follow it, so the row can't read
    9 and Poor fit at once. The refresh read
    requirements the stored snapshot can be missing."""
    cap = fit_scoring.MIN_CAP_TWO
    if result["score"] <= cap:
        return
    props["Role Fit Score"] = {"number": round(cap / 10, 1)}
    props["Research Tier"] = {"select": {"name": fit_scoring.TIER_NAMES["C"]}}
    text = props["Score Breakdown"]["rich_text"][0]["text"]["content"]
    props["Score Breakdown"]["rich_text"][0]["text"]["content"] = (
        text + f" Score capped at {cap}: Poor fit kept from the daily refresh screen.")[:1900]


def rescore_page(page, today):
    """Score one open row from its stored fields and patch it. the user's
    verdicts and labels are never overridden. Returns 1 if patched."""
    p = page.get("properties", {})
    title = _title(p, "Role")
    company_name = _rt(p, "Company")
    snapshot = clean_posting_text(_rt(p, "Posting Snapshot"))  # older captures are HTML-escaped
    salary = p.get("Base Salary", {}).get("number")
    evergreen = _sel(p, "Posting Health") == "Suspected evergreen"
    company_page_id = _row_company_page(p)
    profile = fetch_company_profile(company_page_id) if company_page_id else {}
    result = fit_scoring.score_posting(title, snapshot, salary_min=salary, company=profile,
                                       company_name=company_name or profile.get("name", ""),
                                       evergreen=evergreen, today=today,
                                       remote_hint=_sel(p, "Remote Status") == "Fully Remote",
                                       age_days=_row_age_days(p, today))
    existing_verdict = _sel(p, "Overall Verdict")
    if not snapshot and result["verdict"] == "Poor fit" and not (
            result.get("hard_skip") and any(r.startswith(("Base", "Company", "Title", "Weak", "One Weak"))
                                            for r in result["reasons"])):
        # Without the posting text the work-type match is title-only and pay
        # can't be read, so don't Skip on text we never saw: the user's call.
        result["verdict"], result["hard_skip"], result["skip_why"] = "Possible fit", False, None
    if existing_verdict == "Applying" and result["tier"] != "A":
        # Anything the user is applying to gets full information every run,
        # whatever the score says.
        result["tier"] = "A"
        result["breakdown"] = (result["breakdown"] + " Tier raised to A: Applying.")[:1900]
    props = scoring_properties(result, today)
    existing_label = _rt(p, "Label Reason")
    human_set = (existing_verdict and existing_label and not MACHINE_LABEL.search(existing_label)
                 and not is_legacy_machine_label(existing_label, _rt(p, "Notes")))
    if existing_verdict in fit_scoring.HUMAN_VERDICTS:
        # The user's decision stands (Applying or Passed). Keep their verdict
        # and their reason; still record the new score, tier, and evidence.
        props.pop("Overall Verdict", None)
        props.pop("Label Reason", None)
    elif human_set:
        # v3.3: a reason the user wrote is kept, but the row still gets an
        # agent verdict (Watch, Ask me first, and Watch (no decision) are retired).
        props.pop("Label Reason", None)
    elif SCREENED_LABEL.search(existing_label or ""):
        # The daily refresh already screened this row against the posting's
        # stated minimums: keep its text and refresh the agent stamp. Its
        # Your call or Skip stands (it read the qualifications); anything
        # else (a retired label, Apply, blank) gets the agent's verdict.
        props["Label Reason"] = {"rich_text": [{"text": {"content": merge_label(
            existing_label, props["Label Reason"]["rich_text"][0]["text"]["content"])}}]}
        if existing_verdict in ("Possible fit", "Poor fit"):
            props.pop("Overall Verdict", None)
        if existing_verdict == "Poor fit":
            cap_kept_poor_fit(props, result)
    if not snapshot:
        # Without the posting text the work-type match is title-only; say so.
        props["Score Breakdown"]["rich_text"][0]["text"]["content"] = (
            NO_SNAPSHOT_TAG + " (title-only score; refresh fills it). " + result["breakdown"])[:1900]
    if _sel(p, "Domain Tier"):
        props.pop("Domain Tier", None)  # already assigned, don't churn it
    if patch_page(page["id"], props):
        if company_page_id:
            company_tier_update(company_page_id, profile, result["tier"])
            ensure_company_icon(company_page_id, profile)
        return 1
    return 0


def refresh_open_rows(all_jobs, history, today):
    """For open rows whose posting is in today's fetch: stamp Last Verified,
    backfill Posting Snapshot when empty (rows created another way
    or by hand have none), and backfill Posted Date where empty. Returns
    (verified, dated)."""
    by_key = {}
    for job in all_jobs:
        k = posting_key(job.get("url"))
        if k:
            by_key.setdefault(k, job)
    verified = dated = 0
    today_iso = today.isoformat()
    for page in query_open_rows():
        p = page.get("properties", {})
        url = p.get("Job Posting", {}).get("url")
        job = by_key.get(posting_key(url)) if url else None
        props = {}
        if job:
            # Oct 29, 2026: stamp Last Verified every VERIFY_STAMP_DAYS days,
            # not daily. A daily stamp was one PATCH per open row per run for
            # information nothing reads at day resolution; the stamp still
            # rides along free whenever another field on the row changes.
            last_verified = _date(p, "Last Verified")
            days_ago = _days_since(last_verified, today) if last_verified else None
            if days_ago is None or days_ago >= VERIFY_STAMP_DAYS:
                props["Last Verified"] = {"date": {"start": today_iso}}
            stored = _rt(p, "Posting Snapshot")
            snap = make_snapshot(job.get("description", ""))
            if snapshot_is_stale(stored, snap):
                props["Posting Snapshot"] = {"rich_text": snapshot_rich_text(snap)}
                if stored:
                    # Force a rescore on the new text: rescore_tracker picks up any
                    # breakdown that doesn't carry the current RUBRIC_VERSION.
                    props["Score Breakdown"] = {"rich_text": [{"text": {"content":
                        SNAPSHOT_REFRESHED_TAG + " " + today_iso + "; rescore pending."}}]}
            if p.get("Base Salary", {}).get("number") is None:
                s = extract_salary_min(job.get("salary_text", ""), job.get("description", ""))
                if s:
                    props["Base Salary"] = {"number": s}
                    props["Pay Basis"] = {"select": {"name": "Base"}}
        if not _date(p, "Posted Date"):
            if job:
                props.update(posted_date_properties(job, history, today))
            else:
                # Not on a board we fetch: fall back to the first day the
                # history file saw this company+title, if it ever did.
                pseudo = {"company": _rt(p, "Company"), "title": _title(p, "Role")}
                props.update(posted_date_properties(pseudo, history, today))
        if job and props and "Last Verified" not in props and _date(p, "Last Verified") != today_iso:
            props["Last Verified"] = {"date": {"start": today_iso}}   # free: the row is being patched anyway
        if props and patch_page(page["id"], props):
            verified += "Last Verified" in props
            dated += "Posted Date" in props
    return verified, dated


VERIFY_STAMP_DAYS = 3   # Oct 29, 2026: Last Verified is re-stamped when it is this many days old


def list_your_call_rows():
    """Open rows at Your call, best score first, for the Sunday digest (v3.3;
    replaces the 48-hour rule and the Watch (no decision) list)."""
    rows = query_open_rows({"property": "Overall Verdict", "select": {"equals": "Possible fit"}})
    out = []
    for page in rows:
        p = page.get("properties", {})
        score = (p.get("Role Fit Score") or {}).get("number")
        out.append((_rt(p, "Company"), _title(p, "Role"), score if score is not None else "?"))
    return sorted(out, key=lambda r: -(r[2] if isinstance(r[2], (int, float)) else 0))


def close_skipped_rows(today):
    """Hard-rule Skips and the user's Passed are decided; move them to Closed so
    they stop counting as open, stop getting liveness checks, and leave the
    Triage views. New hard-rule fails are written Closed directly
    (write_to_notion). v3.3: a soft Skip (no pay, 2+ missing minimums, weak
    fit; label starts "Skip (") stays open; the tracker's main view hides them."""
    rows = query_open_rows({"or": [{"property": "Overall Verdict", "select": {"equals": "Poor fit"}},
                                   {"property": "Overall Verdict", "select": {"equals": "Passed"}}]})
    closed = 0
    for page in rows:
        p = page.get("properties", {})
        if _sel(p, "Overall Verdict") == "Poor fit" and SOFT_SKIP_LABEL.search(_rt(p, "Label Reason") or ""):
            continue
        if update_status(page["id"], "Closed"):
            closed += 1
    return closed


def migrate_verdict_names(today):
    """One-time carry-over (fit scoring v3.6):
    every row, open or closed, whose Overall Verdict still has an old name
    gets the new one (fit_scoring.OLD_VERDICTS). The user's Pursue and Pass
    become Applying and Passed, so nothing they decided is lost. Runs every morning
    but matches nothing once done. Returns the number of rows converted."""
    if not NOTION_TOKEN:
        return 0
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    flt = {"or": [{"property": "Overall Verdict", "select": {"equals": old}}
                  for old in fit_scoring.OLD_VERDICTS]}
    payload, converted = {"filter": flt, "page_size": 100}, 0
    while True:
        try:
            resp = request_with_retry(requests.post, url, headers=NOTION_HEADERS, json=payload, timeout=60)
        except requests.RequestException as e:
            print(f"[warn] Verdict-name query failed: {e}", file=sys.stderr)
            return converted
        if resp.status_code >= 300:
            return converted
        data = resp.json()
        for page in data.get("results", []):
            old = _sel(page.get("properties", {}), "Overall Verdict")
            new = fit_scoring.OLD_VERDICTS.get(old)
            if new and patch_page(page["id"], {"Overall Verdict": {"select": {"name": new}}}):
                converted += 1
        if not data.get("has_more"):
            return converted
        payload["start_cursor"] = data.get("next_cursor")


def migrate_needs_your_ok(today):
    """One-time cleanup: the retired Companies verdict 'Needs your OK' was
    written by an earlier triage routine and refused by the risk research
    routine, so companies sat in it. Convert to 'Watch list' and keep the
    reason. Runs every morning but matches nothing once done."""
    if not NOTION_TOKEN:
        return 0
    url = f"https://api.notion.com/v1/databases/{NOTION_COMPANIES_DATABASE_ID}/query"
    payload = {"filter": {"property": "Verdict", "select": {"equals": "Needs your OK"}}, "page_size": 100}
    converted = 0
    while True:
        try:
            resp = request_with_retry(requests.post, url, headers=NOTION_HEADERS, json=payload, timeout=60)
        except requests.RequestException as e:
            logger.warning(f"Needs-your-OK query failed: {e}")
            return converted
        if resp.status_code >= 300:
            return converted
        data = resp.json()
        for page in data.get("results", []):
            p = page.get("properties", {})
            reason = _rt(p, "Verdict Reason")
            note = f"(was Needs your OK; converted to Watch list {today.isoformat()})"
            new_reason = (reason + " " + note).strip() if reason else note
            if patch_page(page["id"], {"Verdict": {"select": {"name": "Watch list"}},
                                       "Verdict Reason": {"rich_text": [{"text": {"content": new_reason[:1900]}}]}}):
                converted += 1
        if not data.get("has_more"):
            return converted
        payload["start_cursor"] = data["next_cursor"]


REPAIRS_FILE = DATA_DIR / "repairs_done.json"
EEO_REPAIR_NAME = "eeo_closed_rows_v4.1"


def _repairs_done():
    try:
        return json.loads(REPAIRS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def repair_eeo_closed_rows(today, apply=True):
    """One-time repair (fit scoring v4.1). Before v4.1 a rule word inside the
    equal-opportunity statement ("... military or veteran status ...") could
    fail a hard rule, so the row was written Closed on arrival and never shown.
    Finds Closed rows the user never applied to or decided on, re-reads each
    stored posting both ways, and reopens a row (Status Interested, rescored)
    only when the old reading failed a hard rule and the new one doesn't.
    Runs on the first full run after the update, then records itself in
    repairs_done.json and never runs again. apply=False only lists.
    Returns the list of (company, role) reopened (or that would be)."""
    if not NOTION_TOKEN or _repairs_done().get(EEO_REPAIR_NAME):
        return []
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    flt = {"and": [{"property": "Status", "status": {"equals": "Closed"}},
                   {"property": "Date Applied", "date": {"is_empty": True}}]}
    payload, rows = {"filter": flt, "page_size": 100}, []
    while True:
        try:
            resp = request_with_retry(requests.post, url, headers=NOTION_HEADERS, json=payload, timeout=60)
        except requests.RequestException as e:
            logger.warning(f"EEO repair query failed: {e}")
            return []
        if resp.status_code >= 300:
            logger.warning(f"EEO repair query failed: {resp.status_code}")
            return []
        data = resp.json()
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    reopened = []
    for page in rows:
        p = page.get("properties", {})
        if _sel(p, "Overall Verdict") in fit_scoring.HUMAN_VERDICTS:
            continue   # the user's own decision stands
        snapshot = clean_posting_text(_rt(p, "Posting Snapshot"))
        if not snapshot:
            continue
        title, company_name = _title(p, "Role"), _rt(p, "Company")
        salary = p.get("Base Salary", {}).get("number")
        remote = _sel(p, "Remote Status") == "Fully Remote"
        old, _ = fit_scoring.hard_screen(title, snapshot, salary_min=salary, remote_hint=remote,
                                         company_name=company_name, eeo_aware=False)
        new, _ = fit_scoring.hard_screen(title, snapshot, salary_min=salary, remote_hint=remote,
                                         company_name=company_name)
        if old != "skip" or new == "skip":
            continue
        reopened.append((company_name, title))
        if apply:
            rescore_page(page, today)
            update_status(page["id"], "Interested")
    if apply and not run_stats.DRY_RUN:
        done = _repairs_done()
        done[EEO_REPAIR_NAME] = {"date": today.isoformat(), "reopened": len(reopened)}
        REPAIRS_FILE.write_text(json.dumps(done, indent=2))
    return reopened


ROLE_TITLE_RE = _S("agent.ROLE_TITLE_RE")
ROLE_BAD_RE = _S("agent.ROLE_BAD_RE")


def screen_candidates(today):
    """For each company in candidates.json ({name: {slugs: [...], page_id: ...}}),
    probe greenhouse/ashby/lever with the slug guesses and record what's live.
    Writes candidate_results.json and updates the Companies row (ATS, Job
    Board URL, Monitoring). Returns a digest section or None. A company drops
    out of candidates.json once it has been screened, so this costs nothing
    on later runs. The slug trap applies: a probe can hit the wrong company,
    so the ATS field says 'unverified' until the sample titles are checked."""
    if not CANDIDATES_FILE.exists():
        return None
    try:
        candidates = json.loads(CANDIDATES_FILE.read_text())
    except (OSError, ValueError) as e:
        logger.warning(f"candidates.json unreadable: {e}")
        return None
    if not candidates:
        return None
    results = json.loads(CANDIDATE_RESULTS_FILE.read_text()) if CANDIDATE_RESULTS_FILE.exists() else {}
    lines = ["## Candidate company screen (zero-token ATS probe)"]
    remaining = {}
    for name, spec in candidates.items():
        rec = {"ats": None, "slug": None, "total": 0, "pm": [], "sample": [], "screened": today.isoformat()}
        for platform in ("greenhouse", "ashby", "lever"):
            for slug in spec.get("slugs", []):
                try:
                    jobs = FETCHERS[platform](slug)
                except Exception:
                    jobs = []
                if jobs:
                    rec.update(ats=platform, slug=slug, total=len(jobs),
                               sample=[j.get("title", "") for j in jobs[:4]])
                    for j in jobs:
                        t = j.get("title", "")
                        if ROLE_TITLE_RE.search(t) and not ROLE_BAD_RE.search(t):
                            rec["pm"].append({"title": t, "location": j.get("location", ""),
                                              "url": j.get("url", ""), "published": j.get("published", "")})
                    break
            if rec["ats"]:
                break
        results[name] = rec
        page_id = spec.get("page_id")
        if page_id:
            if rec["ats"]:
                board = {"greenhouse": f"https://boards.greenhouse.io/{rec['slug']}",
                         "ashby": f"https://jobs.ashbyhq.com/{rec['slug']}",
                         "lever": f"https://jobs.lever.co/{rec['slug']}"}[rec["ats"]]
                ats_text = (f"{rec['ats']} / {rec['slug']} (unverified probe {today.isoformat()}: "
                            f"{rec['total']} postings, {len(rec['pm'])} PM; sample: "
                            + "; ".join(rec["sample"][:3]) + ")")
                props = {"ATS": {"rich_text": [{"text": {"content": ats_text[:1900]}}]},
                         "Job Board URL": {"url": board},
                         "Monitoring": {"select": {"name": "MANUAL CHECK NEEDED"}}}
            else:
                props = {"ATS": {"rich_text": [{"text": {"content":
                         f"No greenhouse/ashby/lever board found for slugs {spec.get('slugs')} on {today.isoformat()}; custom portal or other ATS. Manual check."}}]},
                         "Monitoring": {"select": {"name": "MANUAL CHECK NEEDED"}}}
            if not patch_page(page_id, props):
                remaining[name] = spec  # retry next run
        if rec["ats"]:
            pm_lines = "".join(f"\n    - {j['title']} ({j['location']}) {j['url']}" for j in rec["pm"][:6])
            lines.append(f"- **{name}**: {rec['ats']} / {rec['slug']}, {rec['total']} postings, "
                         f"{len(rec['pm'])} PM-titled. Sample: {'; '.join(rec['sample'][:3])}{pm_lines}")
        else:
            lines.append(f"- **{name}**: no board found on greenhouse/ashby/lever (slugs tried: "
                         f"{', '.join(spec.get('slugs', []))}). Manual check.")
    try:
        CANDIDATE_RESULTS_FILE.write_text(json.dumps(results, indent=2))
        CANDIDATES_FILE.write_text(json.dumps(remaining, indent=2))
    except OSError as e:
        logger.warning(f"Could not save candidate results: {e}")
    lines.append("\nVerify sample titles before adding a slug to CONFIRMED_COMPANIES (wrong-company trap).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LEAD RESOLUTION (LinkedIn cards -> the company's own posting, zero tokens)
# First of two passes: board lookup here, web lookup in the daily research
# step for whatever is left. See
# lead_resolver.py for the matching rules.
# ---------------------------------------------------------------------------

def _prefer_us_remote(job):
    return location_rejection_reason(job.get("location", "")) is None


def resolve_linkedin_leads(all_jobs, seen, today):
    """Before scoring: swap each new LinkedIn lead for the same role on the
    company's own board when it is there, drop leads whose role is already in
    today's fetch, and stamp the rest for the refresh's web lookup.
    Returns (all_jobs, summary line or None, ids to mark seen)."""
    leads = [j for j in all_jobs if j.get("source") == "LinkedIn"]
    if not leads:
        return all_jobs, None, set()
    others = [j for j in all_jobs if j.get("source") != "LinkedIn"]
    index = lead_resolver.build_index(others)
    cache = lead_resolver.load_board_cache()
    kept, dropped, counts = [], set(), Counter()
    for lead in leads:
        if lead["id"] in seen or get_rejection_reason(lead):
            kept.append(lead)  # main() skips or rejects it as before; no lookup spent
            continue
        r = lead_resolver.resolve(lead["company"], lead["title"], index=index, today=today,
                                  prefer=_prefer_us_remote, cache=cache)
        counts[r["status"]] += 1
        if r["status"] == "in_run":
            dropped.add(lead["id"])  # the board copy is in all_jobs and wins
            logger.info("LinkedIn lead %r @ %r is in today's fetch; board copy wins", lead["title"], lead["company"])
            continue
        if r["status"] == "swapped":
            lead_resolver.apply_match(lead, r["job"])
            if r["company"]:
                lead["company"] = r["company"]  # the board's canonical name, e.g. Harborline not Harborline, Inc
            lead["notes_extra"] = f"{r['note']} {SCORED_ON_TEXT} {today}."  # scored on the text at write time
        else:
            lead["notes_extra"] = r["note"]
        kept.append(lead)
    lead_resolver.save_board_cache(cache)
    unresolved = counts["none"] + counts["no_board"]
    summary = (f"LinkedIn leads: {sum(counts.values())} new card(s) looked up; {counts['in_run']} already in today's "
               f"fetch, {counts['swapped']} swapped for the company's own posting, {counts['ambiguous']} ambiguous, "
               f"{unresolved} without a board match (daily refresh does the web lookup).")
    return others + kept, summary, dropped


def resolve_tracked_leads(today, limit=25):
    """Maintenance pass for LinkedIn rows already in the tracker with no
    posting text and no Board lookup stamp: same board lookup, then patch the
    row with the board posting's text, salary, date, and (unless the user has
    labelled the row) URL, and rescore it on the spot. Returns the number of
    rows resolved."""
    rows = query_open_rows({"and": [
        {"property": "Source", "select": {"equals": "LinkedIn"}},
        {"property": "Posting Snapshot", "rich_text": {"is_empty": True}},
        {"property": "Notes", "rich_text": {"does_not_contain": lead_resolver.BOARD_STAMP}},
    ]})
    if not rows:
        return 0
    cache = lead_resolver.load_board_cache()
    resolved = 0
    for page in rows[:limit]:
        p = page.get("properties", {})
        title, company = _title(p, "Role"), _rt(p, "Company")
        company_page_id = _row_company_page(p)
        profile = fetch_company_profile(company_page_id) if company_page_id else {}
        r = lead_resolver.resolve(company, title, today=today, prefer=_prefer_us_remote, cache=cache,
                                  job_board_url=profile.get("job_board_url"), website=profile.get("website"))
        notes = (_rt(p, "Notes") + " " + r["note"]).strip()
        props = {"Notes": {"rich_text": [{"text": {"content": notes[:1900]}}]}}
        job = r["job"]
        canonical = r.get("company")
        if job and canonical and canonical != company:
            # The board knows this company under its tracked name ("Harborline",
            # not "Harborline, Inc"); point the row at that Companies page.
            canon_id = find_company_page(canonical)
            if canon_id:
                props["Company"] = {"rich_text": [{"text": {"content": canonical[:200]}}]}
                props["Company Profile"] = {"relation": [{"id": canon_id}]}
        if job:
            snap = make_snapshot(job.get("description", ""))
            if snap:
                props["Posting Snapshot"] = {"rich_text": snapshot_rich_text(snap)}
            if p.get("Base Salary", {}).get("number") is None:
                s = extract_salary_min(job.get("salary_text", ""), job.get("description", ""))
                if s:
                    props["Base Salary"] = {"number": s}
                    props["Pay Basis"] = {"select": {"name": "Base"}}
            if _sel(p, "Posted Date Source") in (None, "Board approximate", "First seen by agent"):
                props.update(posted_date_properties(job, None, today))
            remote_status = remote_status_for(job)
            if remote_status and not _sel(p, "Remote Status"):
                props["Remote Status"] = {"select": {"name": remote_status}}
            props["Last Verified"] = {"date": {"start": today.isoformat()}}
            existing_verdict = _sel(p, "Overall Verdict")
            human_set = existing_verdict and not MACHINE_LABEL.search(_rt(p, "Label Reason") or "")
            if job.get("url") and not human_set:
                # Point the row at the company's posting; the LinkedIn link is kept in Notes.
                li = p.get("Job Posting", {}).get("url") or ""
                li_host = (urlparse(li).hostname or "").lower() if li else ""
                if li_host in ("linkedin.com", "www.linkedin.com") and "LinkedIn alert" not in notes:
                    props["Notes"]["rich_text"][0]["text"]["content"] = (notes + f" LinkedIn alert link: {li}")[:1900]
                props["Job Posting"] = {"url": job["url"]}
            elif job.get("url"):
                props["Notes"]["rich_text"][0]["text"]["content"] = (notes + f" Company posting: {job['url']}")[:1900]
        if patch_page(page["id"], props) and job:
            resolved += 1
    lead_resolver.save_board_cache(cache)
    return resolved


SCORED_ON_TEXT = "Scored on board text"


def rescore_board_matched(today, limit=40):
    """Rows whose LinkedIn card was matched to a board posting but whose score
    is still the title-only one: score them on the real text now, and stamp
    Notes so it happens once. Runs right after resolve_tracked_leads, so a
    match lands with a real score the same morning."""
    rows = query_open_rows({"and": [
        {"property": "Notes", "rich_text": {"contains": lead_resolver.BOARD_STAMP + ": matched"}},
        {"property": "Notes", "rich_text": {"does_not_contain": SCORED_ON_TEXT}},
    ]})
    rescored = 0
    for page in rows[:limit]:
        p = page.get("properties", {})
        if not _rt(p, "Posting Snapshot"):
            continue
        if rescore_page(page, today):
            notes = (_rt(p, "Notes") + f" {SCORED_ON_TEXT} {today}.").strip()
            patch_page(page["id"], {"Notes": {"rich_text": [{"text": {"content": notes[:1900]}}]}})
            rescored += 1
    return rescored


def _job_id_from_url(url):
    """The trailing posting id in a board URL (Greenhouse numeric id, Ashby or
    Lever uuid), lowercased; '' when there isn't one."""
    m = re.search(r"/jobs/(\d+)|/([0-9a-f]{8}-[0-9a-f-]{8,})", url or "", re.I)
    return (m.group(1) or m.group(2) or "").lower() if m else ""


def find_board_posting(url, title):
    """The full board posting a row's Job Posting URL points at: matched by
    posting id first, then by title. None when the board has no such job."""
    board = lead_resolver.board_from_url(url)
    if not board:
        return None
    jobs = lead_resolver.fetch_board(*board)
    want = _job_id_from_url(url)
    if want:
        for j in jobs:
            if want in (j.get("url", "") + " " + str(j.get("id", ""))).lower():
                return j
    status, job, _ = lead_resolver.best_match(title, jobs)
    return job if status in ("exact", "unique") else None


def refetch_board_text(today, limit=40):
    """v3.4 (found on a row scored from a short paraphrase).
    A row whose Job Posting is a Greenhouse, Ashby, or Lever posting but which
    was never scored on that posting's own text (a LinkedIn lead matched by the
    daily research step's web lookup, whose Posting Snapshot is a short
    paraphrase): fetch the full description from the board, replace the
    snapshot when the board text is longer, rescore, and stamp Notes once.
    That row scored 59 on the paraphrase and 88 on the full text."""
    rows = query_open_rows({"and": [
        {"property": "Notes", "rich_text": {"does_not_contain": SCORED_ON_TEXT}},
        {"or": [
            {"property": "Source", "select": {"equals": "LinkedIn"}},
            {"property": "Notes", "rich_text": {"contains": lead_resolver.WEB_STAMP}},
        ]},
    ]})
    done = 0
    for page in rows:
        if done >= limit:
            break
        p = page.get("properties", {})
        url = p.get("Job Posting", {}).get("url") or ""
        if not lead_resolver.board_from_url(url):
            continue
        job = find_board_posting(url, _title(p, "Role"))
        if not job:
            continue
        fresh = make_snapshot(job.get("description", ""))
        stored = _rt(p, "Posting Snapshot")
        props = {}
        if fresh and len(fresh) > len(stored or "") * 1.2:
            props["Posting Snapshot"] = {"rich_text": snapshot_rich_text(fresh)}
            # rescore_page reads the page dict, so give it the new text too
            p["Posting Snapshot"] = {"rich_text": [{"plain_text": fresh, "text": {"content": fresh}}]}
        if p.get("Base Salary", {}).get("number") is None:
            sal = extract_salary_min(job.get("salary_text", ""), job.get("description", ""))
            if sal:
                props["Base Salary"] = {"number": sal}
                props["Pay Basis"] = {"select": {"name": "Base"}}
                p["Base Salary"] = {"number": sal}
        notes = (_rt(p, "Notes") + f" {SCORED_ON_TEXT} {today}.").strip()
        props["Notes"] = {"rich_text": [{"text": {"content": notes[:1900]}}]}
        if patch_page(page["id"], props):
            rescore_page(page, today)
            done += 1
    return done


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def _settings_update():
    """After a kit update, bring an older settings folder forward (a backup is
    taken first). Never stops the run."""
    try:
        import kit_settings
        import backup as kit_backup
        changes, warning = kit_settings.migrate(backup=lambda: kit_backup.backup(tag="before-settings-update"))
        for c in changes:
            print(f"Settings updated: {c}")
        if warning:
            print(f"[warn] {warning}", file=sys.stderr)
    except Exception as e:   # a settings problem shows up in the run that needs the setting
        print(f"[warn] settings update check failed: {type(e).__name__}: {e}", file=sys.stderr)


NETCHECK_URLS = _S("agent.NETCHECK_URLS", default=["https://boards-api.greenhouse.io/v1/boards",
                                                 "https://api.ashbyhq.com/posting-api/job-board",
                                                 "https://remotive.com/api/remote-jobs"])
FULL_RUN_MAX_AGE_HOURS = 26   # a quick run with no full run this recent becomes the full run


def network_ok(urls=NETCHECK_URLS, timeout=10):
    """True when any probe answers (any HTTP status counts). v4.0: a run on a
    laptop that just woke with no Wi-Fi used to spend an hour timing out
    board by board; now it stops here and the next scheduled run tries again."""
    for url in urls:
        try:
            requests.get(url, headers={"User-Agent": _ks_user_agent()}, timeout=timeout)
            return True
        except requests.RequestException:
            continue
    return False


def hours_since_last_full_run():
    """Hours since the newest non-dry full run in run_stats, or None if none in 7 days."""
    try:
        runs = [r for r in run_stats.read_recent(7) if r.get("run") == "full" and not r.get("dry_run")]
    except Exception:   # noqa: BLE001
        return None
    if not runs:
        return None
    last = datetime.fromisoformat(runs[-1]["ts"])
    return (datetime.now() - last).total_seconds() / 3600


def fetch_all_sources():
    """Every source at once (v4.0), results concatenated in source order so
    the first-occurrence dedupe keeps the company's own ATS URL: company
    boards, then feeds, then the title-only LinkedIn leads. Remotive and
    RemoteOK first, as before."""
    sources = [("Remotive", fetch_remotive), ("RemoteOK", fetch_remoteok),
               ("company boards", fetch_all_confirmed), ("feeds", fetch_board_feeds),
               ("LinkedIn alerts", fetch_linkedin_alerts)]
    # company boards and feeds run their own inner pools, so the outer budget
    # is generous; each inner source still has its own budget.
    results = run_concurrently(sources, workers=len(sources), budget=600, label="source")
    all_jobs = []
    for name, _fn in sources:
        jobs, seconds, err = results[name]
        if err is not None:
            print(f"[warn] {name} failed: {err}", file=sys.stderr)
            continue
        all_jobs.extend(jobs or [])
        STATS.extra.setdefault("source_seconds", {})[name] = seconds
    return all_jobs


def main(quick=False):
    """quick=True (the daytime --quick runs, Oct 25, 2026): fetch, write new
    rows, and send fresh Tier A alerts, then stop. Tracker maintenance, the
    digest file, and the market snapshot stay with the 8am full run.
    v4.0 (Nov 7, 2026): a quick run that finds no full run in the last
    FULL_RUN_MAX_AGE_HOURS (the laptop slept through 8am) runs as the full run
    instead, so the digest, rescoring, and stale-close never skip a day."""
    if quick and not run_stats.DRY_RUN:
        age = hours_since_last_full_run()
        if age is None or age > FULL_RUN_MAX_AGE_HOURS:
            print(f"\nNo full run in the last {FULL_RUN_MAX_AGE_HOURS} hours"
                  f"{'' if age is None else f' ({age:.0f}h ago)'}; running the full run instead of a quick one.")
            quick = False
    print(f"\n=== {'Quick run' if quick else 'Run'} started {datetime.now().isoformat(timespec='seconds')} ===")
    _settings_update()
    sys.stdout.flush()
    if not network_ok():
        print("[warn] no network (none of the probe hosts answered); run skipped, the next scheduled run retries.", file=sys.stderr)
        return
    if not check_notion_schema():
        return
    today = datetime.now().date()
    today_str = today.isoformat()
    seen = load_seen()
    history = load_history()
    STATS.reset()
    global OPEN_ROWS_CACHE
    OPEN_ROWS_CACHE = None
    if run_stats.DRY_RUN:
        print("DRY RUN: Notion writes are recorded to dry_run_writes.jsonl, not sent.")
    # Company boards before the feeds, so a posting seen on both keeps the
    # company's own ATS URL (first occurrence wins the dedupe below).
    # LinkedIn alert leads go last of all: they carry no description, so a
    # copy of the same role from the company's own board should win.
    with STATS.stage("fetch"):
        all_jobs = fetch_all_sources()
    print(f"Fetched {len(all_jobs)} total postings.")
    sys.stdout.flush()
    STATS.extra["fetched"] = len(all_jobs)
    # LinkedIn cards are title-only; trade each for the company's own posting
    # when the board has it (zero tokens), before anything is scored.
    with STATS.stage("linkedin_leads"):
        all_jobs, lead_summary, lead_dupes = resolve_linkedin_leads(all_jobs, seen, today)
    if lead_summary:
        print(lead_summary)
    seen.update(lead_dupes)

    with STATS.stage("tracked_keys"):
        tracked_keys = fetch_tracked_posting_keys()
    STATS.stages["score_and_write"] = None   # filled below
    _t_score = __import__("time").time()
    new_matches = []
    written_matches = []
    ghost_skipped = []
    written_count = 0
    already_tracked = 0
    seen_company_title = set()
    for job in all_jobs:
        # History sees every PM-titled posting, including ones the location
        # filter rejects: the city-sprayed variants of a remote role are
        # exactly the evergreen signal we're counting.
        key = None
        if job["company"].strip() and matches_title(job["title"]):
            key = record_sighting(history, job, today_str)
        if job["id"] in seen:
            continue
        reason = get_rejection_reason(job)
        if reason:
            logger.debug("Rejected %r @ %r: %s", job["title"], job["company"], reason)
            seen.add(job["id"])
            continue
        _legacy_score, flag, salary_min = score_job(job)
        if flag == "Excluded":
            seen.add(job["id"])
            continue  # never surface hard-excluded postings at all

        dedupe_key = (job["company"].strip().lower(),
                      re.sub(r"\s+", " ", job["title"].strip().lower()))
        if dedupe_key in seen_company_title:
            seen.add(job["id"])
            continue  # same role from a different source -- one Notion row, not two
        seen_company_title.add(dedupe_key)

        if tracked_keys is not None and (
                posting_key(job["url"]) in tracked_keys
                or (job["company"].strip().lower(), norm_title(job["title"])) in TRACKED_TITLE_PAIRS):
            # Already a row in the tracker (any status, including Closed and
            # Rejected), by URL or by company + title; don't bring it back as
            # a new Interested row.
            logger.info("Already tracked, not re-adding: %r @ %r", job["title"], job["company"])
            already_tracked += 1
            seen.add(job["id"])
            continue

        ghost_note, evergreen, ghost_skip, repost_of_tracked = assess_posting_health(
            history, key, today, job)
        if repost_of_tracked:
            # The tracker already has a row for this company+title from the
            # last 30 days; a repost should not create a second row.
            logger.info("Repost of tracked role, not re-adding: %r @ %r",
                        job["title"], job["company"])
            seen.add(job["id"])
            continue
        if ghost_skip:
            ghost_skipped.append((job, ghost_note))
            seen.add(job["id"])
            continue

        # Fit scoring v2: hard rules from the user's criteria, work-type match
        # from the Evidence Bank, company fields from the Companies row.
        company_page_id = job.get("notion_page_id") or get_or_create_company_page(job)
        result = evaluate_job(job, company_page_id, evergreen=evergreen, today=today)
        new_matches.append((job, result, flag, salary_min))
        if write_to_notion(job, result, flag, salary_min, ghost_note=ghost_note,
                           evergreen=evergreen, company_page_id=company_page_id,
                           history=history):
            written_count += 1
            written_matches.append((job, result, flag, salary_min))
            seen.add(job["id"])
            if key:
                history.setdefault(key, {"ids": {}, "locations": {}})["last_written"] = today_str
        # else: leave unseen so a transient failure (e.g. a timeout) gets
        # retried on the next run instead of the job being silently lost.

    STATS.stages["score_and_write"] = {"seconds": round(__import__("time").time() - _t_score, 1),
                                       "notion_calls": STATS.calls["notion:page_create"] + STATS.calls["notion:page_read"]}
    if run_stats.DRY_RUN:
        print("DRY RUN: seen_jobs.json and posting_history.json left untouched.")
    else:
        save_seen(seen)
        save_history(history, today)
    print(f"{len(new_matches)} new matches found, {written_count} written to Notion, "
          f"{already_tracked} skipped as already in the tracker.")
    STATS.extra.update({"new_matches": len(new_matches), "written": written_count,
                        "already_tracked": already_tracked})

    if run_stats.DRY_RUN:
        print("DRY RUN: fresh Tier A alert email skipped.")
    else:
        send_fresh_alerts(written_matches, history, today)
    if quick:
        if written_count and not run_stats.DRY_RUN:
            notify("Job agent", f"{written_count} new match(es) in your Applications tracker.")
        print("Quick run done (maintenance, digest, and snapshot run at 8am).")
        write_tracker_snapshot()
        print(STATS.summary_line())
        STATS.write("quick")
        return

    with STATS.stage("close_stale"):
        closed_count = close_stale_postings(all_jobs)
    print(f"{closed_count} stale posting(s) marked Closed.")
    STATS.extra["closed"] = closed_count

    # Keep the tracker itself current, at zero token cost:
    #   * rows still scored by v1 get rescored with v2 (one pass, then only
    #     when RUBRIC_VERSION changes),
    #   * open rows get Posted Date backfilled and Last Verified stamped when
    #     today's fetch still shows the posting,
    #   * candidate companies from candidates.json get their ATS probed so
    #     only the ones with live PM postings ever cost research tokens.
    with STATS.stage("migrate_verdict_names"):
        renamed = migrate_verdict_names(today)                            # v3.6 one-time carry-over
        if renamed:
            print(f"{renamed} verdict(s) renamed to the v3.6 names.")
    with STATS.stage("migrate_needs_ok"):
        converted = migrate_needs_your_ok(today)                        # one-time, then no-op
    with STATS.stage("refresh_open_rows"):
        verified, dated = refresh_open_rows(all_jobs, history, today)   # snapshots first
    with STATS.stage("tracked_leads"):
        lead_rows = resolve_tracked_leads(today)                         # LinkedIn rows -> board posting
    with STATS.stage("rescore_board_matched"):
        lead_rescored = rescore_board_matched(today)                     # ...scored on that text today
    with STATS.stage("refetch_board_text"):
        lead_rescored += refetch_board_text(today)                       # web-matched rows: full board text (v3.4)
    with STATS.stage("rescore_tracker"):
        rescored = rescore_tracker(today)                                # then score on them
    with STATS.stage("close_skips"):
        closed_skips = close_skipped_rows(today)                         # Skip rows leave the open views
    with STATS.stage("repair_eeo"):
        eeo_reopened = repair_eeo_closed_rows(today)                     # one-time (v4.1), then no-op
    if eeo_reopened:
        print(f"{len(eeo_reopened)} row(s) reopened: closed before v4.1 over equal-opportunity wording.")
    with STATS.stage("screen_candidates"):
        candidate_report = screen_candidates(today)
    STATS.extra.update({"rescored": rescored, "verified": verified, "dated": dated,
                        "closed_skips": closed_skips})
    print(f"{rescored} row(s) rescored with {fit_scoring.RUBRIC_VERSION}, "
          f"{verified} verified live today, {dated} posted date(s) backfilled, "
          f"{lead_rows} LinkedIn row(s) matched to a company posting ({lead_rescored} rescored on its text), "
          f"{closed_skips} Poor fit or Passed row(s) closed, "
          f"{converted} company verdict(s) converted from Needs your OK.")

    failures = len(new_matches) - written_count
    if failures:
        notify("Job agent: write failures",
               f"{failures} Notion write(s) failed — check agent.log. "
               "Unwritten matches retry on the next run.")
    elif written_count:
        notify("Job agent",
               f"{written_count} new match(es) in your Applications tracker.")
    if ghost_skipped:
        print(f"{len(ghost_skipped)} posting(s) skipped as likely ghost/evergreen "
              "(see Latest_Agent_Digest.md).")
    extra = []
    if today.weekday() == 6:   # Sunday: every open row still waiting on the user
        waiting = list_your_call_rows()
        if waiting:
            extra.append("## Possible fit, still waiting on you\n" + "\n".join(
                f"- {company}, {role} ({score}/10)" for company, role, score in waiting))
    if eeo_reopened:
        extra.append("## Reopened by the v4.1 repair\nClosed earlier because a rule word was only in the equal-opportunity statement:\n"
                     + "\n".join(f"- {c}, {r}" for c, r in eeo_reopened))
    if candidate_report:
        extra.append(candidate_report)
    if run_stats.DRY_RUN:
        print("DRY RUN: digest, market snapshot, and text digest skipped.")
    else:
        write_digest(new_matches, written_count, closed_count, ghost_skipped,
                     extra_sections=extra or None, history=history, today=today)
        maybe_refresh_market_snapshot(today)
        send_text_digest(new_matches)

    write_tracker_snapshot()
    print(STATS.summary_line())
    STATS.write("full")
    if not run_stats.DRY_RUN:
        # Post-run invariants: the rules every run must leave true. Emails
        # The user only on a failure. Never breaks the run.
        try:
            import invariants
            with STATS.stage("invariants"):
                invariants.run_after_agent(today, all_jobs=all_jobs)
        except Exception as e:   # noqa: BLE001
            logger.warning(f"invariants check failed to run: {e}")
        # Daily backup of the tracker, contacts, evidence bank, and settings
        # (data/backups, 14 days kept). Never breaks the run.
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            import backup
            with STATS.stage("backup"):
                backup.backup(today)
        except Exception as e:   # noqa: BLE001
            logger.warning(f"daily backup failed: {e}")
        try:
            import housekeeping
            with STATS.stage("housekeeping"):
                housekeeping.trim_logs()
        except Exception as e:   # noqa: BLE001
            logger.warning(f"log cleanup failed: {e}")


def write_tracker_snapshot():
    """tracker_snapshot.md: the compact tracker view chat sessions read instead
    of querying Notion through the connector (Oct 29, 2026). Best effort."""
    if run_stats.DRY_RUN:
        return
    try:
        import notion_q
        with STATS.stage("tracker_snapshot"):
            notion_q.write_snapshot()
    except Exception as e:   # noqa: BLE001
        logger.warning(f"tracker snapshot failed: {e}")


def maybe_refresh_market_snapshot(today):
    """Regenerate the market snapshot when the newest one is over 28 days old
    (or missing), so the user always has a current read on their market worth
    without remembering to run market_report.py."""
    here = DATA_DIR   # the user's data folder, never the install folder
    snapshots = sorted(here.glob("Market_Snapshot_*.md"))
    if snapshots:
        stamp = snapshots[-1].stem.replace("Market_Snapshot_", "")
        if _within_days(stamp, today, 28):
            return
    print("Market snapshot is stale or missing; regenerating...")
    try:
        result = subprocess.run(
            [sys.executable, str(here / "market_report.py")],
            capture_output=True, text=True, timeout=900)
        if result.returncode == 0:
            notify("Job agent", "Monthly market snapshot refreshed. "
                   "See Market_Snapshot files in Job Search.")
        else:
            logger.warning(f"market_report.py failed: {result.stderr[-400:]}")
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"Could not run market_report.py: {e}")


if __name__ == "__main__":
    main(quick="--quick" in sys.argv[1:])
