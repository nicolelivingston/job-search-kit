"""Regression tests for the Oct 29, 2026 testing and efficiency layer:
run_stats (profiler, dry run, Pursue guard), the Last Verified stamp policy,
and invariants.py's checks. No network. Run:
    python3 Tooling/agent/agent_tests/test_invariants_and_stats.py
"""
import contextlib
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ats_tools            # noqa: E402
import run_stats            # noqa: E402
import invariants           # noqa: E402
import job_search_agent as jsa   # noqa: E402
import fit_scoring          # noqa: E402

TODAY = date(2026, 10, 29)
TIER_A, TIER_B, TIER_C = (fit_scoring.TIER_NAMES[t] for t in "ABC")


def _fake(name, status=200, body=None):
    """A requests-like function with a given __name__ (get/post/patch)."""
    calls = []

    def fn(url, **kwargs):
        calls.append((url, kwargs))
        r = run_stats._FakeResponse(body or {})
        r.status_code = status
        return r
    fn.__name__ = name
    fn.calls = calls
    return fn


class RunStatsTests(unittest.TestCase):
    def setUp(self):
        run_stats.STATS.reset()

    def test_counts_notion_calls_by_kind(self):
        get, post, patch = _fake("get"), _fake("post"), _fake("patch")
        ats_tools.request_with_retry(post, "https://api.notion.com/v1/databases/abc/query", json={})
        ats_tools.request_with_retry(get, "https://api.notion.com/v1/pages/00000000-0000-4000-8000-000000000201")
        ats_tools.request_with_retry(patch, "https://api.notion.com/v1/pages/00000000-0000-4000-8000-000000000201", json={"properties": {}})
        ats_tools.request_with_retry(post, "https://api.notion.com/v1/pages", json={"properties": {}})
        ats_tools.request_with_retry(get, "https://boards-api.greenhouse.io/v1/boards/x/jobs")
        c = run_stats.STATS.calls
        self.assertEqual((c["notion:query"], c["notion:page_read"], c["notion:page_patch"], c["notion:page_create"], c["board"]),
                         (1, 1, 1, 1, 1))
        self.assertIn("Notion 4 calls", run_stats.STATS.summary_line())

    def test_dry_run_records_writes_and_sends_nothing(self):
        post, patch, get = _fake("post"), _fake("patch"), _fake("get")
        lt = sys.modules.get("local_tracker")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(lt, "_DATA", None) if lt else contextlib.nullcontext(), \
                mock.patch.object(run_stats, "DRY_RUN", True), \
                mock.patch.object(run_stats, "DRY_RUN_FILE", Path(tmp) / "w.jsonl"):
            r = ats_tools.request_with_retry(patch, "https://api.notion.com/v1/pages/00000000-0000-4000-8000-000000000201",
                                             json={"properties": {"Status": {"status": {"name": "Closed"}}}})
            ats_tools.request_with_retry(post, "https://api.notion.com/v1/pages", json={"properties": {"Role": {}}})
            ats_tools.request_with_retry(post, "https://api.notion.com/v1/databases/abc/query", json={})   # a read: still sent
            ats_tools.request_with_retry(get, "https://api.notion.com/v1/pages/00000000-0000-4000-8000-000000000201")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(patch.calls, [])
            self.assertEqual(len(post.calls), 1)          # only the query went out
            self.assertEqual(len(get.calls), 1)
            recorded = [json.loads(l) for l in (Path(tmp) / "w.jsonl").read_text().splitlines()]
            self.assertEqual([x["method"] for x in recorded], ["patch", "post"])
            self.assertEqual(recorded[0]["payload"]["properties"]["Status"]["status"]["name"], "Closed")
            self.assertEqual(run_stats.STATS.dry_writes, 2)

    def test_pursue_write_is_a_violation(self):
        patch = _fake("patch")
        ats_tools.request_with_retry(patch, "https://api.notion.com/v1/pages/00000000-0000-4000-8000-000000000201",
                                     json={"properties": {"Overall Verdict": {"select": {"name": "Applying"}}}})
        ats_tools.request_with_retry(patch, "https://api.notion.com/v1/pages/00000000-0000-4000-8000-000000000201",
                                     json={"properties": {"Overall Verdict": {"select": {"name": "Possible fit"}}}})
        ats_tools.request_with_retry(patch, "https://api.notion.com/v1/pages/00000000-0000-4000-8000-000000000201",
                                     json={"properties": {"Overall Verdict": {"select": {"name": "Passed"}}}})
        self.assertEqual(len(run_stats.STATS.violations), 2)
        self.assertIn("Applying", run_stats.STATS.violations[0])
        self.assertIn("Passed", run_stats.STATS.violations[1])

    def test_stage_timing_and_stats_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(run_stats, "STATS_FILE", Path(tmp) / "s.jsonl"):
            with run_stats.STATS.stage("fetch"):
                ats_tools.request_with_retry(_fake("post"), "https://api.notion.com/v1/databases/abc/query", json={})
            rec = run_stats.STATS.write("full")
            self.assertEqual(rec["stages"]["fetch"]["notion_calls"], 1)
            self.assertEqual(len(run_stats.read_recent()), 1)


def _page(pid, url="https://job-boards.greenhouse.io/acme/jobs/1234567890", verified=None, snapshot="", salary=5, posted="2026-10-01",
          health=None):
    props = {"Job Posting": {"url": url}, "Posting Snapshot": {"rich_text": [{"plain_text": snapshot}]},
             "Base Salary": {"number": salary}, "Posted Date": {"date": {"start": posted}},
             "Company": {"rich_text": [{"plain_text": "Acme"}]}, "Role": {"title": [{"plain_text": "Senior Product Manager"}]}}
    if verified:
        props["Last Verified"] = {"date": {"start": verified}}
    if health:
        props["Posting Health"] = {"select": {"name": health}}
    return {"id": pid, "properties": props}


class LastVerifiedPolicyTests(unittest.TestCase):
    """Oct 29, 2026: Last Verified is re-stamped every VERIFY_STAMP_DAYS days,
    not every run; it rides along free when the row is patched anyway."""

    def run_refresh(self, page, job):
        patches = []
        with mock.patch.object(jsa, "NOTION_TOKEN", "x"), \
                mock.patch.object(jsa, "query_open_rows", return_value=[page]), \
                mock.patch.object(jsa, "patch_page", side_effect=lambda pid, props=None, icon_url=None: patches.append(props) or True):
            jsa.refresh_open_rows([job], {}, TODAY)
        return patches

    def test_verified_yesterday_is_not_patched(self):
        job = {"url": "https://job-boards.greenhouse.io/acme/jobs/1234567890", "description": ""}
        self.assertEqual(self.run_refresh(_page("p1", verified="2026-10-28"), job), [])

    def test_verified_three_days_ago_is_stamped(self):
        job = {"url": "https://job-boards.greenhouse.io/acme/jobs/1234567890", "description": ""}
        patches = self.run_refresh(_page("p1", verified="2026-10-26"), job)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["Last Verified"]["date"]["start"], "2026-10-29")

    def test_unlisted_mark_clears_when_the_posting_is_back_on_the_list(self):
        # Nov 13, 2026: Unlisted means off the public list; found in the fetch again, the mark goes
        job = {"url": "https://job-boards.greenhouse.io/acme/jobs/1234567890", "description": ""}
        patches = self.run_refresh(_page("p1", verified="2026-10-28", health="Unlisted"), job)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["Posting Health"], {"select": None})
        self.assertEqual(patches[0]["Last Verified"]["date"]["start"], "2026-10-29")
        # any other mark is left alone
        self.assertEqual(self.run_refresh(_page("p1", verified="2026-10-28", health="Suspected evergreen"), job), [])

    def test_never_verified_is_stamped(self):
        job = {"url": "https://job-boards.greenhouse.io/acme/jobs/1234567890", "description": ""}
        self.assertEqual(self.run_refresh(_page("p1"), job)[0]["Last Verified"]["date"]["start"], "2026-10-29")

    def test_stamp_rides_along_when_row_changes_anyway(self):
        job = {"url": "https://job-boards.greenhouse.io/acme/jobs/1234567890",
               "description": "Requirements: 5+ years product management. Fully remote."}
        patches = self.run_refresh(_page("p1", verified="2026-10-28", snapshot=""), job)
        self.assertEqual(len(patches), 1)
        self.assertIn("Posting Snapshot", patches[0])
        self.assertEqual(patches[0]["Last Verified"]["date"]["start"], "2026-10-29")


def R(**kw):
    base = {"id": "00000000-0000", "company": "Acme", "role": "Senior Product Manager", "status": "Interested",
            "verdict": "Possible fit", "tier": TIER_B, "label": "", "pay_basis": "Base", "breakdown": fit_scoring.RUBRIC_VERSION,
            "posted": "2026-10-20", "verified": "2026-10-28", "applied": None, "drafting_started": None,
            "resume_versions": None, "override": "", "outcome": None, "score": 6,
            "url": "https://job-boards.greenhouse.io/acme/jobs/1234567890", "created": "2026-10-20", "edited": "2026-10-28"}
    base.update(kw)
    return base


class InvariantTests(unittest.TestCase):
    def fails(self, findings):
        return [t for lv, t in findings if lv == "FAIL"]

    def warns(self, findings):
        return [t for lv, t in findings if lv == "WARN"]

    def test_clean_rows_hold(self):
        f = invariants.check_rows([R()], [], [], TODAY)
        self.assertEqual(f, [])

    def test_duplicate_open_rows(self):
        f = invariants.check_rows([R(id="a"), R(id="b", role="Senior  Product Manager ")], [], [], TODAY)
        self.assertTrue(any("duplicate" in t for t in self.fails(f)))

    def test_hard_skip_or_pass_still_open_and_apply_on_tier_b(self):
        f = invariants.check_rows([R(verdict="Poor fit", label="Skip: hybrid. Scored 2026-11-01 by agent v3.3."),
                                   R(id="2", role="PM II", verdict="Strong fit", tier=TIER_B),
                                   R(id="3", role="PM III", verdict="Passed")], [], [], TODAY)
        self.assertEqual(len(self.fails(f)), 3)

    def test_soft_skip_open_and_apply_on_tier_a_are_fine(self):
        f = invariants.check_rows([R(verdict="Poor fit", tier=TIER_C, pay_basis="Not posted",
                                     label="Skip (no base pay posted), left open. Tier C, 49/100."),
                                   R(id="2", role="PM II", verdict="Strong fit", tier=TIER_A)], [], [], TODAY)
        self.assertEqual(f, [])

    def test_no_posted_pay_must_be_tier_c(self):
        f = invariants.check_rows([R(pay_basis="Not posted", tier=TIER_B)], [], [], TODAY)
        self.assertTrue(any("no posted pay" in t for t in self.fails(f)))
        ok = invariants.check_rows([R(pay_basis="Not posted", tier=TIER_C),
                                    R(id="2", role="X", pay_basis="Not posted", tier=TIER_A, verdict="Applying",
                                      breakdown="v2.7 ... Tier raised to A: Pursue.")], [], [], TODAY)
        self.assertEqual(self.fails(ok), [])

    def test_blank_or_retired_verdict_fails_once_rescored(self):
        # Nov 1, 2026: the best near-misses sat with a blank verdict
        f = invariants.check_rows([R(verdict=None), R(id="2", role="PM II", verdict="Watch"),
                                   R(id="3", role="PM III", verdict="Ask me first")], [], [], TODAY)
        fails = self.fails(f)
        self.assertTrue(any("no verdict" in t for t in fails))
        self.assertEqual(sum("retired verdict" in t for t in fails), 2)
        old = invariants.check_rows([R(verdict=None, breakdown="v3.2 score 69/100")], [], [], TODAY)
        self.assertEqual(self.fails(old), [])

    def test_pursue_hygiene_warns(self):
        f = invariants.check_rows([R(verdict="Applying", score=5, created="2026-10-01")], [], [], TODAY)
        w = self.warns(f)
        self.assertTrue(any("Override Reason" in t for t in w) and any("14 days" in t for t in w))
        self.assertEqual(self.fails(f), [])

    def test_closed_while_live_is_the_oct_27_bug(self):
        fetched = {jsa.posting_key("https://job-boards.greenhouse.io/acme/jobs/1234567890?gh_jid=1234567890")}
        covered = {jsa._board_scope("https://job-boards.greenhouse.io/acme/jobs/1234567890")}
        closed = [R(status="Closed", edited=TODAY.isoformat())]
        f = invariants.check_rows([], [], closed, TODAY, fetched, covered)
        self.assertTrue(any("closed today while still live" in t for t in self.fails(f)))
        # a Skip close or a recorded outcome is a legitimate close
        f2 = invariants.check_rows([], [], [R(status="Closed", verdict="Poor fit")], TODAY, fetched, covered)
        self.assertEqual(self.fails(f2), [])

    def test_verified_today_but_not_fetched(self):
        covered = {jsa._board_scope("https://job-boards.greenhouse.io/acme/jobs/1234567890")}
        f = invariants.check_rows([R(verified=TODAY.isoformat())], [], [], TODAY, set(), covered)
        self.assertTrue(any("absent from today's fetch" in t for t in self.fails(f)))

    def test_unlisted_row_verified_today_is_expected_to_be_absent(self):
        # Nov 13, 2026: an Unlisted row is verified by asking its board about that one posting
        covered = {jsa._board_scope("https://job-boards.greenhouse.io/acme/jobs/1234567890")}
        f = invariants.check_rows([R(verified=TODAY.isoformat(), health="Unlisted")], [], [], TODAY, set(), covered)
        self.assertEqual(self.fails(f), [])

    def test_stale_on_fetched_board_warns(self):
        covered = {jsa._board_scope("https://job-boards.greenhouse.io/acme/jobs/1234567890")}
        f = invariants.check_rows([R(verified="2026-10-15")], [], [], TODAY, None, covered)
        self.assertTrue(any("not verified in 14 days" in t for t in self.warns(f)))

    def test_cycle_time_fields_on_sends(self):
        sent = [R(status="Applied", applied="2026-10-25"), R(id="2", status="Applied", applied="2026-10-01")]
        with mock.patch.object(invariants, "TRACKING_STARTS", date(2026, 10, 18)):
            f = invariants.check_rows([], sent, [], TODAY)
        self.assertEqual(len(self.warns(f)), 2)   # the Oct 1 send predates tracking

    def test_run_checks_fetch_drop_and_zero_boards(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats = Path(tmp) / "s.jsonl"
            recs = [{"ts": f"2026-10-2{d}T08:00:00", "run": "full", "fetched": 5700, "calls": {"notion:query": 10}} for d in range(3, 9)]
            recs.append({"ts": "2026-10-29T08:00:00", "run": "full", "fetched": 2000, "calls": {"notion:query": 50},
                         "violations": ["write would set Overall Verdict = Pursue: x"]})
            stats.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
            log = Path(tmp) / "agent.log"
            log.write_text("=== Run started 2026-10-28T08:00:00 ===\n  Pagecraft: 4 postings\n  feed Himalayas: 20 postings\n"
                           "=== Run started 2026-10-29T08:00:00 ===\n  Pagecraft: 0 postings\n  feed Himalayas: 20 postings\n")
            with mock.patch.object(run_stats, "STATS_FILE", stats), mock.patch.object(invariants, "LOG_FILE", log), \
                    mock.patch("run_stats.time.time", return_value=1793404800.0):   # 2026-10-30 midnight UTC-ish
                f = invariants.check_runs(TODAY)
        texts = [t for _, t in f]
        self.assertTrue(any("under 60%" in t for t in texts))
        self.assertTrue(any("run violation" in t for t in texts))
        self.assertTrue(any("twice the 7-day median" in t for t in texts))
        self.assertTrue(any("Pagecraft" in t for t in texts))
        self.assertFalse(any("Himalayas" in t for t in texts))

    def test_email_once_per_day_per_failure(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(invariants, "STATE_FILE", Path(tmp) / "st.json"), \
                mock.patch.object(jsa, "GMAIL_ADDRESS", "n@x"), mock.patch.object(jsa, "GMAIL_APP_PASSWORD", "p"), \
                mock.patch("invariants.smtplib.SMTP_SSL") as smtp:
            self.assertTrue(invariants.email_if_new(["a"], TODAY))
            self.assertFalse(invariants.email_if_new(["a"], TODAY))        # same failure, same day: quiet
            self.assertTrue(invariants.email_if_new(["a", "b"], TODAY))   # a new one: email again
            self.assertFalse(invariants.email_if_new([], TODAY))
            self.assertEqual(smtp.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
