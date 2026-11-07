"""Setup wizard model: reading a user's settings into plain answers and
writing them back changes nothing, and settings rebuilt from each synthetic
test person's answers score their postings exactly as before (same skips,
missing requirements, and scores). Also checks single answers land in the
right settings. No network.
    python3 app/agent/agent_tests/test_setup_model.py
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
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "agent" / "agent_tests"))
import setup_model as sm          # noqa: E402
from test_personas import SCORE, EXAMPLES, env_for   # noqa: E402


def score(root, settings):
    r = subprocess.run([sys.executable, "-c", SCORE, str(APP / "agent"), str(root)], capture_output=True, text=True,
                       env=env_for(settings), timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class SetupModel(unittest.TestCase):
    def copy_settings(self, root, tmp):
        dst = Path(tmp) / "settings"
        shutil.copytree(root / "settings", dst)
        p = json.loads((dst / "paths.json").read_text())
        p["bank_dir"] = str((root / "settings" / p["bank_dir"]).resolve())
        p["data_dir"] = str(Path(tmp) / "data")
        (dst / "paths.json").write_text(json.dumps(p))
        return dst

    def test_round_trip_and_same_scores(self):
        for root in EXAMPLES:
            with self.subTest(person=root.name), tempfile.TemporaryDirectory() as tmp:
                dst = self.copy_settings(root, tmp)
                before = score(root, dst)
                a = sm.read_answers(dst)
                sm.write_answers(dst, a)
                self.assertEqual(sm.read_answers(dst), a, "answers should survive a write and read")
                after = score(root, dst)
                self.assertEqual(after, before, f"{root.name}: rebuilding settings from answers changed results")

    def test_single_answers(self):
        root = next(r for r in EXAMPLES if r.name.startswith("priya"))
        with tempfile.TemporaryDirectory() as tmp:
            dst = self.copy_settings(root, tmp)
            a = sm.read_answers(dst)
            self.assertFalse(a["rules"]["direct_reports_ok"])
            a["rules"]["direct_reports_ok"] = True
            a["where"].update(mode="remote_or_hybrid", commute_areas=["columbus"], max_office_days=2)
            a["pay"]["floor"] = 140000
            a["rules"]["excluded_industries"] = ["tobacco", "firearms"]
            sm.write_answers(dst, a)
            c = json.loads((dst / "criteria.json").read_text())
            codes = [h["$tuple"][0] for h in c["fit_scoring"]["HARD_RULES"]]
            self.assertNotIn("people-manager", codes)
            self.assertEqual(c["fit_scoring"]["WORK_ARRANGEMENT"]["commute_areas"], ["columbus"])
            self.assertEqual(c["agent"]["SALARY_FLOOR"], 140000)
            self.assertEqual(c["fit_scoring"]["PAY_HARD_FLOOR"], 140000)
            self.assertIn("firearms", c["fit_scoring"]["EXCLUDED_INDUSTRY_RE"]["$rx"])
            sm.write_advanced(dst, {"agent.FRESH_DAYS": "21"})
            self.assertEqual(sm.read_advanced(dst)["agent.FRESH_DAYS"], 21)
            self.assertEqual(sm.read_answers(dst)["pay"]["floor"], 140000, "advanced write keeps setup answers")
            ap = dst / "app.json"
            appj = json.loads(ap.read_text()); appj.setdefault("schedule", {})["update"] = "10:15"; ap.write_text(json.dumps(appj))
            a = sm.read_answers(dst)
            self.assertTrue(a["run"]["auto_update"], "automatic updates default on")
            a["run"]["auto_update"] = False
            sm.write_answers(dst, a)
            appj = json.loads(ap.read_text())
            self.assertIs(appj["auto_update"], False)
            self.assertEqual(appj["schedule"]["update"], "10:15", "setup keeps the update time it doesn't ask about")


if __name__ == "__main__":
    unittest.main(verbosity=2)
