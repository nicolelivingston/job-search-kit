"""Small cross-platform helpers for the Job Search Kit (macOS and Windows).

notify()       desktop notification: macOS Notification Center, Windows toast
               (built-in PowerShell, no extra install). Also appends the alert
               to <data folder>/alerts.jsonl so the tracker can show a banner.
find_soffice() LibreOffice's command-line converter, used to render a resume
               to PDF and count its pages.
secure_private_file()  make a secrets file (.env) readable by this user account only:
               chmod 600 on macOS and Linux, icacls on Windows.
SecretMask     a logging filter that replaces secret values with [secret] in
               every log record, so a token never lands in agent.log or an
               error report.
"""
import logging
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

_WIN_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [System.Security.SecurityElement]::Escape($env:KIT_TITLE)
$m = [System.Security.SecurityElement]::Escape($env:KIT_MSG)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$m</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Job Search Kit').Show($toast)
"""


def notify_command(title, message, platform=None):
    """The command (and extra environment) that shows a notification, or None."""
    platform = platform or sys.platform
    if platform == "darwin":
        return (["osascript", "-e",
                 f"display notification {json.dumps(message)} with title {json.dumps(title)}"], {})
    if platform.startswith("win"):
        return (["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                 "-Command", _WIN_TOAST], {"KIT_TITLE": title, "KIT_MSG": message})
    return None


def record_alert(title, message, data_dir=None):
    try:
        if data_dir is None:
            from kit_settings import data_dir as _dd
            data_dir = _dd()
        with open(Path(data_dir) / "alerts.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                                 "title": title, "message": message}) + "\n")
    except Exception:
        pass


def notify(title, message, data_dir=None):
    """Best effort. Never breaks the run."""
    record_alert(title, message, data_dir)
    try:
        cmd = notify_command(title, message)
        if cmd:
            args, extra = cmd
            subprocess.run(args, capture_output=True, timeout=15, env={**os.environ, **extra})
    except Exception:
        pass


SOFFICE_CANDIDATES = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def find_soffice():
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for c in SOFFICE_CANDIDATES:
        if Path(c).exists():
            return c
    return None


# ---------------------------------------------------------------- secrets
SECRET_ENV_NAMES = ("NOTION_TOKEN", "GMAIL_APP_PASSWORD", "GMAIL_PASSWORD", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def secure_private_file(path, run=subprocess.run, platform=None):
    """Restrict a file to the current user account. Returns what was done."""
    path = Path(path)
    if not path.exists():
        return "missing"
    platform = platform or sys.platform
    if platform.startswith("win"):
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if not user:
            return "skipped"
        # drop inherited permissions, then grant only this user full control
        run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True)
        return "icacls"
    os.chmod(path, 0o600)
    return "chmod600"


class SecretMask(logging.Filter):
    """Replace every known secret value in log messages and their arguments."""
    def __init__(self, values=None):
        super().__init__()
        vals = values if values is not None else [os.environ.get(n, "") for n in SECRET_ENV_NAMES]
        self.values = [v for v in vals if v and len(v) >= 6]

    def mask(self, text):
        for v in self.values:
            text = text.replace(v, "[secret]")
        return text

    def filter(self, record):
        if self.values:
            try:
                record.msg = self.mask(record.getMessage())   # formats the args too, whatever their type
                record.args = ()
            except Exception:
                record.msg = self.mask(str(record.msg))
        return True


def protect_secrets(env_file, logger_names=("",)):
    """Lock down the .env file and mask its values in logging. Called at agent start."""
    done = secure_private_file(env_file)
    mask = SecretMask()
    for name in logger_names:
        logging.getLogger(name).addFilter(mask)
    for h in logging.getLogger().handlers:
        h.addFilter(mask)
    return done, mask
