"""Oct 30, 2026: open rows are fetched from Notion once per run and filtered
locally; patches keep the cache current. These tests guard the local filter
evaluator against the exact filter shapes the agent uses, and the cache
against going stale after a patch or a close. No network.
    python3 Tooling/agent/agent_tests/test_open_row_cache.py
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import job_search_agent as jsa   # noqa: E402
import fit_scoring               # noqa: E402
import lead_resolver             # noqa: E402


def page(pid, **props):
    out = {"id": pid, "properties": {"Status": {"type": "status", "status": {"name": "Interested"}}}}
    for k, v in props.items():
        name = k.replace("_", " ")
        if isinstance(v, (int, float)):
            out["properties"][name] = {"type": "number", "number": v}
        elif name in ("Overall Verdict", "Research Tier", "Source", "Pay Basis"):
            out["properties"][name] = {"type": "select", "select": {"name": v} if v else None}
        elif name == "Job Posting":
            out["properties"][name] = {"type": "url", "url": v}
        else:
            out["properties"][name] = {"type": "rich_text", "rich_text": [{"plain_text": v}] if v else []}
    return out


class FilterEvaluatorTests(unittest.TestCase):
    def test_rescore_filter(self):
        flt = {"or": [
            {"property": "Score Breakdown", "rich_text": {"does_not_contain": fit_scoring.RUBRIC_VERSION}},
            {"property": "Score Breakdown", "rich_text": {"contains": jsa.NO_SNAPSHOT_TAG}},
        ]}
        self.assertTrue(jsa._matches_filter(page("a", Score_Breakdown="scored v1.0"), flt))
        self.assertTrue(jsa._matches_filter(page("b", Score_Breakdown=f"{jsa.NO_SNAPSHOT_TAG} {fit_scoring.RUBRIC_VERSION}"), flt))
        self.assertFalse(jsa._matches_filter(page("c", Score_Breakdown=f"fine {fit_scoring.RUBRIC_VERSION}"), flt))
        self.assertTrue(jsa._matches_filter(page("d"), flt), "a missing breakdown counts as not containing the version")

    def test_select_and_filters(self):
        flt = {"and": [
            {"property": "Overall Verdict", "select": {"equals": "Ask me first"}},
            {"property": "Research Tier", "select": {"equals": fit_scoring.TIER_NAMES["A"]}},
        ]}
        self.assertTrue(jsa._matches_filter(page("a", Overall_Verdict="Ask me first", Research_Tier=fit_scoring.TIER_NAMES["A"]), flt))
        self.assertFalse(jsa._matches_filter(page("b", Overall_Verdict="Ask me first", Research_Tier=fit_scoring.TIER_NAMES["B"]), flt))
        self.assertFalse(jsa._matches_filter(page("c", Overall_Verdict=None), flt))

    def test_linkedin_lead_filter(self):
        flt = {"and": [
            {"property": "Source", "select": {"equals": "LinkedIn"}},
            {"property": "Posting Snapshot", "rich_text": {"is_empty": True}},
            {"property": "Notes", "rich_text": {"does_not_contain": lead_resolver.BOARD_STAMP}},
        ]}
        self.assertTrue(jsa._matches_filter(page("a", Source="LinkedIn", Posting_Snapshot="", Notes="LinkedIn alert"), flt))
        self.assertFalse(jsa._matches_filter(page("b", Source="LinkedIn", Posting_Snapshot="text", Notes=""), flt))
        self.assertFalse(jsa._matches_filter(page("c", Source="LinkedIn", Posting_Snapshot="", Notes=lead_resolver.BOARD_STAMP + ": none"), flt))

    def test_unknown_shape_raises(self):
        with self.assertRaises(ValueError):
            jsa._matches_filter(page("a"), {"property": "Posted Date", "date": {"before": "2026-01-01"}})


class CacheTests(unittest.TestCase):
    def setUp(self):
        jsa.OPEN_ROWS_CACHE = None

    def tearDown(self):
        jsa.OPEN_ROWS_CACHE = None

    def test_one_fetch_per_run(self):
        rows = [page("a", Overall_Verdict="Poor fit"), page("b", Overall_Verdict="Watch")]
        with mock.patch.object(jsa, "NOTION_TOKEN", "x"), \
                mock.patch.object(jsa, "_fetch_open_rows", return_value=rows) as fetch:
            self.assertEqual(len(jsa.query_open_rows()), 2)
            skips = jsa.query_open_rows({"property": "Overall Verdict", "select": {"equals": "Poor fit"}})
            self.assertEqual([p["id"] for p in skips], ["a"])
            jsa.query_open_rows({"property": "Overall Verdict", "select": {"equals": "Watch"}})
            self.assertEqual(fetch.call_count, 1)

    def test_failed_fetch_is_not_cached(self):
        with mock.patch.object(jsa, "NOTION_TOKEN", "x"), \
                mock.patch.object(jsa, "_fetch_open_rows", return_value=None) as fetch:
            self.assertEqual(jsa.query_open_rows(), [])
            self.assertEqual(jsa.query_open_rows(), [])
            self.assertEqual(fetch.call_count, 2)

    def test_patch_updates_cache_so_rescore_sees_new_text(self):
        rows = [page("a", Score_Breakdown=f"fine {fit_scoring.RUBRIC_VERSION}")]
        ok = mock.Mock(status_code=200, text="")
        with mock.patch.object(jsa, "NOTION_TOKEN", "x"), \
                mock.patch.object(jsa, "_fetch_open_rows", return_value=rows), \
                mock.patch.object(jsa, "request_with_retry", return_value=ok):
            jsa.query_open_rows()
            jsa.patch_page("a", {"Score Breakdown": {"rich_text": [{"text": {"content": "SNAPSHOT REFRESHED; rescore pending."}}]},
                                 "Overall Verdict": {"select": {"name": "Watch"}}})
            due = jsa.query_open_rows({"property": "Score Breakdown", "rich_text": {"does_not_contain": fit_scoring.RUBRIC_VERSION}})
            self.assertEqual([p["id"] for p in due], ["a"])
            self.assertEqual(jsa._sel(due[0]["properties"], "Overall Verdict"), "Watch")

    def test_close_removes_row_from_cache(self):
        rows = [page("a", Overall_Verdict="Poor fit"), page("b")]
        ok = mock.Mock(status_code=200, text="")
        with mock.patch.object(jsa, "NOTION_TOKEN", "x"), \
                mock.patch.object(jsa, "_fetch_open_rows", return_value=rows), \
                mock.patch.object(jsa, "request_with_retry", return_value=ok):
            jsa.query_open_rows()
            self.assertTrue(jsa.update_status("a", "Closed"))
            self.assertEqual([p["id"] for p in jsa.query_open_rows()], ["b"])

    def test_filter_properties_url(self):
        jsa.APP_PROPERTY_IDS.clear()
        base = "https://api.notion.com/v1/databases/x/query"
        self.assertEqual(jsa._filter_properties_url(base, ("Job Posting",)), base, "no ids yet: plain url")
        jsa.APP_PROPERTY_IDS.update({"Job Posting": "abc", "Company": "d%3Ae", "Role": "title"})
        self.assertEqual(jsa._filter_properties_url(base, ("Job Posting", "Company", "Role")),
                         base + "?filter_properties=abc&filter_properties=d%3Ae&filter_properties=title")
        jsa.APP_PROPERTY_IDS.clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
