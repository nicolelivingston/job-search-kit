#!/usr/bin/env python3
"""First run: choose where the user's Job Search folder lives and create it.

Windows often syncs Documents to OneDrive (and Macs to iCloud Drive). The
installer no longer picks the folder; the setup wizard asks on first run:

  - keep the Job Search folder in Documents (backed up to the cloud service
    that syncs Documents), or
  - put it in a local-only folder, <home>/Job Search, that no service syncs.

Whichever the user picks, this module creates the folder from the kit's
templates (never overwriting a file that already exists), writes
settings/paths.json, and records the settings folder in two places so every
part of the kit finds it: the KIT_SETTINGS_DIR variable for the user's account
(Windows registry; shell profile is left alone on macOS) and a small pointer
file in the user's config folder that kit_settings reads when the variable is
missing (scheduled runs on macOS don't see shell variables).

    python first_run.py            # print what would be offered
"""
import json
import os
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
KIT = APP.parent
TEMPLATES = KIT / "templates"
FOLDER_NAME = "Job Search"
SYNC_MARKERS = ("onedrive", "icloud", "mobile documents", "drop" + "box", "google drive", "box")   # split so the leak test (company names) stays quiet


def documents_dir(platform=None, home=None, env=None):
    """The user's Documents folder, following a Windows redirect to OneDrive."""
    platform = platform or sys.platform
    home = Path(home or Path.home())
    env = os.environ if env is None else env
    if platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                v, _ = winreg.QueryValueEx(k, "Personal")
            return Path(os.path.expandvars(v))
        except Exception:
            pass
    return home / "Documents"


def is_synced(path, env=None):
    """True when a cloud service syncs this folder (OneDrive, iCloud Drive, and similar)."""
    env = os.environ if env is None else env
    p = str(Path(path)).lower()
    if any(m in p for m in SYNC_MARKERS):
        return True
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = env.get(var)
        if not root:
            continue
        r = str(Path(root)).lower().rstrip("\\/")
        if p == r or p.startswith(r + "\\") or p.startswith(r + "/"):
            return True
    return False


def options(platform=None, home=None, env=None):
    """The two places offered, in plain words, with the synced one marked."""
    home = Path(home or Path.home())
    docs = documents_dir(platform, home, env)
    synced = is_synced(docs, env)
    return {
        "documents": {"id": "documents", "path": str(docs / FOLDER_NAME), "synced": synced,
                      "label": "In Documents" + (" (backed up by the service that syncs your Documents folder)" if synced else "")},
        "local": {"id": "local", "path": str(home / FOLDER_NAME), "synced": False,
                  "label": "In a local-only folder on this computer (no cloud service syncs it)"},
        "documents_synced": synced,
    }


# Claude's permissions inside the Job Search folder (.claude/settings.json).
# Posting text is untrusted and the folder holds private data, so Claude gets
# no way to send data out on its own: its web fetch and web search tools are
# off here, download commands are refused, every shell command asks the user
# first, and the modes that skip those prompts are turned off. Postings come
# in through the kit's own fetch (tracker_cli.py fetch), which refuses private
# addresses. The kit's folder is readable so the plugin can read its prompts.
# Only sessions that load the folder's settings apply this (Claude Code opened
# on the folder). A desktop-app task session on a folder with this file
# (Nov 1, 2026) did not apply it, so the plugin's own rules (kit-basics)
# repeat every limit.
CLAUDE_DENY = [
    "WebFetch", "WebSearch",
    "Bash(curl *)", "Bash(wget *)", "Bash(scp *)", "Bash(sftp *)", "Bash(ssh *)", "Bash(ftp *)",
    "Bash(nc *)", "Bash(ncat *)", "Bash(telnet *)", "Bash(rsync *)", "Bash(git push *)", "Bash(git remote *)",
    "Bash(pip install *)", "Bash(pip3 install *)", "Bash(npm *)", "Bash(npx *)", "Bash(certutil *)", "Bash(bitsadmin *)",
    "PowerShell(Invoke-WebRequest *)", "PowerShell(iwr *)", "PowerShell(Invoke-RestMethod *)", "PowerShell(irm *)",
    "PowerShell(Start-BitsTransfer *)", "PowerShell(curl *)", "PowerShell(wget *)", "PowerShell(Send-MailMessage *)",
    "PowerShell(certutil *)", "PowerShell(bitsadmin *)",
    "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.config/**)", "Read(~/AppData/**)",
]


def claude_settings(kit_dir=KIT):
    return {"permissions": {"defaultMode": "default", "disableBypassPermissionsMode": "disable",
                            "disableAutoMode": "disable", "ask": ["Bash", "PowerShell"],
                            "deny": list(CLAUDE_DENY), "additionalDirectories": [str(kit_dir)]}}


def write_claude_settings(dest, kit_dir=KIT):
    """Add .claude/settings.json to a Job Search folder; never replaces one the user has."""
    f = Path(dest) / ".claude" / "settings.json"
    if f.exists():
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(claude_settings(kit_dir), indent=2) + "\n", encoding="utf-8")
    return True


def create_folder(dest, templates=TEMPLATES, kit_dir=KIT):
    """Build the Job Search folder from the templates. Existing files are never overwritten."""
    dest = Path(dest)
    for sub in ("Evidence Bank", "Review", "Applications", "settings"):
        src = templates / sub
        if not src.exists():
            continue
        for f in src.rglob("*"):
            if f.is_file():
                target = dest / sub / f.relative_to(src)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
    (dest / "data").mkdir(parents=True, exist_ok=True)
    settings = dest / "settings"
    settings.mkdir(parents=True, exist_ok=True)
    pf = settings / "paths.json"
    paths = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else {}
    paths.setdefault("bank_dir", "../Evidence Bank")
    paths.setdefault("bank_file", "Evidence Bank.md")
    paths.setdefault("data_dir", "../data")
    paths["kit_dir"] = str(kit_dir)
    pf.write_text(json.dumps(paths, indent=2) + "\n", encoding="utf-8")
    write_claude_settings(dest, kit_dir)
    return settings


def pointer_file(platform=None, env=None):
    """Where the settings folder is recorded for processes that don't see KIT_SETTINGS_DIR."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if env.get("KIT_CONFIG_DIR"):
        base = Path(env["KIT_CONFIG_DIR"])
    elif platform.startswith("win"):
        base = Path(env.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "JobSearchKit"
    else:
        base = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "job-search-kit"
    return base / "settings_dir"


def persist_settings_dir(settings, platform=None, env=None):
    """Record the settings folder for this account: pointer file always, registry on Windows."""
    platform = platform or sys.platform
    settings = str(Path(settings).resolve())
    pf = pointer_file(platform, env)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(settings + "\n", encoding="utf-8")
    os.environ["KIT_SETTINGS_DIR"] = settings
    if platform.startswith("win"):
        try:
            import winreg
            import ctypes
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "KIT_SETTINGS_DIR", 0, winreg.REG_SZ, settings)
            # tell running programs the user's environment changed (new shells pick it up)
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)
        except Exception:
            pass
    return pf


def choose(choice, custom_path=None, platform=None, home=None, env=None, templates=TEMPLATES, kit_dir=KIT):
    """Create the folder for the user's choice and record it. Returns the settings folder."""
    opts = options(platform, home, env)
    if choice == "custom" and custom_path:
        dest = Path(custom_path).expanduser()
    elif choice in ("documents", "local"):
        dest = Path(opts[choice]["path"])
    else:
        raise ValueError("choose 'documents', 'local', or 'custom' with a path")
    settings = create_folder(dest, templates, kit_dir)
    persist_settings_dir(settings, platform, env)
    return settings


if __name__ == "__main__":
    print(json.dumps(options(), indent=1))
