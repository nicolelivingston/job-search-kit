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

    def test_preferences_step(self):
        """Step 8 (How Claude works for you): defaults, the two gate settings it writes, bad values refused,
        and the keys the plugin owns kept."""
        root = next(r for r in EXAMPLES if r.name.startswith("priya"))
        with tempfile.TemporaryDirectory() as tmp:
            dst = self.copy_settings(root, tmp)
            self.assertFalse((dst / "preferences.json").exists(), "an older folder has no preferences file")
            before = score(root, dst)
            a = sm.read_answers(dst)
            p = a["prefs"]
            self.assertEqual(p["voice"]["avoid_habits"], [], "habits are suggestions only, none picked by default")
            self.assertTrue(all(p["format_rules"].values()), "format rules start on")
            self.assertEqual((p["resume_pages"], p["file_format"], p["permissions"]["save_fixes"]), ("auto", "word", "ask"))
            limit = json.loads((dst / "resume.json").read_text())["presend_gate"].get("PAGE_LIMIT")

            sm.write_answers(dst, a)   # defaults: no gate change beyond writing the em dash flag off
            g = json.loads((dst / "resume.json").read_text())["presend_gate"]
            self.assertIs(g["FLAG_EM_DASH"], False)
            self.assertEqual(g.get("PAGE_LIMIT"), limit, "'auto' leaves the page limit to Start Here session 3")

            pf = json.loads((dst / "preferences.json").read_text())
            pf["talked_through"] = "2026-11-07"   # written by the plugin, not the wizard
            (dst / "preferences.json").write_text(json.dumps(pf))
            a = sm.read_answers(dst)
            a["prefs"].update(tools=["Excel", " excel ", "Jira", ""], resume_pages="one", feedback="savage",
                              file_format="pdf", permissions={"update_tracker": "never", "save_fixes": "sometimes"})
            a["prefs"]["voice"].update(avoid_habits=["em_dash", "emojis", "not-a-habit"], tone="pirate", oxford_comma=True)
            a["prefs"]["format_rules"]["explain_jargon"] = False
            sm.write_answers(dst, a)
            p = sm.read_answers(dst)["prefs"]
            self.assertEqual(p["tools"], ["Excel", "Jira"], "tools are trimmed and de-duplicated")
            self.assertEqual(p["voice"]["avoid_habits"], ["em_dash", "emojis"])
            self.assertEqual((p["voice"]["tone"], p["feedback"], p["file_format"]), ("", "balanced", "word"), "unknown choices keep the saved value (Word is the only format for now)")
            self.assertEqual(p["permissions"], {"update_tracker": "never", "draft_messages": "can",
                                                "draft_form_answers": "can", "save_fixes": "ask"})
            self.assertFalse(p["format_rules"]["explain_jargon"])
            self.assertTrue(p["voice"]["oxford_comma"])
            self.assertEqual(p["talked_through"], "2026-11-07", "the wizard keeps the plugin's date")
            g = json.loads((dst / "resume.json").read_text())["presend_gate"]
            self.assertIs(g["FLAG_EM_DASH"], True, "picking em dashes turns on the gate's em dash flag")
            self.assertEqual(g["PAGE_LIMIT"], 1)
            self.assertEqual(sm.read_answers(dst)["prefs"], p, "preferences survive a write and read")
            self.assertEqual(score(root, dst), before, "preferences never change fit scores")

            a = sm.read_answers(dst)
            del a["prefs"]   # a page from before step 8 doesn't send them
            sm.write_answers(dst, a)
            self.assertEqual(sm.read_answers(dst)["prefs"], p, "an answer set without preferences leaves them alone")


class CurrentField(unittest.TestCase):
    """Setup's "which field is your current job in?" writes SAME_DOMAINS (the
    most careful tailoring tier) only for a field the user listed, and leaves
    companies tiered by name (TIER_PRECEDENTS, Advanced) alone."""

    def test_current_field_sets_the_same_field_tier(self):
        import tempfile
        dst = Path(tempfile.mkdtemp())
        a = sm.read_answers(dst)
        a["fields"]["domains"] = [{"name": "Healthcare", "interest": "high", "keywords": ["clinic"], "points": None, "was": None},
                                  {"name": "Retail", "interest": "low", "keywords": [], "points": None, "was": None}]
        a["fields"]["current_field"] = " healthcare "
        sm.write_answers(dst, a)
        crit = json.loads((dst / "criteria.json").read_text())
        crit["fit_scoring"]["TIER_PRECEDENTS"] = {"$dict": [[1, ["acme"]]]}
        (dst / "criteria.json").write_text(json.dumps(crit))
        self.assertEqual(crit["fit_scoring"]["SAME_DOMAINS"], ["Healthcare"])
        self.assertEqual(sm.read_answers(dst)["fields"]["current_field"], "Healthcare")

        a = sm.read_answers(dst)
        a["fields"]["current_field"] = "Not a listed field"
        sm.write_answers(dst, a)
        fs = json.loads((dst / "criteria.json").read_text())["fit_scoring"]
        self.assertEqual(fs["SAME_DOMAINS"], [], "only a field the user listed counts")
        self.assertEqual(fs["TIER_PRECEDENTS"], {"$dict": [[1, ["acme"]]]}, "setup leaves companies tiered by name alone")

if __name__ == "__main__":
    unittest.main(verbosity=2)
