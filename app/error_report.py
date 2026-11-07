#!/usr/bin/env python3
"""Error report: save a scrubbed log bundle and open a new email with it.

The report holds only what a builder needs to debug a run: the kit version,
the operating system and Python version, the daily schedule, which settings
files exist, the tracker's row counts by status, the last 20 alerts, and the
error lines from the agent log (WARNING, ERROR, CRITICAL, and tracebacks with
the lines that follow them; at most the last 400 such lines). Ordinary INFO
lines never go in, so posting titles and company names the run mentioned
stay out. It never includes a posting, a resume, the evidence bank, settings
values, or the tracker rows themselves.

Before saving, every line is scrubbed: email addresses, phone numbers, the
user's home folder, web links (host kept, path dropped), anything that looks
like a token or key, anything that matches the user's name or contact line
from master-selection.json, and every company name and role title in the
tracker.

    python error_report.py            # save the report and open the email
    python error_report.py --save-only   # save the report, print its path

The email opens in the user's own mail app addressed to `support_email` in
settings/app.json (blank means the user fills in the address). Attaching a
file through a mailto link isn't possible, so on Windows the report is
attached through Outlook when Outlook is installed, on macOS through Mail;
otherwise the mail draft carries the report's path in its body and the
report's folder is opened so the user can drag the file in. The user always
presses Send.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
import kit_settings  # noqa: E402

LOG_LINES = 400
ALERT_LINES = 20
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TOKEN_RE = re.compile(r"(?i)((?:token|secret|password|api[_-]?key|authorization)\s*[:=]\s*).*$|\b(?:ntn_|secret_|ghp_|github_pat_)[A-Za-z0-9_-]{8,}")
ERROR_LINE_RE = re.compile(r"^(WARNING|ERROR|CRITICAL|Traceback|\s+File \"|[A-Za-z_.]*(Error|Exception)\b)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
URL_RE = re.compile(r"(https?://[^/\s]+)[^\s]*")


def _tracker_terms(data):
    """Company names and role titles in the built-in tracker: never in a report."""
    f = data / "tracker" / "applications.json"
    terms = []
    if f.exists():
        try:
            for p in json.loads(f.read_text(encoding="utf-8"))["pages"].values():
                pr = p.get("properties", {})
                for key in ("Company", "Role"):
                    v = pr.get(key) or {}
                    items = v.get("rich_text") or v.get("title") or []
                    text = "".join(x.get("plain_text") or x.get("text", {}).get("content", "") for x in items).strip()
                    if len(text) >= 3:
                        terms.append(text)
        except Exception:
            pass
    return terms


def _personal_terms():
    """Words from the user's own master selection that must not appear in a report."""
    terms = []
    for base in (kit_settings.settings_dir().parent, kit_settings.KIT_ROOT):
        f = base / "master-selection.json"
        if f.exists():
            try:
                sel = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for key in ("name", "contact"):
                for part in re.split(r"[|,]", str(sel.get(key, ""))):
                    part = part.strip()
                    if len(part) >= 3 and not part.startswith("<"):
                        terms.append(part)
    return terms


def scrub(text, extra_terms=(), home=None):
    home = str(home or Path.home())
    out = []
    for line in text.splitlines():
        line = line.replace(home, "~").replace(home.replace("\\", "\\\\"), "~")   # plain and repr'd (doubled backslash) forms
        if home.startswith("/Users/") or home.startswith("/home/"):
            line = re.sub(r"(/Users|/home)/[^/\s]+", "~", line)
        line = re.sub(r"[A-Za-z]:\\{1,2}Users\\{1,2}[^\\\s'\"]+", "~", line)
        # an exception message can quote data (a path, a value, posting text): keep the class, drop the payload
        line = re.sub(r"^(\s*[A-Za-z_.]*(?:Error|Exception))\b:.*$", r"\1: [message left out]", line)
        line = TOKEN_RE.sub(lambda m: (m.group(1) or "") + "[secret]", line)
        line = EMAIL_RE.sub("[email]", line)
        line = PHONE_RE.sub("[phone]", line)
        line = URL_RE.sub(r"\1/...", line)
        for t in extra_terms:
            line = re.sub(re.escape(t), "[redacted]", line, flags=re.I)
        out.append(line)
    return "\n".join(out)


def _tail(path, n):
    if not path.exists():
        return f"(no {path.name})"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def error_lines(text, n=LOG_LINES, follow=12):
    """Only the lines that describe a problem: warnings, errors, tracebacks and the
    lines right after a traceback header. Everything else in the log stays out."""
    out, keep = [], 0
    for line in text.splitlines():
        if line.startswith("Traceback"):
            keep = follow
        if keep > 0:
            keep -= 1
            # frames and the final exception line stay; the echoed source lines (indented, no
            # "File") can quote posting text or data, so they go
            if line.startswith("    ") and not line.lstrip().startswith("File "):
                out.append("    [source line left out]")
                continue
            out.append(line)
            if not line.startswith((" ", "\t", "Traceback")):
                keep = 0      # the exception line ends the traceback
        elif ERROR_LINE_RE.match(line):
            out.append(line)
    return "\n".join(out[-n:]) if out else "(no error lines in the log)"


def _tracker_counts(data):
    f = data / "tracker" / "applications.json"
    if not f.exists():
        return "(no built-in tracker file)"
    counts = {}
    try:
        for p in json.loads(f.read_text(encoding="utf-8"))["pages"].values():
            st = ((p.get("properties", {}).get("Status") or {}).get("status") or {}).get("name", "?")
            counts[st] = counts.get(st, 0) + 1
    except Exception as e:
        return f"(couldn't read: {e})"
    return ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "(empty)"


def build_report():
    data = kit_settings.data_dir()
    sdir = kit_settings.settings_dir()
    v = APP / "VERSION"
    app = kit_settings.app_settings()
    parts = [
        "Job Search Kit error report",
        f"Made: {datetime.now().isoformat(timespec='seconds')}",
        f"Kit version: {v.read_text().strip() if v.exists() else 'dev'}",
        f"System: {platform.platform()}  Python {platform.python_version()}",
        f"Schedule: {json.dumps(app.get('schedule', {}))}  Tracker: {app.get('tracker', 'local')}",
        "Settings files present: " + ", ".join(sorted(p.name for p in sdir.glob("*.json"))) if sdir.exists() else "Settings folder missing",
        f"Tracker rows by status: {_tracker_counts(data)}",
        "",
        f"--- last {ALERT_LINES} alerts ---",
        _tail(data / "alerts.jsonl", ALERT_LINES),
        "",
        f"--- error lines from agent.log (last {LOG_LINES} at most) ---",
        error_lines((data / "agent.log").read_text(encoding="utf-8", errors="replace")) if (data / "agent.log").exists() else "(no agent.log)",
    ]
    return scrub("\n".join(parts), _personal_terms() + _tracker_terms(data))


def save_report():
    data = kit_settings.data_dir()
    out = data / f"error-report-{datetime.now().strftime('%Y-%m-%d-%H%M')}.txt"
    out.write_text(build_report(), encoding="utf-8")
    return out


def _open_folder(path):
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception:
        pass


def open_email(report, to="", platform_name=None, run=subprocess.run):
    """Open a new email with the report attached when the platform allows it.

    Returns "attached" when a mail app took the attachment, "mailto" when a
    plain draft was opened and the report's folder shown instead.
    """
    platform_name = platform_name or sys.platform
    subject = "Job Search Kit error report"
    body = ("The error report is attached. It holds the kit's log only (no postings, resumes, or personal details).\n\n"
            "What I was doing when it went wrong:\n\n")
    env = dict(os.environ, KIT_TO=str(to or ""), KIT_SUBJECT=subject, KIT_BODY=body, KIT_REPORT=str(report))
    if platform_name == "win32":
        # values come in through the environment, never pasted into the script text
        ps = ("$o = New-Object -ComObject Outlook.Application; $m = $o.CreateItem(0); "
              "$m.To = $env:KIT_TO; $m.Subject = $env:KIT_SUBJECT; $m.Body = $env:KIT_BODY; "
              "$m.Attachments.Add($env:KIT_REPORT) | Out-Null; $m.Display()")
        try:
            r = run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30, env=env)
            if r.returncode == 0:
                return "attached"
        except Exception:
            pass
    elif platform_name == "darwin":
        script = '''set theTo to system attribute "KIT_TO"
set theSubject to system attribute "KIT_SUBJECT"
set theBody to system attribute "KIT_BODY"
set theReport to system attribute "KIT_REPORT"
tell application "Mail"
  set m to make new outgoing message with properties {subject:theSubject, content:theBody, visible:true}
  if theTo is not "" then tell m to make new to recipient at end of to recipients with properties {address:theTo}
  tell m to make new attachment with properties {file name:POSIX file theReport} at after the last paragraph
  activate
end tell'''
        try:
            r = run(["osascript", "-e", script], capture_output=True, text=True, timeout=30, env=env)
            if r.returncode == 0:
                return "attached"
        except Exception:
            pass
    link = f"mailto:{to}?subject={quote(subject)}&body={quote(body + 'Please attach this file: ' + str(report))}"
    webbrowser.open(link)
    _open_folder(report)
    return "mailto"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Save a scrubbed error report and open an email with it.")
    ap.add_argument("--save-only", action="store_true")
    a = ap.parse_args(argv)
    report = save_report()
    if a.save_only:
        print(report)
        return
    how = open_email(report, kit_settings.app_settings().get("support_email", ""))
    print(f"{report}\n{'Attached to a new email. Press Send.' if how == 'attached' else 'A new email is open; drag the report file into it, then press Send.'}")


if __name__ == "__main__":
    main()
