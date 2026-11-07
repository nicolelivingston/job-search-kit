"""Tests for fresh Tier A email alerts and the 90-day repost window (Oct 25, 2026).

Run:  python3 agent_tests/test_fresh_alerts.py
No network calls and no email is sent: SMTP is replaced with a stub.
"""

import pathlib
import sys
import json
import tempfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import job_search_agent as jsa   # noqa: E402

TODAY = date(2026, 10, 25)
RESULTS = []


def check(name, ok):
    RESULTS.append(ok)
    print("  [%s] %s" % ("PASS" if ok else "FAIL", name))


def job(i, days_old, company="Acme", title="Senior Product Manager"):
    return {"id": f"ashby-x-{i}", "title": title, "company": company,
            "url": f"https://jobs.ashbyhq.com/x/{i}", "location": "Remote",
            "published": (TODAY - timedelta(days=days_old)).isoformat()}


def res(tier="A", score=88, verdict=None):
    return {"tier": tier, "score": score, "verdict": verdict, "evidence": "workflow, governance"}


print("fresh alert rules")
written = [
    (job(1, 0), res(), "", 160000),
    (job(2, 2), res(score=81), "", None),
    (job(3, 3), res(), "", None),                      # too old
    (job(4, 0), res(tier="B"), "", None),              # not Tier A
    (job(5, 0), res(verdict="Poor fit"), "", None),        # hard-rule skip
    ({**job(6, 0), "published": ""}, res(), "", None), # unknown age, no history
]
c = jsa.fresh_alert_candidates(written, history={}, today=TODAY)
check("only Tier A, non-Skip, 0-2 days old alert", [m[0]["id"] for m in c] == ["ashby-x-1", "ashby-x-2"])
subj, body = jsa.fresh_alert_message(c)
check("subject leads with [Fresh Tier A] and counts extras",
      subj.startswith("[Fresh Tier A] Acme – Senior Product Manager, 88 fit, posted today") and subj.endswith("(+1 more)"))
check("no em dashes in subject or body", "—" not in subj + body)
check("body carries both links", "x/1" in body and "x/2" in body)

print("send: own inbox only, one alert per posting")
sent_msgs = []


class FakeSMTP:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, *a): pass
    def send_message(self, msg): sent_msgs.append(msg)


orig = (jsa.smtplib.SMTP_SSL, jsa.FRESH_ALERTS_SENT_FILE, jsa.GMAIL_ADDRESS, jsa.GMAIL_APP_PASSWORD)
with tempfile.TemporaryDirectory() as d:
    jsa.smtplib.SMTP_SSL = FakeSMTP
    jsa.FRESH_ALERTS_SENT_FILE = pathlib.Path(d) / "sent.json"
    jsa.GMAIL_ADDRESS, jsa.GMAIL_APP_PASSWORD = "me@example.com", "x"
    n1 = jsa.send_fresh_alerts(written, {}, TODAY)
    n2 = jsa.send_fresh_alerts(written, {}, TODAY)
    check("first run sends 2, repeat run sends 0", n1 == 2 and n2 == 0 and len(sent_msgs) == 1)
    check("To and From are the user's own address", sent_msgs[0]["To"] == sent_msgs[0]["From"] == "me@example.com")
jsa.smtplib.SMTP_SSL, jsa.FRESH_ALERTS_SENT_FILE, jsa.GMAIL_ADDRESS, jsa.GMAIL_APP_PASSWORD = orig

print("v4.0: a failed alert is kept as text and retried next run")


class BrokenSMTP(FakeSMTP):
    def send_message(self, msg): raise jsa.smtplib.SMTPException("mail server down")


sent_msgs.clear()
orig2 = orig + (jsa.FRESH_ALERTS_PENDING_FILE, jsa.notify)
with tempfile.TemporaryDirectory() as d:
    jsa.FRESH_ALERTS_SENT_FILE = pathlib.Path(d) / "sent.json"
    jsa.FRESH_ALERTS_PENDING_FILE = pathlib.Path(d) / "pending.json"
    jsa.GMAIL_ADDRESS, jsa.GMAIL_APP_PASSWORD = "me@example.com", "x"
    jsa.notify = lambda *a, **k: None
    jsa.smtplib.SMTP_SSL = BrokenSMTP
    n1 = jsa.send_fresh_alerts(written, {}, TODAY)
    pend = json.loads(jsa.FRESH_ALERTS_PENDING_FILE.read_text())
    check("failed send writes the message text and ids only", n1 == 0 and set(pend) == {"ids", "subject", "body"} and len(pend["ids"]) == 2)
    check("...and nothing from the rows beyond title, company, and link", "salary" not in json.dumps(pend).lower() and "breakdown" not in json.dumps(pend).lower())
    jsa.smtplib.SMTP_SSL = FakeSMTP
    n2 = jsa.send_fresh_alerts([], {}, TODAY)
    check("next run resends the pending alert and clears it", n2 == 2 and len(sent_msgs) == 1 and not jsa.FRESH_ALERTS_PENDING_FILE.exists())
    check("retry carries the links", all(f"x/{i}" in sent_msgs[0].get_payload(decode=True).decode() for i in (1, 2)))
jsa.smtplib.SMTP_SSL, jsa.FRESH_ALERTS_SENT_FILE, jsa.GMAIL_ADDRESS, jsa.GMAIL_APP_PASSWORD, jsa.FRESH_ALERTS_PENDING_FILE, jsa.notify = orig2

print("90-day repost window")
key = "acme::senior product manager"
old = (TODAY - timedelta(days=60)).isoformat()
history = {key: {"ids": {"gh-acme-1": old, "gh-acme-2": TODAY.isoformat()},
                 "locations": {"remote": old},
                 "id_locs": {"gh-acme-1": "remote", "gh-acme-2": "remote"}}}
note, flag, _skip, _ = jsa.assess_posting_health(history, key, TODAY, {"title": "Senior Product Manager"})
check("close-and-reopen 60 days apart is flagged as a repost", flag and "reposted" in (note or ""))
very_old = (TODAY - timedelta(days=100)).isoformat()
history[key]["ids"]["gh-acme-1"] = very_old
_, flag2, _, _ = jsa.assess_posting_health(history, key, TODAY, {"title": "Senior Product Manager"})
check("an ID first seen 100 days ago no longer counts", not flag2)
check("retention covers the repost window", jsa.HISTORY_RETENTION_DAYS >= jsa.REPOST_WINDOW_DAYS)

print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
sys.exit(0 if all(RESULTS) else 1)
