"""Daily backups: the tracker, contacts, evidence bank, and settings are
zipped into data/backups, 14 days are kept, and a restore puts every file
back (after taking its own safety backup) and refuses unsafe names.
Runs on a temporary copy of a test person. No network.
    python3 app/agent/agent_tests/test_backup.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent
PERSON = KIT / "examples" / "priya-healthtech-pm"


class Backup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(PERSON, self.tmp / "js")
        self.root = self.tmp / "js"
        self.data = self.root / "data"
        (self.data / "tracker").mkdir(parents=True, exist_ok=True)
        (self.data / "tracker" / "applications.json").write_text(json.dumps({"pages": {"a": {"id": "a"}}}))
        (self.data / "contacts.json").write_text(json.dumps([{"name": "Sam Example"}]))
        self.env = dict(os.environ, KIT_SETTINGS_DIR=str(self.root / "settings"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def cli(self, *args, code=0):
        r = subprocess.run([sys.executable, str(APP / "backup.py"), *args], env=self.env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_backup_and_restore(self):
        bank = self.root / "Evidence Bank" / "Evidence Bank.md"
        original = bank.read_text()
        made = self.cli("now")["backup"]
        self.assertTrue((self.data / "backups" / made).exists())
        with zipfile.ZipFile(self.data / "backups" / made) as z:
            names = set(z.namelist())
        self.assertTrue({"tracker/applications.json", "contacts.json", "Evidence Bank/Evidence Bank.md",
                         "settings/paths.json"} <= names, names)
        bank.write_text("damaged")
        (self.data / "contacts.json").unlink()
        shutil.rmtree(self.data / "tracker")
        r = self.cli("restore", made)
        self.assertTrue(r["ok"])
        self.assertEqual(bank.read_text(), original)
        self.assertEqual(json.loads((self.data / "contacts.json").read_text())[0]["name"], "Sam Example")
        self.assertIn("a", json.loads((self.data / "tracker" / "applications.json").read_text())["pages"])
        self.assertIn(r["safety_backup"], self.cli("list"))   # the restore can itself be undone
        bank.write_text("changed again")
        self.cli("restore", made, "--only", "contacts")
        self.assertEqual(bank.read_text(), "changed again")      # --only leaves the rest alone

    def test_keeps_fourteen_days(self):
        b = self.data / "backups"
        b.mkdir(parents=True)
        for i in range(1, 21):
            (b / f"backup-{(date.today() - timedelta(days=i)).isoformat()}.zip").write_bytes(b"x")
        self.cli("now")
        self.assertEqual(len(self.cli("list")), 14)

    def test_unsafe_names_refused(self):
        b = self.data / "backups"
        b.mkdir(parents=True)
        bad = b / "backup-2026-01-01.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("tracker/../../escape.txt", "x")
        self.cli("restore", str(bad), code=1)
        self.assertFalse((self.root / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
