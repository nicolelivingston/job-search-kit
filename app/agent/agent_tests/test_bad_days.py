"""Bad days: what the kit does when something outside it goes wrong.

Each case is a thing that will happen to a real user sooner or later. The
kit must not crash the whole run, must not quietly replace the user's data,
and must say in plain words what happened and what to do.
  - every job feed is down (no network): the run gets zero postings, no crash
  - a feed returns an HTML error page or garbage: skipped with a warning
  - a feed declares a DOCTYPE or entities (an XML attack): refused
  - a tracker file is cut off mid-write: reading stops with a message that
    names the file and the backups, and the file is left exactly as it was
  - a settings file is damaged: the error names the file
  - a backup zip is damaged: the restore refuses before changing anything
No network.
    python3 app/agent/agent_tests/test_bad_days.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent
PERSON = KIT / "examples" / "priya-healthtech-pm"
sys.path[:0] = [str(APP / "agent"), str(APP)]
os.environ.setdefault("KIT_SETTINGS_DIR", str(PERSON / "settings"))

import requests          # noqa: E402
import board_feeds       # noqa: E402
import local_tracker     # noqa: E402
import kit_settings      # noqa: E402

RSS = """<?xml version="1.0"?><rss><channel><item><title>Acme: Product Manager</title>
<link>https://example.com/jobs/1</link><guid>1</guid><region>USA Only</region>
<pubDate>Wed, 28 Oct 2026 10:00:00 +0000</pubDate><description>Remote.</description></item></channel></rss>"""
ATTACK = """<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]>
<rss><channel><item><title>&b;</title><link>https://example.com/x</link></item></channel></rss>"""


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return json.loads(self.text)


@contextlib.contextmanager
def feeds_answer(fn):
    saved = board_feeds.request_with_retry
    board_feeds.request_with_retry = lambda request_fn, url, **kw: fn(url)
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            yield err
    finally:
        board_feeds.request_with_retry = saved


class Feeds(unittest.TestCase):
    def test_no_network_means_no_postings_not_a_crash(self):
        def down(url):
            raise requests.ConnectionError("network is unreachable")
        with feeds_answer(down) as err:
            self.assertEqual(board_feeds.fetch_board_feeds(), [])
        self.assertIn("[warn]", err.getvalue())

    def test_an_error_page_is_skipped(self):
        with feeds_answer(lambda url: Resp("<html><body>Service unavailable</body></html>", 200)) as err:
            self.assertEqual(board_feeds.fetch_board_feeds(), [])
        self.assertIn("[warn]", err.getvalue())

    def test_a_good_feed_still_reads(self):
        self.assertEqual(len(board_feeds._parse_rss(RSS, "We Work Remotely", "wwr")), 1)

    def test_entities_are_refused(self):
        with self.assertRaises(ValueError):
            board_feeds._parse_rss(ATTACK, "We Work Remotely", "wwr")
        if board_feeds.WWR_FEEDS:
            with feeds_answer(lambda url: Resp(ATTACK if "weworkremotely" in url else "[]")) as err:
                self.assertEqual(board_feeds.fetch_weworkremotely(), [])
            self.assertIn("DOCTYPE", err.getvalue())


class DamagedFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_cut_off_tracker_file_is_never_replaced(self):
        local_tracker.configure(self.tmp, "apps-db", "companies-db")
        f = self.tmp / "tracker" / "applications.json"
        f.write_text('{"pages": {"a": {"id": "a", "properties": {"Role": ')   # cut off mid-write
        before = f.read_bytes()
        with self.assertRaises(local_tracker.TrackerDamaged) as cm:
            local_tracker._load("applications")
        msg = str(cm.exception)
        self.assertIn(str(f), msg)
        self.assertIn("backup", msg)
        self.assertEqual(f.read_bytes(), before)

    def test_a_damaged_settings_file_is_named(self):
        s = self.tmp / "settings"
        s.mkdir()
        (s / "app.json").write_text('{"tracker": "local",')
        kit_settings._cache.clear()
        old = os.environ.get("KIT_SETTINGS_DIR")
        os.environ["KIT_SETTINGS_DIR"] = str(s)
        try:
            with self.assertRaises(ValueError) as cm:
                kit_settings.app_settings()
        finally:
            os.environ["KIT_SETTINGS_DIR"] = old
            kit_settings._cache.clear()
        self.assertIn(str(s / "app.json"), str(cm.exception))

    def test_a_damaged_backup_changes_nothing(self):
        root = self.tmp / "js"
        shutil.copytree(PERSON, root)
        data = root / "data"
        (data / "tracker").mkdir(parents=True, exist_ok=True)
        tracker = data / "tracker" / "applications.json"
        tracker.write_text(json.dumps({"pages": {"keep": {"id": "keep"}}}))
        env = dict(os.environ, KIT_SETTINGS_DIR=str(root / "settings"))
        run = lambda *a: subprocess.run([sys.executable, str(APP / "backup.py"), *a], env=env,
                                        capture_output=True, text=True, timeout=120)
        r = run("now")
        self.assertEqual(r.returncode, 0, r.stderr)
        zips = sorted((data / "backups").glob("backup-*.zip"))
        good = zips[-1].read_bytes()
        tracker.write_text(json.dumps({"pages": {"newer": {"id": "newer"}}}))
        before = tracker.read_bytes()
        # Where the damage lands decides which error the zip reader raises, so
        # damage it at several points, and cut it short.
        damaged = []
        for frac in (0.2, 0.33, 0.5, 0.7):
            blob = bytearray(good)
            i = int(len(blob) * frac)
            blob[i:i + 64] = b"\0" * 64
            damaged.append(bytes(blob))
        damaged.append(good[: len(good) // 2])
        for n, blob in enumerate(damaged):
            bad = data / "backups" / f"backup-2026-01-0{n + 1}.zip"
            bad.write_bytes(blob)
            with self.subTest(damage=n):
                r = run("restore", str(bad))
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("nothing was restored", r.stdout + r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(tracker.read_bytes(), before)
                self.assertFalse(list((data / "backups").glob("*before-restore*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
