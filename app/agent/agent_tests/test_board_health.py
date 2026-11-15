"""A followed company's job board that goes dark is reported every day, not
once: a board that listed 5 or more postings and has shown none for 3 days
(the company has likely moved its jobs), or one that fails on every run for 3
days, is a failure; a board that never returned a posting in a week is a
note; a small board that emptied, a board that recovered, and one the user
checked by hand ("zero_ok") are left alone. The user is told once per board.
Made-up companies and a made-up run log. No network.
    python3 app/agent/agent_tests/test_board_health.py
"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.pop("NOTION_TOKEN", None)

import invariants as inv  # noqa: E402

START = date(2026, 11, 1)


def log(days):
    """A run log: one full run a day; each day is {board: count, or None for a failed fetch}."""
    out = []
    for i, boards in enumerate(days):
        out.append(f"\n=== Run started {(START + timedelta(days=i)).isoformat()}T08:00:00 ===")
        for name, n in boards.items():
            out.append(f"  [warn] {name} failed: HTTPError 503" if n is None else f"  {name}: {n} postings")
        out.append("Fetched 120 total postings.")
    return "\n".join(out) + "\n"


def names(findings, level):
    return sorted(m.rsplit(": ", 1)[1].split(" (")[0] for lv, m in findings if lv == level)


class BoardHealth(unittest.TestCase):
    BOARDS = [{"name": n} for n in ("Lumenfold", "Tessaway", "Quillco", "Harborline", "Paylane", "Northfield")]

    def days(self, n=8):
        return [{"Lumenfold": 22 if i < 2 else 0,            # moved: 22 postings, then nothing
                 "Tessaway": 3 if i < 2 else 0,              # a small board that emptied
                 "Quillco": 0,                               # never a posting
                 "Harborline": 14 if i < 4 else None,        # failing on every run since day 5
                 "Paylane": 9 if i != 5 else 0,              # one empty day, then back
                 "Northfield": 40} for i in range(n)]

    def test_dark_boards_are_reported_every_day(self):
        text = log(self.days())
        today = START + timedelta(days=7)
        f = inv.board_health(text, today, self.BOARDS)
        self.assertEqual(names(f, "FAIL"), ["Harborline", "Lumenfold"])
        self.assertEqual(names(f, "WARN"), ["Quillco"])
        moved = next(m for lv, m in f if m.endswith(": Lumenfold"))
        self.assertIn("no postings for 6 days (it listed up to 22, last on 2026-11-02)", moved)
        self.assertIn("failed on every run for 4 days", next(m for lv, m in f if m.endswith(": Harborline")))
        # the same findings the next day: a board that stays dark keeps being reported
        f2 = inv.board_health(log(self.days(9)), today + timedelta(days=1), self.BOARDS)
        self.assertEqual(names(f2, "FAIL"), ["Harborline", "Lumenfold"])

    def test_too_early_or_too_small_is_left_alone(self):
        self.assertEqual(inv.board_health(log(self.days(4)), START + timedelta(days=3), self.BOARDS), [])   # 2 dark days so far
        f = inv.board_health(log(self.days(8)), START + timedelta(days=7), self.BOARDS)
        self.assertNotIn("Tessaway", names(f, "FAIL") + names(f, "WARN"))      # 3 postings at most: it can just be empty
        self.assertNotIn("Paylane", names(f, "FAIL") + names(f, "WARN"))       # listing again

    def test_a_hand_check_quiets_a_board_for_a_while(self):
        text, today = log(self.days()), START + timedelta(days=7)
        checked = [dict(b, zero_ok="2026-11-05") if b["name"] in ("Lumenfold", "Quillco") else b for b in self.BOARDS]
        f = inv.board_health(text, today, checked)
        self.assertEqual((names(f, "FAIL"), names(f, "WARN")), (["Harborline"], []))
        late = today + timedelta(days=inv.ZERO_OK_DAYS)
        days = self.days(8 + inv.ZERO_OK_DAYS)
        f = inv.board_health(log(days), late, checked)
        self.assertIn("Lumenfold", names(f, "FAIL"))                             # asked about again once the check lapses
        self.assertEqual(inv.board_health(text, today, [dict(self.BOARDS[0], zero_ok="soon")])[0][0], "FAIL")   # a bad date isn't a check

    def test_boards_no_longer_read_and_other_lines_are_ignored(self):
        days = self.days(4) + [{"Northfield": 40}] * 4                           # the rest came off the list
        self.assertEqual(inv.board_health(log(days), START + timedelta(days=7), self.BOARDS), [])
        text = log(self.days()) + "  feed Remote Jobs: 0 postings\n  Someone Else: 0 postings\n"
        f = inv.board_health(text, START + timedelta(days=7), self.BOARDS)
        self.assertEqual(names(f, "FAIL"), ["Harborline", "Lumenfold"])
        self.assertEqual(inv.board_health("", START, self.BOARDS), [])

    def test_lines_before_the_first_run_header_count(self):
        early = "  Lumenfold: 30 postings\n  Lumenfold: 0 postings\n"                # an older log with no headers
        text = early + log([{"Lumenfold": 0}] * 4)
        f = inv.board_health(text, START + timedelta(days=3), [{"name": "Lumenfold"}])
        self.assertEqual(names(f, "FAIL"), ["Lumenfold"])
        self.assertIn("listed up to 30", f[0][1])

    def test_quick_runs_count_as_runs(self):
        text = log([{"Lumenfold": 12}]) + f"\n=== Quick run started {(START + timedelta(days=4)).isoformat()}T11:00:00 ===\n  Lumenfold: 0 postings\n"
        f = inv.board_health(text, START + timedelta(days=4), [{"name": "Lumenfold"}])
        self.assertEqual(names(f, "FAIL"), ["Lumenfold"])

    def test_the_user_is_told_once_per_board(self):
        tmp = Path(tempfile.mkdtemp()) / "state.json"
        tmp.write_text('{"sent_on": "2026-11-01", "fails": ["x"]}')
        told = []
        say = lambda title, message: told.append((title, message))
        f = inv.board_health(log(self.days()), START + timedelta(days=7), self.BOARDS)
        self.assertEqual(sorted(inv.notify_dark_boards(f, tmp, say)), ["Harborline", "Lumenfold"])
        self.assertEqual(len(told), 2)
        self.assertTrue(all("Companies page" in m and "gone quiet" in t for t, m in told))
        self.assertEqual(inv.notify_dark_boards(f, tmp, say), [])                # the next day: nothing new to say
        self.assertEqual(len(told), 2)
        import json
        state = json.loads(tmp.read_text())
        self.assertEqual((state["dark_boards"], state["sent_on"]), (["Harborline", "Lumenfold"], "2026-11-01"))
        back = [x for x in f if not x[1].endswith(": Lumenfold")]                # Lumenfold listed postings again...
        self.assertEqual(inv.notify_dark_boards(back, tmp, say), [])
        self.assertEqual(inv.notify_dark_boards(f, tmp, say), ["Lumenfold"])     # ...and went dark again: said again
        self.assertEqual(inv.notify_dark_boards([("WARN", "board has never returned a posting in 9 days of runs: Quillco (x)")], tmp, say), [])

    def test_the_daily_checks_include_it(self):
        import inspect
        self.assertIn("board_health(text, today, followed_companies())", inspect.getsource(inv.check_runs))
        self.assertIn("notify_dark_boards(findings)", inspect.getsource(inv.run))


if __name__ == "__main__":
    unittest.main(verbosity=2)
