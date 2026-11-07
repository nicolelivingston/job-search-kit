#!/usr/bin/env python3
"""Fit scoring v3.3 to v4.0: verdict names, required sections, years grace,
one-miss Strong fit, required-item coverage, staffing signal, near-miss alerts.

Runs against any settings folder (CI uses the example person's); every posting
below is made up. The mechanisms real criteria exercise are
covered generically here, so the suite proves them for any user.

    cd app/agent && KIT_SETTINGS_DIR=../../examples/priya-healthtech-pm/settings python3 agent_tests/test_scoring_v4.py
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fit_scoring as fs          # noqa: E402
import job_search_agent as jsa    # noqa: E402

GOOD_COMPANY = {"remote_posture": "Structurally remote (no HQ)", "risk": "Low", "pto": "Strong",
                "health": "Strong", "domains": list(fs.DOMAIN_SCORES)[:1]}
# Wording that matches the settings' own work families, whatever they are.
FAMILY_WORDS = " ".join(fs._phrases("fit_scoring.WORK_FAMILIES")[:12])
YEARS = fs.YEARS_CLAIMABLE
FIELD = fs.YEARS_LABEL.replace("years of ", "")
BENEFITS = " Benefits: medical, dental, and a 401(k) match."


def posting(req_block, extra="", pay="Base $180,000 to $200,000."):
    return (f"Fully remote. We work on {FAMILY_WORDS}. {extra} "
            f"<ul><li>Requirements</li><li>{req_block}</li></ul> {pay}{BENEFITS}")


class VerdictNames(unittest.TestCase):
    def test_agent_verdicts_and_human_verdicts_are_disjoint(self):
        self.assertEqual(fs.AGENT_VERDICTS, ("Strong fit", "Possible fit", "Poor fit"))
        self.assertEqual(fs.HUMAN_VERDICTS, ("Applying", "Passed"))
        self.assertFalse(set(fs.AGENT_VERDICTS) & set(fs.HUMAN_VERDICTS))

    def test_old_names_map_once_to_new_ones(self):
        for old, new in fs.OLD_VERDICTS.items():
            self.assertIn(new, fs.AGENT_VERDICTS + fs.HUMAN_VERDICTS, old)
        self.assertEqual(fs.OLD_VERDICTS["Pursue"], "Applying")
        self.assertEqual(fs.OLD_VERDICTS["Pass"], "Passed")
        for retired in fs.RETIRED_VERDICTS:
            self.assertIn(retired, fs.OLD_VERDICTS)

    def test_every_row_gets_a_verdict(self):
        for title, text, sal in [("Product Manager", "Remote.", None),
                                 ("Senior Product Manager", "Fully remote. Base $170,000." + BENEFITS, 170000),
                                 ("Product Manager", posting("Strong communication skills"), 180000)]:
            r = fs.score_posting(title, text, salary_min=sal)
            self.assertIn(r["verdict"], fs.AGENT_VERDICTS, (title, r["breakdown"]))

    def test_the_agent_never_writes_a_human_verdict(self):
        import run_stats
        run_stats.STATS = run_stats._Stats()
        for name in ("Applying", "Passed"):
            run_stats.STATS.note("patch", "https://api.notion.com/v1/pages/0f0f0f0f-cb28-819a-adbc-ef9e08fc8d41",
                                 {"json": {"properties": {"Overall Verdict": {"select": {"name": name}}}}})
        self.assertEqual(len(run_stats.STATS.violations), 2)

    def test_no_pay_is_a_soft_poor_fit_that_stays_open(self):
        r = fs.score_posting("Product Manager", f"Fully remote. {FAMILY_WORDS}.", salary_min=None)
        self.assertEqual(r["verdict"], "Poor fit")
        self.assertFalse(r["hard_skip"])
        label = fs.label_reason(r, date(2026, 11, 7))
        self.assertTrue(label.startswith("Poor fit (no base pay posted), left open"), label)
        self.assertTrue(jsa.SOFT_SKIP_LABEL.search(label))
        self.assertFalse(jsa.SOFT_SKIP_LABEL.search("Poor fit: hybrid. Scored 2026-11-02 by agent v3.6."))

    def test_the_48_hour_rule_is_gone(self):
        self.assertFalse(hasattr(jsa, "expire_unanswered_asks"))
        self.assertFalse(hasattr(jsa, "NO_DECISION_VERDICT"))
        self.assertTrue(hasattr(jsa, "migrate_verdict_names"))


class RequiredSections(unittest.TestCase):
    def test_cleaning_keeps_bullet_boundaries(self):
        t = fs._clean("<p>Intro.</p><ul><li>One thing</li><li>Two thing</li></ul>")
        self.assertIn(fs.SEP, t)
        self.assertEqual([p.strip() for p in t.split("•")], ["Intro.", "One thing", "Two thing"])

    def test_required_headings_in_the_forms_boards_use(self):
        for head in ("Requirements", "What you'll bring", "Who you are", "About you", "What we need from you",
                     "MINIMUM QUALIFICATIONS", "You have"):
            t = fs._clean(f"<p>About the role.</p><p>{head}</p><ul><li>Something we need</li></ul><p>Benefits</p><p>Health.</p>")
            spans = fs.required_spans(t)
            self.assertEqual(len(spans), 1, (head, t))
            a, b = spans[0]
            self.assertIn("Something we need", t[a:b])
            self.assertNotIn("Health.", t[a:b])

    def test_required_block_family_counts_only_inside_the_block(self):
        fam = [("ledger close", fs._rx("month-end close"))]
        old = fs.REQUIRED_BLOCK_FAMILIES
        fs.REQUIRED_BLOCK_FAMILIES = fam
        try:
            inside = fs._clean("<p>Requirements</p><ul><li>Experience with month-end close</li></ul><p>Benefits</p>")
            outside = fs._clean("<p>Responsibilities</p><ul><li>Help the team with month-end close</li></ul>")
            self.assertTrue(any(m.startswith("ledger close") for m in fs.missing_minimums(inside)))
            self.assertFalse(any(m.startswith("ledger close") for m in fs.missing_minimums(outside)))
        finally:
            fs.REQUIRED_BLOCK_FAMILIES = old

    def test_out_of_field_industry_is_a_miss_only_when_set(self):
        text = fs._clean("<p>Requirements</p><ul><li>5+ years of experience in adtech platforms</li></ul>")
        old = fs.OUT_OF_DOMAIN_INDUSTRY_RX
        try:
            fs.OUT_OF_DOMAIN_INDUSTRY_RX = None
            self.assertEqual(fs.industry_minimums(text), [])
            fs.OUT_OF_DOMAIN_INDUSTRY_RX = fs._rx("adtech")
            out = fs.industry_minimums(text)
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0].startswith(fs.OUT_OF_DOMAIN_LABEL), out[0])
        finally:
            fs.OUT_OF_DOMAIN_INDUSTRY_RX = old


class YearsAndOneMiss(unittest.TestCase):
    def test_years_within_grace_are_met(self):
        r = fs.score_posting("Product Manager", posting(f"{YEARS + fs.YEARS_GRACE}+ years of {FIELD} experience"), salary_min=180000)
        self.assertFalse(any("years" in m for m in r["missing_minimums"]), r["missing_minimums"])
        self.assertIn("counted as met", r["breakdown"])

    def test_years_past_grace_are_a_miss(self):
        r = fs.score_posting("Product Manager", posting(f"{YEARS + fs.YEARS_GRACE + 1}+ years of {FIELD} experience"), salary_min=180000)
        self.assertTrue(any("years" in m for m in r["missing_minimums"]), r["breakdown"])

    def test_one_miss_at_a_high_score_is_still_strong_fit(self):
        n = YEARS + fs.YEARS_GRACE + 1
        r = fs.score_posting("Senior Product Manager", posting(f"{n}+ years of {FIELD} experience"),
                             salary_min=190000, company=GOOD_COMPANY, age_days=2)
        self.assertEqual(len(r["missing_minimums"]), 1, r["missing_minimums"])
        if r["score_uncapped"] >= fs.ONE_MISS_STRONG_MIN:
            self.assertEqual(r["verdict"], "Strong fit", r["breakdown"])
            self.assertTrue(r["one_miss_strong"])
            self.assertIn("one gap to address", fs.label_reason(r, date(2026, 11, 7)))
        else:
            self.assertEqual(r["score"], min(r["score_uncapped"], fs.MIN_CAP_ONE))

    def test_two_misses_cap_at_poor_fit(self):
        n = YEARS + fs.YEARS_GRACE + 1
        r = fs.score_posting("Senior Product Manager",
                             posting(f"{n}+ years of {FIELD} experience; </li><li>{n + 1}+ years of {FIELD} experience in a listed company"),
                             salary_min=190000, company=GOOD_COMPANY)
        # a second countable miss comes from a configured minimum family when one exists
        label = fs.MINIMUM_FAMILIES[0][0] if fs.MINIMUM_FAMILIES else None
        if label:
            words = fs._phrases("fit_scoring.MINIMUM_FAMILIES")[:1]
            r = fs.score_posting("Senior Product Manager",
                                 posting(f"{n}+ years of {FIELD} experience</li><li>Proven experience with {words[0]}"),
                                 salary_min=190000, company=GOOD_COMPANY)
            self.assertGreaterEqual(len(r["missing_minimums"]), 2, r["breakdown"])
            self.assertLessEqual(r["score"], fs.MIN_CAP_TWO)
            self.assertEqual(r["verdict"], "Poor fit")


class Coverage(unittest.TestCase):
    def test_lead_phrase_is_what_must_be_vouched(self):
        self.assertEqual(fs.req_lead_phrase("Knowledge of ledger close processes, including supplier onboarding"),
                         "ledger close processes, including")
        self.assertIsNone(fs.req_lead_phrase("Strong communication skills and attention to detail; a track record of shipping products on time is a plus"))

    def test_soft_items_never_count(self):
        self.assertEqual(fs.classify_required_item("Experience with astrophysics modeling is a plus, ideally in a lab"), "soft")

    def test_vouched_and_unvouched(self):
        words = fs._phrases("fit_scoring.WORK_FAMILIES")
        if not words:
            self.skipTest("no keyword groups in these settings")
        self.assertEqual(fs.classify_required_item(f"Experience with {words[0]} across several teams and launches"), "vouched")
        self.assertEqual(fs.classify_required_item("Strong written communication and collaboration with stakeholders"), "vouched")
        self.assertEqual(fs.classify_required_item("Experience with reinsurance treaty pricing models and bordereaux files"), "unvouched")

    def test_unvouched_items_cap_and_are_quoted(self):
        req = ("Experience with reinsurance treaty pricing models</li>"
               "<li>Knowledge of bordereaux file reconciliation across cedants</li>"
               "<li>Background in actuarial reserving methods and triangles</li>"
               "<li>Familiarity with catastrophe modeling software suites</li>")
        r = fs.score_posting("Senior Product Manager", posting(req), salary_min=190000, company=GOOD_COMPANY)
        self.assertGreaterEqual(len(r["unvouched"]), 4, r["unvouched"])
        self.assertLessEqual(r["score"], fs.MIN_CAP_TWO)
        self.assertEqual(r["verdict"], "Poor fit")
        self.assertIn("can't vouch for", r["breakdown"])
        self.assertIn("reinsurance treaty", r["breakdown"])
        self.assertIn("uncapped", r["breakdown"])

    def test_two_unvouched_items_cap_at_possible_fit(self):
        req = ("Experience with reinsurance treaty pricing models</li>"
               "<li>Knowledge of bordereaux file reconciliation across cedants</li>"
               "<li>Strong written communication skills and stakeholder management")
        r = fs.score_posting("Senior Product Manager", posting(req), salary_min=190000, company=GOOD_COMPANY, age_days=2)
        self.assertEqual(len(r["unvouched"]), 2, r["unvouched"])
        self.assertLessEqual(r["score"], fs.MIN_CAP_ONE)
        self.assertNotEqual(r["verdict"], "Strong fit")

    def test_coverage_can_be_turned_off(self):
        old = fs.REQUIRED_COVERAGE
        fs.REQUIRED_COVERAGE = False
        try:
            cov = fs.required_coverage(fs._clean("<p>Requirements</p><ul><li>Experience with reinsurance treaty pricing models</li></ul>"))
            self.assertIsNone(cov["cap"])
            self.assertEqual(cov["unvouched"], [])
        finally:
            fs.REQUIRED_COVERAGE = old

    def test_near_miss_alerts_like_tier_a(self):
        n = YEARS + fs.YEARS_GRACE + 1
        r = fs.score_posting("Senior Product Manager", posting(f"{n}+ years of {FIELD} experience"),
                             salary_min=190000, company=GOOD_COMPANY, age_days=2)
        r["verdict"] = "Possible fit"
        r["score_uncapped"] = max(r["score_uncapped"], fs.ONE_MISS_STRONG_MIN)
        self.assertTrue(jsa.is_near_miss(r))
        self.assertIn("near miss", fs.label_reason(r, date(2026, 11, 7)))
        r["unvouched"] = ["a", "b", "c"]
        self.assertFalse(jsa.is_near_miss(r))


class StaffingAndDomain(unittest.TestCase):
    def test_no_benefits_and_one_flat_figure_caps_at_possible_fit(self):
        text = f"Fully remote. We work on {FAMILY_WORDS}. Requirements: strong communication. Salary: $150,000."
        self.assertTrue(fs.staffing_signal(fs._clean(text)))
        self.assertFalse(fs.staffing_signal(fs._clean(text + " Benefits: medical and dental.")))
        self.assertFalse(fs.staffing_signal(fs._clean(text.replace("$150,000", "$150,000 to $170,000"))))
        r = fs.score_posting("Senior Product Manager", text, salary_min=150000, company=GOOD_COMPANY, age_days=2)
        self.assertLessEqual(r["score"], fs.STAFFING_CAP)
        self.assertIn("staffing-agency signal", r["caps"])

    def test_no_domain_scores_zero_when_guessing_is_off(self):
        old = fs.DOMAIN_GUESS
        fs.DOMAIN_GUESS = False
        try:
            pts, label = fs.domain_score("Product Manager", "401(k) retirement benefits and wellness", None)
            self.assertEqual((pts, label), (0, fs.DOMAIN_NONE_LABEL))
        finally:
            fs.DOMAIN_GUESS = old

if __name__ == "__main__":
    unittest.main(verbosity=1)
