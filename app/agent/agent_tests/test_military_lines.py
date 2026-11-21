"""A hiring or benefit line about military service is not the work. For a user
whose excluded-industries list has "military" or "defense", lines such as
"including military members and their spouses", "military leave", and
"military service" no longer drop a posting at the first industry check or
close it at the hard rules. Real defense work still does, and the
equal-opportunity paragraph stays ignored as before. Ported from the personal
system (first gate Nov 16, fit scoring v4.9 Nov 17, 2026; NIC-43). Every
posting here is made up. No network.
    python3 app/agent/agent_tests/test_military_lines.py
"""
import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
os.environ.pop("NOTION_TOKEN", None)

import fit_scoring as fs  # noqa: E402
import job_search_agent as agent  # noqa: E402

ROLE = "You will own reporting for our insurance agency software. This role is fully remote in the US. "
BENIGN = {
    "hiring line": ROLE + "Our teams hire from many paths: career changers, parents coming back, military members and their spouses.",
    "benefits list": ROLE + "Benefits include parental leave, military leave, and a home office stipend.",
    "skills line": ROLE + "We value the skills people build through military service and career changes.",
    "hiring program": ROLE + "We partner with programs that place military spouses in remote roles.",
    "equal-opportunity paragraph": ROLE + "We consider all applicants without regard to race, color, religion, sex, "
                                   "national origin, age, disability, military or veteran status, or any other protected category.",
}
WORK = {
    "defense customers": ROLE + "You will own mission planning software for military customers and the Department of Defense.",
    "military bases": ROLE + "Our customers include military bases and defense contractors.",
    "defense plus a hiring line": ROLE + "You will build tools for defense agencies. We welcome military spouses.",
}


class MilitaryLines(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(agent, "EXCLUDE_KEYWORDS", ["military", "defense"]),
                  mock.patch.object(agent, "INDUSTRY_EXCEPTION_KEYWORDS", []),
                  mock.patch.object(fs, "EXCLUDED_INDUSTRY_RE", fs._rx("military", "defense")),
                  mock.patch.object(fs, "EXCLUDED_COMPANIES", fs._rx("~(?!)"))]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def industry_reasons(self, text):
        _, reasons = fs.hard_screen("Senior Analyst", text, salary_min=400000, remote_hint=True)
        return [r for r in reasons if r.startswith(fs.EXCLUDED_INDUSTRY_LABEL)]

    def test_hiring_and_benefit_lines_pass(self):
        for name, text in BENIGN.items():
            with self.subTest(line=name):
                self.assertIsNone(agent.excluded_industry_word(text))
                self.assertEqual(agent.industry_flag(text), "Clear")
                self.assertNotEqual(agent.score_domain(text), 0)
                self.assertEqual(self.industry_reasons(text), [])

    def test_real_work_is_still_excluded(self):
        for name, text in WORK.items():
            with self.subTest(work=name):
                self.assertIsNotNone(agent.excluded_industry_word(text))
                self.assertEqual(agent.industry_flag(text), "Excluded")
                self.assertEqual(agent.score_domain(text), 0)
                self.assertTrue(self.industry_reasons(text), name)

    def test_one_list_for_both_checks(self):
        self.assertTrue(fs.is_benign_line("military leave", 0))
        self.assertFalse(fs.is_benign_line("military customers", 0))
        self.assertIn("fit_scoring.is_benign_line", inspect.getsource(agent.excluded_industry_word))

    def test_log_names_the_word(self):
        src = inspect.getsource(agent.main)
        self.assertIn("excluded industry (%r is on your list)", src)
        self.assertIn("same role already handled from another source this run", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
