"""Updater: reads the latest release, compares versions, and runs an installer
only when (1) the release's SHA256SUMS.txt carries a valid Ed25519 signature
from the maintainer's pinned key and (2) the installer's SHA-256 matches that
signed list. A missing signature, a signature by another key, a tampered
list, a tampered installer, or a missing entry means the download is deleted
and nothing runs. No network: GitHub is a fake opener.
    python3 app/agent/agent_tests/test_updater.py
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
import updater  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(files):
    def opener(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        return FakeResponse(files[url])
    return opener


class Updater(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.key = ed25519.Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        self.exe_bytes = b"MZ fake installer " * 100
        self.exe = {"name": "JobSearchKit-Setup-0.2.0.exe", "browser_download_url": "https://x/setup.exe"}
        self.sums = {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"}
        self.sig = {"name": "SHA256SUMS.txt.sig", "browser_download_url": "https://x/SHA256SUMS.txt.sig"}
        good = hashlib.sha256(self.exe_bytes).hexdigest()
        self.good_sums = f"{good}  JobSearchKit-Setup-0.2.0.exe\nabc  job-search-kit.plugin\n".encode()
        self.good_sig = self.key.sign(self.good_sums)

    def files(self, exe=None, sums=None, sig=None):
        return {"https://x/setup.exe": self.exe_bytes if exe is None else exe,
                "https://x/SHA256SUMS.txt": self.good_sums if sums is None else sums,
                "https://x/SHA256SUMS.txt.sig": self.good_sig if sig is None else sig}

    def verify(self, **kw):
        return updater.fetch_and_verify(self.exe, self.sums, self.sig, self.tmp, opener_for(self.files(**kw)), pubkey_hex=self.pub)

    def test_scheduled_check_does_nothing_when_auto_update_is_off(self):
        from unittest import mock
        def no_network():
            raise AssertionError("the scheduled check reached GitHub with auto_update off")
        with mock.patch.object(updater, "auto_update_on", return_value=False), \
             mock.patch.object(updater, "latest_release", side_effect=no_network) as lr:
            self.assertEqual(updater.main([]), 0)
            lr.assert_not_called()
            updater.main(["--now"])   # Check for updates still runs when asked
            lr.assert_called_once()

    def test_release_parsing_and_versions(self):
        release = {"tag_name": "v0.2.0", "assets": [self.exe, self.sums, self.sig, {"name": "job-search-kit.plugin", "browser_download_url": "https://x/p"}]}
        tag, exe, sums, sig, _ = updater.latest_release(opener_for({updater.API: json.dumps(release).encode()}))
        self.assertEqual((tag, exe["name"], sums["name"], sig["name"]), ("v0.2.0", self.exe["name"], "SHA256SUMS.txt", "SHA256SUMS.txt.sig"))
        self.assertTrue(updater.needs_update("0.1.0", "v0.2.0"))
        self.assertFalse(updater.needs_update("0.2.0", "v0.2.0"))
        self.assertFalse(updater.needs_update("0.2.1", "v0.2.0"))
        self.assertEqual(updater.expected_hash(self.good_sums.decode(), "job-search-kit.plugin"), "abc")
        self.assertIsNone(updater.expected_hash(self.good_sums.decode(), "other.exe"))
        self.assertEqual(len(bytes.fromhex(updater.RELEASE_PUBLIC_KEY_HEX)), 32)   # a real pinned key is in the code

    def test_signed_and_matching_passes(self):
        target = self.verify()
        self.assertEqual(target.read_bytes(), self.exe_bytes)

    def test_unsigned_or_wrongly_signed_list_refuses(self):
        with self.assertRaises(ValueError) as cm:
            updater.fetch_and_verify(self.exe, self.sums, None, self.tmp, opener_for(self.files()), pubkey_hex=self.pub)
        self.assertIn("signature", str(cm.exception))
        other = ed25519.Ed25519PrivateKey.generate().sign(self.good_sums)
        with self.assertRaises(ValueError) as cm:
            self.verify(sig=other)
        self.assertIn("signed by the maintainer", str(cm.exception))
        self.assertFalse((self.tmp / self.exe["name"]).exists())      # the installer was never even downloaded

    def test_tampered_list_or_installer_refuses(self):
        evil = hashlib.sha256(self.exe_bytes + b"!").hexdigest().encode() + b"  JobSearchKit-Setup-0.2.0.exe\n"
        with self.assertRaises(ValueError):
            self.verify(exe=self.exe_bytes + b"!", sums=evil)          # list edited after signing
        with self.assertRaises(ValueError) as cm:
            self.verify(exe=self.exe_bytes + b"!")                     # installer swapped
        self.assertIn("checksum", str(cm.exception))
        self.assertFalse((self.tmp / self.exe["name"]).exists())
        with self.assertRaises(ValueError):
            self.verify(sums=b"deadbeef  something-else.exe\n", sig=self.key.sign(b"deadbeef  something-else.exe\n"))

    def test_waits_72_hours_and_honors_the_pause_file(self):
        from datetime import datetime, timedelta, timezone
        from unittest import mock
        import urllib.error
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(hours=10)).isoformat().replace("+00:00", "Z")
        aged = (now - timedelta(hours=80)).isoformat().replace("+00:00", "Z")
        installs = []
        def run(published, pause):
            installs.clear()
            with mock.patch.object(updater, "auto_update_on", return_value=True), \
                 mock.patch.object(updater, "latest_release", return_value=("v9.0.0", self.exe, self.sums, self.sig, published)), \
                 mock.patch.object(updater, "paused", return_value=pause), \
                 mock.patch.object(updater.sys, "platform", "win32"), \
                 mock.patch.object(updater, "fetch_and_verify", side_effect=lambda *a, **k: installs.append(1) or Path("x.exe")), \
                 mock.patch.object(updater.subprocess, "Popen"):
                updater.main([])
            return bool(installs)
        self.assertFalse(run(fresh, False))     # too new
        self.assertFalse(run(None, False))      # no publish time: wait
        self.assertFalse(run(aged, True))       # paused
        self.assertTrue(run(aged, False))
        def opener_raising(code):
            def o(req, timeout=30):
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
            return o
        self.assertFalse(updater.paused(opener_raising(404)))   # no pause file
        self.assertTrue(updater.paused(opener_raising(500)))    # can't tell: stay put
        self.assertTrue(updater.paused(lambda req, timeout=30: io.BytesIO(b"{}")))   # file exists


if __name__ == "__main__":
    unittest.main(verbosity=2)
