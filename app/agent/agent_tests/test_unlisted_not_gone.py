"""A posting that leaves its board's public list is not always gone. Before
a row is closed as gone, the agent asks the board about that one posting. A
posting that still answers stays open and is marked Unlisted; a posting the
board no longer has closes as before. No network: every answer is faked.

    python3 app/agent/agent_tests/test_unlisted_not_gone.py
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import job_search_agent as agent  # noqa: E402

GH = "https://job-boards.greenhouse.io/acme/jobs/9100021001"
GH_API = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/9100021001"
LEVER_ID = "00000000-0000-4000-8000-000000000001"
OTHER = {"id": "gh-acme-9100021002", "url": "https://job-boards.greenhouse.io/acme/jobs/9100021002"}
JOB = {"id": 9100021001, "title": "Senior Analyst"}


class Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


def getter(code=200, body=None, calls=None, error=None):
    def get(url, **kw):
        if calls is not None:
            calls.append(url)
        if error:
            raise error
        return Resp(code, body)
    get.__name__ = "get"
    return get


class AskTheBoard(unittest.TestCase):
    def test_greenhouse_is_asked_by_board_and_job_id(self):
        calls = []
        self.assertEqual(agent.ask_the_board(GH, get=getter(200, JOB, calls)), agent.LIVE)
        self.assertEqual(calls, [GH_API])
        # the older host and a query string are the same job
        old = "https://boards.greenhouse.io/acme/jobs/9100021001?gh_jid=9100021001"
        self.assertEqual(agent.single_posting_api(old), GH_API)

    def test_no_such_job_means_gone(self):
        self.assertEqual(agent.ask_the_board(GH, get=getter(404)), agent.GONE)
        self.assertEqual(agent.ask_the_board(GH, get=getter(410)), agent.GONE)

    def test_anything_else_is_unclear(self):
        with mock.patch("time.sleep"):
            self.assertEqual(agent.ask_the_board(GH, get=getter(503)), agent.UNCLEAR)
            self.assertEqual(agent.ask_the_board(GH, get=getter(200, None)), agent.UNCLEAR)          # a page, not a job
            self.assertEqual(agent.ask_the_board(GH, get=getter(200, {"jobs": []})), agent.UNCLEAR)  # a list, not a job
            self.assertEqual(agent.ask_the_board(GH, get=getter(error=requests.ConnectionError("down"))), agent.UNCLEAR)

    def test_lever_is_asked_by_board_and_posting_id(self):
        calls = []
        url = f"https://jobs.lever.co/acme/{LEVER_ID}/apply"
        self.assertEqual(agent.ask_the_board(url, get=getter(200, {"id": LEVER_ID}, calls)), agent.LIVE)
        self.assertEqual(calls, [f"https://api.lever.co/v0/postings/acme/{LEVER_ID}"])
        self.assertIsNone(agent.single_posting_api("https://jobs.lever.co/acme"))   # a board, not a posting

    def test_careers_site_link_needs_the_days_fetch(self):
        calls = []
        url = "https://acme.careers/job/?gh_jid=9100021001"
        self.assertIsNone(agent.ask_the_board(url, get=getter(200, JOB, calls)))   # host unknown: can't ask
        self.assertEqual(agent.ask_the_board(url, {"acme.careers": ("gh", "acme")}, get=getter(200, JOB, calls)), agent.LIVE)
        self.assertEqual(calls, [GH_API])

    def test_boards_that_cannot_be_asked_about_one_job(self):
        calls = []
        for url in (f"https://jobs.ashbyhq.com/acme/{LEVER_ID}",
                    "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/Remote/Senior-Analyst_R-91001",
                    "", None):
            self.assertIsNone(agent.ask_the_board(url, get=getter(200, JOB, calls)))
        self.assertEqual(calls, [])

    def test_only_the_two_board_apis_are_ever_asked(self):
        # a look-alike host, a board name that isn't a plain name, a job ID that isn't a number
        for url in ("https://notgreenhouse.io/acme/jobs/9100021001",
                    "https://job-boards.greenhouse.io.example.com/acme/jobs/9100021001",
                    "https://job-boards.greenhouse.io/../jobs/9100021001",
                    "https://job-boards.greenhouse.io/acme/jobs/abc",
                    "https://jobs.lever.co.example.com/acme/" + LEVER_ID):
            self.assertIsNone(agent.single_posting_api(url), url)
        self.assertIsNone(agent.single_posting_api("https://acme.careers/job/?gh_jid=9100021001",
                                                   {"acme.careers": ("gh", "../acme")}))
        for url in (GH, f"https://jobs.lever.co/acme/{LEVER_ID}"):
            self.assertRegex(agent.single_posting_api(url), r"^https://(boards-api\.greenhouse\.io|api\.lever\.co)/")


class StaleClose(unittest.TestCase):
    def run_close(self, answers, stored=GH, fetched=OTHER, health=None, two_tuple=False, runs=None):
        """answers[i] is what the board says the i-th time it is asked. Runs
        default to one more than the answers (the first miss never asks)."""
        closed, marked, asked = [], [], []
        answers = list(answers)

        def ask(url, host_boards=None, get=None):
            asked.append((url, dict(host_boards or {})))
            return answers[len(asked) - 1] if len(asked) <= len(answers) else None

        row = ("page-1", stored) if two_tuple else ("page-1", stored, health)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(agent, "NOTION_TOKEN", "x"), \
                mock.patch.object(agent, "STALE_MISS_FILE", Path(tmp) / "misses.json"), \
                mock.patch.object(agent, "fetch_interested_rows", return_value=[row]), \
                mock.patch.object(agent, "ask_the_board", side_effect=ask), \
                mock.patch.object(agent, "mark_unlisted", side_effect=lambda pid, today=None: marked.append(pid) or True), \
                mock.patch.object(agent, "update_status", side_effect=lambda pid, s: closed.append((pid, s)) or True):
            for _ in range(runs or len(answers) + 1):
                agent.close_stale_postings([fetched])
        return closed, marked, asked

    def test_off_the_list_but_live_stays_open_and_is_marked(self):
        closed, marked, asked = self.run_close([agent.LIVE])
        self.assertEqual((closed, marked), ([], ["page-1"]))
        self.assertEqual(len(asked), 1)   # not asked on the first miss, asked on the second

    def test_gone_closes(self):
        closed, marked, _ = self.run_close([agent.GONE])
        self.assertEqual((closed, marked), ([("page-1", "Closed")], []))

    def test_a_board_that_cannot_be_asked_closes_as_before(self):
        closed, marked, _ = self.run_close([None])
        self.assertEqual((closed, marked), ([("page-1", "Closed")], []))
        closed, _, _ = self.run_close([None], two_tuple=True)   # rows without a health value still work
        self.assertEqual(closed, [("page-1", "Closed")])

    def test_no_clear_answer_asks_again_next_run(self):
        closed, marked, asked = self.run_close([agent.UNCLEAR, agent.UNCLEAR, agent.LIVE])
        self.assertEqual((closed, marked, len(asked)), ([], ["page-1"], 3))

    def test_no_clear_answer_five_runs_in_a_row_closes(self):
        closed, marked, asked = self.run_close([agent.UNCLEAR] * 5)
        self.assertEqual((closed, marked, len(asked)), ([("page-1", "Closed")], [], 5))

    def test_a_still_unlisted_row_is_asked_again_and_closes_once_gone(self):
        answers = [agent.LIVE, agent.LIVE, agent.GONE]
        closed, marked, asked = self.run_close(answers, runs=4)   # asked on runs 2 and 4 only
        self.assertEqual((closed, marked, len(asked)), ([], ["page-1", "page-1"], 2))
        closed, marked, asked = self.run_close(answers, runs=6)   # asked a third time on run 6
        self.assertEqual((closed, len(asked)), ([("page-1", "Closed")], 3))

    def test_another_posting_health_mark_is_kept(self):
        # Suspected evergreen carries a score deduction; Verified real is set by hand
        for health in ("Suspected evergreen", "Verified real"):
            closed, marked, _ = self.run_close([agent.LIVE], health=health)
            self.assertEqual((closed, marked), ([], []), health)
        closed, marked, _ = self.run_close([agent.LIVE], health="Unlisted")   # already marked: stamped again
        self.assertEqual((closed, marked), ([], ["page-1"]))

    def test_a_careers_site_host_is_mapped_from_the_fetch(self):
        fetched = {"id": "gh-acme-9100021002", "url": "https://acme.careers/job/?gh_jid=9100021002"}
        _, _, asked = self.run_close([agent.LIVE], stored="https://acme.careers/job/?gh_jid=9100021001", fetched=fetched)
        self.assertEqual(asked[0][1], {"acme.careers": ("gh", "acme")})

    def test_mark_writes_health_and_last_verified(self):
        sent = []
        with mock.patch.object(agent, "patch_page", side_effect=lambda pid, props=None, icon_url=None: sent.append((pid, props)) or True):
            self.assertTrue(agent.mark_unlisted("page-1", date(2026, 11, 13)))
        self.assertEqual(sent, [("page-1", {"Posting Health": {"select": {"name": "Unlisted"}},
                                            "Last Verified": {"date": {"start": "2026-11-13"}}})])


if __name__ == "__main__":
    unittest.main(verbosity=1)
