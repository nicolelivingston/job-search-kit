"""The Work column: Fully Remote, Hybrid, Onsite, or not stated, read from
what a posting says about the role. Before Nov 15, 2026 only Fully Remote was
ever set, so hybrid and onsite postings showed "Not stated". Made-up posting
text only. No network.
    python3 app/agent/agent_tests/test_work_status.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fit_scoring as fs  # noqa: E402
import job_search_agent as jsa  # noqa: E402


def work(text, remote=False, location=""):
    return fs.work_status(text, location, remote_hint=remote)


class WorkStatus(unittest.TestCase):
    def test_hybrid(self):
        for t in ("Hybrid: 2 days per week in our Denver office. Build dashboards.",
                  "3 days a week in the office in Austin.",
                  "You will work in-office 3 days per week.",
                  "This is a hybrid role based in Toronto.",
                  "Come to our Seattle office two days a week."):
            self.assertEqual(work(t), "Hybrid", t)

    def test_onsite(self):
        for t in ("Onsite in our Chicago office, 5 days per week.",
                  "This is an on-site position.",
                  "Fully onsite at our Atlanta campus.",
                  "Five days a week in our Boston office."):
            self.assertEqual(work(t), "Onsite", t)

    def test_remote_and_not_stated(self):
        self.assertEqual(work("Build dashboards.", remote=True), "Fully Remote")
        self.assertIsNone(work("Location: New York. Own the roadmap."))

    def test_firm_wording_wins_over_a_remote_location(self):
        self.assertEqual(work("Hybrid: 2 days per week in our Denver office.", remote=True, location="Remote (US)"), "Hybrid")

    def test_choice_other_teams_and_tech_words_are_ignored(self):
        for t in ("This role is remote or hybrid, your choice.",
                  "Hybrid optional; most of the team is remote.",
                  "Some roles in our sales team are hybrid. This role is remote.",
                  "We build hybrid cloud infrastructure for retailers.",
                  "Ship our hybrid mobile apps."):
            self.assertEqual(work(t, remote=True), "Fully Remote", t)

    def test_daily_agent_uses_it(self):
        job = {"title": "Senior Analyst", "location": "Denver, CO", "description": "Hybrid: 3 days per week in our Denver office."}
        self.assertEqual(jsa.remote_status_for(job), "Hybrid")
        job = {"title": "Senior Analyst", "location": "Remote - US", "description": "Build dashboards."}
        self.assertEqual(jsa.remote_status_for(job), "Fully Remote")
        job = {"title": "Senior Analyst", "location": "Chicago, IL", "description": "Build dashboards."}
        self.assertIsNone(jsa.remote_status_for(job))


if __name__ == "__main__":
    unittest.main(verbosity=2)
