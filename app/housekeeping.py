#!/usr/bin/env python3
"""Keep logs to about 30 days, and delete the user's data when they ask.

Logs: after each full daily run, lines older than 30 days are dropped from
the dated logs (alerts.jsonl, run_stats.jsonl, dry_run_writes.jsonl), error
reports and market snapshots older than 30 days are deleted, and agent.log
(whose lines carry no dates) is started fresh every 15 days with only the
previous one kept, so nothing in it is older than 30 days.

Delete my data: removes only what the kit created. "records" removes the
data folder (tracker, contacts, backups, logs, run state). "everything" also
removes the Job Search folder's kit parts (Evidence Bank, Applications,
Review, Interview Prep, Archive, settings, the master selection and master
resume), the scheduled runs, and the pointer to the folder. Anything else
the user keeps in that folder is left alone, and the folder itself goes only
if it ends up empty.
"""
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_settings   # noqa: E402

KEEP_DAYS = 30
LOG_ROTATE_DAYS = 15
CONFIRM = "delete my data"
DATED_LOGS = ("alerts.jsonl", "run_stats.jsonl", "dry_run_writes.jsonl")
DATED_FILES = ("error-report-*.txt", "Market_Snapshot_*.md")
KIT_PARTS = ("Evidence Bank", "Applications", "Review", "Interview Prep", "Archive", "settings", "data",
             "master-selection.json")


def _ts(rec):
    for k in ("ts", "time", "date", "when"):
        v = rec.get(k) if isinstance(rec, dict) else None
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                continue
    return None


def trim_logs(now=None, data=None):
    now = now or datetime.now()
    data = Path(data or kit_settings.data_dir())
    cutoff = now - timedelta(days=KEEP_DAYS)
    done = {}
    for name in DATED_LOGS:
        f = data / name
        if not f.exists():
            continue
        keep, dropped = [], 0
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                t = _ts(json.loads(line))
            except ValueError:
                t = None
            if t is not None and t < cutoff:
                dropped += 1
            else:
                keep.append(line)
        if dropped:
            f.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
            done[name] = dropped
    for pattern in DATED_FILES:
        for f in data.glob(pattern):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                done[f.name] = "deleted"
    log, stamp = data / "agent.log", data / "agent.log.started"
    started = None
    try:
        started = date.fromisoformat(stamp.read_text().strip())
    except (OSError, ValueError):
        stamp.write_text(now.date().isoformat())
    if started and (now.date() - started).days >= LOG_ROTATE_DAYS:
        if log.exists():
            os.replace(log, data / "agent.log.1")
        stamp.write_text(now.date().isoformat())
        done["agent.log"] = "started fresh"
    return done


def _unsafe(p):
    p = Path(p).resolve()
    home = Path.home().resolve()
    return p == Path(p.anchor) or p in (home, home / "Documents", home / "Desktop", home / "OneDrive")


def plan(scope):
    """What delete(scope) would remove: [(path, kind)]."""
    if scope not in ("records", "everything"):
        raise ValueError("scope is records or everything")
    out = []
    data = kit_settings.data_dir()
    if not _unsafe(data):
        out.append(data)
    if scope == "everything":
        root = kit_settings.settings_dir().parent
        if not _unsafe(root) and (root / "settings" / "paths.json").exists():
            out += [root / n for n in KIT_PARTS if (root / n).exists() and (root / n) not in out]
            out += sorted(root.glob("*_Master_Resume*.docx"))
    return out


def delete(scope, confirm, remove_schedule=None):
    if (confirm or "").strip().lower() != CONFIRM:
        return {"ok": False, "error": f'Type "{CONFIRM}" to confirm.'}
    targets = plan(scope)
    root = kit_settings.settings_dir().parent
    if scope == "everything" and remove_schedule:
        try:
            remove_schedule()
        except Exception:   # noqa: BLE001  (best effort; the files still go)
            pass
    removed = []
    for t in targets:
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
        elif t.exists():
            t.unlink()
        removed.append(str(t))
    if scope == "everything":
        try:
            import first_run
            pf = first_run.pointer_file()
            if pf.exists():
                pf.unlink()
        except Exception:   # noqa: BLE001
            pass
        try:
            root.rmdir()   # only when nothing of the user's own is left in it
        except OSError:
            pass
    kit_settings._cache.clear()
    return {"ok": True, "removed": removed, "folder_left": root.exists()}
