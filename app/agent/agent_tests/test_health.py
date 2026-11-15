"""The Health page's numbers: headline counts, what needs you today, the
weekly chart against your target, whether drafting is getting easier, and
the targets you save from the page. Made-up rows only. No network.
    python3 app/agent/agent_tests/test_health.py
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import health  # noqa: E402

TODAY = date(2026, 3, 18)   # a Wednesday; the week starts Monday March 16
CFG = {"WEEKLY_TARGET": 2, "CONTACTS_TARGET": 2, "NO_REPLY_DAYS": 30, "GOAL_DATE": ""}


def row(n, status, applied="", **kw):
    return {"id": f"0000000{n}", "Company": f"Example Co {n}", "Role": "Analyst", "Status": status,
            "Date Applied": applied, **kw}


class Summary(unittest.TestCase):
    def test_headline_counts(self):
        rows = [row(1, "Applied", "2026-03-17"), row(2, "Interviewing", "2026-03-02"),
                row(3, "Rejected", "2026-01-05", **{"Outcome Type": "Recruiter screen"}),
                row(4, "Rejected", "2026-02-25", **{"Outcome Type": "Rejected"}),
                row(5, "Interested"), row(6, "Drafting Resume")]
        h = health.summarize(rows, [], TODAY, CFG)["headline"]
        self.assertEqual((h["in_progress"], h["interviews"], h["sent_total"], h["sent_30"]), (2, 2, 4, 3))
        self.assertEqual(h["interview_rate"], 50)
        self.assertEqual(h["sent_week"], 1)
        self.assertEqual(h["open_postings"], 1)

    def test_nothing_sent_yet(self):
        s = health.summarize([row(1, "Interested")], [], TODAY, CFG)
        self.assertIsNone(s["headline"]["interview_rate"])
        self.assertEqual(s["drafting"]["sends"], 0)
        self.assertIsNone(s["drafting"]["versions_recent"])
        self.assertIn("0 sent in the last 30 days", s["takeaway"])

    def test_weeks_and_target(self):
        rows = [row(1, "Applied", "2026-03-16"), row(2, "Applied", "2026-03-10"), row(3, "Applied", "2026-03-12"),
                row(4, "Applied", "2026-03-03")]
        s = health.summarize(rows, [], TODAY, CFG)
        w = s["weeks"]
        self.assertEqual(len(w), 8)
        self.assertEqual(w[-1], {"week": "2026-03-16", "sent": 1, "target": 2, "done": False})
        self.assertEqual(w[-2]["sent"], 2)
        self.assertEqual(s["headline"]["weeks_hit"], 1)          # only the week of March 9 met 2
        self.assertEqual(s["headline"]["weeks_finished"], 7)     # this week isn't over

    def test_no_target_hides_the_line(self):
        s = health.summarize([row(1, "Applied", "2026-03-16")], [], TODAY, {**CFG, "WEEKLY_TARGET": 0})
        self.assertIsNone(s["weeks"][-1]["target"])
        self.assertIsNone(s["headline"]["weeks_hit"])

    def test_attention_order_and_kinds(self):
        rows = [row(1, "Interested", **{"Overall Verdict": "Strong fit", "Role Fit Score": 81}),
                row(2, "Applied", "2026-02-01"),
                row(3, "Applied", "2026-03-10", **{"Follow-up Date": "2026-03-17"}),
                row(4, "Interviewing", "2026-03-01", **{"Next Step": "Second round Friday"}),
                row(5, "Drafting Resume", **{"Drafting Started": "2026-03-15", "Resume Versions": 3}),
                row(6, "Interested", **{"Overall Verdict": "Applying"}),
                row(7, "Applied", "2026-02-01", **{"Outcome Type": "Rejected"}),
                row(8, "Interested", **{"Overall Verdict": "Possible fit", "Role Fit Score": 75})]
        a = health.summarize(rows, [], TODAY, CFG)["attention"]
        self.assertEqual([x["kind"] for x in a], ["Interview", "Follow-up due", "No reply", "Draft open", "Not sent yet", "Your call"])
        self.assertEqual(a[0]["what"], "Second round Friday")
        self.assertIn("45 days", a[2]["what"])
        self.assertEqual(a[3]["what"], "Draft in progress (started 2026-03-15, resume at version 3). Send it or close it.")
        self.assertNotIn("Example Co 7", [x["company"] for x in a])   # has an outcome, so it isn't waiting
        self.assertNotIn("Example Co 8", [x["company"] for x in a])   # Possible fit stays on the Applications page

    def test_no_reply_days_is_yours(self):
        rows = [row(1, "Applied", "2026-03-01")]
        self.assertEqual(health.summarize(rows, [], TODAY, CFG)["attention"], [])
        a = health.summarize(rows, [], TODAY, {**CFG, "NO_REPLY_DAYS": 14})["attention"]
        self.assertEqual([x["kind"] for x in a], ["No reply"])

    def test_attention_is_capped(self):
        rows = [row(i, "Interested", **{"Overall Verdict": "Strong fit"}) for i in range(1, 16)]
        s = health.summarize(rows, [], TODAY, CFG)
        self.assertEqual((len(s["attention"]), s["attention_more"]), (health.ATTENTION_MAX, 15 - health.ATTENTION_MAX))
        self.assertIn("15 things waiting on you", s["takeaway"])

    def test_drafting_trend_recent_against_earlier(self):
        rows = [row(i, "Applied", f"2026-02-{i + 1:02d}", **{"Resume Versions": v, "Drafting Started": f"2026-02-{i:02d}"})
                for i, v in enumerate([6, 7, 5, 3, 2, 2, 3, 1], start=1)]
        rows.append(row(20, "Applied", "2025-12-01", **{"Resume Versions": 12}))   # before tracking began
        d = health.summarize(rows, [], TODAY, CFG, tracking_starts=date(2026, 1, 1))["drafting"]
        self.assertEqual(d["sends"], 8)
        self.assertEqual(d["versions_recent"], 2)      # last 5: 3, 2, 2, 3, 1
        self.assertEqual(d["versions_earlier"], 6)     # first 3: 6, 7, 5
        self.assertEqual(d["days_median"], 1)
        self.assertEqual(d["since"], "2026-01-01")

    def test_contacts_and_goal_date(self):
        contacts = [{"name": "A", "last": "2026-03-17"}, {"name": "B", "last": "2026-03-02"}, {"name": "C"}]
        s = health.summarize([], contacts, TODAY, {**CFG, "GOAL_DATE": "2026-04-17"})
        self.assertEqual((s["contacts"]["this_week"], s["contacts"]["last_4_weeks"], s["contacts"]["people"]), (1, 2, 3))
        self.assertEqual(s["headline"]["days_left"], 30)
        self.assertEqual(health.summarize([], [], TODAY, CFG)["headline"]["days_left"], None)

    def test_bad_dates_dont_break_it(self):
        rows = [row(1, "Applied", "not a date"), row(2, "Drafting Resume", **{"Drafting Started": "soon"})]
        s = health.summarize(rows, [{"last": "yesterday"}], TODAY, CFG)
        self.assertEqual(s["headline"]["sent_total"], 0)
        self.assertEqual(s["contacts"]["this_week"], 0)


class Targets(unittest.TestCase):
    def test_clean(self):
        ok, err = health.clean_targets({"WEEKLY_TARGET": "4", "CONTACTS_TARGET": 0, "NO_REPLY_DAYS": "21", "GOAL_DATE": "2027-03-31"})
        self.assertIsNone(err)
        self.assertEqual(ok, {"WEEKLY_TARGET": 4, "CONTACTS_TARGET": 0, "NO_REPLY_DAYS": 21, "GOAL_DATE": "2027-03-31"})
        for bad in ({"WEEKLY_TARGET": "two"}, {"WEEKLY_TARGET": "-1"}, {"WEEKLY_TARGET": "51"},
                    {"NO_REPLY_DAYS": "0"}, {"GOAL_DATE": "March 31"}):
            self.assertIsNone(health.clean_targets(bad)[0], bad)
        self.assertEqual(health.clean_targets({"GOAL_DATE": ""})[0], {"GOAL_DATE": ""})

    def test_save_keeps_the_rest_of_criteria(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "criteria.json"
            f.write_text(json.dumps({"agent": {"FRESH_DAYS": 14}}))
            old = os.environ.get("KIT_SETTINGS_DIR")
            os.environ["KIT_SETTINGS_DIR"] = d
            try:
                r = health.save_targets(d, {"WEEKLY_TARGET": "5", "GOAL_DATE": "2027-01-31"})
                self.assertTrue(r["ok"], r)
                saved = json.loads(f.read_text())
                self.assertEqual(saved["agent"], {"FRESH_DAYS": 14})
                self.assertEqual(saved["health"], {"WEEKLY_TARGET": 5, "GOAL_DATE": "2027-01-31"})
                self.assertEqual(r["targets"]["CONTACTS_TARGET"], health.DEFAULTS["CONTACTS_TARGET"])
                r = health.save_targets(d, {"WEEKLY_TARGET": "lots"})
                self.assertFalse(r["ok"])
                self.assertEqual(json.loads(f.read_text())["health"]["WEEKLY_TARGET"], 5)   # nothing saved on an error
            finally:
                if old is None:
                    os.environ.pop("KIT_SETTINGS_DIR", None)
                else:
                    os.environ["KIT_SETTINGS_DIR"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
