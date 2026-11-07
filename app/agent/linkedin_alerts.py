#!/usr/bin/env python3
"""
LinkedIn Job Alert emails as a capture source (added 2026-10-21).
------------------------------------------------------------------
The user gets daily Job Alert digests from jobalerts-noreply@linkedin.com. This
reads them over IMAP with a Gmail app password and turns each job card into
the same job dict the rest of the agent uses, at zero tokens. It never
touches linkedin.com itself (that was ruled out in September on terms-of-
service grounds); the email is the source.

Each card in the plain-text body looks like:

    Principal Product Manager, Platform and Shared Capabilities
    Maple Learning
    United States

    3 school alumni
    View job: https://www.linkedin.com/comm/jobs/view/4000000001/?trackingId=...

Cards are separated by a dashed line. Title, company, and location are the
first three lines; badge lines ("Fast growing", "107 company alumni") are
ignored; the job id comes from the View job URL.

What a lead does and does not carry: title, company, location, LinkedIn job
id and a clean URL, the alert date (approximate posting date). No salary, no
description, so the agent scores it title-only (NO SNAPSHOT) and the row shows
Remote Status Unverified until someone reads the posting. City-only locations
("Charlotte, NC") fail the agent's location filter, so only "United States"
and remote-worded leads get in. If the same role is on a company board the
agent already fetches, the board copy wins and the LinkedIn copy is dropped.

Where it looks: All Mail (inbox, archive, Updates tab) and Trash. Trash
matters: in one mailbox nearly every alert had been moved to Trash within
hours of arriving (a filter or another tool), and All
Mail excludes Trash, so the first run saw one email out of about twenty.
Gmail keeps trashed mail for 30 days, far longer than the lookback window,
so reading Trash loses nothing. Everything is opened read-only; nothing is
moved, labelled, or deleted.

Setup (one time): a Gmail app password (Google Account > Security > 2-Step
Verification > App passwords). An app password gives full access to the mailbox,
not just these alerts, so keep .env private (the kit locks it to your account) and
revoke the password in your Google Account if you stop using this. Then in .env:
    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
Test: python3 linkedin_alerts.py
"""

import email
import email.utils
import imaplib
import os
import re
import sys
from datetime import date, datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:  # pragma: no cover
    pass

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
ALERT_SENDER = "jobalerts-noreply@linkedin.com"
IMAP_HOST = "imap.gmail.com"
LOOKBACK_DAYS = int(os.environ.get("LINKEDIN_ALERT_DAYS", "3"))

VIEW_RE = re.compile(r"View job:\s*(https?://www\.linkedin\.com/(?:comm/)?jobs/view/(\d{6,}))", re.I)
BADGE_RE = re.compile(r"^(\d[\d,]*\s+(school|company)\s+alum\w*|this company is actively hiring|fast growing|"
                      r"actively recruiting|be an early applicant|\d+\s+connections?.*|promoted|"
                      r"\d+\s+applicants?.*|easy apply|your (profile|skills) match.*|see who you know.*)$", re.I)
SEPARATOR_RE = re.compile(r"\n-{10,}\n")


def _clean_lines(block):
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in block.split("\n")]
    return [ln for ln in lines if ln]


def parse_alert_text(text, email_date=None):
    """Plain-text alert body -> list of job dicts."""
    email_date = email_date or date.today()
    pub = email_date.isoformat() if hasattr(email_date, "isoformat") else str(email_date)[:10]
    # Real emails arrive with CRLF line endings; the dashed separator only
    # matches on bare newlines, and without this every digest collapsed into
    # one block and yielded only its first card (found 2026-10-21).
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    jobs = []
    for block in SEPARATOR_RE.split(text):
        m = VIEW_RE.search(block)
        if not m:
            continue
        url, job_id = m.group(1), m.group(2)
        head = block[:m.start()]
        lines = [ln for ln in _clean_lines(head) if not BADGE_RE.match(ln)]
        # The first block starts with "Your job alert for ... in ..."; drop it.
        lines = [ln for ln in lines if not ln.lower().startswith("your job alert for")]
        if len(lines) < 2:
            continue
        title, company = lines[0], lines[1]
        location = lines[2] if len(lines) >= 3 else ""
        jobs.append({
            "source": "LinkedIn",
            "id": f"linkedin-{job_id}",
            "title": title,
            "company": company,
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
            "location": location,
            "salary_text": "",
            "description": "",
            "published": pub,
            "published_approx": True,
        })
    return jobs


def _text_part(msg):
    """Prefer the text/plain part; fall back to a stripped HTML part."""
    plain, html_body = "", ""
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            body = payload.decode(charset, errors="replace")
        except LookupError:
            body = payload.decode("utf-8", errors="replace")
        if ctype == "text/plain" and not plain:
            plain = body
        elif ctype == "text/html" and not html_body:
            html_body = body
    if plain:
        return plain
    text = re.sub(r"<br\s*/?>|</p>|</div>|</td>|</tr>", "\n", html_body, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def _subject(msg):
    raw = msg.get("Subject", "")
    out = []
    for chunk, enc in decode_header(raw):
        out.append(chunk.decode(enc or "utf-8", errors="replace") if isinstance(chunk, bytes) else chunk)
    return "".join(out)


LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>"[^"]*"|\S+)$')
DEFAULT_MAILBOXES = {"All": '"[Gmail]/All Mail"', "Trash": '"[Gmail]/Trash"'}


def special_mailboxes(list_lines):
    """Pick the All Mail and Trash folders out of an IMAP LIST response by
    their special-use flags (\\All, \\Trash), so a renamed or localised Gmail
    still works. Falls back to the English Gmail names."""
    found = dict(DEFAULT_MAILBOXES)
    for raw in list_lines or []:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        m = LIST_RE.match(line.strip())
        if not m:
            continue
        flags = m.group("flags").lower()
        name = m.group("name")
        if not name.startswith('"'):
            name = f'"{name}"'
        if "\\all" in flags:
            found["All"] = name
        elif "\\trash" in flags:
            found["Trash"] = name
    return found


def _alert_messages(box, mailbox, since, cap=40):
    """Yield (message, mailbox) for alert emails in one folder, newest-last.
    A folder that can't be opened is skipped with a warning."""
    status, _ = box.select(mailbox, readonly=True)
    if status != "OK":
        print(f"[warn] LinkedIn alerts: could not open {mailbox}", file=sys.stderr)
        return
    status, data = box.search(None, "FROM", f'"{ALERT_SENDER}"', "SINCE", since)
    if status != "OK":
        raise imaplib.IMAP4.error(f"search failed in {mailbox}: {status}")
    for num in data[0].split()[-cap:]:  # never more than `cap` emails per folder
        status, parts = box.fetch(num, "(RFC822)")
        if status != "OK" or not parts or not parts[0]:
            continue
        msg = email.message_from_bytes(parts[0][1])
        # IMAP FROM is a substring match; only the exact sender counts (not a look-alike
        # domain or a display name that merely contains it)
        if email.utils.parseaddr(msg.get("From", ""))[1].lower() != ALERT_SENDER.lower():
            continue
        yield msg, mailbox


def fetch_linkedin_alerts(days=LOOKBACK_DAYS):
    """All job cards from LinkedIn alert emails received in the last `days`
    days, from All Mail and Trash. Returns [] with one [warn] line when
    credentials are missing or the mailbox can't be reached, so the run never
    stops here."""
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        print("[warn] LinkedIn alerts skipped: GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env "
              "(see linkedin_alerts.py for the one-time setup).", file=sys.stderr)
        return []
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    jobs, seen_ids, seen_msgs = [], set(), set()
    emails, in_trash = 0, 0
    try:
        box = imaplib.IMAP4_SSL(IMAP_HOST, timeout=60)  # a dropped connection hung the Oct 24 run for a day
        box.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        status, listing = box.list()
        folders = special_mailboxes(listing if status == "OK" else [])
        for kind in ("All", "Trash"):
            for msg, mailbox in _alert_messages(box, folders[kind], since):
                msg_id = msg.get("Message-ID") or f"{mailbox}:{msg.get('Date')}:{_subject(msg)}"
                if msg_id in seen_msgs:
                    continue
                seen_msgs.add(msg_id)
                emails += 1
                if kind == "Trash":
                    in_trash += 1
                try:
                    when = parsedate_to_datetime(msg.get("Date")).date()
                except (TypeError, ValueError):
                    when = date.today()
                for job in parse_alert_text(_text_part(msg), when):
                    if job["id"] in seen_ids:
                        continue  # the same job repeats across daily digests
                    seen_ids.add(job["id"])
                    job["alert_subject"] = _subject(msg)
                    jobs.append(job)
        box.logout()
    except (imaplib.IMAP4.error, OSError) as e:
        print(f"[warn] LinkedIn alerts: could not read Gmail over IMAP: {e}", file=sys.stderr)
        return jobs
    print(f"  LinkedIn alerts: {emails} email(s) ({in_trash} in Trash), {len(jobs)} distinct job card(s)",
          file=sys.stderr)
    return jobs


if __name__ == "__main__":
    found = fetch_linkedin_alerts()
    for j in found:
        print(f"- {j['title']} @ {j['company']} ({j['location']}) {j['published']} -> {j['url']}")
    if not found:
        print("No leads parsed. If credentials are set, check that alerts arrived in the last "
              f"{LOOKBACK_DAYS} days and that IMAP is enabled in Gmail settings.")
