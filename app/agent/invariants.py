#!/usr/bin/env python3
"""Post-run invariants for the job search system (Oct 29, 2026).

The rules every run must leave true, checked against the Notion tracker and
the agent's own records, so the bugs the user finds by asking questions get
asked by a script first. Runs at the end of the 8am full run (called from
job_search_agent.main) and on demand:

    python3 Tooling/agent/invariants.py            # check and report
    python3 Tooling/agent/invariants.py --no-email # never email

Output: Tooling/agent/invariants_last.md (always), one email to the user only
when a FAIL is new since the last email (invariants_state.json remembers what
was already sent, so a standing failure nags once a day, not five times).
WARNs go in the file and the agent log, never in email.

Read-only against Notion. Never changes a row.
"""

import json
import re
import smtplib
import statistics
import sys
from datetime import date, datetime
from email.mime.text import MIMEText
from pathlib import Path
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import data_dir as _ks_data_dir  # agent state lives in the data folder

import requests

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import job_search_agent as jsa   # noqa: E402
import fit_scoring               # noqa: E402
import run_stats                 # noqa: E402
from ats_tools import request_with_retry   # noqa: E402

LAST_FILE = _ks_data_dir() / "invariants_last.md"
STATE_FILE = _ks_data_dir() / "invariants_state.json"
LOG_FILE = _ks_data_dir() / "agent.log"

OPEN = set(jsa.OPEN_STATUSES)
TIER_C = fit_scoring.TIER_NAMES["C"]
TIER_A = fit_scoring.TIER_NAMES["A"]
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S  # personal settings live in the settings folder, not the code

TRACKING_STARTS = _S("invariants.TRACKING_STARTS")   # version and cycle tracking starts on this date


# ---------------------------------------------------------------------------
# Notion reads (raw API, counted by run_stats like every other call)
# ---------------------------------------------------------------------------

def query(flt=None, database_id=None):
    """Every page matching `flt` in the Applications database (paginated)."""
    if not jsa.NOTION_TOKEN:
        return []
    url = f"https://api.notion.com/v1/databases/{database_id or jsa.NOTION_DATABASE_ID}/query"
    payload, rows = {"page_size": 100}, []
    if flt:
        payload["filter"] = flt
    while True:
        try:
            resp = request_with_retry(requests.post, url, headers=jsa.NOTION_HEADERS, json=payload, timeout=60)
        except requests.RequestException as e:
            print(f"[warn] invariants query failed: {e}", file=sys.stderr)
            return rows
        if resp.status_code >= 300:
            print(f"[warn] invariants query failed: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            return rows
        data = resp.json()
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        payload["start_cursor"] = data["next_cursor"]


def row(page):
    """Flatten the properties this module reads."""
    p = page.get("properties", {})
    return {
        "id": page.get("id"),
        "company": jsa._rt(p, "Company").strip(),
        "role": jsa._title(p, "Role").strip(),
        "status": (p.get("Status", {}).get("status") or {}).get("name"),
        "verdict": jsa._sel(p, "Overall Verdict"),
        "tier": jsa._sel(p, "Research Tier"),
        "label": jsa._rt(p, "Label Reason"),
        "pay_basis": jsa._sel(p, "Pay Basis"),
        "breakdown": jsa._rt(p, "Score Breakdown"),
        "posted": jsa._date(p, "Posted Date"),
        "verified": jsa._date(p, "Last Verified"),
        "applied": jsa._date(p, "Date Applied"),
        "drafting_started": jsa._date(p, "Drafting Started"),
        "resume_versions": p.get("Resume Versions", {}).get("number"),
        "override": jsa._rt(p, "Override Reason"),
        "outcome": jsa._sel(p, "Outcome Type"),
        "score": p.get("Role Fit Score", {}).get("number"),
        "url": p.get("Job Posting", {}).get("url"),
        "created": (page.get("created_time") or "")[:10],
        "edited": (page.get("last_edited_time") or "")[:10],
    }


def _name(r):
    return f"{r['company']}, {r['role']}"


# ---------------------------------------------------------------------------
# Checks. Each returns a list of (level, text). level is FAIL or WARN.
# ---------------------------------------------------------------------------

def check_rows(open_rows, applied_rows, closed_today, today, fetched_keys=None, covered_boards=None):
    out = []
    F, W = "FAIL", "WARN"
    today_iso = today.isoformat()

    # 1. one open row per company + title
    seen = {}
    for r in open_rows:
        k = (r["company"].lower(), jsa.norm_title(r["role"]))
        if k in seen:
            out.append((F, f"duplicate open rows: {_name(r)} ({r['id'][:8]} and {seen[k][:8]})"))
        else:
            seen[k] = r["id"]

    for r in open_rows:
        current = fit_scoring.RUBRIC_VERSION in (r["breakdown"] or "")
        # 2. hard-rule Poor fit and Passed rows leave the open views (a soft
        #    Poor fit, label "Poor fit (...)", stays open by design, v3.3)
        if r["verdict"] == "Passed" or (r["verdict"] == "Poor fit" and not jsa.SOFT_SKIP_LABEL.search(r["label"] or "")):
            out.append((F, f"{r['verdict']} row still open: {_name(r)} (Status {r['status']})"))
        # 3. v3.3: every scored open row has a verdict, and never a retired one
        if current and not r["verdict"]:
            out.append((F, f"open row with no verdict: {_name(r)}"))
        if current and r["verdict"] in fit_scoring.RETIRED_VERDICTS:
            out.append((F, f"retired verdict {r['verdict']!r} on a rescored row: {_name(r)}"))
        # 4. Strong fit is Tier A only
        if r["verdict"] == "Strong fit" and r["tier"] != TIER_A:
            out.append((F, f"Strong fit on a {r['tier'] or 'no-tier'} row: {_name(r)}"))
        # 5. v2.7: no posted pay means the lowest tier (Applying rows are raised to A on purpose)
        if (r["pay_basis"] == "Not posted" and r["tier"] and r["tier"] != TIER_C
                and r["verdict"] != "Applying" and fit_scoring.RUBRIC_VERSION in (r["breakdown"] or "")
                and "Tier raised to A" not in (r["breakdown"] or "")):
            out.append((F, f"no posted pay but {r['tier']}: {_name(r)}"))
        # 6. research spend on Tier C
        if r["tier"] == TIER_C and "Qualifications screened" in (r["label"] or ""):
            out.append((W, f"Tier C row carries a daily-refresh screen (spend on a C): {_name(r)}"))
        # 7. Posted Date filled once the row is 2 days old
        if not r["posted"] and r["created"] and jsa._days_since(r["created"], today) >= 2:
            out.append((W, f"no Posted Date after {jsa._days_since(r['created'], today)} days: {_name(r)}"))
        # 8. Applying hygiene
        if r["verdict"] == "Applying":
            if r["score"] is not None and r["score"] < 7 and not r["override"]:
                out.append((W, f"Applying under 7 with no Override Reason: {_name(r)} ({r['score']}/10)"))
            if r["created"] and jsa._days_since(r["created"], today) > 14 and not r["applied"]:
                out.append((W, f"Applying older than 14 days, not applied: {_name(r)}"))
        # 9. a fetched-board posting not seen for 7+ days should have closed
        if covered_boards and r["url"]:
            scope = jsa._board_scope(r["url"])
            if scope in covered_boards and r["verified"] and jsa._days_since(r["verified"], today) >= 7:
                out.append((W, f"on a fetched board but not verified in {jsa._days_since(r['verified'], today)} days: {_name(r)}"))
        # 10. a live posting must not be stamped as verified without being in today's fetch
        if fetched_keys is not None and r["verified"] == today_iso and r["url"]:
            k = jsa.posting_key(r["url"])
            scope = jsa._board_scope(r["url"])
            if k and scope in (covered_boards or set()) and k not in fetched_keys:
                out.append((F, f"stamped Last Verified today but absent from today's fetch: {_name(r)}"))

    # 11. the agent must never close a posting that is in today's fetch (Oct 27-28 bug class)
    if fetched_keys is not None:
        for r in closed_today:
            if r["verdict"] in ("Poor fit", "Passed") or r["outcome"]:
                continue
            k = jsa.posting_key(r["url"]) if r["url"] else None
            if k and k in fetched_keys:
                out.append((F, f"closed today while still live on its board: {_name(r)}"))

    # 12. cycle-time fields on recent sends
    for r in applied_rows:
        if r["applied"] and r["applied"] >= TRACKING_STARTS.isoformat():
            if not r["drafting_started"]:
                out.append((W, f"sent without Drafting Started: {_name(r)} (applied {r['applied']})"))
            if r["resume_versions"] is None:
                out.append((W, f"sent without Resume Versions: {_name(r)} (applied {r['applied']})"))
    return out


def check_runs(today, stats_today=None):
    """Run-level health from run_stats.jsonl and agent.log."""
    out = []
    F, W = "FAIL", "WARN"
    recent = run_stats.read_recent(days=7)
    fulls = [r for r in recent if r.get("run") == "full" and not r.get("dry_run")]
    if stats_today is None and fulls:
        stats_today = fulls[-1]
    if stats_today:
        for v in stats_today.get("violations", []):
            out.append((F, f"run violation: {v}"))
        prior = [r for r in fulls if r is not stats_today and r.get("fetched")]
        if prior and stats_today.get("fetched") is not None:
            med = statistics.median(r["fetched"] for r in prior)
            if med and stats_today["fetched"] < 0.6 * med:
                out.append((F, f"fetched {stats_today['fetched']} postings, under 60% of the 7-day median {int(med)}"))
            calls = lambda r: sum(v for k, v in r.get("calls", {}).items() if k.startswith("notion:"))  # noqa: E731
            med_calls = statistics.median(calls(r) for r in prior)
            if med_calls and calls(stats_today) > 2 * med_calls:
                out.append((W, f"Notion calls {calls(stats_today)} today, over twice the 7-day median {int(med_calls)}"))
    # boards that went to zero since the previous full run
    try:
        text = LOG_FILE.read_text(errors="replace")
    except OSError:
        text = ""
    blocks = re.split(r"^=== Run started ", text, flags=re.M)[1:]
    if len(blocks) >= 2:
        def counts(block):
            return {m.group(1).strip(): int(m.group(2)) for m in re.finditer(r"^  (?:feed )?([^:\n]+): (\d+) postings$", block, re.M)}
        prev, cur = counts(blocks[-2]), counts(blocks[-1])
        for name, n in cur.items():
            if n == 0 and prev.get(name, 0) > 0:
                out.append((W, f"board returned 0 postings (was {prev[name]} last run): {name}"))
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(findings, today, context=""):
    fails = [t for lv, t in findings if lv == "FAIL"]
    warns = [t for lv, t in findings if lv == "WARN"]
    lines = [f"# Invariants, {today.isoformat()} {datetime.now().strftime('%H:%M')}", ""]
    if context:
        lines += [context, ""]
    lines.append(f"{len(fails)} FAIL, {len(warns)} WARN")
    if fails:
        lines += ["", "## FAIL"] + [f"- {t}" for t in fails]
    if warns:
        lines += ["", "## WARN"] + [f"- {t}" for t in warns]
    if not findings:
        lines += ["", "All invariants hold."]
    body = "\n".join(lines) + "\n"
    try:
        LAST_FILE.write_text(body)
    except OSError:
        pass
    return body


def email_if_new(fails, today, no_email=False):
    """Email the FAIL list when it holds anything not emailed in the last day."""
    if not fails or no_email:
        return False
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        state = {}
    sent_on = state.get("sent_on")
    sent_set = set(state.get("fails", []))
    new = [f for f in fails if f not in sent_set]
    if sent_on == today.isoformat() and not new:
        return False
    if not (jsa.GMAIL_ADDRESS and jsa.GMAIL_APP_PASSWORD):
        print("[warn] invariants: GMAIL not configured, failure email skipped.", file=sys.stderr)
        return False
    body = (f"{len(fails)} invariant failure(s) after today's job agent run.\n\n"
            + "\n".join(f"- {f}" for f in fails)
            + "\n\nFull report: Job Search/Tooling/agent/invariants_last.md\n")
    msg = MIMEText(body)
    msg["Subject"] = f"Job agent invariants: {len(fails)} failure(s)"
    msg["From"] = jsa.GMAIL_ADDRESS
    msg["To"] = jsa.GMAIL_ADDRESS
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(jsa.GMAIL_ADDRESS, jsa.GMAIL_APP_PASSWORD)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        print(f"[warn] invariants email failed: {e}", file=sys.stderr)
        return False
    try:
        STATE_FILE.write_text(json.dumps({"sent_on": today.isoformat(), "fails": fails}, indent=1))
    except OSError:
        pass
    return True


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def gather(today):
    open_rows = [row(p) for p in query({"or": [{"property": "Status", "status": {"equals": s}} for s in jsa.OPEN_STATUSES]})]
    applied_rows = [row(p) for p in query({"property": "Date Applied", "date": {"on_or_after": TRACKING_STARTS.isoformat()}})]
    closed_today = [row(p) for p in query({"and": [
        {"property": "Status", "status": {"equals": "Closed"}},
        {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": today.isoformat()}}]})]
    return open_rows, applied_rows, closed_today


def run(today=None, all_jobs=None, no_email=False, stats_today=None):
    today = today or date.today()
    open_rows, applied_rows, closed_today = gather(today)
    fetched_keys = covered = None
    if all_jobs is not None:
        urls = [j.get("url") for j in all_jobs if j.get("url")]
        fetched_keys = {jsa.posting_key(u) for u in urls} - {None}
        covered = {jsa._board_scope(u) for u in urls} - {None}
    findings = check_rows(open_rows, applied_rows, closed_today, today, fetched_keys, covered)
    findings += check_runs(today, stats_today)
    context = (f"{len(open_rows)} open rows, {len(applied_rows)} sent since {TRACKING_STARTS}, "
               f"{len(closed_today)} closed today" + ("" if all_jobs is None else f", {len(all_jobs)} postings fetched"))
    report = write_report(findings, today, context)
    fails = [t for lv, t in findings if lv == "FAIL"]
    emailed = email_if_new(fails, today, no_email)
    print(f"Invariants: {len(fails)} FAIL, {len(findings) - len(fails)} WARN"
          + (" (emailed)" if emailed else "") + "; see invariants_last.md")
    return findings, report


def run_after_agent(today, all_jobs):
    return run(today, all_jobs=all_jobs, stats_today=None)


if __name__ == "__main__":
    _, rep = run(no_email="--no-email" in sys.argv[1:])
    print(rep)
