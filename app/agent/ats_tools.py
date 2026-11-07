#!/usr/bin/env python3
"""
ATS Detector + Generic Fetchers  (v2 -- with JS-rendered page fallback)
-----------------------------------------------------------------------
CHANGE IN v2: the original detector only scanned static HTML, which missed
JavaScript-rendered career pages (some companies load their job
board client-side, so the ATS link isn't in the initial page source).

detect_ats() now has two stages:
  Stage 1 -- scan the page HTML for known ATS URL patterns (fast, exact)
  Stage 2 -- if stage 1 finds nothing, guess likely company slugs from the
             domain name and probe the Greenhouse/Lever/Ashby public APIs
             directly. A slug that returns real job postings is a match.

This catches most JS-rendered sites. It still won't catch companies on a
truly custom portal (e.g. Example Clearing, which self-hosts a Laravel careers
app) -- those genuinely need page-scraping and are flagged as such.

IMPORTANT: a slug probe can occasionally return the WRONG company -- the
generic slug "apex" returns a dental-office job board, not Example Clearing.
Always eyeball the first few job titles to confirm it's really the company
you meant before adding it to CONFIRMED_COMPANIES.

USAGE:
    python3 ats_tools.py detect "https://www.example.com/careers"
    python3 ats_tools.py greenhouse example-slug
    python3 ats_tools.py lever example-slug
    python3 ats_tools.py ashby example-slug
    python3 ats_tools.py all          # pull from every confirmed company
"""

import hashlib
import html
import json
import os
import re
from datetime import datetime
import sys
import time
from urllib.parse import urlparse

import requests

import run_stats


def _host(url):
    """Hostname of url, lowercased, or "" (a substring test would match a query string too)."""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""

import sys as _ua_sys, os as _ua_os
_ua_sys.path.insert(0, _ua_os.path.dirname(_ua_os.path.dirname(_ua_os.path.abspath(__file__))))
from kit_settings import user_agent as _ks_ua
HEADERS = {"User-Agent": _ks_ua()}


# v4.0 (Nov 7, 2026): every source is fetched on its own daemon thread, at most
# FETCH_WORKERS at a time, and a source that hasn't answered within
# FETCH_SOURCE_BUDGET seconds is abandoned (its thread dies with the process).
# Before this, 80 sources were fetched one after another with 60-second
# timeouts and three attempts each, so a laptop that lost Wi-Fi mid-run spent
# up to three minutes per source: quick runs of 2,100 to 7,600 seconds on
# Nov 5, 2026, and alerts hours late.
FETCH_WORKERS = int(os.environ.get("FETCH_WORKERS", "8"))
FETCH_SOURCE_BUDGET = float(os.environ.get("FETCH_SOURCE_BUDGET", "90"))
FETCH_ATTEMPTS = int(os.environ.get("FETCH_ATTEMPTS", "2"))
FETCH_TIMEOUT = float(os.environ.get("FETCH_TIMEOUT", "30"))


def run_concurrently(named_fns, workers=None, budget=None, label="source"):
    """Run [(name, fn)] on daemon threads, at most `workers` at a time, and
    return {name: (result or None, seconds, error or None)} in input order.
    A fn that overruns `budget` seconds is reported as a timeout and left to
    die with the process; its result is dropped. Exceptions are caught and
    reported, never raised."""
    import threading
    workers = workers or FETCH_WORKERS
    budget = budget if budget is not None else FETCH_SOURCE_BUDGET
    out = {}
    gate = threading.Semaphore(workers)
    done = {}

    def runner(name, fn):
        t0 = time.time()
        try:
            with gate:
                res = fn()
            out[name] = (res, round(time.time() - t0, 1), None)
        except Exception as e:   # noqa: BLE001
            out[name] = (None, round(time.time() - t0, 1), e)
        finally:
            done[name].set()

    threads = []
    for name, fn in named_fns:
        done[name] = threading.Event()
        t = threading.Thread(target=runner, args=(name, fn), daemon=True, name=f"fetch:{name}")
        t.start()
        threads.append(t)
    # One deadline for the whole batch: a slow source holds a worker slot, so
    # the batch budget grows with the number of batches, not per source.
    deadline = time.time() + budget * max(1, -(-len(named_fns) // workers))
    for name, _fn in named_fns:
        remaining = max(0.0, deadline - time.time())
        if not done[name].wait(timeout=remaining):
            out[name] = (None, round(budget, 1), TimeoutError(f"{label} still running after {budget:.0f}s; abandoned"))
    return {name: out[name] for name, _fn in named_fns}


def request_with_retry(request_fn, url, attempts=3, **kwargs):
    """Call request_fn(url, **kwargs) -- e.g. requests.get/post/patch -- retrying
    up to `attempts` times with exponential backoff (1s, 2s, 4s, ...) on
    network-level failures (timeouts, connection errors). Does not retry on
    HTTP error status codes; callers still handle those via raise_for_status()
    or their own status check."""
    method = getattr(request_fn, "__name__", "get").lower()
    run_stats.STATS.note(method, url, kwargs)
    notion = _host(url) == "api.notion.com"
    if run_stats.DRY_RUN and notion and method in ("post", "patch") \
            and not url.rstrip("/").endswith("/query"):
        # Dry run: Notion reads still happen, writes are recorded, not sent.
        return run_stats.STATS.dry_response(method, url, kwargs)
    if notion:
        local = sys.modules.get("local_tracker")
        if local is not None and local._DATA is not None:
            # Built-in tracker (kit default): answered from local files, no network.
            return local.handle(method, url, kwargs)
    for attempt in range(attempts):
        try:
            return request_fn(url, **kwargs)
        except requests.RequestException as e:
            if attempt == attempts - 1:
                raise
            wait = 2 ** attempt
            print(f"[warn] request to {url} failed ({e}); retrying in {wait}s "
                  f"(attempt {attempt + 1}/{attempts})...", file=sys.stderr)
            time.sleep(wait)


# ---------------------------------------------------------------------------
# CONFIRMED TARGET COMPANIES
# Verified working. Add new ones as you confirm them.
# ---------------------------------------------------------------------------

# "notion_page_id" points at the company's row in the Notion "Companies"
# database -- used to set the "Company Profile" relation on each posting we
# write. None means no Companies page exists for that company yet.
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S  # personal settings live in the settings folder, not the code

CONFIRMED_COMPANIES = _S("ats_tools.CONFIRMED_COMPANIES")

# Some careers sites have no third-party ATS (a fully custom portal) or block
# automated requests with a bot challenge (Cloudflare, AWS WAF). Those can't be
# probed automatically; list them in CUSTOM_SITE_COMPANIES and check them by
# hand. A slug match on a shared ATS can also be the wrong company (an ATS's
# own test board, or another company with the same name), so verify sample
# titles before trusting one.

# Confirmed to have NO third-party ATS -- don't waste time re-probing these.
CUSTOM_SITE_COMPANIES = _S("ats_tools.CUSTOM_SITE_COMPANIES")


# ---------------------------------------------------------------------------
# DETECTION
# ---------------------------------------------------------------------------

STATIC_PATTERNS = {
    "greenhouse": r"(?:boards|job-boards)\.greenhouse\.io/([a-zA-Z0-9\-]+)",
    "lever": r"jobs\.lever\.co/([a-zA-Z0-9\-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([a-zA-Z0-9\-]+)",
    "workday": r"([a-zA-Z0-9\-]+)\.wd\d+\.myworkdayjobs\.com",
    "smartrecruiters": r"jobs\.smartrecruiters\.com/([a-zA-Z0-9\-]+)",
    "recruitee": r"([a-zA-Z0-9\-]+)\.recruitee\.com",
    "workable": r"apply\.workable\.com/([a-zA-Z0-9\-]+)",
}

# Hints that a JS-rendered page pulls from a given ATS even when the board URL
# isn't in the HTML (e.g. a careers page's Builder.io "useAshbyData" flag).
SOFT_HINTS = {
    "ashby": [r"useAshbyData", r"ashbyhq"],
    "greenhouse": [r"greenhouse", r"grnhse"],
    "lever": [r"lever\.co", r"leverJobs"],
}


def guess_slugs(url):
    """Derive plausible ATS slugs from a company's domain."""
    host = urlparse(url).netloc.lower()
    host = re.sub(r"^(www|careers|jobs|about)\.", "", host)
    base = host.split(".")[0]
    guesses = [base, base.replace("-", ""), base.replace("-", "_")]
    parts = host.split(".")
    if len(parts) > 2:
        guesses.append(parts[-2])
    seen, out = set(), []
    for g in guesses:
        if g and g not in seen:
            seen.add(g)
            out.append(g)
    return out


def probe_slug(platform, slug):
    """Return (job_count, sample_titles) if real postings found, else None."""
    try:
        if platform == "greenhouse":
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                             headers=HEADERS, timeout=10)
            if r.ok:
                jobs = r.json().get("jobs", [])
                if jobs:
                    return len(jobs), [j.get("title", "") for j in jobs[:3]]
        elif platform == "lever":
            r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json",
                             headers=HEADERS, timeout=10)
            if r.ok:
                jobs = r.json()
                if isinstance(jobs, list) and jobs:
                    return len(jobs), [j.get("text", "") for j in jobs[:3]]
        elif platform == "ashby":
            r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                             headers=HEADERS, timeout=10)
            if r.ok:
                jobs = r.json().get("jobs", [])
                if jobs:
                    return len(jobs), [j.get("title", "") for j in jobs[:3]]
    except (requests.RequestException, ValueError):
        pass
    return None


def detect_ats(url, html=None):
    """Find the job board behind a careers page. Pass `html` to skip the fetch (the wizard
    fetches through its public-host check so a redirect can't reach a private address)."""
    if html is None:
        # Same fetch the wizard uses: public hosts only, every redirect hop checked.
        import wizard
        try:
            html = wizard.safe_fetch(url)
        except (ValueError, OSError) as e:
            return {"error": f"Could not fetch {url}: {e}"}

    # --- Stage 1: exact URL patterns in static HTML ---
    matches = {}
    for platform, pattern in STATIC_PATTERNS.items():
        m = re.search(pattern, html)
        if m:
            matches[platform] = m.group(1)
    if matches:
        return {"result": "ATS detected (static HTML)", "matches": matches}

    # --- Stage 2: soft hints + slug probing against live APIs ---
    print("  [no static match -- probing APIs for JS-rendered board...]", file=sys.stderr)

    hinted = [p for p, pats in SOFT_HINTS.items()
              if any(re.search(pat, html, re.I) for pat in pats)]
    platforms = hinted + [p for p in ("greenhouse", "lever", "ashby") if p not in hinted]

    for platform in platforms:
        for slug in guess_slugs(url):
            found = probe_slug(platform, slug)
            if found:
                count, samples = found
                return {
                    "result": "ATS detected (API probe)",
                    "matches": {platform: slug},
                    "job_count": count,
                    "sample_titles": samples,
                    "VERIFY": "Check the sample titles above actually belong to the "
                              "company you meant -- generic slugs sometimes hit a "
                              "different company's board.",
                }

    return {
        "result": "No known ATS found",
        "note": "Static scan and API probing both came up empty. This company likely "
                "runs a fully custom careers portal. Verify by opening the careers "
                "page and seeing where the 'Apply' button goes -- if it stays on "
                "their own domain, there's no third-party ATS to query.",
    }


# ---------------------------------------------------------------------------
# FETCHERS
# ---------------------------------------------------------------------------

def clean_posting_url(url, job_id=None):
    """Drop a redundant ?gh_jid= query when the job id is already in the path.
    Some companies' absolute_url (example.com/careers/123/?gh_jid=123)
    doesn't open cleanly; the bare path does. Pages that
    identify the job only by the query (company.com/careers?gh_jid=123) keep it."""
    if not url or "?" not in url or not job_id:
        return url
    path, _, query = url.partition("?")
    jid = str(job_id)
    if jid in path and query == f"gh_jid={jid}":
        return path
    return url


def fetch_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    resp = request_with_retry(requests.get, url, headers=HEADERS, timeout=FETCH_TIMEOUT, attempts=FETCH_ATTEMPTS)
    resp.raise_for_status()
    return [{
        "source": f"Greenhouse:{slug}",
        "id": f"gh-{slug}-{job['id']}",
        "title": job.get("title", ""),
        "company": slug,
        "url": clean_posting_url(job.get("absolute_url", ""), job.get("id")),
        "location": job.get("location", {}).get("name", ""),
        # Original publish date (YYYY-MM-DD). Survives edits, unlike
        # updated_at, which boards bump in bulk.
        "published": (job.get("first_published") or "")[:10],
        "salary_text": "",
        # Not truncated -- compensation sections typically sit near the end
        # of a JD, well past the old 2000-char cap, and salary extraction
        # needs to see them.
        "description": re.sub("<[^<]+?>", "", job.get("content", "")),
    } for job in resp.json().get("jobs", [])]


def _lever_location(job):
    """Lever's "location" category is a physical place ("United States") and
    says nothing about remote/hybrid/onsite -- that's a separate top-level
    "workplaceType" field the old fetch silently dropped, which meant a
    plainly-remote posting scored as not-remote. Fold it in so downstream
    remote-keyword checks (job_search_agent.py's score_remote et al) see it."""
    location = job.get("categories", {}).get("location", "")
    workplace_type = job.get("workplaceType", "")
    if workplace_type:
        return f"{location} ({workplace_type})".strip()
    return location


def _epoch_ms_to_date(ms):
    """Lever's createdAt is epoch milliseconds; return YYYY-MM-DD or ""."""
    try:
        return datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def fetch_lever(slug):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    resp = request_with_retry(requests.get, url, headers=HEADERS, timeout=FETCH_TIMEOUT, attempts=FETCH_ATTEMPTS)
    resp.raise_for_status()
    return [{
        "source": f"Lever:{slug}",
        "id": f"lever-{slug}-{job.get('id', '')}",
        "title": job.get("text", ""),
        "company": slug,
        "url": job.get("hostedUrl", ""),
        "location": _lever_location(job),
        "published": _epoch_ms_to_date(job.get("createdAt")),
        "salary_text": "",
        "description": re.sub("<[^<]+?>", "",
                              job.get("descriptionPlain", job.get("description", ""))),
    } for job in resp.json()]


def fetch_ashby(slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = request_with_retry(requests.get, url, headers=HEADERS, timeout=FETCH_TIMEOUT, attempts=FETCH_ATTEMPTS)
    resp.raise_for_status()
    return [{
        "source": f"Ashby:{slug}",
        "id": f"ashby-{slug}-{job.get('id', '')}",
        "title": job.get("title", ""),
        "company": slug,
        "url": job.get("jobUrl", ""),
        "location": job.get("location", ""),
        "published": (job.get("publishedAt") or "")[:10],
        "salary_text": "",
        "description": job.get("descriptionPlain", "") or "",
    } for job in resp.json().get("jobs", [])]



def fetch_workday(tenant, instance, board):
    """Workday's CXS API (undocumented publicly, but stable and widely used
    for exactly this purpose). URL shape:
    https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs

    e.g. tenant="exampleco", instance="wd5", board="Exampleco_External".
    """
    base = f"https://{tenant}.{instance}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{tenant}/{board}/jobs"
    headers = {**HEADERS, "Content-Type": "application/json"}
    jobs = []
    limit = 20
    offset = 0
    total = None

    while total is None or offset < total:
        resp = request_with_retry(
            requests.post, url, headers=headers, timeout=60,
            json={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
        )
        resp.raise_for_status()
        data = resp.json()
        if total is None:
            # Only trust the first response's count -- later pages sometimes
            # report a stale/zero "total", which would truncate or loop pagination.
            total = data.get("total", 0)
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for job in postings:
            path = job.get("externalPath", "")
            jobs.append({
                "source": f"Workday:{tenant}",
                "id": f"workday-{tenant}-{path}",
                "title": job.get("title", ""),
                "company": tenant,
                "url": f"{base}/{board}{path}",
                "location": job.get("locationsText", ""),
                # Workday only gives relative text ("Posted 30+ Days Ago").
                "posted_text": job.get("postedOn", ""),
                "salary_text": "",
                "description": "",
            })
        offset += limit
    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workday": lambda params: fetch_workday(**params) if params else [],
}


# Workday is opt-in per company (decided Nov 1, 2026): Workday's own site terms
# restrict automated tools, and whether they reach the career sites companies
# host on myworkdayjobs.com is unclear (SOURCES.md). A Workday board is read
# only when its CONFIRMED_COMPANIES entry has "workday_ok": true, which the
# user sets in the setup wizard after reading a plain note.
def workday_allowed(slug):
    return any(c.get("platform") == "workday" and c.get("slug") == slug and c.get("workday_ok") is True
               for c in CONFIRMED_COMPANIES)


def _slug_display(slug):
    """Human-readable form of a company's slug, e.g. for a new Companies-page
    ATS field: "examplecorp", or for Workday's dict slug,
    "exampleco (wd5, Exampleco_External)"."""
    if isinstance(slug, dict):
        return f"{slug.get('tenant')} ({slug.get('instance')}, {slug.get('board')})"
    return slug or ""


# Portfolio companies (one shared ATS board covering several distinct
# brands) whose job titles embed the real brand as a " | Brand" suffix, e.g.
# "Director of Product Management | Example Brand". Splitting on these matters:
# brands under one parent can have different remote postures and team
# cultures, so lumping them under the parent's name would apply one brand's
# risk profile to another. Settings: {"Parent name": ["Brand", ...]}.
PORTFOLIO_BRAND_SUFFIXES = {k: set(v) for k, v in (_S("ats_tools.PORTFOLIO_BRAND_SUFFIXES", default={}) or {}).items()}


def _split_portfolio_brand(job, parent_name):
    """If job's title ends in " | <known brand>" for a tracked portfolio
    company, return (title_without_suffix, brand_name). Otherwise return
    (title, parent_name) unchanged -- covers corporate/unbranded roles
    (e.g. "Director of Engineering, Agentic Workflows", internal-team
    suffixes like "| Corporate Technology") that really do belong to the
    parent, not a consumer brand."""
    known_brands = PORTFOLIO_BRAND_SUFFIXES.get(parent_name)
    title = job.get("title", "")
    if known_brands and " | " in title:
        base, _, suffix = title.rpartition(" | ")
        if suffix.strip() in known_brands:
            return base.strip(), suffix.strip()
    return title, parent_name


SLOW_BOARD_SECONDS = 20   # a board slower than this is named in the run log


def _fetch_company(company):
    jobs = FETCHERS[company["platform"]](company["slug"])
    for j in jobs:
        title, brand = _split_portfolio_brand(j, company["name"])
        j["title"] = title
        j["company"] = brand
        j["notion_page_id"] = company.get("notion_page_id") if brand == company["name"] else None
        j["ats_platform"] = company["platform"]
        j["ats_slug"] = _slug_display(company["slug"])
    return jobs


def fetch_all_confirmed():
    """Pull postings from every company in CONFIRMED_COMPANIES, concurrently
    (run_concurrently), in CONFIRMED_COMPANIES order. Failed and abandoned
    boards are warned about and skipped; the slowest boards are named."""
    def _on(c):
        # The kit reads a Workday board only when its entry has workday_ok (see SOURCES.md).
        return not (c.get("platform") == "workday" and c.get("workday_ok") is not True)
    for company in CONFIRMED_COMPANIES:
        if not _on(company):
            print(f"  {company['name']}: skipped (Workday board is off; turn it on in Setup if you want it read)", file=sys.stderr)
    results = run_concurrently([(c["name"], (lambda c=c: _fetch_company(c))) for c in CONFIRMED_COMPANIES if _on(c)],
                               label="board")
    all_jobs, failed, slow = [], [], []
    for company in CONFIRMED_COMPANIES:
        if not _on(company):
            continue
        jobs, seconds, err = results[company["name"]]
        if err is not None:
            failed.append(company["name"])
            print(f"  [warn] {company['name']} failed: {err}", file=sys.stderr)
            continue
        if seconds >= SLOW_BOARD_SECONDS:
            slow.append(f"{company['name']} {seconds:.0f}s")
        all_jobs.extend(jobs)
        print(f"  {company['name']}: {len(jobs)} postings", file=sys.stderr)
    if failed:
        print(f"  boards failed or abandoned ({len(failed)}): {', '.join(failed)}", file=sys.stderr)
    if slow:
        print(f"  slow boards: {', '.join(slow)}", file=sys.stderr)
    return all_jobs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "detect":
        print(json.dumps(detect_ats(sys.argv[2]), indent=2))
    elif command in FETCHERS:
        slug = sys.argv[2] if len(sys.argv) > 2 else None
        for j in FETCHERS[command](slug):
            print(f"- {j['title']} ({j['location']}) -> {j['url']}")
    elif command == "all":
        jobs = fetch_all_confirmed()
        print(f"\n{len(jobs)} total postings across "
              f"{len(CONFIRMED_COMPANIES)} confirmed companies.")
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
