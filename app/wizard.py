#!/usr/bin/env python3
"""Job Search Kit: setup wizard and tracker, as a page in the user's browser.

    python app/wizard.py            # open setup
    python app/wizard.py --tracker  # open the tracker
    python app/wizard.py --no-browser --port 8765   # serve only (tests)

Runs only on this computer (127.0.0.1). Reads and writes the user's
settings folder (KIT_SETTINGS_DIR) and the data folder; nothing leaves the
machine except fetching a job posting the user pastes in.

Who may talk to it: every launch makes a random token; the page URL carries
it and the page sends it with every API call. Requests without it, requests
whose Host header isn't 127.0.0.1:<port> (a website using the browser as a
relay, DNS rebinding), and cross-site POSTs (Origin check) are refused.
Links stored in the tracker are http or https only, and Add a Posting
refuses local and private-network addresses, following redirects by hand so
a public link can't bounce to a private one.
"""
import argparse
import ipaddress
import json
import secrets
import socket
import sys
import threading
import time
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "agent"))
import kit_settings     # noqa: E402
import setup_model      # noqa: E402

PAGE = APP / "wizard_page.html"
_AGENT = {}
TOKEN = secrets.token_urlsafe(24)   # new on every launch; the page URL carries it


ACK_TERMS = "beta-as-is-1"   # bump when the beta terms on the privacy page change, so users confirm again


def acknowledged():
    f = settings_dir() / "app.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("acknowledged", {}).get("terms") == ACK_TERMS
    except (OSError, ValueError, AttributeError):
        return False


def acknowledge():
    """Record that the user confirmed the beta terms (date and terms version) in settings/app.json."""
    f = settings_dir() / "app.json"
    if not (settings_dir() / "paths.json").exists():
        return {"ok": False, "later": True}   # no folder yet: saved when the folder is created
    try:
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        d = {}
    d["acknowledged"] = {"terms": ACK_TERMS, "date": date.today().isoformat()}
    f.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    return {"ok": True}


def settings_dir():
    return kit_settings.settings_dir()


def agent():
    """Import the agent lazily, after setup has written the settings."""
    if "jsa" not in _AGENT:
        import job_search_agent as jsa
        import fit_scoring
        import local_tracker
        _AGENT.update(jsa=jsa, fs=fit_scoring, lt=local_tracker)
    return _AGENT


# ---------------------------------------------------------------- tracker
def _plain(prop):
    t = (prop or {}).get("type")
    v = (prop or {}).get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in v or [])
    if t in ("select", "status"):
        return v["name"] if v else ""
    if t == "date":
        return (v or {}).get("start") or ""
    if t == "relation":
        return [x["id"] for x in v or []]
    return v if v is not None else ""


def safe_url(u):
    """A link the page may show: http or https with a host, else empty."""
    try:
        s = urlsplit(str(u or "").strip())
    except ValueError:
        return ""
    return s.geturl() if s.scheme in ("http", "https") and s.hostname else ""


def _private_ip(ip):
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped is not None:
        return _private_ip(str(a.ipv4_mapped))
    if a.version == 6 and a.sixtofour is not None:
        return _private_ip(str(a.sixtofour))
    return not a.is_global or a.is_multicast or a.is_loopback or a.is_link_local or a.is_private or a.is_reserved


def _public_ips(url, resolve=None):
    """The addresses url's host resolves to; ValueError unless http(s) to a public internet host."""
    s = urlsplit(url)
    if s.scheme not in ("http", "https"):
        raise ValueError("only http and https links can be opened")
    host = s.hostname
    if not host or s.username or s.password:
        raise ValueError("that link isn't a plain web address")
    h = host.lower().rstrip(".")
    if h in ("localhost", "localhost.localdomain") or h.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".arpa")):
        raise ValueError("local addresses can't be opened from here")
    try:
        ips = [host] if ipaddress.ip_address(host) else []
    except ValueError:
        resolve = resolve or (lambda hn: sorted({r[4][0] for r in socket.getaddrinfo(hn, None)}))
        try:
            ips = resolve(host)
        except Exception:
            raise ValueError("that address couldn't be looked up")
    if not ips or any(_private_ip(ip) for ip in ips):
        raise ValueError("local and private network addresses can't be opened from here")
    return ips


def check_public_url(url, resolve=None):
    """Raise ValueError unless url is http(s) to a public internet host."""
    _public_ips(url, resolve)
    return url


MAX_PAGE = 2_000_000   # a posting is a page, not a download


def _pinned_get(url, ip):
    """GET url by connecting to the already-checked address ip, never a fresh DNS lookup.

    Closes the DNS-rebinding gap: a host that answered with a public address for
    the check can't swap in a private one for the fetch. The Host header and the
    TLS certificate check still use the link's hostname. Returns (status, headers, text).
    """
    import urllib3
    import requests.certs
    s = urlsplit(url)
    https = s.scheme == "https"
    port = s.port or (443 if https else 80)
    path = (s.path or "/") + ("?" + s.query if s.query else "")
    headers = {"Host": s.netloc.rsplit("@", 1)[-1], "User-Agent": kit_settings.user_agent(),
               "Accept-Encoding": "gzip, deflate"}
    if https:
        pool = urllib3.HTTPSConnectionPool(ip, port, server_hostname=s.hostname, assert_hostname=s.hostname,
                                           cert_reqs="CERT_REQUIRED", ca_certs=requests.certs.where(),
                                           timeout=20, retries=False)
    else:
        pool = urllib3.HTTPConnectionPool(ip, port, timeout=20, retries=False)
    try:
        r = pool.request("GET", path, headers=headers, redirect=False, preload_content=False)
        body = r.read(MAX_PAGE)
        r.release_conn()
    finally:
        pool.close()
    ctype = r.headers.get("Content-Type", "")
    charset = ctype.split("charset=", 1)[1].split(";")[0].strip(' "') if "charset=" in ctype else "utf-8"
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    return r.status, r.headers, text


def safe_fetch(url, resolve=None, get=None):
    """Fetch a public page, checking every redirect hop and connecting only to the checked address."""
    from urllib.parse import urljoin
    get = get or _pinned_get
    for _ in range(5):
        ip = _public_ips(url, resolve)[0]
        status, headers, text = get(url, ip)
        if status in (301, 302, 303, 307, 308) and headers.get("Location"):
            url = urljoin(url, headers["Location"])
            continue
        if status >= 400:
            raise ValueError(f"the site answered {status}")
        return text[:MAX_PAGE]
    raise ValueError("too many redirects")


# Statuses, in the order the tracker shows and sorts them, and the three groups
# (the tracker's status rules). Rejected is its own status; Closed means
# the user stopped or the posting closed.
STATUSES = ("Interested", "Drafting Resume", "Applied", "Interviewing", "Offer", "Closed", "Rejected")
STATUS_GROUPS = (("To Do", ("Interested", "Drafting Resume")), ("In Progress", ("Applied", "Interviewing")),
                 ("Complete", ("Offer", "Closed", "Rejected")))
OPEN_STATUSES = STATUSES[:4]
NEW_DAYS = 14   # a posting the daily check added counts as New until opened, for at most this long


def _read_store(stem):
    f = kit_settings.data_dir() / "tracker" / f"{stem}.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8")).get("pages", {})


def _is_new(row, today=None):
    """New: the daily check added it, it's still Interested, and the user hasn't opened it."""
    if row.get("Opened") or row.get("Status") != "Interested" or row.get("Source") == "Added by you":
        return False
    try:
        age = ((today or date.today()) - date.fromisoformat(row.get("created") or "")).days
    except ValueError:
        return False
    return 0 <= age <= NEW_DAYS


def tracker_rows():
    rows = []
    for p in _read_store("applications").values():
        if p.get("archived"):
            continue
        pr = p["properties"]
        rows.append({"id": p["id"], **{k: _plain(pr.get(k)) for k in (
            "Role", "Company", "Job Posting", "Status", "Role Fit Score", "Research Tier", "Overall Verdict",
            "Label Reason", "Posted Date", "Base Salary", "Remote Status", "Notes", "Date Applied", "Outcome Type",
            "Source", "Follow-up Date", "Next Step", "Resume Versions", "Opened", "Posting Health")},
            "created": p.get("created_time", "")[:10]})
        r = rows[-1]
        r["Job Posting"] = safe_url(r["Job Posting"])
        rel = _plain(pr.get("Company Profile"))
        r["company_id"] = rel[0] if isinstance(rel, list) and rel else ""
        r["is_new"] = _is_new(r)
    rows.sort(key=lambda r: (r["Status"] not in ("Interested", "Drafting Resume"), -(r["Role Fit Score"] or 0)))
    alerts = []
    af = kit_settings.data_dir() / "alerts.jsonl"
    if af.exists():
        alerts = [json.loads(l) for l in af.read_text(encoding="utf-8").splitlines()[-5:] if l.strip()]
    return {"rows": rows, "alerts": alerts, "last_run": last_run(), "statuses": list(STATUSES),
            "groups": [[g, list(s)] for g, s in STATUS_GROUPS], "new_count": sum(r["is_new"] for r in rows)}


STALE_HOURS = 36


def last_run():
    """The last daily or quick run that finished (run_stats.jsonl gets a line only
    when a run reaches its end), and whether that's more than 36 hours ago."""
    f = kit_settings.data_dir() / "run_stats.jsonl"
    last = None
    if f.exists():
        with f.open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 65536))
            tail = fh.read().decode("utf-8", "ignore").splitlines()
        for line in reversed(tail):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not rec.get("dry_run") and rec.get("ts"):
                last = rec
                break
    if not last:
        return {"ts": None, "run": None, "stale": None}
    from datetime import datetime
    try:
        age = (datetime.now() - datetime.fromisoformat(last["ts"])).total_seconds() / 3600
    except ValueError:
        age = None
    return {"ts": last["ts"], "run": last.get("run"), "hours": round(age, 1) if age is not None else None,
            "stale": age is None or age > STALE_HOURS}


def _date_prop(v):
    v = str(v or "").strip()
    if not v:
        return {"date": None}
    date.fromisoformat(v)   # ValueError on anything but YYYY-MM-DD
    return {"date": {"start": v}}


def tracker_update(body):
    a = agent()
    props = {}
    if "status" in body:
        if body["status"] not in STATUSES:
            return {"ok": False, "error": f"unknown status {body['status']!r}"}
        props["Status"] = {"status": {"name": body["status"]}}
        if body["status"] == "Applied" and not body.get("applied"):
            page = _read_store("applications").get(body["id"]) or {}
            if not _plain((page.get("properties") or {}).get("Date Applied")):
                props["Date Applied"] = {"date": {"start": date.today().isoformat()}}
        if body["status"] == "Rejected" and "outcome" not in body:
            props["Outcome Type"] = {"select": {"name": "Rejected"}}
            props["Outcome Date"] = {"date": {"start": date.today().isoformat()}}
    try:
        if "applied" in body:
            props["Date Applied"] = _date_prop(body["applied"])
        if "follow_up" in body:
            props["Follow-up Date"] = _date_prop(body["follow_up"])
    except ValueError:
        return {"ok": False, "error": "dates must look like 2026-11-01"}
    if "next" in body:
        props["Next Step"] = {"rich_text": [{"text": {"content": str(body["next"])[:300]}}]}
    if "versions" in body:
        v = str(body["versions"] if body["versions"] is not None else "").strip()
        if v and not v.isdigit():
            return {"ok": False, "error": "resume versions must be a whole number"}
        props["Resume Versions"] = {"number": int(v) if v else None}
    if body.get("opened"):
        page = _read_store("applications").get(body["id"]) or {}
        if _plain((page.get("properties") or {}).get("Opened")):
            if len(props) == 0 and set(body) <= {"id", "opened"}:
                return {"ok": True}
        else:
            props["Opened"] = {"date": {"start": date.today().isoformat()}}
    if "verdict" in body:
        props["Overall Verdict"] = {"select": {"name": body["verdict"]} if body["verdict"] else None}
    if "notes" in body:
        props["Notes"] = {"rich_text": [{"text": {"content": body["notes"][:1900]}}]}
    if "outcome" in body:
        props["Outcome Type"] = {"select": {"name": body["outcome"]} if body["outcome"] else None}
        props["Outcome Date"] = {"date": {"start": date.today().isoformat()}}
    r = a["lt"].handle("patch", f"https://api.notion.com/v1/pages/{body['id']}", {"json": {"properties": props}})
    return {"ok": r.status_code < 300}


def tracker_add(body, fetch=None):
    """Score a posting the user pasted in and add it to the tracker."""
    a = agent()
    jsa, fs = a["jsa"], a["fs"]
    url = body.get("url", "").strip()
    text = body.get("text", "").strip()
    if url:
        try:
            url = check_public_url(url)
        except ValueError as e:
            return {"ok": False, "message": f"Couldn't use that link: {e}. Paste the posting text instead."}
    if url and not text:
        try:
            text = jsa.clean_posting_text((fetch or safe_fetch)(url))
        except Exception as e:
            return {"ok": False, "message": f"Couldn't open that link ({e}). Paste the posting text instead."}
    if not text:
        return {"ok": False, "message": "Paste a link or the posting text."}
    title = body.get("title", "").strip() or "Pasted posting"
    company = body.get("company", "").strip() or "Unknown company"
    salary = jsa.extract_salary_min("", text)
    # A pasted posting has no location field, so read remote from its opening
    # lines ("Location: Remote (US)") or its own wording; otherwise the Work
    # column showed "Not stated" for a posting that said Remote.
    head = text[:400].lower()
    remote = bool(fs.POSTING_REMOTE_RE.search(text)
                  or any(kw in head for kw in (jsa.REMOTE_KEYWORDS or [])))
    result = fs.score_posting(title, text, salary_min=salary, company_name=company, today=date.today(),
                              remote_hint=remote)
    props = {"Role": {"title": [{"text": {"content": title}}]},
             "Company": {"rich_text": [{"text": {"content": company}}]},
             "Status": {"status": {"name": "Closed" if result.get("hard_skip") else "Interested"}},
             "Source": {"select": {"name": "Added by you"}},
             "Notes": {"rich_text": [{"text": {"content": "Added by you (tracker page or the Claude plugin)."}}]},
             "Posting Snapshot": {"rich_text": [{"text": {"content": text[:1900]}}]},
             **jsa.scoring_properties(result)}
    if url:
        props["Job Posting"] = {"url": url}
    if salary:
        props["Base Salary"] = {"number": salary}
    if remote:
        props["Remote Status"] = {"select": {"name": "Fully Remote"}}
    r = a["lt"].handle("post", "https://api.notion.com/v1/pages",
                       {"json": {"parent": {"database_id": jsa.NOTION_DATABASE_ID}, "properties": props}})
    try:
        new_id = r.json().get("id") if r.status_code < 300 else None
    except Exception:
        new_id = None
    return {"ok": r.status_code < 300, "id": new_id, "score": result["score"], "tier": result["tier"],
            "verdict": result["verdict"], "hard_skip": bool(result.get("hard_skip")),
            "reasons": result["reasons"], "missing": result["missing_minimums"]}


# ---------------------------------------------------------------- contacts
def contacts_file():
    return kit_settings.data_dir() / "contacts.json"


def contacts_get():
    f = contacts_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def contacts_put(rows):
    import local_tracker
    with local_tracker.file_lock(contacts_file()):
        contacts_file().write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------- companies
# The Companies table. Rows live in the built-in tracker's companies file (the
# daily check makes a stub row for each new company). Research fields are typed
# in by the user or by Claude from pages they open together; the kit never
# reads review sites on its own.
#
# Four fields also feed fit scoring, so the page shows plain labels but stores
# the values the scorer already knows (fit_scoring.company_score and
# hard_rules): Remote Posture, Risk Level, Verdict, and the two benefit
# selects. "Not a fit" is stored as "Do not pursue", which skips that
# company's postings, the same as before.
POSTURE_UI = {"Structurally remote (no HQ)": "Fully remote", "Remote-first with offices": "Remote-first",
              "Hybrid / RTO risk": "Hybrid", "Onsite": "Onsite", "Unknown": "Unknown"}
VERDICT_UI = {"Pursue": "Pursue", "Watch list": "Watch list", "Needs research": "Not reviewed yet",
              "Do not pursue": "Not a fit"}
RISK_UI = {"Low": "Low", "Some concerns": "Some concerns", "High": "High", "Not researched": "Needs research"}
GROWTH = ("Growing", "Steady", "Shrinking", "Unknown")
CAREER = ("Strong", "Some", "Limited", "Unknown")
# key on the page -> (property, kind)
RESEARCH = {"field": ("Field", "text"), "bonus": ("Bonus and Equity", "text"), "perks": ("Other Perks", "text"),
            "pto": ("PTO Policy", "text"), "values": ("Key Values", "text"), "green": ("Green Flags", "text"),
            "red": ("Red Flags", "text"), "health": ("Health Rating", "rating"), "dni": ("D&I Rating", "rating"),
            "glassdoor": ("Glassdoor Rating", "rating"), "match": ("401k Match", "percent"),
            "growth": ("Company Growth", GROWTH), "career": ("Career Growth", CAREER),
            "careers": ("Careers Page", "url")}


def _ui(table, stored, default):
    if not stored:
        return default
    if table is POSTURE_UI and stored.startswith("Hybrid"):
        return "Hybrid"
    return table.get(stored, default if table is not VERDICT_UI else "Not reviewed yet")


def _stored(table, label):
    back = {v: k for k, v in table.items()}
    if label not in back:
        raise ValueError(f"unknown choice {label!r}")
    return back[label]


def health_select(rating):
    """The scorer's Health Benefits value for a 1-to-5 rating: 2 or lower counts as Weak."""
    if rating is None:
        return None
    return "Weak" if rating <= 2 else "Average" if rating < 4 else "Strong"


def board_link(platform, slug):
    """The public page for a company's job board."""
    if platform == "greenhouse":
        return f"https://job-boards.greenhouse.io/{slug}"
    if platform == "lever":
        return f"https://jobs.lever.co/{slug}"
    if platform == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}"
    if platform == "workday" and isinstance(slug, dict):
        return f"https://{slug.get('tenant')}.{slug.get('instance')}.myworkdayjobs.com/{slug.get('board')}"
    return ""


def _board_settings():
    f = settings_dir() / "companies.json"
    try:
        at = json.loads(f.read_text(encoding="utf-8")).get("ats_tools", {}) if f.exists() else {}
    except ValueError:
        at = {}
    return at.get("CONFIRMED_COMPANIES") or [], at.get("CUSTOM_SITE_COMPANIES") or []


def _board_for(name, boards, custom):
    key = (name or "").strip().lower()
    for i, b in enumerate(boards):
        if (b.get("name") or "").strip().lower() == key:
            wd = b.get("platform") == "workday"
            return {"label": "Workday" if wd else str(b.get("platform", "")).title(), "platform": b.get("platform"),
                    "url": safe_url(board_link(b.get("platform"), b.get("slug"))), "index": i,
                    "note": ("Read daily" if b.get("workday_ok") is True else "Not read daily (your choice)") if wd else "Read daily",
                    "workday_ok": b.get("workday_ok") is True}
    for c in custom:
        if (c.get("name") or "").strip().lower() == key:
            return {"label": "Careers page", "platform": "custom", "url": safe_url(c.get("careers_url")),
                    "note": "No standard board; check by hand"}
    return {"label": "", "platform": "", "url": "", "note": "Not found yet"}


def companies_rows():
    boards, custom = _board_settings()
    apps = tracker_rows()["rows"]
    out, names = [], set()

    def row(cid, name, pr):
        mine = [a for a in apps if (a["company_id"] and a["company_id"] == cid)
                or (not a["company_id"] and (a["Company"] or "").strip().lower() == name.strip().lower())]
        r = {"id": cid, "name": name, "board": _board_for(name, boards, custom),
             "posture": _ui(POSTURE_UI, _plain(pr.get("Remote Posture")), "Unknown"),
             "verdict": _ui(VERDICT_UI, _plain(pr.get("Verdict")), "Not reviewed yet"),
             "risk": _ui(RISK_UI, _plain(pr.get("Risk Level")), "Needs research"),
             "pto_weak": _plain(pr.get("PTO")) == "Weak",
             "open_roles": sum(a["Status"] not in ("Closed", "Rejected") for a in mine),
             "open_apps": sum(a["Status"] in OPEN_STATUSES for a in mine),
             "apps": [{"id": a["id"], "role": a["Role"], "status": a["Status"]} for a in mine]}
        for k, (prop, kind) in RESEARCH.items():
            v = _plain(pr.get(prop)) if pr.get(prop) else None
            r[k] = (v if v != "" else None) if kind in ("rating", "percent") else (v or "")
        if not r["field"]:
            dom = pr.get("Domain", {}).get("multi_select") or []
            r["field"] = ", ".join(d.get("name", "") for d in dom)
        r["careers"] = safe_url(r["careers"] or _plain(pr.get("Website")) or "")
        jb = safe_url(_plain(pr.get("Job Board URL")) or "") if pr.get("Job Board URL") else ""
        if not r["board"]["label"] and jb:
            r["board"] = {"label": "Job board", "platform": "", "url": jb, "note": "Not read daily; add it in Setup to read it"}
        return r

    for p in _read_store("companies").values():
        if p.get("archived"):
            continue
        pr = p.get("properties") or {}
        name = _plain(pr.get("Company")) or ""
        if not name.strip() or name.strip().lower() in names:
            continue
        names.add(name.strip().lower())
        out.append(row(p["id"], name, pr))
    for b in [*boards, *custom]:   # boards picked in setup that the daily check hasn't met yet
        name = (b.get("name") or "").strip()
        if name and name.lower() not in names:
            names.add(name.lower())
            out.append(row("", name, {}))
    out.sort(key=lambda r: r["name"].lower())
    return {"rows": out, "choices": {"posture": list(POSTURE_UI.values()), "verdict": list(VERDICT_UI.values()),
                                     "risk": list(RISK_UI.values()), "growth": list(GROWTH), "career": list(CAREER)}}


def _company_props(body):
    props = {}
    if "posture" in body:
        props["Remote Posture"] = {"select": {"name": _stored(POSTURE_UI, body["posture"])}}
    if "verdict" in body:
        props["Verdict"] = {"select": {"name": _stored(VERDICT_UI, body["verdict"])}}
    if "risk" in body:
        props["Risk Level"] = {"select": {"name": _stored(RISK_UI, body["risk"])}}
    if "pto_weak" in body:
        props["PTO"] = {"select": {"name": "Weak"} if body["pto_weak"] else None}
    for k, (prop, kind) in RESEARCH.items():
        if k not in body:
            continue
        v = body[k]
        if kind == "text":
            props[prop] = {"rich_text": [{"text": {"content": str(v or "").strip()[:1900]}}]}
        elif kind == "url":
            u = str(v or "").strip()
            if u and not safe_url(u):
                raise ValueError("the careers page must be an http or https link")
            props[prop] = {"url": u or None}
        elif kind in ("rating", "percent"):
            s = str(v if v is not None else "").strip().rstrip("%")
            n = float(s) if s else None
            hi = 5 if kind == "rating" else 100
            if n is not None and not (0 <= n <= hi):
                raise ValueError(f"{prop} must be between 0 and {hi}")
            props[prop] = {"number": n}
            if k == "health":
                props["Health Benefits"] = {"select": {"name": health_select(n)} if n is not None else None}
        else:
            if v and v not in kind:
                raise ValueError(f"unknown choice {v!r}")
            props[prop] = {"select": {"name": v} if v else None}
    return props


def company_save(body):
    """Create or update a company's research. A new company starts as Not reviewed yet."""
    a = agent()
    try:
        props = _company_props(body)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    cid = (body.get("id") or "").strip()
    if cid:
        r = a["lt"].handle("patch", f"https://api.notion.com/v1/pages/{cid}", {"json": {"properties": props}})
        return {"ok": r.status_code < 300, "id": cid}
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "a company needs a name"}
    if any(c["id"] and c["name"].lower() == name.lower() for c in companies_rows()["rows"]):
        return {"ok": False, "error": f"{name} is already on the Companies page"}
    props = {"Company": {"title": [{"text": {"content": name[:200]}}]},
             "Verdict": {"select": {"name": "Needs research"}}, "Risk Level": {"select": {"name": "Not researched"}},
             "Monitoring": {"select": {"name": "Added by you"}}, **props}
    r = a["lt"].handle("post", "https://api.notion.com/v1/pages",
                       {"json": {"parent": {"database_id": a["jsa"].NOTION_COMPANIES_DATABASE_ID}, "properties": props}})
    try:
        new_id = r.json().get("id") if r.status_code < 300 else None
    except Exception:
        new_id = None
    return {"ok": bool(new_id), "id": new_id}


def company_add(body, detect=None):
    """Add a company from the Companies page; with a careers link, also find its job board for the daily check."""
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if url and not safe_url(url):
        return {"ok": False, "error": "the careers page must be an http or https link"}
    res = company_save({"name": name, **({"careers": url} if url else {})})
    if not res["ok"] or not url:
        return {**res, "message": "Added." if res["ok"] else res.get("error", "")}
    found = (detect or detect_board)({"url": url, "name": name})
    a = setup_model.read_answers(settings_dir())
    if found.get("board"):
        a["fields"]["boards"].append({**found["board"], "name": name})
        msg = ("Added. Found a Workday board; it stays off until you turn it on in the company's details."
               if found["board"]["platform"] == "workday" else f"Added. The daily check will read its {found['board']['platform'].title()} board.")
    else:
        a["fields"]["custom_sites"].append({**found.get("custom", {"careers_url": url}), "name": name})
        msg = "Added. No standard job board found, so check its careers page by hand."
    setup_model.write_answers(settings_dir(), a)
    kit_settings._cache.clear()
    return {**res, "message": msg}


def company_workday(body):
    """Turn reading a company's Workday board on or off (off by default; SOURCES.md)."""
    a = setup_model.read_answers(settings_dir())
    b = next((b for b in a["fields"]["boards"] if b.get("platform") == "workday"
              and (b.get("name") or "").strip().lower() == (body.get("name") or "").strip().lower()), None)
    if not b:
        return {"ok": False, "error": "no Workday board for that company"}
    b["workday_ok"] = body.get("ok") is True
    setup_model.write_answers(settings_dir(), a)
    kit_settings._cache.clear()
    return {"ok": True}


# ---------------------------------------------------------------- page settings
THEMES = ("auto", "light", "dark")
PILL_COLORS = ("gray", "blue", "teal", "green", "yellow", "orange", "red", "purple", "pink")
DEFAULT_STATUS_COLORS = {"Interested": "blue", "Drafting Resume": "purple", "Applied": "teal", "Interviewing": "orange",
                         "Offer": "green", "Closed": "gray", "Rejected": "red"}


def ui_settings():
    ui = kit_settings.app_settings() if (settings_dir() / "app.json").exists() else {}
    colors = {**DEFAULT_STATUS_COLORS, **{k: v for k, v in (ui.get("status_colors") or {}).items()
                                          if k in DEFAULT_STATUS_COLORS and v in PILL_COLORS}}
    theme = ui.get("theme") if ui.get("theme") in THEMES else "auto"
    return {"theme": theme, "status_colors": colors}


def ui_save(body):
    """Theme and status colors live in settings/app.json, so every page and every browser agrees."""
    f = settings_dir() / "app.json"
    if not (settings_dir() / "paths.json").exists():
        return {"ok": False, "later": True}
    d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if "theme" in body:
        if body["theme"] not in THEMES:
            return {"ok": False, "error": "unknown theme"}
        d["theme"] = body["theme"]
    if "status_colors" in body:
        c = body["status_colors"] or {}
        if any(k not in DEFAULT_STATUS_COLORS or v not in PILL_COLORS for k, v in c.items()):
            return {"ok": False, "error": "unknown status or color"}
        d["status_colors"] = {**ui_settings()["status_colors"], **c}
    f.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    kit_settings._cache.clear()
    return {"ok": True, **ui_settings()}


def suggest_email(body, opener=None):
    """Open a suggestion draft in the user's own mail app. The address is read here,
    so it never appears in the page or the repo; the user presses Send."""
    from urllib.parse import quote
    to = kit_settings.app_settings().get("support_email", "") if (settings_dir() / "app.json").exists() else ""
    if not to:
        return {"ok": False, "error": "No support address is set up. Use Suggest on GitHub instead."}
    what = str(body.get("what") or "").strip()[:4000]
    why = str(body.get("why") or "").strip()[:4000]
    subject = "Job Search Kit idea: " + (what.splitlines()[0][:80] if what else "")
    text = f"What I'd like the kit to do:\n{what}\n\nWhat it would help me do:\n{why}\n"
    (opener or webbrowser.open)(f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(text)}")
    return {"ok": True}


def detect_board(body):
    url = body.get("url", "").strip()
    name = body.get("name", "").strip()
    import lead_resolver
    found = lead_resolver.board_from_url(url)
    if not found:
        import ats_tools
        try:
            d = ats_tools.detect_ats(url, html=safe_fetch(url))
        except Exception as e:
            d = {"error": str(e)}
        m = (d or {}).get("matches") or {}
        if m:
            found = next(iter(m.items()))
    if found:
        platform, slug = found
        return {"ok": True, "board": {"name": name or str(slug).replace("-", " ").title(), "platform": platform, "slug": slug}}
    return {"ok": True, "custom": {"name": name or url, "careers_url": url,
                                   "note": "No standard job board found; check this page by hand or ask Claude to watch it."}}


# ---------------------------------------------------------------- server
MAX_BODY = 1_000_000          # a pasted posting is well under this; anything bigger is refused
DRAIN_LIMIT = 16_000_000      # a refused body up to this size is read and discarded so the 413 reaches the page
IDLE_MINUTES = 30             # the page server stops after this long with no requests


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; img-src 'self' data:; form-action 'none'; base-uri 'none'; "
                             "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _allowed(self):
        """Host must be this server, and the request must carry this launch's token."""
        self.server.last_seen = time.monotonic()
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self._send(403, {"error": "wrong host"})
            return False
        path, _, query = self.path.partition("?")
        tok = self.headers.get("X-Kit-Token")
        if not tok and path in ("/", "/index.html"):
            tok = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("t")
        if not tok or not secrets.compare_digest(tok, TOKEN):
            if path in ("/", "/index.html"):
                return self._send(403, b"<p>Open the Job Search Kit from the Start menu (or the Applications folder) so it opens with today's key.</p>", "text/html") or False
            self._send(403, {"error": "missing or stale key; open the kit from the Start menu"})
            return False
        return True

    def do_GET(self):
        path = self.path.split("?")[0]
        if not self._allowed():
            return
        try:
            if path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html")
            if path == "/api/folder":
                import first_run
                return self._send(200, {**first_run.options(), "needs_folder": not (settings_dir() / "paths.json").exists()})
            if path == "/api/answers":
                return self._send(200, setup_model.read_answers(settings_dir()))
            if path == "/api/advanced":
                return self._send(200, setup_model.read_advanced(settings_dir()))
            if path == "/api/tracker":
                return self._send(200, tracker_rows())
            if path == "/api/contacts":
                return self._send(200, contacts_get())
            if path == "/api/companies":
                return self._send(200, companies_rows())
            if path == "/api/ui":
                return self._send(200, ui_settings())
            if path == "/api/status":
                v = APP / "VERSION"
                return self._send(200, {"settings": str(settings_dir()), "version": v.read_text().strip() if v.exists() else "dev",
                                        "configured": (settings_dir() / "criteria.json").exists(),
                                        "needs_folder": not (settings_dir() / "paths.json").exists(),
                                        "needs_ack": (settings_dir() / "paths.json").exists() and not acknowledged(),
                                        "support_email_set": bool(kit_settings.app_settings().get("support_email"))
                                        if (settings_dir() / "app.json").exists() else False,
                                        **ui_settings()})
            if path == "/api/schedule":
                import schedule
                return self._send(200, {"plan": [n for n, _ in schedule.plan()]})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._allowed():
            return
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
            return self._send(403, {"error": "local page only"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.close_connection = True
            if 0 < n <= DRAIN_LIMIT:
                # read and discard the body in small pieces so the browser gets
                # the message below instead of a dropped connection
                left = n
                while left > 0:
                    got = self.rfile.read(min(65536, left))
                    if not got:
                        break
                    left -= len(got)
            return self._send(413, {"ok": False, "error": "That's too much to send at once. Paste a shorter posting text."})
        try:
            b = self._body()
            if path == "/api/folder":
                import first_run
                settings = first_run.choose(b.get("choice"), b.get("path"))
                kit_settings._cache.clear()
                if b.get("acknowledged") is True:
                    acknowledge()
                return self._send(200, {"ok": True, "settings": str(settings)})
            if path == "/api/acknowledge":
                return self._send(200, acknowledge())
            if path == "/api/delete_data":
                import housekeeping
                import schedule
                return self._send(200, housekeeping.delete(b.get("scope"), b.get("confirm"),
                                                           remove_schedule=schedule.remove))
            if path == "/api/answers":
                setup_model.write_answers(settings_dir(), b)
                kit_settings._cache.clear()
                return self._send(200, {"ok": True})
            if path == "/api/advanced":
                setup_model.write_advanced(settings_dir(), b)
                return self._send(200, {"ok": True})
            if path == "/api/detect":
                return self._send(200, detect_board(b))
            if path == "/api/tracker/update":
                return self._send(200, tracker_update(b))
            if path == "/api/tracker/add":
                return self._send(200, tracker_add(b))
            if path == "/api/contacts":
                return self._send(200, contacts_put(b))
            if path == "/api/companies/save":
                return self._send(200, company_save(b))
            if path == "/api/companies/add":
                return self._send(200, company_add(b))
            if path == "/api/companies/workday":
                return self._send(200, company_workday(b))
            if path == "/api/ui":
                return self._send(200, ui_save(b))
            if path == "/api/suggest":
                return self._send(200, suggest_email(b))
            if path == "/api/error_report":
                import error_report
                report = error_report.save_report()
                how = error_report.open_email(report, kit_settings.app_settings().get("support_email", "")) if not b.get("save_only") else "saved"
                return self._send(200, {"ok": True, "report": str(report), "how": how})
            if path == "/api/schedule/install":
                import schedule
                schedule.install()
                return self._send(200, {"ok": True, "message": "Daily runs are set up."})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_idle_watch(srv, minutes=None, every=30.0):
    """Stop the page server after IDLE_MINUTES with no requests (it is started
    again from the Start menu). The page says so if it's used after that."""
    limit = 60 * (IDLE_MINUTES if minutes is None else minutes)
    srv.last_seen = time.monotonic()

    def watch():
        while True:
            time.sleep(every)
            if time.monotonic() - srv.last_seen > limit:
                srv.shutdown()
                return
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    return t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int)
    a = ap.parse_args(argv)
    if (settings_dir() / "paths.json").exists():   # folders made before v0.2 get Claude's permissions file too
        try:
            import first_run
            first_run.write_claude_settings(settings_dir().parent)
        except OSError:
            pass
    if (settings_dir() / "app.json").exists():   # after a kit update, bring older settings forward (backup first)
        try:
            import backup as kit_backup
            changes, warning = kit_settings.migrate(backup=lambda: kit_backup.backup(tag="before-settings-update"))
            for c in changes + ([warning] if warning else []):
                print(c, flush=True)
        except Exception as e:
            print(f"Settings update check failed: {type(e).__name__}: {e}", flush=True)
    port = a.port or free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    start_idle_watch(srv)
    url = f"http://127.0.0.1:{port}/?t={TOKEN}" + ("#tracker" if a.tracker else "#setup")
    print(f"Job Search Kit is open at {url} (close this window to stop it)", flush=True)
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
