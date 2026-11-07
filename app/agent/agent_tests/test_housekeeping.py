"""Log cleanup keeps about 30 days, and Delete my data removes only what the
kit made: "records" takes the data folder, "everything" also takes the
evidence bank, applications, settings, and schedule, leaves the user's own
files, and needs the typed confirmation. No network.
    python3 app/agent/agent_tests/test_housekeeping.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))


class Housekeeping(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old_env = {k: os.environ.get(k) for k in ("KIT_SETTINGS_DIR", "KIT_CONFIG_DIR")}
        os.environ["KIT_CONFIG_DIR"] = str(self.tmp / "config")   # never the real pointer file
        import first_run
        self.root = self.tmp / "Job Search"
        first_run.create_folder(self.root)
        os.environ["KIT_SETTINGS_DIR"] = str(self.root / "settings")
        import kit_settings
        kit_settings._cache.clear()
        self.data = kit_settings.data_dir()
        import housekeeping
        self.hk = housekeeping

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import kit_settings
        kit_settings._cache.clear()
        shutil.rmtree(self.tmp)

    def test_trim_logs(self):
        now = datetime(2026, 11, 1, 9, 0)
        old, new = (now - timedelta(days=40)).isoformat(), (now - timedelta(days=2)).isoformat()
        (self.data / "alerts.jsonl").write_text(json.dumps({"time": old}) + "\n" + json.dumps({"time": new}) + "\n")
        (self.data / "run_stats.jsonl").write_text(json.dumps({"ts": old}) + "\n" + json.dumps({"ts": new}) + "\n")
        rep = self.data / "error-report-2026-09-01-0800.txt"
        rep.write_text("x")
        t = (now - timedelta(days=45)).timestamp()
        os.utime(rep, (t, t))
        (self.data / "agent.log").write_text("INFO old line\n")
        (self.data / "agent.log.started").write_text((now - timedelta(days=16)).date().isoformat())
        self.hk.trim_logs(now=now, data=self.data)
        self.assertEqual(len((self.data / "alerts.jsonl").read_text().splitlines()), 1)
        self.assertEqual(len((self.data / "run_stats.jsonl").read_text().splitlines()), 1)
        self.assertFalse(rep.exists())
        self.assertFalse((self.data / "agent.log").exists())
        self.assertEqual((self.data / "agent.log.1").read_text(), "INFO old line\n")
        self.assertEqual((self.data / "agent.log.started").read_text(), now.date().isoformat())

    def test_delete_records_then_everything(self):
        (self.data / "tracker").mkdir(exist_ok=True)
        (self.data / "tracker" / "applications.json").write_text("{}")
        mine = self.root / "my notes.txt"
        mine.write_text("mine")
        self.assertFalse(self.hk.delete("records", "please")["ok"])
        self.assertTrue((self.data / "tracker").exists())
        self.assertTrue(self.hk.delete("records", "delete my data")["ok"])
        self.assertFalse(self.data.exists())
        self.assertTrue((self.root / "Evidence Bank" / "Evidence Bank.md").exists())
        called = []
        r = self.hk.delete("everything", " Delete my data ", remove_schedule=lambda: called.append(1))
        self.assertTrue(r["ok"], r)
        self.assertEqual(called, [1])
        for part in ("Evidence Bank", "Applications", "Review", "settings", "data"):
            self.assertFalse((self.root / part).exists(), part)
        self.assertTrue(mine.exists())          # the user's own file stays
        self.assertTrue(r["folder_left"])

    def test_never_a_home_folder(self):
        self.assertTrue(self.hk._unsafe(Path.home()))
        self.assertTrue(self.hk._unsafe(Path.home() / "Documents"))
        self.assertFalse(self.hk._unsafe(self.root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
