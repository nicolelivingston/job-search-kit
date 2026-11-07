#!/usr/bin/env python3
"""Checks GitHub for a newer Job Search Kit release and installs it.

    python app/updater.py          # check quietly; install if newer (runs daily, scheduled by schedule.py)
    python app/updater.py --now    # same, and say so when already up to date

Updates replace only the code and bundled Python. The installer never
touches the user's Job Search folder, settings, evidence bank, or tracker.
The repository is public, so no sign-in is needed.

Safety, in order:
1. The release's SHA256SUMS.txt must carry a valid Ed25519 signature
   (SHA256SUMS.txt.sig) made with the maintainer's release key. The public
   key is pinned below; the private key never leaves the maintainer's own
   computer and is not on GitHub or in CI. A release that CI built but the
   maintainer hasn't signed installs nothing. A stolen GitHub account can't
   push an update to anyone.
2. The installer's SHA-256 must match the signed list.
3. Only then does the installer run. A failed check deletes the download.
4. A release installs only after it has been public for 72 hours, so a bad
   release can be pulled before it reaches anyone.
5. If the repository has an UPDATES_PAUSED file on its main branch, nothing
   installs (the maintainer's switch to stop every update at once). If that
   check can't be made, nothing installs either.
The previous version can always be reinstalled from the releases page (SUPPORT.md).
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = os.environ.get("KIT_REPO", "nicolelivingston/job-search-kit")
APP = Path(__file__).resolve().parent
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAUSE_API = f"https://api.github.com/repos/{REPO}/contents/UPDATES_PAUSED?ref=main"
UA = "job-search-kit-updater (+https://github.com/" + REPO + ")"
WAIT = timedelta(hours=72)
# Ed25519 public key (raw, hex) of the maintainer's release-signing key. Changing it is a
# code change that goes through the same review as everything else.
RELEASE_PUBLIC_KEY_HEX = os.environ.get("KIT_RELEASE_PUBKEY", "68f4f6ee3addc368f0e420a3b27ad559eed59370d284e774ecebe28767ee5265")


def current_version():
    f = APP / "VERSION"
    return f.read_text().strip() if f.exists() else "0.0.0"


def parse(v):
    out = []
    for part in v.lstrip("v").split("-")[0].split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out + [0] * (3 - len(out)))


def latest_release(opener=urllib.request.urlopen):
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": UA})
    with opener(req, timeout=30) as r:
        data = json.load(r)
    assets = {a["name"]: a for a in data.get("assets", [])}
    exe = next((a for n, a in assets.items() if n.endswith(".exe")), None)
    return (data.get("tag_name", "v0.0.0"), exe, assets.get("SHA256SUMS.txt"), assets.get("SHA256SUMS.txt.sig"),
            data.get("published_at"))


def ready_at(published_at):
    """When a release may install (72 hours after it was published), or None if unknown."""
    try:
        return datetime.fromisoformat(str(published_at).replace("Z", "+00:00")) + WAIT
    except ValueError:
        return None


def paused(opener=urllib.request.urlopen):
    """True if UPDATES_PAUSED exists on main, or if that can't be checked (fail closed)."""
    req = urllib.request.Request(PAUSE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": UA})
    try:
        with opener(req, timeout=30):
            return True
    except urllib.error.HTTPError as e:
        return e.code != 404
    except Exception:
        return True


def needs_update(current, latest):
    return parse(latest) > parse(current)


def expected_hash(sums_text, name):
    """The SHA-256 listed for `name` in a SHA256SUMS.txt, or None."""
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1] == name:
            return parts[0].lower()
    return None


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_signature(sums_bytes, sig_bytes, pubkey_hex=None):
    """True only if sig_bytes is a valid Ed25519 signature of sums_bytes by the pinned key."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.exceptions import InvalidSignature
    try:
        key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex or RELEASE_PUBLIC_KEY_HEX))
        key.verify(sig_bytes, sums_bytes)
        return True
    except (InvalidSignature, ValueError):
        return False


def download(url, target, opener=urllib.request.urlopen, limit=200 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    total = 0
    with opener(req, timeout=120) as r, open(target, "wb") as out:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            total += len(chunk)
            if total > limit:
                raise ValueError("download larger than expected")
            out.write(chunk)


def fetch_and_verify(exe, sums, sig, tmpdir=None, opener=urllib.request.urlopen, pubkey_hex=None):
    """Download installer, checksum list, and signature; return the installer path only if
    the signature is valid and the installer matches the signed list."""
    if exe is None or sums is None or sig is None:
        raise ValueError("this release is missing its installer, checksum list, or signature, so nothing was installed")
    tmpdir = Path(tmpdir or tempfile.mkdtemp(prefix="jobsearchkit-update-"))
    target = tmpdir / exe["name"]
    sums_file = tmpdir / "SHA256SUMS.txt"
    sig_file = tmpdir / "SHA256SUMS.txt.sig"
    download(sums["browser_download_url"], sums_file, opener)
    download(sig["browser_download_url"], sig_file, opener)
    if not verify_signature(sums_file.read_bytes(), sig_file.read_bytes(), pubkey_hex):
        raise ValueError("the release's checksum list isn't signed by the maintainer's key, so nothing was installed")
    download(exe["browser_download_url"], target, opener)
    want = expected_hash(sums_file.read_text(encoding="utf-8", errors="ignore"), exe["name"])
    got = sha256_of(target)
    if not want or want != got:
        try:
            target.unlink()
        except OSError:
            pass
        raise ValueError("the downloaded installer didn't match its signed checksum, so it was deleted and not run")
    return target


def auto_update_on():
    """False when the user turned off automatic updates (app.auto_update).
    The scheduled check then does nothing; Check for updates (--now) still
    works because the user asked for it."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from kit_settings import app_settings
        return app_settings().get("auto_update", True) is not False
    except Exception:
        return True


def main(argv):
    loud = "--now" in argv
    if not loud and not auto_update_on():
        return 0
    try:
        tag, exe, sums, sig, published = latest_release()
    except Exception as e:
        if loud:
            print(f"Couldn't reach GitHub to check for updates ({e}). Try again later.")
        return 1
    if not needs_update(current_version(), tag) or exe is None:
        if loud:
            print(f"You're up to date (version {current_version()}).")
        return 0
    when = ready_at(published)
    if when is None or datetime.now(timezone.utc) < when:
        if loud:
            local = when.astimezone().strftime("%B %d at %I:%M %p").replace(" 0", " ") if when else "later"
            print(f"Version {tag} is out. Updates wait 72 hours after a release as a safety check, so it installs after {local}.")
        return 0
    if paused():
        if loud:
            print("Updates are paused by the maintainer right now (or the check couldn't be made). Nothing was installed.")
        return 0
    if not sys.platform.startswith("win"):
        print(f"Version {tag} is available; the automatic installer is Windows-only for now.")
        return 0
    try:
        target = fetch_and_verify(exe, sums, sig)
    except Exception as e:
        print(f"Update to {tag} not installed: {e}")
        return 1
    # /SILENT shows a progress bar only; settings and data are never touched
    subprocess.Popen([str(target), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    print(f"Updating to {tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
