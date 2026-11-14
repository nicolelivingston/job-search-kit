#!/usr/bin/env python3
"""Skills watch: what the postings in your search keep asking for, and where
you stand on each skill.

Reuses the daily agent's fetchers to pull every live posting from your
sources, keeps the ones that match your titles, location, and industry
screens, and counts how many ask for each skill on your list. Each skill
carries your status:

  Skilled      your evidence bank backs it with real examples
  Partial gap  you have some examples, but not the full ask
  Gap          you can't back it with an example yet

Your skills list comes from, in order: market_report.SKILLS (the Skills page
on the tracker page writes it), the older market_report.LEXICON, or, when
both are empty, your evidence bank's keyword groups (fit_scoring.WORK_FAMILIES
as Skilled, fit_scoring.GAP_FAMILIES as Gap).

Each run writes into your data folder:
  Market_Snapshot_<date>.md   the full report (pay, levels, skills, companies)
  market_history.jsonl        one line per snapshot, so trends build up
  market_skills_latest.json   the ranked table the Skills page shows
and, when your tracker is Notion and market_report.NOTION_DATABASE_ID is set,
rewrites one row per skill in that Notion database.

The daily run refreshes it every market_report.REFRESH_DAYS days (default 7),
and the next morning after you change your skills list.
Run on demand:  python3 market_report.py      (AGENT_DRY_RUN=1 skips Notion)
"""

import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
import kit_settings  # noqa: E402
from kit_settings import setting as _S  # noqa: E402  personal settings live in the settings folder

STATUSES = ("Skilled", "Partial gap", "Gap")
_STATUS_WORDS = {"skilled": "Skilled", "have": "Skilled", "partial gap": "Partial gap", "partial": "Partial gap",
                 "gap": "Gap"}

LEVEL_BUCKETS = [tuple(x) for x in _S("market_report.LEVEL_BUCKETS", default=[["All", ""]])]
SALARY_RANGE = tuple(_S("market_report.SALARY_RANGE", default=[20000, 1000000]))
REFRESH_DAYS = int(_S("market_report.REFRESH_DAYS", default=7))
NOTION_SKILLS_DB = _S("market_report.NOTION_DATABASE_ID", default="")


# ---------- skills (pure, tested in agent_tests/test_skills_watch.py) ----------

def normalize_status(value):
    s = _STATUS_WORDS.get(str(value or "").strip().lower())
    if not s:
        raise ValueError(f"status {value!r} must be one of {', '.join(STATUSES)}")
    return s


def phrases_pattern(phrases):
    """Whole-word phrases, case-insensitive, the same way keyword groups read:
    a phrase that starts with "~" is a raw regular expression."""
    parts = []
    for p in phrases:
        p = str(p).strip()
        if not p:
            continue
        if p.startswith("~"):
            parts.append(p[1:])
        else:
            parts.append(r"(?<!\w)" + re.escape(p).replace(r"\ ", r"\s+") + r"(?!\w)")
    return "|".join(parts)


def _skill(name, pattern, status, evidence="", track=True, keywords=None, source="settings"):
    re.compile(pattern, re.I)
    return {"name": str(name).strip(), "pattern": pattern, "status": normalize_status(status),
            "evidence": str(evidence or ""), "track": bool(track), "keywords": keywords or [], "source": source}


def from_settings(items):
    out = []
    for it in items or []:
        if not str(it.get("name", "")).strip():
            continue
        kws = [k for k in (it.get("keywords") or []) if str(k).strip()]
        pattern = it.get("pattern") or phrases_pattern(kws)
        if not pattern:
            continue
        out.append(_skill(it["name"], pattern, it.get("status", "Gap"), it.get("evidence", ""),
                          it.get("track", True), kws))
    return out


def from_lexicon(rows):
    return [_skill(n, p, s, source="lexicon") for n, p, s in rows or []]


def _family_phrases(v):
    """The phrases inside a keyword group's {"$rx": [...]} value."""
    return v.get("$rx", []) if isinstance(v, dict) else []


def from_keyword_groups(groups):
    """Work families (label, cards, points, phrases) as Skilled, gap families
    (label, points, phrases) as Gap, straight from keyword-groups.json."""
    fs = (groups or {}).get("fit_scoring", {})
    out, seen = [], set()
    for kind, status in (("WORK_FAMILIES", "Skilled"), ("GAP_FAMILIES", "Gap")):
        for fam in fs.get(kind, []):
            t = fam.get("$tuple") if isinstance(fam, dict) else fam
            if not isinstance(t, (list, tuple)) or len(t) < 3:
                continue
            label, phrases = t[0], _family_phrases(t[-1])
            cards = t[1] if kind == "WORK_FAMILIES" and isinstance(t[1], str) else ""
            pattern = phrases_pattern(phrases)
            if label in seen or not pattern:
                continue
            seen.add(label)
            out.append(_skill(label, pattern, status, cards, True, list(phrases), source="evidence bank"))
    return out


def _read_keyword_groups():
    try:
        return json.loads(kit_settings.keyword_groups_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_skills():
    """(skills, source): the list the report counts, and where it came from."""
    s = from_settings(_S("market_report.SKILLS", default=[]))
    if s:
        return s, "settings"
    s = from_lexicon(_S("market_report.LEXICON", default=[]))
    if s:
        return s, "lexicon"
    s = from_keyword_groups(_read_keyword_groups())
    return s, ("evidence bank" if s else "none")


def pattern_key(pattern):
    return hashlib.sha1(pattern.encode()).hexdigest()[:8]


def lexicon_keys(skills):
    return {s["name"]: pattern_key(s["pattern"]) for s in skills}


def count_matches(skills, texts):
    out = {}
    for s in skills:
        rx = re.compile(s["pattern"], re.I)
        out[s["name"]] = sum(1 for t in texts if rx.search(t or ""))
    return out


def applications_dir():
    return kit_settings.settings_dir().parent / "Applications"


def application_texts(folder=None):
    folder = Path(folder or applications_dir())
    return [p.read_text(encoding="utf-8", errors="ignore") for p in sorted(folder.glob("*/posting.md"))]


# ---------- history and ranking ----------

def history_file():
    return kit_settings.data_dir() / "market_history.jsonl"


def latest_file():
    return kit_settings.data_dir() / "market_skills_latest.json"


def load_history(path=None):
    p = Path(path or history_file())
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue   # one damaged line never loses the rest
    return sorted(rows, key=lambda r: r.get("date", ""))


def previous_entry(history, today):
    earlier = [h for h in history if h.get("date", "") < today]
    return earlier[-1] if earlier else None


def _ranks(counts, names):
    order = sorted(names, key=lambda n: (-counts.get(n, 0), n))
    return {n: i + 1 for i, n in enumerate(order)}


def build_rows(skills, counts, matched, prev=None, app_counts=None):
    """One row per tracked skill, ranked by share of matched postings. Changes
    are worked out only against a snapshot that counted the same skill with
    the same keywords; otherwise they stay None (shown as "new")."""
    tracked = [s for s in skills if s["track"]]
    names = [s["name"] for s in tracked]
    ranks = _ranks(counts, names)
    prev_counts = (prev or {}).get("counts", {})
    prev_keys = (prev or {}).get("keys", {})
    prev_matched = (prev or {}).get("matched", 0)
    prev_ranks = _ranks(prev_counts, [n for n in names if n in prev_counts])
    rows = []
    for s in tracked:
        n = s["name"]
        share = counts.get(n, 0) / matched if matched else 0.0
        same = bool(prev and prev_matched and n in prev_counts and prev_keys.get(n) == pattern_key(s["pattern"]))
        rows.append({
            "name": n, "status": s["status"], "evidence": s["evidence"],
            "rank": ranks[n], "postings": counts.get(n, 0), "matched": matched,
            "share": round(share, 4),
            "share_change": round(share - prev_counts[n] / prev_matched, 4) if same else None,
            "rank_change": (prev_ranks[n] - ranks[n]) if same and n in prev_ranks else None,
            "applications": (app_counts or {}).get(n),
        })
    return sorted(rows, key=lambda r: r["rank"])


def append_history(entry, path=None):
    """One line per date; a rerun the same day replaces that day's line."""
    p = Path(path or history_file())
    kept = [h for h in load_history(p) if h.get("date") != entry["date"]]
    kept.append(entry)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(h) + "\n" for h in sorted(kept, key=lambda r: r["date"])), encoding="utf-8")
    os.replace(tmp, p)


def skills_changed(skills=None, history=None):
    """True when the skills list (names or keywords) differs from the last
    snapshot's, so the next daily run refreshes the ranking."""
    if skills is None:
        skills, _ = load_skills()
    history = load_history() if history is None else history
    if not skills:
        return False
    if not history:
        return True
    return history[-1].get("keys", {}) != lexicon_keys(skills)


# ---------- Notion (optional) ----------

def notion_properties(row, today):
    num = lambda v: {"number": v}  # noqa: E731
    return {
        "Skill": {"title": [{"text": {"content": row["name"]}}]},
        "Status": {"select": {"name": row["status"]}},
        "Rank": num(row["rank"]),
        "Market Share": num(row["share"]),
        "Share Change": num(row["share_change"]),
        "Rank Change": num(row["rank_change"]),
        "Market Postings": num(row["postings"]),
        "Matched Postings": num(row["matched"]),
        "In Your Applications": num(row["applications"]),
        "Closest Evidence": {"rich_text": [{"text": {"content": row["evidence"][:1900]}}]},
        "Snapshot Date": {"date": {"start": today}},
    }


def sync_notion(rows, today):
    """Upsert one page per skill, matched by title, in the Notion database
    named by market_report.NOTION_DATABASE_ID. Returns (updated, created)."""
    import requests
    from job_search_agent import NOTION_TOKEN, NOTION_HEADERS, request_with_retry
    if not (NOTION_TOKEN and NOTION_SKILLS_DB):
        return 0, 0
    existing, cursor = {}, None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        r = request_with_retry(requests.post, f"https://api.notion.com/v1/databases/{NOTION_SKILLS_DB}/query",
                               headers=NOTION_HEADERS, json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
        for page in data["results"]:
            existing["".join(t["plain_text"] for t in page["properties"]["Skill"]["title"])] = page["id"]
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    updated = created = 0
    for row in rows:
        props = notion_properties(row, today)
        if row["name"] in existing:
            r = request_with_retry(requests.patch, f"https://api.notion.com/v1/pages/{existing[row['name']]}",
                                   headers=NOTION_HEADERS, json={"properties": props}, timeout=60)
            updated += 1
        else:
            r = request_with_retry(requests.post, "https://api.notion.com/v1/pages", headers=NOTION_HEADERS,
                                   json={"parent": {"database_id": NOTION_SKILLS_DB}, "properties": props}, timeout=60)
            created += 1
        r.raise_for_status()
    return updated, created


# ---------- report ----------

def level_of(title):
    t = title.lower()
    for name, pat in LEVEL_BUCKETS:
        if pat and re.search(pat, t):
            return name
    return "Unleveled"


def pct(n, d):
    return f"{100.0 * n / d:.0f}%" if d else "n/a"


def fmt_change(v, points=False):
    if v is None:
        return "new"
    if points:
        v = round(v * 100)
    return f"+{v}" if v > 0 else str(v)


def main():
    from job_search_agent import (
        fetch_remotive, fetch_remoteok, get_rejection_reason, industry_flag,
        extract_salary_min, matches_title,
    )
    from ats_tools import fetch_all_confirmed

    skills, source = load_skills()
    all_jobs = fetch_remotive() + fetch_remoteok() + fetch_all_confirmed()
    title_matched = [j for j in all_jobs if matches_title(j.get("title", ""))]
    matched = [j for j in title_matched if not get_rejection_reason(j)]
    matched = [j for j in matched
               if industry_flag((j.get("title", "") + " " + j.get("description", "")).lower()) != "Excluded"]

    lo, hi = SALARY_RANGE
    salaries = sorted(s for s in (extract_salary_min(j.get("salary_text", ""), j.get("description", ""))
                                  for j in matched) if s and lo <= s <= hi)

    def quantile(q):
        return salaries[min(len(salaries) - 1, int(q * len(salaries)))] if salaries else 0

    levels = Counter(level_of(j["title"]) for j in matched)
    counts = count_matches(skills, [j.get("description", "") for j in matched])
    app_texts = application_texts()
    app_counts = count_matches(skills, app_texts)
    today = datetime.now().strftime("%Y-%m-%d")
    prev = previous_entry(load_history(), today)
    rows = build_rows(skills, counts, len(matched), prev, app_counts)
    companies = Counter(j["company"].strip().title() for j in matched)

    L = [f"# Market snapshot, {today}", ""]
    L.append(f"Sources: Remotive, RemoteOK, and {len(set(j['source'] for j in all_jobs))} tracked "
             f"company boards. {len(all_jobs)} live postings scanned; {len(title_matched)} match your titles; "
             f"**{len(matched)} match your search** (titles, location, and industry screens).")
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
    for name, _ in LEVEL_BUCKETS + [("Unleveled", "")]:
        if levels.get(name):
            L.append(f"- {name}: {levels[name]} ({pct(levels[name], len(matched))})")
    L.append("")
    since = f" (changes since {prev['date']})" if prev else ""
    L.append(f"## Skills the market keeps asking for{since}")
    L.append("")
    if not rows:
        L.append("No skills on your list yet. Add them on the Skills page, or build your evidence bank's "
                 "keyword groups in the Start Here interviews.")
    else:
        if source == "evidence bank":
            L.append("_Skills come from your evidence bank's keyword groups. Edit them on the Skills page._")
            L.append("")
        L.append(f"| Rank | Skill | Postings | Share | Share change (pts) | Rank change | "
                 f"In your {len(app_texts)} saved postings | Status |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in rows:
            L.append(f"| {r['rank']} | {r['name']} | {r['postings']} | {pct(r['postings'], len(matched))} | "
                     f"{fmt_change(r['share_change'], points=True)} | {fmt_change(r['rank_change'])} | "
                     f"{r['applications']} | {r['status']} |")
    L.append("")
    L.append("## Most active matching companies right now")
    for co, n in companies.most_common(10):
        L.append(f"- {co}: {n}")
    L.append("")
    L.append("_Gap rows are skills you can't back with an example yet; never claim them. They show where "
             "to collect more examples or build more experience._")

    report = "\n".join(L)
    data = kit_settings.data_dir()
    (data / f"Market_Snapshot_{today}.md").write_text(report, encoding="utf-8")
    append_history({"date": today, "matched": len(matched), "counts": counts, "keys": lexicon_keys(skills),
                    "applications": app_counts, "applications_total": len(app_texts)})
    latest = {"date": today, "previous": prev["date"] if prev else None, "matched": len(matched),
              "applications_total": len(app_texts), "source": source, "rows": rows}
    tmp = latest_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(latest, indent=1), encoding="utf-8")
    os.replace(tmp, latest_file())
    print(report)

    if os.environ.get("AGENT_DRY_RUN", "") == "1" or "--dry-run" in sys.argv[1:]:
        return
    if kit_settings.tracker_mode() == "notion" and NOTION_SKILLS_DB:
        try:
            updated, created = sync_notion(rows, today)
            print(f"Skills in Notion: {updated} updated, {created} created.", file=sys.stderr)
        except Exception as e:   # noqa: BLE001  (the snapshot and history are already saved)
            print(f"[warn] Skills Notion sync failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
