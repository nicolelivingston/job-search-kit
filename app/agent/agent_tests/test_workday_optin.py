"""Workday boards are read only when the user turned them on for that
company ("workday_ok": true): the daily fetch skips the others, and the lead
lookup never probes a Workday board that isn't on. No network.
    python3 app/agent/agent_tests/test_workday_optin.py
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))
import ats_tools        # noqa: E402
import lead_resolver    # noqa: E402

ON = {"tenant": "acme", "instance": "wd5", "board": "Acme_External"}
OFF = {"tenant": "bolt", "instance": "wd1", "board": "Bolt_Careers"}
COMPANIES = [
    {"name": "Acme", "platform": "workday", "slug": ON, "workday_ok": True},
    {"name": "Bolt", "platform": "workday", "slug": OFF},
    {"name": "Cora", "platform": "greenhouse", "slug": "cora"},
]


class WorkdayOptIn(unittest.TestCase):
    def test_daily_fetch_reads_only_opted_in_workday(self):
        called = []
        fetchers = {"workday": lambda s: called.append(("workday", s["tenant"])) or [],
                    "greenhouse": lambda s: called.append(("greenhouse", s)) or []}
        with mock.patch.object(ats_tools, "CONFIRMED_COMPANIES", COMPANIES), \
             mock.patch.dict(ats_tools.FETCHERS, fetchers):
            ats_tools.fetch_all_confirmed()
        self.assertEqual(called, [("workday", "acme"), ("greenhouse", "cora")])

    def test_lead_lookup_never_probes_an_off_workday_board(self):
        called = []
        lead_resolver._RUN_CACHE.clear()
        with mock.patch.object(ats_tools, "CONFIRMED_COMPANIES", COMPANIES), \
             mock.patch.dict(lead_resolver.FETCHERS, {"workday": lambda s: called.append(s["tenant"]) or [{"title": "x"}]}):
            self.assertEqual(lead_resolver.fetch_board("workday", OFF), [])
            self.assertEqual(lead_resolver.fetch_board("workday", ON), [{"title": "x"}])
        self.assertEqual(called, ["acme"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
