"""Loads a user's personal settings for the Job Search Kit.

All personal choices (criteria, target companies, keyword groups tied to the
evidence bank, resume format and word lists) live in a settings folder, never
in the code. The folder is <kit>/settings by default; KIT_SETTINGS_DIR points
somewhere else (the comparison runs use dev-settings).

settings/
  criteria.json        search criteria and scoring rules
  companies.json       target company job boards
  resume.json          resume format and pre-send gate word lists
  paths.json           where the evidence bank and data folder live (optional)
  app.json             {"tracker": "local"} or {"tracker": "notion"} (default local)
<bank folder>/keyword-groups.json   evidence keyword groups for fit scoring
                     (path can be overridden with "keyword_groups" in paths.json)

Values use a few markers so regexes, tuples, and dates survive JSON:
{"$rx": [...]}, {"$re": "...", "flags": ["I"]}, {"$tuple": [...]},
{"$set": [...]}, {"$dict": [[key, value], ...]}, {"$date": [y, m, d]}.
"""
import json
import os
import re
from datetime import date
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
FILES = {"agent": "criteria.json", "fit_scoring": "criteria.json", "board_feeds": "criteria.json",
         "invariants": "criteria.json", "market_report": "criteria.json", "ats_tools": "companies.json",
         "presend_gate": "resume.json", "build_resume": "resume.json"}
EVIDENCE_NAMES = {"WORK_FAMILIES", "GAP_FAMILIES", "MINIMUM_FAMILIES", "REQUIRED_BLOCK_FAMILIES", "VOUCH_WORDS"}
_cache = {}


def user_agent():
    """A descriptive User-Agent for every request the kit makes to a job board or feed:
    who we are, where to find us, and that it's one person's search run a few times a day."""
    v = KIT_ROOT / "app" / "VERSION"
    ver = v.read_text().strip() if v.exists() else "dev"
    return f"JobSearchKit/{ver} (+https://github.com/nicolelivingston/job-search-kit; personal job search, a few polite runs a day)"


def _pointer():
    """The settings folder recorded by first_run.py for processes that don't see KIT_SETTINGS_DIR
    (scheduled runs on macOS, a Windows task started before the variable existed)."""
    try:
        import first_run
        pf = first_run.pointer_file()
        if pf.exists():
            v = pf.read_text(encoding="utf-8").strip()
            if v and Path(v).exists():
                return v
    except Exception:
        pass
    return None


def settings_dir():
    return Path(os.environ.get("KIT_SETTINGS_DIR") or _pointer() or (KIT_ROOT / "settings")).expanduser().resolve()


def _read(path):
    key = str(path)
    if key not in _cache:
        if not path.exists():
            raise FileNotFoundError(
                f"Job Search Kit settings file not found: {path}. Run the setup wizard, "
                f"or set KIT_SETTINGS_DIR to your settings folder.")
        try:
            _cache[key] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ValueError(
                f"Job Search Kit settings file {path} can't be read ({e}). Daily backups are in the data "
                f"folder's backups folder (python backup.py restore <file> --only settings), or send an error report for help.") from None
    return _cache[key]


def paths():
    p = settings_dir() / "paths.json"
    return _read(p) if p.exists() else {}


def app_settings():
    p = settings_dir() / "app.json"
    return _read(p) if p.exists() else {}


# Settings format version (settings_version in app.json; a folder without it
# is version 0, which is every folder made by v0.1.0). Bump SETTINGS_VERSION
# only when a change renames or removes a setting or changes what a value
# means, and add a step to MIGRATIONS that brings the previous version
# forward. A brand-new setting needs no bump: read it with a default
# (setting(..., default=...)) so older folders keep working unchanged.
SETTINGS_VERSION = 3


def _v0_to_v1(files):
    """v0.1.0 folders already work as they are: every setting added since has
    a default in code. Nothing to change."""
    return []


RETIRED_V2 = ("ASK_EXPIRY_DAYS", "NO_DECISION_VERDICT")


def _v1_to_v2(files):
    """Fit scoring v3.3 retired the 48-hour rule and the Watch (no decision)
    label (every row gets a fit label now), so their two settings go. The
    tracker's old verdict names are carried over by the agent itself on its
    next run (job_search_agent.migrate_verdict_names)."""
    agent = files.get("criteria.json", {}).get("agent", {})
    gone = [k for k in RETIRED_V2 if k in agent]
    for k in gone:
        agent.pop(k)
    return [f"removed the retired setting agent.{k} (the 48-hour rule is gone; every posting gets a fit label instead)"
            for k in gone]


RETIRED_V3 = {"board_feeds": ("REMOTE_CO_FEEDS",),
              "fit_scoring": ("INFRA_DOMAIN", "PLANNING_DOMAIN", "AI_BUSINESS_BONUS")}


def _v2_to_v3(files):
    """Settings the kit no longer reads: the remote.co feed (the site blocks
    automated readers, so it was never fetched) and two optional scoring rules
    that were tied to one person's own fields."""
    crit = files.get("criteria.json", {})
    out = []
    for section, names in RETIRED_V3.items():
        sec = crit.get(section, {})
        for k in names:
            if k in sec:
                sec.pop(k)
                out.append(f"removed the setting {section}.{k}, which the kit no longer uses")
    return out


# from_version: step(files) -> list of plain-words changes. A step edits
# `files` ({"criteria.json": {...}, ...}, the folder's JSON files) in memory.
MIGRATIONS = {0: _v0_to_v1, 1: _v1_to_v2, 2: _v2_to_v3}


def folder_settings_version(folder=None):
    f = Path(folder or settings_dir()) / "app.json"
    try:
        return int(json.loads(f.read_text(encoding="utf-8")).get("settings_version", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def migrate(folder=None, backup=None):
    """Bring an older settings folder up to SETTINGS_VERSION. Runs every step
    in memory first and writes nothing unless one changed something; then it
    calls backup() (the daily backup zip, tagged) before writing the changed
    files and the new settings_version. Returns (changes, warning)."""
    folder = Path(folder or settings_dir())
    have = folder_settings_version(folder)
    if have > SETTINGS_VERSION:
        return [], (f"Your settings were saved by a newer version of the kit (settings version {have}; "
                    f"this kit reads {SETTINGS_VERSION}). Install the latest update before changing settings.")
    files = {f.name: json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("*.json"))}
    before = {n: json.dumps(d, sort_keys=True) for n, d in files.items()}
    changes = []
    for v in range(have, SETTINGS_VERSION):
        if v not in MIGRATIONS:
            raise RuntimeError(f"No settings migration from version {v}")
        changes += MIGRATIONS[v](files)
    if not changes:
        return [], None
    if backup:
        backup()
    files.setdefault("app.json", {})["settings_version"] = SETTINGS_VERSION
    for name, data in files.items():
        if before.get(name) != json.dumps(data, sort_keys=True):
            (folder / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _cache.clear()
    return changes, None


def tracker_mode():
    """"local" (built-in tracker, the kit default) or "notion"."""
    return app_settings().get("tracker", "local")


def data_dir():
    """Where the agent keeps its state files and the built-in tracker."""
    d = paths().get("data_dir")
    p = (settings_dir() / d).resolve() if d else (KIT_ROOT / "data")
    p.mkdir(parents=True, exist_ok=True)
    return p


def bank_dir():
    b = paths().get("bank_dir")
    return (settings_dir() / b).resolve() if b else None


def keyword_groups_file():
    kg = paths().get("keyword_groups")
    if kg:
        return (settings_dir() / kg).resolve()
    b = bank_dir()
    return (b / "keyword-groups.json") if b else (settings_dir() / "keyword-groups.json")


def _flags(names):
    v = 0
    for n in names or []:
        v |= getattr(re, n)
    return v


def build(v, rx=None):
    if isinstance(v, list):
        return [build(x, rx) for x in v]
    if isinstance(v, dict):
        if "$rx" in v:
            if rx is None:
                raise ValueError("setting uses $rx but no rx builder was passed")
            return rx(*[build(x, rx) for x in v["$rx"]])
        if "$re" in v:
            return re.compile(v["$re"], _flags(v.get("flags")))
        if "$tuple" in v:
            return tuple(build(x, rx) for x in v["$tuple"])
        if "$set" in v:
            return {build(x, rx) for x in v["$set"]}
        if "$dict" in v:
            return {build(k, rx): build(x, rx) for k, x in v["$dict"]}
        if "$date" in v:
            return date(*v["$date"])
        return {k: build(x, rx) for k, x in v.items()}
    return v


_NO_DEFAULT = object()


def setting(key, rx=None, default=_NO_DEFAULT):
    """setting("fit_scoring.PAY_TARGET") -> the value from the user's settings."""
    section, name = key.split(".", 1)
    if name in EVIDENCE_NAMES:
        data = _read(keyword_groups_file())
    else:
        data = _read(settings_dir() / FILES[section])
    try:
        return build(data[section][name], rx)
    except KeyError:
        if default is not _NO_DEFAULT:
            return default
        raise KeyError(f"Setting '{key}' is missing from your settings folder ({settings_dir()}).")
