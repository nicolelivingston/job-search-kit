"""Fit scoring v4.3: old postings sink below fresh ones even when both are
capped. A freshness bonus counts before the caps; an age deduction (5 off at
31 to 60 days, 10 past 60, 15 past 90) is taken after them and after the fit
label is decided, so age alone never changes a label. Runs as the test person
in KIT_SETTINGS_DIR with a made-up posting. No network.
    python3 app/agent/agent_tests/test_scoring_v43.py
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import person  # noqa: E402
import fit_scoring as fs  # noqa: E402


def score(age, pay=True):
    job = person.sample_job()
    text = job["description"] if pay else job["description"].split("Base salary")[0]
    salary = (int(fs.PAY_TARGET) + 10000) if pay else None
    return fs.score_posting(job["title"], text, salary, {}, "Made-Up Supply Co", age_days=age, remote_hint=True,
                            salary_text=job["salary_text"] if pay else "")


class OldPostingsSink(unittest.TestCase):
    def test_bands(self):
        self.assertGreaterEqual(fs.RUBRIC_VERSION, "v4.3")
        self.assertEqual([fs.freshness_points(d)[0] for d in (3, 14, 30, 45, 60, 61, 90, 91, 400)],
                         [5, 3, 0, -5, -5, -10, -10, -15, -15])
        self.assertEqual(fs.freshness_points(None), (0, ""))

    def test_deduction_is_taken_from_the_final_score(self):
        base, mid, old, older = score(20), score(45), score(75), score(120)
        self.assertFalse(base["stale_pts"])
        self.assertEqual(mid["score"], max(0, base["score"] - 5), mid["breakdown"])
        self.assertEqual(old["score"], max(0, base["score"] - 10), old["breakdown"])
        self.assertEqual(older["score"], max(0, base["score"] - 15), older["breakdown"])
        self.assertEqual((old["stale_pts"], old["age_days"]), (-10, 75))
        self.assertIn("stale 10 after caps", old["breakdown"])
        self.assertIn("stale 15 after caps", older["breakdown"])
        self.assertIn("Open 75 days", fs.label_reason(old))
        self.assertNotIn("Open ", fs.label_reason(base))
        self.assertEqual(score(None)["score"], base["score"])            # unknown age: no deduction

    def test_age_alone_never_changes_the_label_or_the_tier(self):
        base = score(20)
        for age in (45, 75, 120, 400):
            r = score(age)
            self.assertEqual((r["verdict"], r["tier"]), (base["verdict"], base["tier"]), age)
            self.assertEqual(r["score_uncapped"], base["score_uncapped"], age)   # the score before caps isn't touched by age

    def test_a_capped_posting_sinks_too(self):
        saved = fs.NO_PAY_CAP
        fs.NO_PAY_CAP = 20            # a cap low enough that the made-up posting sits at it without posted pay
        try:
            fresh, old, plain = score(3, pay=False), score(75, pay=False), score(20, pay=False)
        finally:
            fs.NO_PAY_CAP = saved
        self.assertGreater(plain["score_uncapped"], 20, plain["breakdown"])
        self.assertEqual(fresh["score"], 20, fresh["breakdown"])                 # at the cap, bonus or not
        self.assertEqual(old["score"], 10, old["breakdown"])                     # before v4.3 this sat at the cap too
        self.assertEqual(old["verdict"], fresh["verdict"])
        self.assertGreater(fresh["score_uncapped"], plain["score_uncapped"])     # the bonus still counts before the caps
        self.assertIn("(uncapped", old["breakdown"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
