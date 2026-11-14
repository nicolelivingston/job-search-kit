"""Smoke test: main() runs end to end (quick and full) with every fetcher and
every Notion call faked, in dry-run mode, and leaves the profile line, the
stats record, and the dry-run write log behind. Guards the Oct 29, 2026
main() wiring (stage timing, dry run, snapshot, invariants hook). No network.
    python3 Tooling/agent/agent_tests/test_main_smoke.py
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import person                    # noqa: E402
import job_search_agent as jsa   # noqa: E402
import run_stats                 # noqa: E402
import invariants                # noqa: E402
import notion_q                  # noqa: E402

JOB = person.sample_job()   # a posting the test person these tests run as would want


def _fake_http(name):
    def fn(url, **kwargs):
        body = {"results": [], "has_more": False}
        if url.rstrip("/").endswith(f"/v1/databases/{jsa.NOTION_DATABASE_ID}"):
            body = {"properties": {k: {} for k in ("Role", "Company", "Status", "Overall Verdict", "Research Tier",
                                                     "Score Breakdown", "Fit Evidence", "Domain Tier", "Label Reason",
                                                     "Role Fit Score", "Posting Snapshot", "Posted Date", "Last Verified",
                                                     "Base Salary", "Pay Basis", "Job Posting", "Notes", "Source",
                                                     "Industry Flag", "Company Profile", "Remote Status", "Posting Health",
                                                     "Role Red Flags", "Schedule Intensity", "Posted Date Source")}}
        r = run_stats._FakeResponse(body)
        return r
    fn.__name__ = name
    return fn


class MainSmokeTests(unittest.TestCase):
    def run_main(self, quick):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            out = io.StringIO()
            patches = [
                mock.patch.object(run_stats, "DRY_RUN", True),
                mock.patch.object(run_stats, "STATS_FILE", t / "stats.jsonl"),
                mock.patch.object(run_stats, "DRY_RUN_FILE", t / "writes.jsonl"),
                mock.patch.object(jsa, "NOTION_TOKEN", "x"),
                mock.patch.object(jsa, "SEEN_JOBS_FILE", t / "seen.json"),
                mock.patch.object(jsa, "STALE_MISS_FILE", t / "miss.json"),
                mock.patch.object(jsa, "load_history", return_value={}),
                mock.patch.object(jsa, "load_seen", return_value=set()),
                mock.patch.object(jsa, "save_history"),
                mock.patch.object(jsa, "fetch_remotive", return_value=[]),
                mock.patch.object(jsa, "fetch_remoteok", return_value=[]),
                mock.patch.object(jsa, "fetch_all_confirmed", return_value=[dict(JOB)]),
                mock.patch.object(jsa, "fetch_board_feeds", return_value=[]),
                mock.patch.object(jsa, "fetch_linkedin_alerts", return_value=[]),
                mock.patch.object(jsa, "check_notion_schema", return_value=True),
                mock.patch.object(jsa, "screen_candidates", return_value=""),
                mock.patch.object(jsa, "notify"),
                mock.patch.object(jsa.requests, "get", _fake_http("get")),
                mock.patch.object(jsa.requests, "post", _fake_http("post")),
                mock.patch.object(jsa.requests, "patch", _fake_http("patch")),
                mock.patch.object(notion_q, "SNAPSHOT_FILE", t / "snap.md"),
            ]
            with ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                inv = stack.enter_context(mock.patch.object(invariants, "run_after_agent"))
                stack.enter_context(redirect_stdout(out))
                jsa.main(quick=quick)
            text = out.getvalue()
            stats = [json.loads(l) for l in (t / "stats.jsonl").read_text().splitlines()]
            writes = [json.loads(l) for l in (t / "writes.jsonl").read_text().splitlines()] if (t / "writes.jsonl").exists() else []
            return text, stats, writes, inv, (t / "seen.json").exists()

    def test_quick_run(self):
        text, stats, writes, inv, seen_saved = self.run_main(quick=True)
        self.assertIn("DRY RUN", text)
        self.assertIn("Profile:", text)
        self.assertEqual(stats[-1]["run"], "quick")
        self.assertEqual(stats[-1]["written"], 1)
        creates = [w for w in writes if w["url"].endswith("/v1/pages")]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["payload"]["properties"]["Company"]["rich_text"][0]["text"]["content"], "Acme")
        self.assertFalse(seen_saved, "dry run must not save seen_jobs.json")
        self.assertFalse(inv.called, "quick runs don't run invariants")

    def test_full_run(self):
        text, stats, writes, inv, _ = self.run_main(quick=False)
        self.assertEqual(stats[-1]["run"], "full")
        self.assertIn("rescore_tracker", stats[-1]["stages"])
        self.assertIn("fetch", stats[-1]["stages"])
        self.assertEqual(stats[-1]["violations"], [])
        self.assertFalse(inv.called, "dry run skips the invariants email path")
        self.assertIn("Profile:", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
