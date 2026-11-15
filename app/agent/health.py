#!/usr/bin/env python3
"""Search health: one page that shows how your search is going.

Reads the built-in tracker and your contacts and works out, for today:
  - a few headline numbers (in progress, interviews, sent in the last 30 days,
    interview rate, this week against your weekly target)
  - what needs you today (interviews, follow-ups due, open drafts, rows you
    marked Applying but haven't sent, Strong fit rows waiting on your call,
    and applications with no reply after a while)
  - applications sent per week, last 8 weeks, against your weekly target
  - whether drafting is getting easier (resume versions and days from first
    draft to sending, recent sends against earlier ones)

Your targets are settings you own, changed on the Health page itself:
  health.WEEKLY_TARGET     applications a week you're aiming for (0 hides the line)
  health.CONTACTS_TARGET   contact touches a week you're aiming for (0 hides the tile)
  health.NO_REPLY_DAYS     days with no reply before an application shows as likely ghosted
  health.GOAL_DATE         optional end date for your search (YYYY-MM-DD); shows days left

Nothing here writes to the tracker. summarize() is pure and tested in
agent_tests/test_health.py.
"""
import json
import re
import statistics
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kit_settings  # noqa: E402
from kit_settings import setting as _S  # noqa: E402

DEFAULTS = {"WEEKLY_TARGET": 3, "CONTACTS_TARGET": 2, "NO_REPLY_DAYS": 30, "GOAL_DATE": ""}
LIMITS = {"WEEKLY_TARGET": 50, "CONTACTS_TARGET": 50, "NO_REPLY_DAYS": 365}
WEEKS = 8
SENT_STATUSES = ("Applied", "Interviewing", "Offer", "Rejected", "Closed")
INTERVIEW_OUTCOME = re.compile(r"screen|interview|offer", re.I)
ATTENTION_MAX = 12


def targets():
    """The user's targets, read fresh so a change on the page shows at once."""
    kit_settings._cache.clear()
    out = {}
    out["WEEKLY_TARGET"] = int(_S("health.WEEKLY_TARGET", default=DEFAULTS["WEEKLY_TARGET"]))
    out["CONTACTS_TARGET"] = int(_S("health.CONTACTS_TARGET", default=DEFAULTS["CONTACTS_TARGET"]))
    out["NO_REPLY_DAYS"] = int(_S("health.NO_REPLY_DAYS", default=DEFAULTS["NO_REPLY_DAYS"]))
    out["GOAL_DATE"] = str(_S("health.GOAL_DATE", default=DEFAULTS["GOAL_DATE"]) or "")
    return out


def clean_targets(body):
    """Check targets from the page. Returns (values, error). Nothing is saved on an error."""
    out = {}
    for k in ("WEEKLY_TARGET", "CONTACTS_TARGET", "NO_REPLY_DAYS"):
        if k not in body:
            continue
        v = str(body[k] if body[k] is not None else "").strip()
        if not v.isdigit() or int(v) > LIMITS[k]:
            return None, f"{k.replace('_', ' ').lower()} must be a whole number from 0 to {LIMITS[k]}"
        if k == "NO_REPLY_DAYS" and int(v) == 0:
            return None, "days with no reply must be at least 1"
        out[k] = int(v)
    if "GOAL_DATE" in body:
        v = str(body["GOAL_DATE"] or "").strip()
        if v:
            try:
                date.fromisoformat(v)
            except ValueError:
                return None, "the goal date must look like 2027-03-31"
        out["GOAL_DATE"] = v
    return out, None


def save_targets(settings_dir, body):
    values, err = clean_targets(body)
    if err:
        return {"ok": False, "error": err}
    f = Path(settings_dir) / "criteria.json"
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    data.setdefault("health", {}).update(values)
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    kit_settings._cache.clear()
    return {"ok": True, "targets": targets()}


# ---------------------------------------------------------------- the summary (pure)

def _d(s):
    try:
        return date.fromisoformat(str(s or "")[:10])
    except ValueError:
        return None


def _monday(d):
    return d - timedelta(days=d.weekday())


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _is_sent(r):
    return r.get("Status") in SENT_STATUSES and _d(r.get("Date Applied")) is not None


def _interviewed(r):
    return r.get("Status") in ("Interviewing", "Offer") or bool(INTERVIEW_OUTCOME.search(r.get("Outcome Type") or ""))


def _round(x):
    if x is None:
        return None
    return int(x) if float(x).is_integer() else round(float(x), 1)


def summarize(rows, contacts, today, cfg, tracking_starts=None):
    """rows: tracker rows as plain dicts keyed by the tracker's field names.
    contacts: contact dicts with an optional "last" date. today: a date.
    cfg: targets(). tracking_starts: date drafting stats start from (or None)."""
    weekly_target = cfg.get("WEEKLY_TARGET", 0)
    no_reply = cfg.get("NO_REPLY_DAYS", DEFAULTS["NO_REPLY_DAYS"])
    sent = [r for r in rows if _is_sent(r)]
    in_progress = [r for r in rows if r.get("Status") in ("Applied", "Interviewing")]
    interviews = [r for r in rows if _interviewed(r)]
    cut30 = today - timedelta(days=30)
    sent_30 = [r for r in sent if _d(r["Date Applied"]) > cut30]
    week0 = _monday(today)
    sent_week = [r for r in sent if _d(r["Date Applied"]) >= week0]

    # applications sent per week, oldest first
    weeks = []
    for i in range(WEEKS - 1, -1, -1):
        w = week0 - timedelta(days=7 * i)
        n = sum(1 for r in sent if _monday(_d(r["Date Applied"])) == w)
        weeks.append({"week": w.isoformat(), "sent": n, "target": weekly_target or None,
                      "done": i > 0})
    finished = [w for w in weeks if w["done"]]
    weeks_hit = sum(1 for w in finished if weekly_target and w["sent"] >= weekly_target)

    # what needs you today
    attention = []
    for r in rows:
        st, base = r.get("Status"), {"id": r.get("id", ""), "company": r.get("Company") or "",
                                      "role": r.get("Role") or ""}
        applied, follow = _d(r.get("Date Applied")), _d(r.get("Follow-up Date"))
        outcome = r.get("Outcome Type") or ""
        if st == "Interviewing":
            attention.append({**base, "kind": "Interview", "level": "good", "order": 0,
                              "what": r.get("Next Step") or "Prep for the next conversation and keep the next step current."})
        if st in ("Applied", "Interviewing") and follow and follow <= today:
            attention.append({**base, "kind": "Follow-up due", "level": "warn", "order": 1,
                              "what": f"Follow-up date was {follow.isoformat()}."})
        if st == "Applied" and applied and not outcome and (today - applied).days >= no_reply:
            attention.append({**base, "kind": "No reply", "level": "bad", "order": 2,
                              "what": f"{(today - applied).days} days since you applied. Record what happened, or nudge a contact."})
        if st == "Drafting Resume":
            started = _d(r.get("Drafting Started"))
            v = _num(r.get("Resume Versions"))
            bits = [f"started {started.isoformat()}" if started else "", f"resume at version {int(v)}" if v else ""]
            bits = ", ".join(b for b in bits if b)
            attention.append({**base, "kind": "Draft open", "level": "warn", "order": 3,
                              "what": "Draft in progress" + (f" ({bits})" if bits else "") + ". Send it or close it."})
        if st == "Interested" and r.get("Overall Verdict") == "Applying":
            attention.append({**base, "kind": "Not sent yet", "level": "warn", "order": 4,
                              "what": "You marked this Applying. Start the draft, or mark it Passed."})
        if st == "Interested" and r.get("Overall Verdict") == "Strong fit":
            fit = _num(r.get("Role Fit Score"))
            attention.append({**base, "kind": "Your call", "level": "mute", "order": 5, "fit": fit or 0,
                              "what": "Strong fit" + (f", scored {round(fit * 10)}" if fit is not None else "") + ". Applying or Passed?"})
    attention.sort(key=lambda a: (a["order"], -a.get("fit", 0), a["company"].lower()))
    more = max(0, len(attention) - ATTENTION_MAX)
    attention = attention[:ATTENTION_MAX]

    # is drafting getting easier? sends since tracking began, in the order sent
    tracked = sorted((r for r in sent if tracking_starts is None or _d(r["Date Applied"]) >= tracking_starts),
                     key=lambda r: r["Date Applied"])
    versions = [_num(r.get("Resume Versions")) for r in tracked]
    days = []
    for r in tracked:
        s = _d(r.get("Drafting Started"))
        days.append((_d(r["Date Applied"]) - s).days if s else None)
    hours = [_num(r.get("Hours Spent")) for r in tracked]
    recent, earlier = versions[-5:], versions[:-5]
    drafting = {
        "sends": len(tracked),
        "versions_recent": _round(_median(recent)),
        "versions_earlier": _round(_median(earlier)),
        "days_median": _round(_median(days)),
        "hours_median": _round(_median(hours)),
        "hours_kept": sum(1 for h in hours if h is not None),
        "drafts_open": sum(1 for r in rows if r.get("Status") == "Drafting Resume"),
        "since": tracking_starts.isoformat() if tracking_starts else "",
    }

    # contact touches this week
    touches = [c for c in contacts if _d(c.get("last"))]
    contacts_out = {"target": cfg.get("CONTACTS_TARGET", 0),
                    "this_week": sum(1 for c in touches if _d(c["last"]) >= week0),
                    "last_4_weeks": sum(1 for c in touches if _d(c["last"]) >= week0 - timedelta(days=21)),
                    "people": len(contacts)}

    goal = _d(cfg.get("GOAL_DATE"))
    headline = {
        "in_progress": len(in_progress),
        "interviews": len(interviews),
        "sent_30": len(sent_30),
        "sent_total": len(sent),
        "interview_rate": round(100 * len(interviews) / len(sent)) if sent else None,
        "sent_week": len(sent_week),
        "weekly_target": weekly_target,
        "weeks_hit": weeks_hit if weekly_target else None,
        "weeks_finished": len(finished),
        "days_left": max(0, (goal - today).days) if goal else None,
        "goal_date": goal.isoformat() if goal else "",
        "open_postings": sum(1 for r in rows if r.get("Status") == "Interested"),
    }
    return {"today": today.isoformat(), "headline": headline, "attention": attention, "attention_more": more,
            "weeks": weeks, "drafting": drafting, "contacts": contacts_out, "targets": cfg,
            "takeaway": _takeaway(headline, attention, more)}


def _takeaway(h, attention, more):
    s = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"
    parts = [f"{s(h['in_progress'], 'application')} in progress", f"{s(h['interviews'], 'interview')} so far",
             f"{h['sent_30']} sent in the last 30 days"]
    waiting = len(attention) + more
    if waiting:
        parts.append(f"{s(waiting, 'thing')} waiting on you")
    return ", ".join(parts) + "."
