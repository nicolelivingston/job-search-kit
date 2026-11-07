#!/usr/bin/env python3
"""Market-worth snapshot for the user's job search.

Reuses the daily agent's fetchers to pull every live posting from the user's
sources, then reports on the slice matching their title/location/role
filters: how many roles, the salary distribution, the seniority mix, and
which requirements recur in descriptions (compared against their known
strengths and confirmed gaps). Writes Market_Snapshot_<date>.md into the data folder (was: next to
this script and prints the same report.

Run on demand:  python3 market_report.py
Worth running monthly; the snapshot files accumulate as a record of how
their market moves over time.
"""

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from job_search_agent import (
    fetch_remotive, fetch_remoteok, get_rejection_reason, industry_flag,
    extract_salary_min, matches_title, norm_title,
)
from ats_tools import fetch_all_confirmed
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S  # personal settings live in the settings folder, not the code

# Capability lexicon: what postings ask for, as regexes over description text.
# Tagged HAVE / PARTIAL / GAP against the user's evidence bank (settings, criteria.json).
LEXICON = [tuple(x) for x in _S("market_report.LEXICON")]

LEVEL_BUCKETS = [tuple(x) for x in _S("market_report.LEVEL_BUCKETS")]


def level_of(title):
    t = title.lower()
    for name, pat in LEVEL_BUCKETS:
        if pat and re.search(pat, t):
            return name
    return "PM (unleveled)"


def pct(n, d):
    return f"{100.0 * n / d:.0f}%" if d else "n/a"


def main():
    all_jobs = fetch_remotive() + fetch_remoteok() + fetch_all_confirmed()
    pm_titled = [j for j in all_jobs if matches_title(j.get("title", ""))]
    matched = [j for j in pm_titled if not get_rejection_reason(j)]
    matched = [j for j in matched
               if industry_flag((j.get("title", "") + " " + j.get("description", "")).lower()) != "Excluded"]

    salaries = []
    for j in matched:
        s = extract_salary_min(j.get("salary_text", ""), j.get("description", ""))
        if s and 100_000 <= s <= 600_000:
            salaries.append(s)
    salaries.sort()

    def quantile(q):
        return salaries[min(len(salaries) - 1, int(q * len(salaries)))] if salaries else 0

    levels = Counter(level_of(j["title"]) for j in matched)

    demand = []
    for name, pat, status in LEXICON:
        rx = re.compile(pat, re.I)
        n = sum(1 for j in matched if rx.search(j.get("description", "") or ""))
        demand.append((name, n, status))
    demand.sort(key=lambda x: -x[1])

    companies = Counter(j["company"].strip().title() for j in matched)

    today = datetime.now().strftime("%Y-%m-%d")
    L = [f"# Market snapshot — {today}", ""]
    L.append(f"Sources: Remotive, RemoteOK, and {len(set(j['source'] for j in all_jobs))} tracked "
             f"company boards. {len(all_jobs)} live postings scanned; {len(pm_titled)} PM-titled; "
             f"**{len(matched)} match your filters** (US-remote, PM level, industry screens).")
    L.append("")
    L.append("## What the matching market pays (posted minimum base)")
    if salaries:
        L.append(f"- {len(salaries)} of {len(matched)} matched postings disclose salary.")
        L.append(f"- 25th percentile: ${quantile(0.25):,.0f}  |  median: ${quantile(0.5):,.0f}  |  "
                 f"75th percentile: ${quantile(0.75):,.0f}  |  top: ${salaries[-1]:,.0f}")
    else:
        L.append("- No parseable salary data this run.")
    L.append("")
    L.append("## Seniority mix of matching roles")
    for name, _ in LEVEL_BUCKETS:
        if levels.get(name):
            L.append(f"- {name}: {levels[name]} ({pct(levels[name], len(matched))})")
    L.append("")
    L.append("## What the market keeps asking for (share of matched postings)")
    L.append("")
    L.append("| Capability | Postings | Share | You |")
    L.append("|---|---|---|---|")
    for name, n, status in demand:
        L.append(f"| {name} | {n} | {pct(n, len(matched))} | {status} |")
    L.append("")
    L.append("## Most active matching companies right now")
    for co, n in companies.most_common(10):
        L.append(f"- {co}: {n}")
    L.append("")
    L.append("_GAP rows are from the accomplishment bank's confirmed gaps; never claim them. "
             "They are the market's price signals for what to learn next._")

    report = "\n".join(L)
    from kit_settings import data_dir as _ks_data_dir
    out = _ks_data_dir() / f"Market_Snapshot_{today}.md"
    out.write_text(report)
    print(report)
    print(f"\nSaved to {out.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
