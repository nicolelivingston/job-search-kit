"""Tracker command line (used by the Claude plugin): adds a pasted posting to
the built-in tracker, finds the row by company, updates status and extra
fields such as Resume Versions and Drafting Started, lists open rows, shows
one row in full, appends notes, keeps contacts, and exits 1 on a failed update.
Runs against a temporary copy of a test person's settings. No network.
    python3 app/agent/agent_tests/test_tracker_cli.py
"""
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


class TrackerCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        s = Path(cls.tmp) / "settings"
        shutil.copytree(PERSON / "settings", s)
        p = json.loads((s / "paths.json").read_text())
        p["bank_dir"] = str((PERSON / "Evidence Bank").resolve())
        p["data_dir"] = str(Path(cls.tmp) / "data")
        (s / "paths.json").write_text(json.dumps(p))
        cls.data = Path(cls.tmp) / "data"
        cls.env = dict(os.environ, KIT_SETTINGS_DIR=str(s))
        cls.env.pop("NOTION_TOKEN", None)
        posting = PERSON / "Applications" / "03 good fit" / "posting.md"
        cls.posting = str(posting)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_cli(self, *args, code=0):
        r = subprocess.run([sys.executable, str(APP / "tracker_cli.py"), *args], env=self.env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, code, r.stderr)
        return json.loads(r.stdout)

    def test_show_notes_contacts_outcome_and_failure(self):
        added = self.run_cli("add", "--text-file", self.posting, "--title", "Product Manager",
                             "--company", "Second Clinics")
        rid = added["id"]
        self.assertTrue(rid)
        self.run_cli("update", rid, "--notes", "first note", "--set", "Resume Versions=1")
        self.run_cli("update", rid, "--append-notes", "est. 2 hours")
        shown = self.run_cli("show", rid)
        self.assertTrue(shown["Notes"].startswith("first note\n"), shown["Notes"])
        self.assertTrue(shown["Notes"].endswith(": est. 2 hours"), shown["Notes"])
        self.assertEqual(shown["Resume Versions"], 1)
        self.run_cli("update", rid, "--status", "Applied", "--outcome", "Rejected")
        self.assertNotIn(rid, [r["id"] for r in self.run_cli("list", "--open")])
        self.assertFalse(self.run_cli("update", "no-such-row", "--status", "Applied", code=1)["ok"])
        self.assertFalse(self.run_cli("show", "no-such-row", code=1)["ok"])
        self.run_cli("contacts", "add", "--name", "Sam Example", "--company", "Second Clinics", "--last", "2026-11-01")
        self.assertEqual(self.run_cli("contacts", "list")[-1]["name"], "Sam Example")

    def test_company_research(self):
        r = self.run_cli("company", "--name", "Research Co (example)", "--set", "glassdoor=4.1", "--set", "verdict=Watch list",
                         "--set", "pto_weak=yes", "--set", "green=Remote since founding")
        self.assertTrue(r["ok"], r)
        shown = self.run_cli("company", "--name", "research co (example)")
        self.assertEqual((shown["glassdoor"], shown["verdict"], shown["pto_weak"], shown["green"]),
                         (4.1, "Watch list", True, "Remote since founding"))
        self.assertFalse(self.run_cli("company", "--name", "Research Co (example)", "--set", "verdict=Maybe", code=1)["ok"])
        self.assertFalse(self.run_cli("company", "--name", "Nobody (example)", code=1)["ok"])

    def test_add_find_update_list(self):
        added = self.run_cli("add", "--text-file", self.posting, "--title", "Senior Product Manager",
                             "--company", "Good Fit Clinics")
        self.assertTrue(added["ok"], added)
        self.assertIsInstance(added["score"], int)
        self.assertIn(added["tier"], ("A", "B", "C"))   # the verdict is the user's call, so it starts empty

        self.assertTrue(added["id"])
        rows = self.run_cli("find", "--company", "good fit")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Role"], "Senior Product Manager")

        upd = self.run_cli("update", row["id"], "--status", "Drafting Resume",
                           "--set", "Drafting Started=2026-10-31", "--set", "Resume Versions=2",
                           "--set", "Hours Spent=1.5", "--set", "Contact Before Applying=tried, no answer")
        self.assertTrue(upd["ok"])

        pages = json.loads((self.data / "tracker" / "applications.json").read_text())["pages"]
        page = pages[row["id"]]["properties"]
        self.assertEqual(page["Status"]["status"]["name"], "Drafting Resume")
        self.assertEqual(page["Drafting Started"]["date"]["start"], "2026-10-31")
        self.assertEqual(page["Resume Versions"]["number"], 2)
        self.assertEqual(page["Hours Spent"]["number"], 1.5)
        self.assertEqual(page["Contact Before Applying"]["rich_text"][0]["text"]["content"], "tried, no answer")

        open_rows = self.run_cli("list", "--open")
        self.assertIn(row["id"], [r["id"] for r in open_rows])

        self.run_cli("update", row["id"], "--status", "Applied")
        page = json.loads((self.data / "tracker" / "applications.json").read_text())["pages"][row["id"]]["properties"]
        self.assertIn("Date Applied", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
