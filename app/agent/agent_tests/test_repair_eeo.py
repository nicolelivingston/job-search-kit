#!/usr/bin/env python3
"""One-time repair (fit scoring v4.1): rows closed before v4.1 because a rule
word sat only in the equal-opportunity statement get reopened once.

Every row below is made up.

    cd app/agent && KIT_SETTINGS_DIR=../../examples/priya-healthtech-pm/settings python3 agent_tests/test_repair_eeo.py
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fit_scoring as fs          # noqa: E402
import job_search_agent as agent  # noqa: E402

EEO = ("We are an equal opportunity employer and consider applicants without regard to race, color, "
       "religion, sex, national origin, age, disability, marital status, military or veteran status, "
       "or any other status protected by law.")


def row(pid, company, role, snapshot, verdict="Poor fit"):
    return {"id": pid, "properties": {
        "Role": {"type": "title", "title": [{"plain_text": role}]},
        "Company": {"type": "rich_text", "rich_text": [{"plain_text": company}]},
        "Posting Snapshot": {"type": "rich_text", "rich_text": [{"plain_text": snapshot}]},
        "Overall Verdict": {"type": "select", "select": {"name": verdict} if verdict else None},
        "Remote Status": {"type": "select", "select": {"name": "Fully Remote"}},
        "Base Salary": {"type": "number", "number": 180000},
    }}


class FakeResp:
    status_code = 200

    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return {"results": self._rows, "has_more": False}


class RepairEEO(unittest.TestCase):
    ROWS = [
        row("p-eeo", "Ledgerly", "Senior Product Manager",
            "Fully remote. Ledgerly builds invoicing software for small businesses. " + EEO),
        row("p-real", "Brightspan", "Senior Product Manager",
            "Fully remote. You will own mission planning software for military customers. " + EEO),
        row("p-mine", "Answerly", "Product Manager",
            "Fully remote. Answerly builds help desk software. " + EEO, verdict="Passed"),
    ]

    def run_repair(self, tmp, apply=True):
        patched, reopened = [], []
        with mock.patch.object(agent, "NOTION_TOKEN", "x"), \
                mock.patch.object(agent, "REPAIRS_FILE", Path(tmp) / "repairs_done.json"), \
                mock.patch.object(agent, "request_with_retry", return_value=FakeResp(self.ROWS)), \
                mock.patch.object(agent, "rescore_page", side_effect=lambda pg, t: patched.append(pg["id"]) or 1), \
                mock.patch.object(agent, "update_status", side_effect=lambda pid, s: reopened.append((pid, s)) or True), \
                mock.patch.object(fs, "EXCLUDED_INDUSTRY_RE", fs._rx("military", "defense")):
            out = agent.repair_eeo_closed_rows(date(2025, 1, 15), apply=apply)
        return out, patched, reopened

    def test_reopens_only_the_eeo_only_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, patched, reopened = self.run_repair(tmp)
        self.assertEqual(out, [("Ledgerly", "Senior Product Manager")])
        self.assertEqual(patched, ["p-eeo"])
        self.assertEqual(reopened, [("p-eeo", "Interested")])

    def test_runs_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_repair(tmp)
            done = json.loads((Path(tmp) / "repairs_done.json").read_text())
            self.assertIn(agent.EEO_REPAIR_NAME, done)
            out, patched, reopened = self.run_repair(tmp)
        self.assertEqual((out, patched, reopened), ([], [], []))

    def test_preview_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, patched, reopened = self.run_repair(tmp, apply=False)
            self.assertFalse((Path(tmp) / "repairs_done.json").exists())
        self.assertEqual(out, [("Ledgerly", "Senior Product Manager")])
        self.assertEqual((patched, reopened), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
