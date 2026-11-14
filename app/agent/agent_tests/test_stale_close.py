"""Regression test for the Oct 29, 2026 stale-close bug: a live posting whose
stored Job Posting URL has a different shape from the fetched URL must never
be closed. Run: python3 Tooling/agent/agent_tests/test_stale_close.py"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import job_search_agent as agent  # noqa: E402


class StaleCloseTests(unittest.TestCase):
    def run_close(self, stored_url, fetched_url, runs=3):
        closed = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(agent, "NOTION_TOKEN", "x"), \
                mock.patch.object(agent, "STALE_MISS_FILE", Path(tmp) / "misses.json"), \
                mock.patch.object(agent, "fetch_interested_rows",
                                  return_value=[("page-1", stored_url)]), \
                mock.patch.object(agent, "ask_the_board", return_value=None), \
                mock.patch.object(agent, "update_status",
                                  side_effect=lambda pid, s: closed.append(pid) or True):
            for _ in range(runs):
                agent.close_stale_postings([{"url": fetched_url}] if fetched_url else
                                           [{"url": "https://job-boards.greenhouse.io/ridgeline/jobs/1111111111"}])
        return closed

    def test_live_posting_with_query_string_stays_open(self):
        stored = "https://job-boards.greenhouse.io/ridgeline/jobs/9100011004"
        fetched = "https://job-boards.greenhouse.io/ridgeline/jobs/9100011004?gh_jid=9100011004"
        self.assertEqual(self.run_close(stored, fetched), [])

    def test_live_posting_with_trailing_slash_stays_open(self):
        stored = "https://jobs.ashbyhq.com/claimwise/00000000-0000-4000-8000-000000000101"
        fetched = "https://jobs.ashbyhq.com/claimwise/00000000-0000-4000-8000-000000000101/"
        self.assertEqual(self.run_close(stored, fetched), [])

    def test_gone_posting_still_closes_after_two_runs(self):
        stored = "https://job-boards.greenhouse.io/ridgeline/jobs/9100012004"
        self.assertEqual(self.run_close(stored, None, runs=2), ["page-1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
