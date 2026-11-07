#!/usr/bin/env python3
"""Daily backups of the user's own records, kept on this computer.

Once a day (after the full daily run) the kit zips the built-in tracker, the
contacts list, the evidence bank folder, and the settings folder into
`<data folder>/backups/backup-YYYY-MM-DD.zip` and keeps the last 14 days.
Nothing leaves the computer. A restore first takes a fresh backup of what's
there now, so a restore can itself be undone.

    python backup.py now            # back up today (replaces today's file)
    python backup.py list           # the backups on hand, newest first
    python backup.py restore <file> [--only tracker|contacts|bank|settings ...]
"""
import argparse
import json
import re
import sys
import zipfile
import zlib
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_settings   # noqa: E402

KEEP_DAYS = 14
NAME_RE = re.compile(r"^backup-(\d{4}-\d{2}-\d{2})(?:-[a-z-]+)?\.zip$")


def backups_dir():
    d = kit_settings.data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sources():
    """(name in the zip, folder or file on disk) for each part that is backed up."""
    data = kit_settings.data_dir()
    parts = {"tracker": data / "tracker", "contacts": data / "contacts.json",
             "settings": kit_settings.settings_dir()}
    bank = kit_settings.bank_dir()
    if bank:
        parts["bank"] = bank
    return parts


ARC = {"tracker": "tracker", "contacts": "contacts.json", "bank": "Evidence Bank", "settings": "settings"}


def backup(today=None, tag=""):
    today = today or date.today()
    out = backups_dir() / f"backup-{today.isoformat()}{('-' + tag) if tag else ''}.zip"
    tmp = out.with_suffix(".tmp")
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for part, src in sources().items():
            if src.is_file():
                z.write(src, ARC[part]); n += 1
            elif src.is_dir():
                for f in sorted(src.rglob("*")):
                    if f.is_file() and "backups" not in f.relative_to(src).parts and f.suffix not in (".tmp", ".lock"):
                        z.write(f, f"{ARC[part]}/{f.relative_to(src).as_posix()}"); n += 1
        z.writestr("backup.json", json.dumps({"date": today.isoformat(), "files": n, "kit_backup": 1}))
    tmp.replace(out)
    prune(today)
    return out


def prune(today=None):
    today = today or date.today()
    cutoff = today - timedelta(days=KEEP_DAYS - 1)
    gone = []
    for f in backups_dir().glob("backup-*.zip"):
        m = NAME_RE.match(f.name)
        if m and date.fromisoformat(m.group(1)) < cutoff:
            f.unlink()
            gone.append(f.name)
    return gone


def listing():
    return sorted((f.name for f in backups_dir().glob("backup-*.zip")), reverse=True)


def restore(zip_path, only=None):
    """Put the backed-up files back. Takes a 'before-restore' backup first.
    Files in the backup replace the ones on disk; files added since stay."""
    zip_path = Path(zip_path)
    if not zip_path.is_absolute() and not zip_path.exists():
        zip_path = backups_dir() / zip_path
    parts = sources()
    want = set(only or parts)
    # Check the whole backup before touching anything: a damaged zip found
    # halfway through would leave a mix of old and restored files.
    try:
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError) as e:   # any damage, wherever it is
        raise SystemExit(f"That backup can't be read ({e}); nothing was restored. Try an older backup.")
    if bad:
        raise SystemExit(f"That backup is damaged ({bad}); nothing was restored. Try an older backup.")
    safety = backup(tag="before-restore")
    restored = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or name == "backup.json":
                continue
            if name.startswith("/") or "\\" in name or ".." in Path(name).parts or ":" in name:
                raise SystemExit(f"refusing an unsafe name in the backup: {name}")
            part = next((p for p, a in ARC.items() if name == a or name.startswith(a + "/")), None)
            if part is None or part not in want or part not in parts:
                continue
            rel = name[len(ARC[part]):].lstrip("/")
            dest = parts[part] if not rel else parts[part] / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
            restored += 1
    return {"ok": True, "restored_files": restored, "safety_backup": safety.name}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("now")
    sub.add_parser("list")
    r = sub.add_parser("restore"); r.add_argument("file"); r.add_argument("--only", nargs="+", choices=sorted(ARC))
    a = ap.parse_args(argv)
    if a.cmd == "now":
        print(json.dumps({"ok": True, "backup": backup().name}))
    elif a.cmd == "list":
        print(json.dumps(listing(), indent=1))
    else:
        print(json.dumps(restore(a.file, a.only), indent=1))


if __name__ == "__main__":
    main()
