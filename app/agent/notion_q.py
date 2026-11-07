#!/usr/bin/env python3
"""notion_q: compact, zero-token reads of the Notion tracker for chat sessions.

Claude sessions used to pull whole Applications rows through the Notion
connector (100 rows with posting snapshots is a lot of context, and Notion's
SQL and rows query modes share a small allowance). This script answers the
usual questions from the raw API using the agent's own token, prints a
compact table, and costs no connector allowance and almost no context.

    python3 Tooling/agent/notion_q.py open            # open rows (Interested, Drafting Resume)
    python3 Tooling/agent/notion_q.py open --tier A   # Tier A only (A, B, or C)
    python3 Tooling/agent/notion_q.py pursue          # Applying rows (v3.6; was Pursue)
    python3 Tooling/agent/notion_q.py ask             # Possible fit rows (v3.3; was Ask me first)
    python3 Tooling/agent/notion_q.py sent            # Applied, Interviewing, Offer, Rejected
    python3 Tooling/agent/notion_q.py counts          # rows per Status and per Verdict
    python3 Tooling/agent/notion_q.py row "Acme"    # every field of rows matching company or role
    python3 Tooling/agent/notion_q.py row "Acme" --full   # with the whole Posting Snapshot
    python3 Tooling/agent/notion_q.py company "Acme"  # the Companies row
    python3 Tooling/agent/notion_q.py --json ...      # raw flattened JSON instead of a table
    python3 Tooling/agent/notion_q.py snapshot        # rewrite tracker_snapshot.md (the agent does this each run)

Read-only against Notion. The only file it writes is tracker_snapshot.md.
"""

import argparse
import json
import sys
from pathlib import Path
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import data_dir as _ks_data_dir  # agent state lives in the data folder

import requests

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import job_search_agent as jsa   # noqa: E402
from ats_tools import request_with_retry   # noqa: E402

OPEN_FILTER = {"or": [{"property": "Status", "status": {"equals": s}} for s in jsa.OPEN_STATUSES]}
SENT_FILTER = {"or": [{"property": "Status", "status": {"equals": s}}
                      for s in ("Applied", "Interviewing", "Offer", "Rejected")]}


def query(database_id, flt=None, sorts=None):
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload, rows = {"page_size": 100}, []
    if flt:
        payload["filter"] = flt
    if sorts:
        payload["sorts"] = sorts
    while True:
        resp = request_with_retry(requests.post, url, headers=jsa.NOTION_HEADERS, json=payload, timeout=60)
        if resp.status_code >= 300:
            sys.exit(f"Notion query failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        payload["start_cursor"] = data["next_cursor"]


def flat(page, full=False):
    """Every property as a short string."""
    out = {"id": page["id"], "created": page.get("created_time", "")[:10],
           "edited": page.get("last_edited_time", "")[:10], "url": page.get("url")}
    for name, prop in page.get("properties", {}).items():
        t = prop.get("type")
        v = prop.get(t)
        if t in ("title", "rich_text"):
            s = "".join(x.get("plain_text", "") for x in (v or []))
            if name == "Posting Snapshot" and not full:
                s = (s[:300] + f"... [{len(s)} chars, --full for all]") if len(s) > 300 else s
        elif t in ("select", "status"):
            s = (v or {}).get("name")
        elif t == "multi_select":
            s = ", ".join(x["name"] for x in (v or []))
        elif t == "date":
            s = (v or {}).get("start")
        elif t == "relation":
            s = ", ".join(x["id"] for x in (v or []))
        elif t == "formula":
            s = (v or {}).get((v or {}).get("type"))
        elif t in ("number", "url", "checkbox", "email", "phone_number"):
            s = v
        elif t in ("created_time", "last_edited_time"):
            s = (v or "")[:10]
        else:
            s = None
        if s not in (None, "", []):
            out[name] = s
    return out


def table(rows, cols):
    rows = [{c: ("" if r.get(c) is None else str(r.get(c))) for c in cols} for r in rows]
    widths = {c: min(max([len(c)] + [len(r[c]) for r in rows]), 42) for c in cols}
    def line(r):
        return "  ".join(r[c][:widths[c]].ljust(widths[c]) for c in cols)
    print(line({c: c for c in cols}))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print(line(r))
    print(f"({len(rows)} rows)")


APP_COLS = ["Role Fit Score", "Research Tier", "Overall Verdict", "Company", "Role", "Posted Date",
            "Last Verified", "Pay Basis", "Base Salary", "Status"]
SENT_COLS = ["Date Applied", "Status", "Company", "Role", "Outcome Type", "Outcome Date",
             "Resume Versions", "Cover Letter Versions", "Drafting Started", "Follow-up Date"]


SNAPSHOT_FILE = _ks_data_dir() / "tracker_snapshot.md"
SNAPSHOT_COLS = ["Role Fit Score", "Research Tier", "Overall Verdict", "Company", "Role", "Posted Date",
                 "Pay Basis", "Base Salary", "Status", "Job Posting"]


def write_snapshot(open_pages=None, sent_pages=None):
    """Compact tracker snapshot for chat sessions, written at the end of every
    agent run (Oct 29, 2026). A session reads this file (a few KB) instead of
    pulling rows through the Notion connector; it verifies one row by a
    targeted fetch only before writing to it. Returns the text."""
    from io import StringIO
    import contextlib
    from datetime import datetime
    open_rows = [flat(p) for p in (open_pages if open_pages is not None else
                                   query(jsa.NOTION_DATABASE_ID, OPEN_FILTER,
                                         sorts=[{"property": "Role Fit Score", "direction": "descending"}]))]
    sent_rows = [flat(p) for p in (sent_pages if sent_pages is not None else
                                   query(jsa.NOTION_DATABASE_ID, SENT_FILTER,
                                         sorts=[{"property": "Date Applied", "direction": "descending"}]))]
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"# Tracker snapshot, {datetime.now().isoformat(timespec='minutes')}")
        print("Written by the local agent after each run. Notion is the live view; this is the cheap one.")
        print("Rows edited since the last run are not reflected. Verify a row with one targeted fetch before writing to it.\n")
        print(f"## Open rows ({len(open_rows)}), by fit")
        table(open_rows, SNAPSHOT_COLS)
        print(f"\n## Sent ({len(sent_rows)}), newest first")
        table(sent_rows, SENT_COLS)
    text = buf.getvalue()
    try:
        SNAPSHOT_FILE.write_text(text)
    except OSError as e:
        print(f"[warn] tracker snapshot not written: {e}", file=sys.stderr)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["open", "pursue", "ask", "sent", "counts", "row", "company", "snapshot"])
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--tier", choices=["A", "B", "C"])
    ap.add_argument("--full", action="store_true", help="whole Posting Snapshot in `row`")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not jsa.NOTION_TOKEN:
        sys.exit("NOTION_TOKEN missing (Tooling/agent/.env)")

    if a.what == "snapshot":
        print(write_snapshot())
        return

    if a.what in ("open", "pursue", "ask"):
        flt = OPEN_FILTER
        if a.what == "pursue":
            flt = {"property": "Overall Verdict", "select": {"equals": "Applying"}}
        elif a.what == "ask":
            flt = {"and": [OPEN_FILTER, {"property": "Overall Verdict", "select": {"equals": "Possible fit"}}]}
        if a.tier:
            flt = {"and": [flt, {"property": "Research Tier", "select": {"equals": jsa.fit_scoring.TIER_NAMES[a.tier]}}]}
        rows = [flat(p) for p in query(jsa.NOTION_DATABASE_ID, flt,
                                       sorts=[{"property": "Role Fit Score", "direction": "descending"}])]
        return print(json.dumps(rows, indent=1)) if a.json else table(rows, APP_COLS)

    if a.what == "sent":
        rows = [flat(p) for p in query(jsa.NOTION_DATABASE_ID, SENT_FILTER,
                                       sorts=[{"property": "Date Applied", "direction": "descending"}])]
        return print(json.dumps(rows, indent=1)) if a.json else table(rows, SENT_COLS)

    if a.what == "counts":
        rows = [flat(p) for p in query(jsa.NOTION_DATABASE_ID)]
        from collections import Counter
        by_status = Counter(r.get("Status") for r in rows)
        by_verdict = Counter(r.get("Overall Verdict") for r in rows if r.get("Status") in jsa.OPEN_STATUSES)
        by_tier = Counter(r.get("Research Tier") for r in rows if r.get("Status") in jsa.OPEN_STATUSES)
        print(f"{len(rows)} rows")
        print("by Status:", dict(by_status.most_common()))
        print("open rows by Verdict:", dict(by_verdict.most_common()))
        print("open rows by Tier:", dict(by_tier.most_common()))
        return

    if a.what == "row":
        if not a.text:
            sys.exit("row needs text to match on Company or Role")
        flt = {"or": [{"property": "Company", "rich_text": {"contains": a.text}},
                      {"property": "Role", "title": {"contains": a.text}}]}
        rows = [flat(p, full=a.full) for p in query(jsa.NOTION_DATABASE_ID, flt)]
        if a.json:
            return print(json.dumps(rows, indent=1))
        for r in rows:
            print("=" * 70)
            for k, v in r.items():
                print(f"{k}: {v}")
        return print(f"({len(rows)} rows)")

    if a.what == "company":
        flt = {"property": "Company", "title": {"contains": a.text}} if a.text else None
        rows = [flat(p, full=a.full) for p in query(jsa.NOTION_COMPANIES_DATABASE_ID, flt)]
        if a.json:
            return print(json.dumps(rows, indent=1))
        for r in rows:
            print("=" * 70)
            for k, v in r.items():
                print(f"{k}: {v}")
        return print(f"({len(rows)} rows)")


if __name__ == "__main__":
    main()
