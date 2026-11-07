"""Settings folders made by older kits keep working after an update.

fixtures/settings-v0.1.0/ holds the settings files exactly as v0.1.0 shipped
them (the blank template and one example person). Every module that reads
settings at import time must load from them, the setup page must read them,
and the settings update step (kit_settings.migrate) must leave them byte for
byte unchanged until a real migration exists. A setting that disappears from
the current templates without a version bump fails here.
    python3 app/agent/agent_tests/test_settings_versions.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
KIT = APP.parent
OLD = HERE / "fixtures" / "settings-v0.1.0"
sys.path.insert(0, str(APP))
import kit_settings   # noqa: E402

MODULES = ["agent/job_search_agent.py", "agent/fit_scoring.py", "agent/invariants.py",
           "agent/market_report.py", "resume/presend_gate.py", "resume/build_resume.py",
           "resume/build_letter.py", "wizard.py", "setup_model.py"]


def keys(folder):
    out = set()
    for f in sorted(Path(folder).glob("*.json")):
        for section, v in json.loads(f.read_text()).items():
            if isinstance(v, dict) and f.name != "app.json":
                out |= {f"{f.name}:{section}.{k}" for k in v}
            else:
                out.add(f"{f.name}:{section}")
    return out


class OldSettings(unittest.TestCase):
    def folder(self, which):
        """A Job Search folder: the old settings plus a bank and a data folder."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(OLD / which, root / "settings")
        bank = KIT / ("examples/priya-healthtech-pm/Evidence Bank" if which == "priya" else "templates/Evidence Bank")
        shutil.copytree(bank, root / "Evidence Bank")
        (root / "data").mkdir()
        return root / "settings"

    def test_every_module_loads(self):
        for which in ("template", "priya"):
            s = self.folder(which)
            env = dict(os.environ, KIT_SETTINGS_DIR=str(s), AGENT_DRY_RUN="1")
            for m in MODULES:
                path = APP / m
                code = (f"import sys, runpy; sys.path[:0] = [{str(path.parent)!r}, {str(APP)!r}, {str(APP / 'agent')!r}]; "
                        f"import importlib; importlib.import_module({path.stem!r})")
                with self.subTest(settings=which, module=m):
                    r = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(path.parent),
                                       capture_output=True, text=True, timeout=120)
                    self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_setup_page_reads_them(self):
        import setup_model
        for which in ("template", "priya"):
            with self.subTest(settings=which):
                answers = setup_model.read_answers(self.folder(which))
                self.assertIsInstance(answers, dict)
                self.assertTrue(answers)

    def test_update_brings_a_v0_folder_forward(self):
        """v0.1.0 folders reach the current version: the v2 step removes the two
        retired 48-hour-rule settings (after a backup) and touches nothing else."""
        for which in ("template", "priya"):
            s = self.folder(which)
            before = {f.name: f.read_bytes() for f in s.iterdir()}
            calls = []
            changes, warning = kit_settings.migrate(s, backup=lambda: calls.append(1))
            with self.subTest(settings=which):
                self.assertIsNone(warning)
                self.assertEqual(calls, [1])
                self.assertEqual(len(changes), 2, changes)
                self.assertTrue(all("ASK_EXPIRY_DAYS" in c or "NO_DECISION_VERDICT" in c for c in changes))
                after = {f.name: f.read_bytes() for f in s.iterdir()}
                self.assertEqual({n for n in before if before[n] != after.get(n)}, {"criteria.json", "app.json"})
                agent = json.loads((s / "criteria.json").read_text())["agent"]
                self.assertFalse(set(kit_settings.RETIRED_V2) & set(agent))
                self.assertEqual(kit_settings.folder_settings_version(s), kit_settings.SETTINGS_VERSION)
                # a second run changes nothing
                changes, warning = kit_settings.migrate(s, backup=lambda: self.fail("no backup expected"))
                self.assertEqual((changes, warning), ([], None))


class Versions(unittest.TestCase):
    def test_template_carries_the_current_version(self):
        self.assertEqual(kit_settings.folder_settings_version(KIT / "templates" / "settings"),
                         kit_settings.SETTINGS_VERSION)

    def test_every_version_has_a_step(self):
        self.assertEqual(sorted(kit_settings.MIGRATIONS), list(range(kit_settings.SETTINGS_VERSION)))

    def test_removed_settings_need_a_bump(self):
        # Renaming or removing a setting breaks older folders unless a migration
        # moves it. Bump SETTINGS_VERSION, add the step, then update this baseline.
        gone = keys(OLD / "template") - keys(KIT / "templates" / "settings")
        if kit_settings.SETTINGS_VERSION == 2:
            self.assertEqual(gone, {f"criteria.json:agent.{k}" for k in kit_settings.RETIRED_V2},
                             "settings removed or renamed since v0.1.0 without a migration")

    def test_newer_settings_warn_and_write_nothing(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "app.json").write_text(json.dumps({"settings_version": kit_settings.SETTINGS_VERSION + 5}))
        before = (d / "app.json").read_bytes()
        changes, warning = kit_settings.migrate(d, backup=lambda: self.fail("no backup expected"))
        self.assertEqual(changes, [])
        self.assertIn("newer version of the kit", warning)
        self.assertEqual((d / "app.json").read_bytes(), before)

    def test_a_real_step_backs_up_then_writes(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "app.json").write_text(json.dumps({"tracker": "local"}))
        (d / "criteria.json").write_text(json.dumps({"agent": {"OLD_NAME": 3}}))
        (d / "resume.json").write_text(json.dumps({"presend_gate": {}}))
        untouched = (d / "resume.json").read_bytes()

        def rename(files):
            a = files["criteria.json"]["agent"]
            a["NEW_NAME"] = a.pop("OLD_NAME")
            return ["renamed OLD_NAME to NEW_NAME"]
        order = []
        saved = dict(kit_settings.MIGRATIONS)
        kit_settings.MIGRATIONS[0] = lambda files: (order.append("step"), rename(files))[1]
        try:
            changes, warning = kit_settings.migrate(d, backup=lambda: order.append("backup"))
        finally:
            kit_settings.MIGRATIONS.clear()
            kit_settings.MIGRATIONS.update(saved)
        self.assertEqual(changes, ["renamed OLD_NAME to NEW_NAME"])
        self.assertEqual(order, ["step", "backup"])
        self.assertEqual(json.loads((d / "criteria.json").read_text()), {"agent": {"NEW_NAME": 3}})
        self.assertEqual(kit_settings.folder_settings_version(d), kit_settings.SETTINGS_VERSION)
        self.assertEqual((d / "resume.json").read_bytes(), untouched)


if __name__ == "__main__":
    unittest.main(verbosity=2)
