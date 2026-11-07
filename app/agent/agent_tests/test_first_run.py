"""First run: where the user's Job Search folder lives. Detects a Documents
folder synced by OneDrive (by path or by the OneDrive variables) or iCloud,
offers Documents or a local-only folder, creates the folder from the
templates for either choice without overwriting existing files, writes
paths.json with kit_dir, and records the settings folder in a pointer file
that kit_settings falls back to when KIT_SETTINGS_DIR is unset.
    python3 app/agent/agent_tests/test_first_run.py
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
sys.path.insert(0, str(APP))
import first_run  # noqa: E402


class FirstRun(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {"KIT_CONFIG_DIR": str(self.tmp / "config")}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_detects_synced_documents(self):
        self.assertTrue(first_run.is_synced(r"C:\Users\Example\OneDrive\Documents", env={}))
        self.assertTrue(first_run.is_synced(r"C:\Users\Example\OneDrive - Contoso\Documents", env={}))
        self.assertTrue(first_run.is_synced("/Users/example/Library/Mobile Documents/com~apple~CloudDocs/Documents", env={}))
        self.assertTrue(first_run.is_synced(r"C:\Users\Example\Docs", env={"OneDrive": r"C:\Users\Example\Docs"}))
        self.assertTrue(first_run.is_synced(r"C:\Users\Example\Cloud\Documents", env={"OneDriveCommercial": r"C:\Users\Example\Cloud"}))
        self.assertFalse(first_run.is_synced(r"C:\Users\Example\Documents", env={}))
        self.assertFalse(first_run.is_synced(r"C:\Users\Example\Documents", env={"OneDrive": r"C:\Users\Example\OneDrive"}))
        self.assertFalse(first_run.is_synced("/Users/example/Documents", env={}))

    def test_options_name_both_places(self):
        synced_docs = self.home / "OneDrive" / "Documents"
        synced_docs.mkdir(parents=True)
        o = first_run.options(platform="linux", home=self.home, env={})   # linux path: Documents = home/Documents
        self.assertEqual(o["local"]["path"], str(self.home / "Job Search"))
        self.assertEqual(o["documents"]["path"], str(self.home / "Documents" / "Job Search"))
        self.assertFalse(o["documents_synced"])
        o = first_run.options(platform="linux", home=self.home, env={"OneDrive": str(self.home)})
        self.assertTrue(o["documents_synced"])
        self.assertIn("backed up", o["documents"]["label"])

    def _check_folder(self, settings):
        dest = settings.parent
        for f in ("Evidence Bank/Evidence Bank.md", "Evidence Bank/Rules File.md", "Evidence Bank/North Star.md",
                  "Review/review-log.md", "Applications/selection-template.json", "settings/criteria.json"):
            self.assertTrue((dest / f).exists(), f)
        self.assertTrue((dest / "data").is_dir())
        paths = json.loads((settings / "paths.json").read_text())
        self.assertEqual(paths["bank_dir"], "../Evidence Bank")
        self.assertEqual(paths["data_dir"], "../data")
        self.assertEqual(Path(paths["kit_dir"]), APP.parent)
        pointer = first_run.pointer_file(platform="linux", env=self.env)
        self.assertEqual(pointer.read_text().strip(), str(settings.resolve()))

    def test_documents_choice(self):
        settings = first_run.choose("documents", platform="linux", home=self.home, env=self.env)
        self.assertEqual(settings, self.home / "Documents" / "Job Search" / "settings")
        self._check_folder(settings)

    def test_local_choice_and_no_overwrite(self):
        settings = first_run.choose("local", platform="linux", home=self.home, env=self.env)
        self.assertEqual(settings, self.home / "Job Search" / "settings")
        self._check_folder(settings)
        bank = settings.parent / "Evidence Bank" / "Evidence Bank.md"
        bank.write_text("my edits")
        first_run.choose("local", platform="linux", home=self.home, env=self.env)   # running setup again
        self.assertEqual(bank.read_text(), "my edits")

    def test_kit_settings_falls_back_to_pointer(self):
        settings = first_run.choose("local", platform="linux", home=self.home, env=self.env)
        env = dict(os.environ, KIT_CONFIG_DIR=self.env["KIT_CONFIG_DIR"])
        env.pop("KIT_SETTINGS_DIR", None)
        code = "import kit_settings, first_run; print(kit_settings.settings_dir())"
        # pointer_file() reads os.environ, so the subprocess sees KIT_CONFIG_DIR; linux and mac share the path rule
        r = subprocess.run([sys.executable, "-c", code], cwd=str(APP), env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(r.stdout.strip()), settings.resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
