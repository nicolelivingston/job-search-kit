#!/usr/bin/env python3
"""Fit scoring v4.2: a heading's own words don't end its section, and remote
with a catch covers more wording.

Two bugs found by hand. (1) A required-section heading with more words on
its line ("What You Bring To The Team") ended its own section, so none of
its items were read and a requirement the user couldn't claim went unseen.
(2) A posting that said "remote-first, but not remote-only" and asked for
in-person working sessions passed the remote rules with no flag, and the
stored posting text cut that sentence out of the intro.

Runs against any settings folder (the pull request checks use every example
person's); every posting below is made up. The remote checks use the kit's
current default rules in remote-only mode, whatever the folder says, so they
mean the same thing for every person.

    cd app/agent && KIT_SETTINGS_DIR=../../examples/priya-healthtech-pm/settings python3 agent_tests/test_scoring_v42.py
"""
import json
import sys
import unittest
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
KIT = AGENT.parent.parent
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(AGENT.parent))
import fit_scoring as fs          # noqa: E402
import job_search_agent as jsa    # noqa: E402
import kit_settings               # noqa: E402

ITEMS = ["Hands-on work with veterinary practice billing systems and their data",
         "Knowledge of livestock auction settlement rules across several states",
         "Clear writing for readers outside your own team and field"]
NEXT = "Our group of nine people plans the week together every Tuesday morning"


def posting(heading, after="The Team"):
    lis = "".join(f"<li>{i}</li>" for i in ITEMS)
    return (f"<p>Harborline makes scheduling software for small clinics.</p><h3>{heading}</h3><ul>{lis}</ul>"
            f"<h3>{after}</h3><p>{NEXT}.</p>")


def items(html):
    return fs.required_items(fs._clean(html))


class HeadingWithMoreWords(unittest.TestCase):
    def test_rubric_version(self):
        self.assertGreaterEqual(fs.RUBRIC_VERSION, "v4.2")

    def test_more_words_on_the_heading_line_keep_the_section(self):
        plain = items(posting("What You Bring"))
        self.assertEqual(plain, ITEMS)
        for heading in ("What You Bring To The Team", "What you'll need in this role", "Requirements for this role",
                        "Who You Are As A Teammate", "What We're Looking For In You", "Qualifications and experience"):
            with self.subTest(heading=heading):
                self.assertEqual(items(posting(heading)), ITEMS)

    def test_the_section_still_ends_at_the_next_heading(self):
        for heading in ("What You Bring To The Team", "Requirements"):
            for after in ("The Team", "Benefits", "About us"):
                with self.subTest(heading=heading, after=after):
                    got = items(posting(heading, after))
                    self.assertEqual(got, ITEMS)
                    self.assertFalse(any("nine people" in g for g in got))

    def test_a_heading_followed_by_another_heading_is_an_empty_section(self):
        html = f"<h3>Requirements</h3><h3>The Team</h3><p>{NEXT}.</p>"
        self.assertEqual(items(html), [])


def default_remote_rules():
    """The kit's current default hard rules for a remote-only search."""
    crit = json.loads((KIT / "templates" / "settings" / "criteria.json").read_text(encoding="utf-8"))
    return [tuple(r) for r in kit_settings.build(crit["fit_scoring"]["HARD_RULES"], fs._rx)
            if r[0] in ("remote-hybrid", "remote-catch")]


class RemoteWithACatch(unittest.TestCase):
    def setUp(self):
        self._saved = (fs.HARD_RULES, fs.WORK_MODE)
        fs.HARD_RULES, fs.WORK_MODE = default_remote_rules(), "remote"

    def tearDown(self):
        fs.HARD_RULES, fs.WORK_MODE = self._saved

    def screen(self, text):
        return fs.hard_screen("Analyst", "Fully remote. " + text, salary_min=None, remote_hint=True)

    def test_a_catch_asks_and_quotes_the_posting(self):
        for text, quoted in (
                ("This team is remote-first, but not remote-only.", "not remote-only"),
                ("We are remote first, not remote only.", "not remote only"),
                ("Plan on in-person working sessions with the whole team.", "in-person working sessions"),
                ("We hold quarterly off-sites that everyone attends.", "quarterly off-sites"),
                ("The company gets together every quarter.", "gets together every quarter"),
                ("You will travel quarterly to see customers.", "travel quarterly"),
                ("Our team meets in person once a quarter.", "meets in person once a quarter"),
                ("We gather quarterly for a team offsite in another city.", "gather quarterly"),
                ("The group meets every quarter at our Denver office.", "meets every quarter")):
            with self.subTest(text=text):
                verdict, reasons = self.screen(text)
                self.assertEqual(verdict, "ask", reasons)
                self.assertTrue(any(r.startswith("Remote with a catch") and quoted in r for r in reasons), reasons)

    def test_ordinary_quarterly_wording_is_not_a_catch(self):
        for text in ("You will meet quarterly revenue targets.",
                     "Gather quarterly feedback from customers and share it with the team.",
                     "The product council meets quarterly to review the roadmap.",
                     "Present quarterly business reviews to customer executives.",
                     "You will meet quarterly goals. Our office is in Denver.",
                     "The product council meets quarterly • Our office is in Denver",   # the next item, not this one
                     "We meet quarterly with advisors over video.",
                     "The team meets in person once a year at an optional retreat.",
                     "The whole company works remotely across four time zones."):
            with self.subTest(text=text):
                verdict, reasons = self.screen(text)
                self.assertIsNone(verdict, reasons)

    def test_every_settings_folder_in_the_kit_has_the_phrases(self):
        folders = [KIT / "templates" / "settings"] + sorted(p / "settings" for p in (KIT / "examples").iterdir() if p.is_dir())
        self.assertEqual(len(folders), 4)
        for folder in folders:
            rules = json.loads((folder / "criteria.json").read_text(encoding="utf-8"))["fit_scoring"]["HARD_RULES"]
            phrases = next(r["$tuple"][1]["$rx"] for r in rules if r["$tuple"][0] == "remote-catch")
            with self.subTest(folder=folder.parent.name):
                self.assertEqual([p for p in kit_settings.REMOTE_CATCH_V4 if p not in phrases], [])


class SnapshotKeepsTheCatch(unittest.TestCase):
    INTRO = "Harborline makes scheduling software for independent dental offices in small towns. " * 4
    CATCH = "We are a remote-first team, but not remote-only: plan on in-person working sessions a few times a year."
    REST = "<h3>Requirements</h3><ul>" + "".join(f"<li>{i}</li>" for i in ITEMS) + "</ul>"

    def setUp(self):
        self._saved = (fs.HARD_RULES, fs.WORK_MODE)
        fs.HARD_RULES, fs.WORK_MODE = default_remote_rules(), "remote"

    def tearDown(self):
        fs.HARD_RULES, fs.WORK_MODE = self._saved

    def test_a_remote_rule_sentence_in_the_cut_part_is_kept(self):
        desc = f"<p>{self.INTRO}{self.CATCH} We have grown every year since we started.</p>{self.REST}"
        self.assertGreater(fs._clean(desc).index("Requirements"), 300)   # long enough for the intro to be cut
        snap = jsa.make_snapshot(desc)
        self.assertIn("not remote-only", snap)
        self.assertIn("in-person working sessions", snap)
        self.assertNotIn("grown every year", snap)                       # the rest of the cut stays cut
        self.assertIn(ITEMS[1], snap)                                    # the requirements still follow
        self.assertLessEqual(len(snap), jsa.SNAPSHOT_MAX)
        self.assertEqual(fs.hard_screen("Analyst", snap, remote_hint=True)[0], "ask")

    def test_nothing_to_keep_leaves_the_snapshot_as_it_was(self):
        desc = f"<p>{self.INTRO}We have grown every year since we started.</p>{self.REST}"
        snap = jsa.make_snapshot(desc)
        self.assertEqual(snap.count("[...]"), 1)
        self.assertTrue(snap.startswith(fs._clean(desc)[:230]))
        self.assertIn(ITEMS[1], snap)

    def test_a_short_posting_is_kept_whole(self):
        desc = f"<p>{self.CATCH}</p>{self.REST}"
        self.assertNotIn("[...]", jsa.make_snapshot(desc))


class NotRemoteOnly(unittest.TestCase):
    def test_remote_rules_stay_out_of_it_for_a_person_who_accepts_office_work(self):
        if fs.WORK_MODE == "remote":
            self.skipTest("this person's search is remote-only")
        verdict, reasons = fs.hard_screen("Analyst", "Fully remote. This team is remote-first, but not remote-only.",
                                          remote_hint=True)
        self.assertFalse(any(r.startswith("Remote with a catch") for r in reasons), reasons)


if __name__ == "__main__":
    unittest.main(verbosity=1)
