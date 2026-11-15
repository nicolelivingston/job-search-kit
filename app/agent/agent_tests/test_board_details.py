"""Workday boards: a posting whose title is on the user's list gets one more
request for its own page (the description with the pay range, the real posted
date, every location); other titles stay as listings; a failed detail never
drops a posting. A Workday link gives the board's full address (tenant,
instance, board name), which is what the kit needs to read it, and a Workday
board is still read only when the user turned it on. Made-up boards, no network.
    python3 app/agent/agent_tests/test_board_details.py
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import person  # noqa: E402
import ats_tools  # noqa: E402
import lead_resolver  # noqa: E402

TITLE = person.wanted_title()
OTHER = "Facilities Coordinator"
BOARD = {"tenant": "lumenfold", "instance": "wd5", "board": "Lumenfold_External"}


class Reply:
    def __init__(self, data, fail=False):
        self._d, self._fail = data, fail

    def raise_for_status(self):
        if self._fail:
            raise RuntimeError("503")

    def json(self):
        return self._d


class WorkdayDetails(unittest.TestCase):
    def setUp(self):
        self.calls = []
        listing = {"total": 3, "jobPostings": [
            {"title": TITLE, "externalPath": "/job/Remote-USA/Made-Up-Role_R9100005", "locationsText": "2 Locations", "postedOn": "Posted 3 Days Ago"},
            {"title": OTHER, "externalPath": "/job/Denver/Made-Up-Other_R9100006", "locationsText": "Denver", "postedOn": "Posted Today"},
            {"title": TITLE + " II", "externalPath": "/job/Remote-USA/Made-Up-Second_R9100007", "locationsText": "Remote", "postedOn": "Posted 30+ Days Ago"}]}
        detail = {"jobPostingInfo": {"jobDescription": "<p>Fully remote.</p><ul><li>Base salary $120,000 to $140,000</li></ul>",
                                     "startDate": "2026-10-30", "location": "Remote - USA", "additionalLocations": ["Denver, CO"]}}

        def fake(fn, url, **kw):
            self.calls.append(url)
            if url.endswith("/jobs"):
                return Reply(listing)
            return Reply(detail, fail=url.endswith("_R9100007"))
        p1 = mock.patch.object(ats_tools, "request_with_retry", fake)
        p2 = mock.patch.object(ats_tools, "DETAIL_TITLE_RE", re.compile(re.escape(TITLE), re.I))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_titles_on_the_list_get_their_own_page(self):
        jobs = ats_tools.fetch_workday(**BOARD)
        self.assertEqual(len(jobs), 3)                                   # nothing dropped
        mine, other, failed = jobs
        self.assertIn("Base salary $120,000 to $140,000", mine["description"])
        self.assertNotIn("<", mine["description"])
        self.assertEqual((mine["published"], mine["location"]), ("2026-10-30", "Remote - USA, Denver, CO"))
        self.assertEqual(mine["url"], "https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External/job/Remote-USA/Made-Up-Role_R9100005")
        self.assertEqual((other["description"], other["location"]), ("", "Denver"))          # not on the list: left as a listing
        self.assertEqual((failed["description"], failed["location"], failed["posted_text"]),   # a failed detail keeps the listing
                         ("", "Remote", "Posted 30+ Days Ago"))
        self.assertTrue(all("_path" not in j for j in jobs))
        details = [u for u in self.calls if not u.endswith("/jobs")]
        self.assertEqual(len(details), 2)
        self.assertTrue(all(u.startswith("https://lumenfold.wd5.myworkdayjobs.com/wday/cxs/lumenfold/Lumenfold_External/job/") for u in details))

    def test_no_title_list_means_no_detail_calls(self):
        with mock.patch.object(ats_tools, "DETAIL_TITLE_RE", None):
            jobs = ats_tools.fetch_workday(**BOARD)
        self.assertEqual([j["description"] for j in jobs], ["", "", ""])
        self.assertEqual(len(self.calls), 1)


class WorkdayAddresses(unittest.TestCase):
    def test_full_address_from_a_link(self):
        f = ats_tools.workday_params_from_url
        self.assertEqual(f("https://lumenfold.wd5.myworkdayjobs.com/en-US/Lumenfold_External/job/Remote-USA/Made-Up-Role_R9100005"), BOARD)
        self.assertEqual(f("https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External"), BOARD)
        self.assertEqual(f('<a href="https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External">Jobs</a>'), BOARD)
        for bad in ("https://lumenfold.wd5.myworkdayjobs.com/", "https://lumenfold.wd5.myworkdayjobs.com/wday/cxs/x",
                    "https://job-boards.greenhouse.io/lumenfold", "", None):
            self.assertIsNone(f(bad), bad)
        self.assertEqual(lead_resolver.board_from_url("https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External/job/x_R9100005"),
                         ("workday", BOARD))
        self.assertEqual(lead_resolver.board_from_url("https://jobs.lever.co/lumenfold/00000000-0000-4000-8000-000000000003"),
                         ("lever", "lumenfold"))

    def test_careers_page_with_a_workday_link(self):
        page = '<html><a href="https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External">See open roles</a></html>'
        self.assertEqual(ats_tools.detect_ats("https://lumenfold.example.com/careers", html=page)["matches"], {"workday": BOARD})
        # the tenant alone can't be read, so it isn't offered as a board
        bare = '<html><script src="https://lumenfold.wd5.myworkdayjobs.com/"></script><a href="https://jobs.ashbyhq.com/lumenfold">Jobs</a></html>'
        self.assertEqual(ats_tools.detect_ats("https://lumenfold.example.com/careers", html=bare)["matches"], {"ashby": "lumenfold"})

    def test_a_workday_board_is_still_opt_in(self):
        lead_resolver._RUN_CACHE.clear()
        called = []
        with mock.patch.object(ats_tools, "CONFIRMED_COMPANIES", [{"name": "Lumenfold", "platform": "workday", "slug": BOARD}]), \
             mock.patch.dict(lead_resolver.FETCHERS, {"workday": lambda s: called.append(s) or [{"title": TITLE}]}):
            self.assertEqual(lead_resolver.fetch_board(*lead_resolver.board_from_url(
                "https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External/job/x_R9100005")), [])
        self.assertEqual(called, [])

    def test_posting_ids_in_links(self):
        import os
        os.environ.pop("NOTION_TOKEN", None)
        import job_search_agent as jsa
        ids = {"https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External/job/Remote-USA/Made-Up-Role_R9100005": "_r9100005",
               "https://lumenfold.wd5.myworkdayjobs.com/Lumenfold_External/job/Remote/Role_JR9100008-1?source=x": "_jr9100008-1",
               "https://jobs.smartrecruiters.com/Lumenfold/910000000000001-made-up-role": "910000000000001",
               "https://job-boards.greenhouse.io/lumenfold/jobs/9100009": "9100009",
               "https://jobs.ashbyhq.com/lumenfold/00000000-0000-4000-8000-000000000004": "00000000-0000-4000-8000-000000000004",
               "https://lumenfold.example.com/careers": ""}
        for url, want in ids.items():
            self.assertEqual(jsa._job_id_from_url(url), want, url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
