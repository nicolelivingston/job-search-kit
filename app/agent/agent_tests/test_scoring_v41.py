#!/usr/bin/env python3
"""Fit scoring v4.1: posting boilerplate is never a requirement, and
equal-opportunity text never trips a rule.

Two bugs found by hand. (1) Benefits, time-off, and company-values lines
after a posting's requirements were quoted as requirements the user couldn't
meet, capping good fits at Possible fit or Poor fit. (2) A user who excludes
an industry such as defense had nearly every US posting closed on arrival,
because the equal-opportunity statement lists "military or veteran status".

Runs against any settings folder (CI uses the example person's); every
posting below is made up.

    cd app/agent && KIT_SETTINGS_DIR=../../examples/priya-healthtech-pm/settings python3 agent_tests/test_scoring_v41.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fit_scoring as fs          # noqa: E402
import job_search_agent as jsa    # noqa: E402

EEO = ("Ledgerly is an equal opportunity employer. We consider all qualified applicants without regard to "
       "race, color, religion, sex, national origin, age, disability, marital status, citizenship status, "
       "military or veteran status, genetic information, or any other status protected by law.")


class EqualOpportunityText(unittest.TestCase):
    def setUp(self):
        self._saved = (fs.EXCLUDED_INDUSTRY_RE, fs.HARD_RULES)
        fs.EXCLUDED_INDUSTRY_RE = fs._rx("military", "defense", "religious")
        fs.HARD_RULES = list(fs.HARD_RULES) + [("defense-rule", fs._rx("military", "veteran"), "skip", "Defense work")]

    def tearDown(self):
        fs.EXCLUDED_INDUSTRY_RE, fs.HARD_RULES = self._saved

    def test_eeo_statement_alone_does_not_exclude(self):
        text = "Fully remote. Ledgerly builds invoicing software for small businesses. " + EEO
        verdict, reasons = fs.hard_screen("Senior Product Manager", text, salary_min=180000, remote_hint=True)
        self.assertFalse(any("military" in r.lower() or "religio" in r.lower() or "defense" in r.lower()
                             for r in reasons), reasons)

    def test_real_defense_work_still_excluded(self):
        text = "Fully remote. You will own mission planning software for military customers. " + EEO
        verdict, reasons = fs.hard_screen("Senior Product Manager", text, salary_min=180000, remote_hint=True)
        self.assertEqual(verdict, "skip", reasons)

    def test_one_marker_word_is_not_enough_to_hide_a_sentence(self):
        # "veterans" alone doesn't make a sentence equal-opportunity text.
        text = "Fully remote. Brightspan builds benefits tools for veterans and the military."
        verdict, reasons = fs.hard_screen("Senior Product Manager", text, salary_min=180000, remote_hint=True)
        self.assertEqual(verdict, "skip", reasons)

    def test_title_still_counts(self):
        verdict, reasons = fs.hard_screen("Product Manager, Defense Programs", "Fully remote. " + EEO,
                                          salary_min=180000, remote_hint=True)
        self.assertEqual(verdict, "skip", reasons)

    def test_strip_eeo_removes_only_the_statement(self):
        text = "Fully remote role at Answerly. " + EEO + " Apply by Friday."
        out = fs.strip_eeo(text)
        self.assertIn("Answerly", out)
        self.assertIn("Apply by Friday", out)
        self.assertNotIn("veteran", out)

    def test_agent_keyword_checks_ignore_eeo_text(self):
        saved = jsa.EXCLUDE_KEYWORDS
        try:
            jsa.EXCLUDE_KEYWORDS = ["military"]
            self.assertEqual(jsa.industry_flag("Remote. Meridian builds scheduling software. " + EEO), "Clear")
            self.assertEqual(jsa.industry_flag("Remote. Meridian sells to military bases."), "Excluded")
        finally:
            jsa.EXCLUDE_KEYWORDS = saved


BENEFITS_AFTER_REQUIREMENTS = (
    "<h3>What you bring</h3><ul>"
    "<li>Experience defining product requirements and roadmaps with engineering and design partners.</li>"
    "<li>Strong in customer discovery, prioritization, and tradeoff communication with stakeholders.</li></ul>"
    "<p>Offers land within the range after we weigh experience, location, and internal peer equity.</p>"
    "<p>Full-time staff earn vacation each pay period and can carry some of it over.</p>"
    "<p>Part-time staff earn a prorated share of the same time off each month.</p>"
    "<p>Think this sounds like you? Apply today and tell us why in a few lines.</p>"
    "<p>The job involves repeating motions at a keyboard for much of the working day.</p>"
    "<p>The role is remote, and interviews will be conducted by video call only.</p>"
    "<p>Watch out for recruiting scams that borrow our name; we never ask for payment.</p>")


class BoilerplateIsNotARequirement(unittest.TestCase):
    def test_rubric_version(self):
        self.assertGreaterEqual(fs.RUBRIC_VERSION, "v4.1")

    def test_benefits_and_process_lines_are_skipped(self):
        items = fs.required_items(fs._clean(BENEFITS_AFTER_REQUIREMENTS))
        joined = " | ".join(items).lower()
        for word in ("vacation", "peer equity", "apply today", "repeating motions", "interviews will be", "scams", "time off"):
            self.assertNotIn(word, joined, items)

    def test_boilerplate_never_caps_a_posting(self):
        cov = fs.required_coverage(fs._clean(BENEFITS_AFTER_REQUIREMENTS))
        self.assertFalse(any("vacation" in u.lower() or "apply today" in u.lower() for u in cov["unvouched"]), cov)

    def test_required_block_stops_at_time_off_heading(self):
        text = fs._clean("<h3>Requirements</h3><ul><li>Experience shipping workflow software for operations teams.</li></ul>"
                         "<h3>Time off</h3><p>Twenty days of paid time off every year, plus company holidays for everyone.</p>")
        joined = " ".join(fs.required_items(text)).lower()
        self.assertNotIn("twenty days", joined)

    def test_real_requirements_still_count(self):
        text = fs._clean("<h3>Requirements</h3><ul><li>Deep knowledge of semiconductor wafer fabrication process control</li>"
                         "<li>Hands-on experience configuring satellite ground station telemetry systems</li></ul>")
        cov = fs.required_coverage(text)
        self.assertGreaterEqual(len(cov["unvouched"]) + cov["miss"], 1, cov)


if __name__ == "__main__":
    unittest.main(verbosity=1)
