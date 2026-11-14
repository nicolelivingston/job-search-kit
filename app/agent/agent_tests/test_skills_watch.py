"""Skills watch: the skills list (settings, the older lexicon, or the
evidence bank's keyword groups), statuses, weekly history and trend math, the
Skills page's save rules, the weekly refresh (and the market report script
found beside the agent, not in the data folder), Remotive read for every
field, the history in the daily backup, and no field-specific wording in the
report or the page. Runs as the current test person. No network.
    python3 app/agent/agent_tests/test_skills_watch.py
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
KIT = APP.parent
sys.path[:0] = [str(HERE.parent), str(APP), str(HERE)]
import kit_settings  # noqa: E402
import market_report as mr  # noqa: E402
import person  # noqa: E402

SK = [mr._skill("Dashboards", mr.phrases_pattern(["dashboard", "dashboards"]), "Skilled", "E01"),
      mr._skill("Forecasting", mr.phrases_pattern(["forecast", "forecasting"]), "Gap"),
      mr._skill("Hiring", mr.phrases_pattern(["hiring"]), "Gap", track=False)]


class Temp(unittest.TestCase):
    """A temporary Job Search folder: the test person's settings, bank, and an empty data folder."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        src = person.settings_dir()
        s = self.tmp / "settings"
        shutil.copytree(src, s)
        p = json.loads((s / "paths.json").read_text())
        bank = (src / p.get("bank_dir", "../Evidence Bank")).resolve()
        if bank.exists():
            shutil.copytree(bank, self.tmp / "Evidence Bank")
        p.update(bank_dir="../Evidence Bank", data_dir="../data")
        (s / "paths.json").write_text(json.dumps(p))
        self.settings = s
        env = mock.patch.dict(os.environ, {"KIT_SETTINGS_DIR": str(s)})
        env.start()
        self.addCleanup(env.stop)
        kit_settings._cache.clear()
        self.addCleanup(kit_settings._cache.clear)

    def criteria(self):
        return json.loads((self.settings / "criteria.json").read_text())

    def write_market(self, **values):
        c = self.criteria()
        c["market_report"] = {**c.get("market_report", {}), **values}
        (self.settings / "criteria.json").write_text(json.dumps(c))
        kit_settings._cache.clear()


class Pure(unittest.TestCase):
    def test_statuses_and_older_words(self):
        self.assertEqual([mr.normalize_status(x) for x in ("skilled", "HAVE", "Partial gap", "PARTIAL", "gap")],
                         ["Skilled", "Skilled", "Partial gap", "Partial gap", "Gap"])
        with self.assertRaises(ValueError):
            mr.normalize_status("expert")

    def test_keywords_match_whole_words_only(self):
        rx = re.compile(mr.phrases_pattern(["SQL", "a/b test", "C++"]), re.I)
        self.assertTrue(rx.search("Strong SQL skills"))
        self.assertFalse(rx.search("PostgreSQLish tools"))
        self.assertTrue(rx.search("run an A/B test weekly"))
        self.assertTrue(rx.search("C++ and Python"))
        self.assertTrue(re.search(mr.phrases_pattern(["~forecast(ing)?\\b"]), "demand forecasting", re.I))

    def test_rank_share_and_untracked(self):
        counts = mr.count_matches(SK, ["build dashboards", "forecasting and dashboards", "hiring now"])
        self.assertEqual(counts, {"Dashboards": 2, "Forecasting": 1, "Hiring": 1})
        rows = mr.build_rows(SK, counts, 4)
        self.assertEqual([r["name"] for r in rows], ["Dashboards", "Forecasting"])
        self.assertEqual(rows[0]["share"], 0.5)
        self.assertIsNone(rows[0]["share_change"])   # first snapshot: "new", not zero

    def test_change_since_last_snapshot(self):
        prev = {"date": "2026-11-01", "matched": 100, "keys": mr.lexicon_keys(SK),
                "counts": {"Dashboards": 30, "Forecasting": 40}}
        rows = {r["name"]: r for r in mr.build_rows(SK, {"Dashboards": 100, "Forecasting": 50}, 200, prev)}
        self.assertAlmostEqual(rows["Dashboards"]["share_change"], 0.20)
        self.assertAlmostEqual(rows["Forecasting"]["share_change"], -0.15)
        self.assertEqual(rows["Dashboards"]["rank_change"], 1)
        self.assertEqual(rows["Forecasting"]["rank_change"], -1)

    def test_changed_keywords_are_never_compared(self):
        keys = dict(mr.lexicon_keys(SK), Dashboards="00000000")
        prev = {"date": "2026-11-01", "matched": 100, "keys": keys, "counts": {"Dashboards": 30, "Forecasting": 40}}
        rows = {r["name"]: r for r in mr.build_rows(SK, {"Dashboards": 100, "Forecasting": 50}, 200, prev)}
        self.assertIsNone(rows["Dashboards"]["share_change"])
        self.assertIsNotNone(rows["Forecasting"]["share_change"])

    def test_history_rerun_replaces_the_day_and_skips_a_damaged_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "h.jsonl"
            mr.append_history({"date": "2026-11-15", "matched": 1, "counts": {}, "keys": {}}, p)
            mr.append_history({"date": "2026-11-15", "matched": 2, "counts": {}, "keys": {}}, p)
            mr.append_history({"date": "2026-11-08", "matched": 3, "counts": {}, "keys": {}}, p)
            with p.open("a") as f:
                f.write("{cut off\n")
            h = mr.load_history(p)
            self.assertEqual([(x["date"], x["matched"]) for x in h], [("2026-11-08", 3), ("2026-11-15", 2)])
            self.assertEqual(mr.previous_entry(h, "2026-11-15")["date"], "2026-11-08")

    def test_skills_changed(self):
        self.assertTrue(mr.skills_changed(SK, []))
        h = [{"date": "2026-11-08", "keys": mr.lexicon_keys(SK)}]
        self.assertFalse(mr.skills_changed(SK, h))
        self.assertTrue(mr.skills_changed(SK[:1], h))
        self.assertFalse(mr.skills_changed([], []))   # no list, nothing to refresh for


class SkillsList(Temp):
    def test_starts_from_the_keyword_groups(self):
        self.write_market(SKILLS=[], LEXICON=[])
        skills, source = mr.load_skills()
        groups = json.loads(kit_settings.keyword_groups_file().read_text())["fit_scoring"]
        work = [f["$tuple"][0] for f in groups.get("WORK_FAMILIES", [])]
        gaps = [f["$tuple"][0] for f in groups.get("GAP_FAMILIES", [])]
        if not (work or gaps):
            self.assertEqual((skills, source), ([], "none"))
            return
        self.assertEqual(source, "evidence bank")
        by = {s["name"]: s for s in skills}
        for w in work:
            self.assertEqual(by[w]["status"], "Skilled")
        for g in gaps:
            if g not in work:
                self.assertEqual(by[g]["status"], "Gap")

    def test_settings_list_comes_first_then_the_lexicon(self):
        self.write_market(SKILLS=[], LEXICON=[["Dashboards", "dashboard", "HAVE"]])
        skills, source = mr.load_skills()
        self.assertEqual((source, skills[0]["status"]), ("lexicon", "Skilled"))
        self.write_market(SKILLS=[{"name": "Forecasting", "keywords": ["forecast"], "status": "Partial gap"}])
        skills, source = mr.load_skills()
        self.assertEqual((source, [s["name"] for s in skills], skills[0]["status"]),
                         ("settings", ["Forecasting"], "Partial gap"))

    def test_skills_page_saves_and_refuses_bad_rows(self):
        import wizard
        ok = wizard.skills_save({"skills": [
            {"name": "Forecasting", "keywords": "forecast, forecasting", "status": "gap", "evidence": ""},
            {"name": "", "keywords": [], "status": "Gap"},                       # an empty new row is skipped
            {"name": "Dashboards", "keywords": ["dashboard"], "status": "Skilled", "evidence": "E01", "track": False}]})
        self.assertEqual(ok, {"ok": True, "count": 2})
        saved = self.criteria()["market_report"]["SKILLS"]
        self.assertEqual(saved[0], {"name": "Forecasting", "keywords": ["forecast", "forecasting"], "status": "Gap",
                                    "evidence": "", "track": True})
        self.assertFalse(saved[1]["track"])
        got = wizard.skills_get()
        self.assertEqual((got["source"], [s["name"] for s in got["skills"]]), ("settings", ["Forecasting", "Dashboards"]))
        before = (self.settings / "criteria.json").read_bytes()
        for bad in ([{"name": "A", "keywords": ["x"]}, {"name": "a", "keywords": ["y"]}],    # listed twice
                    [{"name": "A", "keywords": []}],                                         # no keyword
                    [{"name": "A", "keywords": ["x"], "status": "Expert"}],                  # unknown status
                    [{"name": "A", "keywords": ["~(unclosed"]}]):                           # bad expression
            r = wizard.skills_save({"skills": bad})
            self.assertFalse(r["ok"], bad)
        self.assertEqual((self.settings / "criteria.json").read_bytes(), before)   # nothing half-saved


class Refresh(Temp):
    def run_refresh(self, today, snapshot="2026-11-12", changed=False):
        import job_search_agent as jsa
        calls = []
        data = kit_settings.data_dir()
        if snapshot:
            (data / f"Market_Snapshot_{snapshot}.md").write_text("x")
        with mock.patch.object(jsa, "DATA_DIR", data), \
                mock.patch.object(mr, "skills_changed", return_value=changed), \
                mock.patch.object(jsa.subprocess, "run",
                                  side_effect=lambda cmd, **k: calls.append(cmd) or mock.Mock(returncode=0)), \
                mock.patch.object(jsa, "notify"):
            jsa.maybe_refresh_market_snapshot(today)
        return calls

    def test_weekly_and_after_a_skills_change(self):
        self.assertEqual(self.run_refresh(date(2026, 11, 15)), [])                 # 3 days old
        self.assertEqual(len(self.run_refresh(date(2026, 11, 19))), 1)             # 7 days old
        self.assertEqual(len(self.run_refresh(date(2026, 11, 13), changed=True)), 1)

    def test_runs_the_script_beside_the_agent_not_in_the_data_folder(self):
        cmd = self.run_refresh(date(2026, 11, 20), snapshot=None)[0]
        script = Path(cmd[-1])
        self.assertEqual(script.name, "market_report.py")
        self.assertTrue(script.exists(), script)
        self.assertNotEqual(script.parent, kit_settings.data_dir())

    def test_history_is_in_the_daily_backup(self):
        import backup
        (kit_settings.data_dir() / "market_history.jsonl").write_text('{"date": "2026-11-08"}\n')
        import zipfile
        with zipfile.ZipFile(backup.backup(date(2026, 11, 15))) as z:
            self.assertIn("market_history.jsonl", z.namelist())


class FieldNeutral(unittest.TestCase):
    def test_remotive_reads_every_listing_by_default(self):
        import job_search_agent as jsa
        seen = {}

        def fake(fn, url, **kw):
            seen.update(kw)
            return mock.Mock(raise_for_status=lambda: None, json=lambda: {"jobs": []})
        with mock.patch.object(jsa, "REMOTIVE_SEARCH", ""), mock.patch.object(jsa, "request_with_retry", fake):
            jsa.fetch_remotive()
        self.assertIsNone(seen.get("params"))

    def test_report_and_page_name_no_field(self):
        """The skills watch works for any field, so its code and page never
        assume one (Nov 14, 2026)."""
        field_words = re.compile(r"product manag|\bPMs?\b|PM-titled|product owner", re.I)
        for f in (HERE.parent / "market_report.py", APP / "wizard.py", APP / "wizard_page.html",
                  HERE.parent / "job_search_agent.py"):
            hits = [line for line in f.read_text(encoding="utf-8").splitlines() if field_words.search(line)]
            self.assertEqual(hits, [], f.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
