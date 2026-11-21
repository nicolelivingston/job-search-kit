"""Reposters are not employers. A known reposter's name is rejected as the
hiring company; a posting from a job site whose text never names the employer
("for our client, we are seeking") is rejected on its first sighting, while
the same words on a company's own board are left alone; and open rows that
are a reposter's copy are closed, except rows the user decided, and a reason
the user wrote is kept. Every company, row, and posting here is made up.
    python3 app/agent/agent_tests/test_reposters.py
"""
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
os.environ.pop("NOTION_TOKEN", None)

import person  # noqa: E402
import lead_resolver as lr  # noqa: E402
import job_search_agent as agent  # noqa: E402

REPOST = "For our client, we are seeking a hands-on lead for a growing team. Fully remote. Base salary $120,000 to $140,000."
PARTNER = "Staffwell is a recruitment partner of this role. Fully remote."
OWN = "Lumenfold makes scheduling software for clinics. You will lead a growing team. Fully remote."


def row(pid, company, snapshot, url="https://jobsite.example.com/listing/9100010", verdict="Possible fit", label="", notes=""):
    return {"id": pid, "properties": {
        "Role": {"type": "title", "title": [{"plain_text": person.wanted_title()}]},
        "Company": {"type": "rich_text", "rich_text": [{"plain_text": company}]},
        "Posting Snapshot": {"type": "rich_text", "rich_text": [{"plain_text": snapshot}]},
        "Job Posting": {"type": "url", "url": url},
        "Overall Verdict": {"type": "select", "select": {"name": verdict} if verdict else None},
        "Label Reason": {"type": "rich_text", "rich_text": [{"plain_text": label}]},
        "Notes": {"type": "rich_text", "rich_text": [{"plain_text": notes}]},
    }}


class Reposters(unittest.TestCase):
    def test_known_reposters_are_not_employers(self):
        for name in ("Ladders", "TheLadders", "RemoteHunter", "TalentHop", "Haystack", "Jobs via Dice"):
            self.assertTrue(lr.is_aggregator(name), name)
        for name in ("Lumenfold", "Haystack Analytics Group", "Ladder Supply Co"):
            self.assertFalse(lr.is_aggregator(name), name)
        job = person.sample_job(company="Ladders", url="https://jobsite.example.com/listing/9100011")
        self.assertIn("aggregator repost", agent.get_rejection_reason(job) or "")

    def test_text_that_never_names_the_employer(self):
        self.assertEqual(lr.repost_phrase(REPOST), "For our client, we are seeking")              # quoted as the posting wrote it
        self.assertEqual(lr.repost_phrase("About our client:\nA leader in its field."), "About our client:")
        self.assertEqual(lr.repost_phrase(PARTNER), "is a recruitment partner of this role")
        self.assertEqual(lr.repost_phrase("FOR   OUR CLIENT we are seeking a lead"), "FOR OUR CLIENT we are seeking")
        # A reposter that names the employer as its client (made-up names; Nov 21, 2026)
        named = "Hirepath is collaborating with Lumenfold to connect them with exceptional professionals for the opening."
        self.assertEqual(lr.repost_phrase(named), "to connect them with exceptional professionals")
        self.assertIsNone(lr.repost_phrase("You will connect them with the right tools and professionals."))
        for clean in (OWN, "We put our clients first. Our client list is long.", "", None):
            self.assertIsNone(lr.repost_phrase(clean), clean)

    def test_a_repost_from_a_job_site_is_rejected_on_its_first_sighting(self):
        base = person.sample_job(company="Staffwell", url="https://jobsite.example.com/listing/9100012")
        self.assertIsNone(agent.get_rejection_reason(dict(base, description=base["description"])))          # a normal posting passes
        reason = agent.get_rejection_reason(dict(base, description=REPOST + " " + base["description"]))
        self.assertIn("third-party repost (", reason or "")
        # the same words on a company's own board describe its business, not a repost
        own = dict(base, company="Lumenfold", ats_platform="greenhouse", description=REPOST + " " + base["description"])
        self.assertIsNone(agent.get_rejection_reason(own))

    def test_open_copies_are_closed_and_the_users_calls_are_kept(self):
        rows = [row("p-name", "Ladders", OWN),                                                    # a known reposter
                row("p-text", "Staffwell", REPOST),                                               # never names the employer
                row("p-own", "Lumenfold", REPOST, url="https://job-boards.greenhouse.io/lumenfold/jobs/9100013"),   # its own board
                row("p-clean", "Tessaway", OWN),                                                  # an ordinary posting
                row("p-applying", "Ladders", OWN, verdict="Applying"),                            # the user's decision
                row("p-passed", "Staffwell", REPOST, verdict="Passed"),
                row("p-mine", "TalentHop", OWN, label="Possible fit: a friend told me who the employer is.")]   # the user's own reason
        patched = {}
        with mock.patch.object(agent, "query_open_rows", return_value=rows), \
                mock.patch.object(agent, "patch_page", side_effect=lambda pid, props: patched.__setitem__(pid, props) or True):
            closed = agent.close_aggregator_rows(date(2026, 11, 2))
        self.assertEqual(closed, 3)
        self.assertEqual(sorted(patched), ["p-mine", "p-name", "p-text"])
        for pid in patched:
            self.assertEqual(patched[pid]["Status"], {"status": {"name": "Closed"}})
            self.assertEqual(patched[pid]["Overall Verdict"], {"select": {"name": "Poor fit"}})
        why = patched["p-name"]["Label Reason"]["rich_text"][0]["text"]["content"]
        self.assertIn("Ladders reposts other companies' jobs and hides the employer", why)
        self.assertIn("Closed 2026-11-02", why)
        self.assertIn("third-party repost", patched["p-text"]["Label Reason"]["rich_text"][0]["text"]["content"])
        self.assertNotIn("Label Reason", patched["p-mine"])                                        # the user's words stay

    def test_a_failed_write_is_not_counted_and_the_full_run_includes_the_pass(self):
        with mock.patch.object(agent, "query_open_rows", return_value=[row("p-name", "Ladders", OWN)]), \
                mock.patch.object(agent, "patch_page", return_value=False):
            self.assertEqual(agent.close_aggregator_rows(date(2026, 11, 2)), 0)
        import inspect
        self.assertIn("close_aggregator_rows(today)", inspect.getsource(agent.main))

    def test_the_phrases_are_a_setting(self):
        import re
        self.assertTrue(lr.REPOST_PHRASES)
        self.assertIn("agent.REPOST_PHRASES", Path(lr.__file__).read_text())
        catalog = (Path(lr.__file__).resolve().parents[2] / "SETTINGS.md").read_text()
        self.assertIn("`agent.REPOST_PHRASES`", catalog)
        self.assertIsNone(re.compile(r"(?!x)x").search(REPOST))                                    # an empty list matches nothing


if __name__ == "__main__":
    unittest.main(verbosity=2)
