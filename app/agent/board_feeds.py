#!/usr/bin/env python3
"""
Remote job-board feeds for the local agent.
-------------------------------------------
These are the boards with a public feed or API, so they cost nothing to poll:

  We Work Remotely   RSS, Product category
  Himalayas          JSON API
  Working Nomads     JSON API

Boards without a usable feed (Built In, Wellfound, Remote Rocketship,
findyourcareer.io, remote.co which blocks bots) are not covered here.

Every fetcher returns the same job dict the agent uses everywhere:
  source, id, title, company, url, location, salary_text, description, published
and swallows its own errors with a [warn] line, so one dead feed never stops
the run. Feeds are recency-windowed, so the agent never treats a posting that
has dropped out of a feed as closed (see FEED_HOSTS and close_stale_postings).
"""

import html
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from ats_tools import request_with_retry

import sys as _ua_sys, os as _ua_os
_ua_sys.path.insert(0, _ua_os.path.dirname(_ua_os.path.dirname(_ua_os.path.abspath(__file__))))
from kit_settings import user_agent as _ks_ua
HEADERS = {"User-Agent": _ks_ua()}

# Hosts whose postings come from a recency-windowed feed. A row whose Job
# Posting URL is on one of these is never marked stale by the agent.
FEED_HOSTS = ("weworkremotely.com", "himalayas.app", "workingnomads.com", "remote.co")


def _iso(dt):
    return dt.date().isoformat() if dt else ""


def _rss_date(text):
    try:
        return _iso(parsedate_to_datetime(text)) if text else ""
    except (TypeError, ValueError):
        return ""


def _epoch_date(value):
    try:
        v = float(value)
        if v > 1e12:  # milliseconds
            v /= 1000
        return _iso(datetime.fromtimestamp(v, tz=timezone.utc))
    except (TypeError, ValueError):
        return ""


def _first(d, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _join(v):
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x)
    return str(v or "")


def _strip(text):
    return re.sub(r"\s+", " ", html.unescape(str(text or ""))).strip()


# ---------------------------------------------------------------------------
# We Work Remotely (RSS)
# ---------------------------------------------------------------------------

import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S  # personal settings live in the settings folder, not the code

WWR_FEEDS = _S("board_feeds.WWR_FEEDS")


def _parse_rss(xml_text, source, id_prefix):
    jobs = []
    # Feeds come from the internet. A real RSS feed never needs a DOCTYPE or
    # entity definitions, so refuse those outright instead of trusting the XML
    # parser's own limits (entity expansion attacks).
    if re.search(r"<!(DOCTYPE|ENTITY)", xml_text or "", re.I):
        raise ValueError(f"{source}: feed declares a DOCTYPE or entities; skipped")
    root = ET.fromstring(xml_text)  # nosec B314
    for item in root.iter("item"):
        get = lambda tag: (item.findtext(tag) or "").strip()  # noqa: E731
        raw_title = _strip(get("title"))
        company, title = "", raw_title
        if ": " in raw_title:
            company, title = raw_title.split(": ", 1)
        link = get("link") or get("guid")
        region = get("region") or get("location") or ""
        # Category tags often carry the location too ("Anywhere in the World").
        cats = [_strip(c.text) for c in item.findall("category") if c.text]
        if not region:
            region = next((c for c in cats if re.search(r"anywhere|usa|united states|americas|north america|remote", c, re.I)), "")
        if not region and re.search(r"anywhere", " ".join(cats), re.I):
            region = "Anywhere in the World"
        location = region or "Remote"
        if re.search(r"anywhere", location, re.I):
            location = "Remote - Anywhere"
        jobs.append({
            "source": source,
            "id": f"{id_prefix}-{get('guid') or link}",
            "title": title,
            "company": company,
            "url": link,
            "location": location,
            "salary_text": "",
            "description": get("description"),
            "published": _rss_date(get("pubDate")),
        })
    return jobs


def fetch_weworkremotely():
    jobs = []
    for url in WWR_FEEDS:
        try:
            resp = request_with_retry(requests.get, url, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            jobs.extend(_parse_rss(resp.text, "We Work Remotely", "wwr"))
        except (requests.RequestException, ET.ParseError, ValueError) as e:
            print(f"[warn] We Work Remotely feed failed ({url}): {e}", file=sys.stderr)
    return jobs


# ---------------------------------------------------------------------------
# Himalayas (JSON API)
# ---------------------------------------------------------------------------

HIMALAYAS_API = "https://himalayas.app/jobs/api"


def _parse_himalayas(payload):
    jobs = []
    for j in payload.get("jobs", []) if isinstance(payload, dict) else payload:
        if not isinstance(j, dict):
            continue
        title = _strip(_first(j, "title"))
        url = _first(j, "applicationLink", "url", "link", "guid")
        restr = _first(j, "locationRestrictions", "locations", "location", default=[])
        location = _join(restr) or "Remote"
        if not re.search(r"united states|usa|\bus\b|americas|north america|anywhere|worldwide", location, re.I) and not restr:
            location = "Remote - Anywhere"
        if re.search(r"worldwide|anywhere", location, re.I):
            location = "Remote - Anywhere"
        elif re.search(r"united states|usa|\bus\b", location, re.I):
            location = f"Remote - {location}"
        lo, hi = _first(j, "minSalary", default=None), _first(j, "maxSalary", default=None)
        salary = f"${lo:,.0f}-${hi:,.0f}" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
        jobs.append({
            "source": "Other",
            "id": f"himalayas-{_first(j, 'guid', 'id', 'slug') or url}",
            "title": title,
            "company": _strip(_first(j, "companyName", "company")),
            "url": url,
            "location": location,
            "salary_text": salary,
            "description": _first(j, "description", "excerpt"),
            "published": _epoch_date(_first(j, "pubDate", "publishedAt", "createdAt", default=None))
                         or (_first(j, "pubDate", "publishedAt", default="")[:10]
                             if isinstance(_first(j, "pubDate", "publishedAt", default=""), str) else ""),
        })
    return jobs


def fetch_himalayas(pages=3, limit=100):
    jobs = []
    for page in range(pages):
        try:
            resp = request_with_retry(requests.get, HIMALAYAS_API, headers=HEADERS,
                                      params={"limit": limit, "offset": page * limit}, timeout=60)
            resp.raise_for_status()
            batch = _parse_himalayas(resp.json())
        except (requests.RequestException, ValueError) as e:
            print(f"[warn] Himalayas feed failed (page {page}): {e}", file=sys.stderr)
            break
        jobs.extend(batch)
        if len(batch) < limit:
            break
    return jobs


# ---------------------------------------------------------------------------
# Working Nomads (JSON API)
# ---------------------------------------------------------------------------

WORKING_NOMADS_API = "https://www.workingnomads.com/api/exposed_jobs/"


def _parse_working_nomads(payload):
    jobs = []
    for j in payload if isinstance(payload, list) else payload.get("results", payload.get("jobs", [])):
        if not isinstance(j, dict):
            continue
        location = _strip(_first(j, "location")) or "Remote"
        if re.search(r"anywhere|worldwide|global", location, re.I):
            location = "Remote - Anywhere"
        elif not re.search(r"remote", location, re.I):
            location = f"Remote - {location}"
        pub = _first(j, "pub_date", "published", default="")
        jobs.append({
            "source": "Other",
            "id": f"workingnomads-{_first(j, 'id', 'slug') or _first(j, 'url')}",
            "title": _strip(_first(j, "title")),
            "company": _strip(_first(j, "company_name", "company")),
            "url": _first(j, "url", "link"),
            "location": location,
            "salary_text": _strip(_first(j, "salary_range", "salary")),
            "description": _first(j, "description"),
            "published": pub[:10] if isinstance(pub, str) else _epoch_date(pub),
        })
    return jobs


def fetch_working_nomads():
    try:
        resp = request_with_retry(requests.get, WORKING_NOMADS_API, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return _parse_working_nomads(resp.json())
    except (requests.RequestException, ValueError) as e:
        print(f"[warn] Working Nomads feed failed: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# remote.co (RSS, best effort)
# ---------------------------------------------------------------------------

REMOTE_CO_FEEDS = _S("board_feeds.REMOTE_CO_FEEDS")


def fetch_remote_co():
    jobs = []
    for url in REMOTE_CO_FEEDS:
        try:
            resp = request_with_retry(requests.get, url, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            if "<rss" not in resp.text[:2000] and "<feed" not in resp.text[:2000]:
                raise ValueError("not an RSS feed (HTML page returned)")
            jobs.extend(_parse_rss(resp.text, "Other", "remoteco"))
        except (requests.RequestException, ET.ParseError, ValueError) as e:
            print(f"[warn] remote.co feed failed ({url}): {e}", file=sys.stderr)
    return jobs


# ---------------------------------------------------------------------------

def fetch_board_feeds():
    """All feed boards, in one list. Order matters to the agent: these come
    after the company boards, so when the same posting arrives from both,
    the company's own ATS URL wins the Notion row."""
    jobs = []
    # remote.co dropped 2026-10-21: it times out and resets the connection
    # (bot protection), which cost two minutes of retries per run for nothing.
    # fetch_remote_co stays available for a manual try.
    for name, fn in (("We Work Remotely", fetch_weworkremotely), ("Himalayas", fetch_himalayas),
                     ("Working Nomads", fetch_working_nomads)):
        batch = fn()
        print(f"  feed {name}: {len(batch)} postings", file=sys.stderr)
        jobs.extend(batch)
    return jobs


if __name__ == "__main__":
    for j in fetch_board_feeds():
        print(f"- [{j['source']}] {j['title']} @ {j['company']} ({j['location']}) {j['published']} -> {j['url']}")
