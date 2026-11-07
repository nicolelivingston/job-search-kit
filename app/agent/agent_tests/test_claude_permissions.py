"""The Job Search folder carries Claude's permissions file: web fetch and
search off, download commands refused, every command asks, approval-skipping
modes off, the kit folder readable; an existing file is never replaced. The
kit's posting fetch writes only .md files under Applications/. No network.
    python3 app/agent/agent_tests/test_claude_permissions.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "agent"))


class ClaudePermissions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {k: os.environ.get(k) for k in ("KIT_SETTINGS_DIR", "KIT_CONFIG_DIR")}
        os.environ["KIT_CONFIG_DIR"] = str(self.tmp / "config")
        import first_run
        self.fr = first_run
        self.root = self.tmp / "Job Search"
        first_run.create_folder(self.root)

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        import kit_settings
        kit_settings._cache.clear()
        shutil.rmtree(self.tmp)

    def test_file_written_with_the_rules(self):
        f = self.root / ".claude" / "settings.json"
        p = json.loads(f.read_text())["permissions"]
        self.assertEqual(p["ask"], ["Bash", "PowerShell"])
        for rule in ("WebFetch", "WebSearch", "Bash(curl *)", "Bash(wget *)", "PowerShell(Invoke-WebRequest *)"):
            self.assertIn(rule, p["deny"])
        self.assertEqual((p["disableBypassPermissionsMode"], p["disableAutoMode"]), ("disable", "disable"))
        self.assertEqual(p["additionalDirectories"], [str(self.fr.KIT)])
        self.assertNotIn("allow", p)   # nothing runs without the user's OK

    def test_existing_file_kept(self):
        f = self.root / ".claude" / "settings.json"
        f.write_text('{"mine": true}')
        self.assertFalse(self.fr.write_claude_settings(self.root))
        self.assertEqual(json.loads(f.read_text()), {"mine": True})

    def test_fetch_writes_only_under_applications(self):
        os.environ["KIT_SETTINGS_DIR"] = str(self.root / "settings")
        import kit_settings
        kit_settings._cache.clear()
        import tracker_cli
        fake = lambda url: "<p>Product Manager. Remote. 5 years.</p>"
        out = self.root / "Applications" / "_pulled" / "acme-2026-11-01.md"
        r = tracker_cli.fetch_posting("https://jobs.example.com/1", str(out), fetch=fake)
        self.assertTrue(r["ok"], r)
        text = out.read_text()
        self.assertTrue(text.startswith("Source: https://jobs.example.com/1\nPulled: "))
        self.assertIn("Product Manager", text)
        for bad in (self.root / "settings" / "x.md", self.root / "Applications" / "x.json", self.tmp / "x.md",
                    self.root / "Applications" / ".." / "Evidence Bank" / "Evidence Bank.md"):
            self.assertFalse(tracker_cli.fetch_posting("https://jobs.example.com/1", str(bad), fetch=fake)["ok"], bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
