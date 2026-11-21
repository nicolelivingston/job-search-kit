"""The never list (setup: "Never show me titles with these words") drops a
title before it is scored, and the log names the word that dropped it. A short
word typed in capitals, such as "IT" or "QA", matches in capitals only, so the
ordinary word "it" in a title doesn't drop it; every other entry matches in any
capitalization, as before (NIC-49). Checked three ways: the daily check's own
filter, setup's Try a title box, and settings written by setup and read back
by a fresh agent. Runs against a temporary copy of a test person's settings.
Every title here is made up. No network.
    python3 app/agent/agent_tests/test_title_never_list.py
"""
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
KIT = APP.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
os.environ.pop("NOTION_TOKEN", None)

import job_search_agent as agent  # noqa: E402
import setup_model as sm  # noqa: E402

WANTED = "data analyst"
NEVER = ["IT", "QA", "intern", "SALES"]
DROPPED = {   # title: the never-list word the reason must name
    "IT Data Analyst": "IT",
    "Data Analyst, IT": "IT",
    "Data Analyst (IT Operations)": "IT",
    "Senior Data Analyst - IT": "IT",
    "QA Data Analyst": "QA",
    "Data Analyst Intern": "intern",
    "DATA ANALYST INTERN": "intern",      # an ordinary entry still matches any capitalization
    "Sales Data Analyst": "SALES",        # five letters typed in capitals is an ordinary entry
}
KEPT = [
    "Data Analyst, Make It Count",        # "It" is the ordinary word, not the capital word
    "Data Analyst for it platforms",
    "Digital Data Analyst",               # "IT" inside a longer word never matches
    "Qa Data Analyst",                    # only capitals count for a capital word
    "Data Analyst, Information Technology",   # not on this list
    "Senior Data Analyst",
]


class DailyFilter(unittest.TestCase):
    def setUp(self):
        pats = [(kw, agent._title_word_pattern(kw)) for kw in NEVER]
        self.p = [mock.patch.object(agent, "ROLE_REJECT_PATTERNS", pats),
                  mock.patch.object(agent, "TITLE_PATTERNS", [agent._phrase_pattern(WANTED)])]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_capital_words(self):
        for w in ("IT", "QA", "HR", "SDR", "UXR"):
            self.assertTrue(agent.is_caps_word(w), w)
        for w in ("it", "It", "SALES", "I", "IT ops", "Q&A", ""):
            self.assertFalse(agent.is_caps_word(w), w)

    def test_dropped_titles_name_the_word(self):
        for title, word in DROPPED.items():
            with self.subTest(title=title):
                reason = agent.role_type_rejection_reason(title)
                self.assertIsNotNone(reason, title)
                self.assertIn(f"rejected role keyword {word!r}", reason)

    def test_kept_titles(self):
        for title in KEPT:
            with self.subTest(title=title):
                self.assertIsNone(agent.role_type_rejection_reason(title), title)

    def test_log_says_why(self):
        src = inspect.getsource(agent.main)
        self.assertIn('"Not written: %r @ %r: %s"', src)
        self.assertIn("(logger.info if key else logger.debug)", src)


class TryATitle(unittest.TestCase):
    A = {"work": {"titles": [WANTED], "never_titles": NEVER, "skip_title_words": [], "ask_title_words": [],
                  "level_at": ["senior"], "level_below": [], "level_junior": []}}

    def test_same_rule_as_the_daily_check(self):
        for title, word in DROPPED.items():
            with self.subTest(title=title):
                r = sm.check_title(self.A, title)
                self.assertFalse(r["kept"]); self.assertIn(f'"{word}"', " ".join(r["lines"]))
        for title in KEPT:
            with self.subTest(title=title):
                self.assertTrue(sm.check_title(self.A, title)["kept"], title)


class SettingsRoundTrip(unittest.TestCase):
    """Setup writes the list; a fresh agent reading those settings applies it."""

    def test_written_and_read_back(self):
        root = KIT / "examples" / "priya-healthtech-pm"
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "settings"
            shutil.copytree(root / "settings", dst)
            p = json.loads((dst / "paths.json").read_text())
            p["bank_dir"] = str((root / "settings" / p["bank_dir"]).resolve())
            p["data_dir"] = str(Path(tmp) / "data")
            (dst / "paths.json").write_text(json.dumps(p))
            a = sm.read_answers(dst)
            a["work"]["titles"] = [WANTED]
            a["work"]["never_titles"] = [" IT ", "Intern", "QA"]
            sm.write_answers(dst, a)
            ag = json.loads((dst / "criteria.json").read_text())["agent"]
            self.assertEqual(ag["ROLE_REJECT_KEYWORDS"], ["IT", "intern", "QA"], "capital words kept as typed, the rest lowercased")
            self.assertEqual(sm.read_answers(dst)["work"]["never_titles"], ["IT", "intern", "QA"])
            code = ("import json, sys; sys.path.insert(0, sys.argv[1]); import job_search_agent as a; "
                    "t = json.loads(sys.argv[2]); "
                    "print(json.dumps({x: [a.role_type_rejection_reason(x), bool(a.ROLE_BAD_RE.search(x))] for x in t}))")
            titles = ["IT Data Analyst", "Data Analyst, Make It Count", "Data Analyst Intern", "Qa Data Analyst"]
            env = dict(os.environ, KIT_SETTINGS_DIR=str(dst))
            env.pop("NOTION_TOKEN", None)
            r = subprocess.run([sys.executable, "-c", code, str(APP / "agent"), json.dumps(titles)],
                               capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            got = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertIn("'IT'", got["IT Data Analyst"][0]); self.assertTrue(got["IT Data Analyst"][1])
            self.assertIsNone(got["Data Analyst, Make It Count"][0]); self.assertFalse(got["Data Analyst, Make It Count"][1])
            self.assertIn("'intern'", got["Data Analyst Intern"][0]); self.assertTrue(got["Data Analyst Intern"][1])
            self.assertIsNone(got["Qa Data Analyst"][0]); self.assertFalse(got["Qa Data Analyst"][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
