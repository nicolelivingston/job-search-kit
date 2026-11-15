"""Setup guidance and the onboarding additions: the Try a title box says what
the daily check would do with a title, in plain words; companies followed
closely and "follow new companies for me" are saved as settings and survive
an older page that doesn't send them; a job board is found from a company's
name alone and offered with sample titles (never saved unconfirmed); the
resume the user already has is saved in their folder and read as text; and
the research queue lists the companies that matter most, until the user's
approved research is saved with its sources. Runs against a temporary copy of
a test person's settings. No network.
    python3 app/agent/agent_tests/test_setup_guidance.py
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent
PERSON = KIT / "examples" / "dana-retail-analytics"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "agent"))
sys.path.insert(0, str(APP / "resume"))

import setup_model  # noqa: E402


class TitleCheck(unittest.TestCase):
    A = {"work": {"titles": ["data analyst", "analytics lead"], "never_titles": ["intern", "sales"],
                  "skip_title_words": ["vice president"], "ask_title_words": ["head of"],
                  "level_at": ["senior"], "level_below": ["data analyst ii"], "level_junior": ["junior", "associate"]}}

    def lines(self, title, answers=None):
        r = setup_model.check_title(self.A if answers is None else answers, title)
        return r, " ".join(r["lines"])

    def test_plain_words_for_each_outcome(self):
        r, text = self.lines("Sr. Data Analyst, Pricing")
        self.assertTrue(r["kept"]); self.assertEqual(r["level"], "level_at")
        self.assertIn('Picked up: it has "data analyst"', text)
        self.assertIn("At your level", text)
        r, text = self.lines("DATA   ANALYST II")                      # capitals and spacing don't matter
        self.assertTrue(r["kept"]); self.assertEqual(r["level"], "level_below")
        r, text = self.lines("Database Analyst")                        # whole words only
        self.assertFalse(r["kept"]); self.assertIn("none of your job titles", text)
        r, text = self.lines("Sales Data Analyst")
        self.assertFalse(r["kept"]); self.assertIn('"sales"', text); self.assertIn("never list", text)
        r, text = self.lines("Vice President, Analytics Lead")
        self.assertFalse(r["kept"]); self.assertIn("Poor fit", text)
        r, text = self.lines("Head of Analytics, Analytics Lead")
        self.assertTrue(r["kept"]); self.assertIn("Possible fit", text)
        r, text = self.lines("Data Analyst")
        self.assertTrue(r["kept"]); self.assertEqual(r["level"], ""); self.assertIn("scores low on level", text)

    def test_empty_answers_ask_for_what_is_missing(self):
        self.assertIn("Type a job title", self.lines("")[1])
        self.assertIn("Add at least one job title", self.lines("Data Analyst", {"work": {"titles": []}})[1])
        self.assertIn("Add at least one job title", self.lines("Data Analyst", {})[1])
        self.assertFalse(self.lines("Data Analyst", {"work": {"titles": ["~("]}})[0]["kept"])   # a broken pattern never crashes


class Folder(unittest.TestCase):
    """A temporary Job Search folder with a copy of a test person's settings."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "Job Search"
        self.settings = self.root / "settings"
        shutil.copytree(PERSON / "settings", self.settings)
        p = json.loads((self.settings / "paths.json").read_text())
        p["bank_dir"] = str(self.root / "Evidence Bank")                      # the folder's own, so a saved resume lands in the temp folder
        p["keyword_groups"] = str((PERSON / "Evidence Bank" / "keyword-groups.json").resolve())
        p["data_dir"] = str(self.root / "data")
        (self.settings / "paths.json").write_text(json.dumps(p))
        self.saved = os.environ.get("KIT_SETTINGS_DIR")
        os.environ["KIT_SETTINGS_DIR"] = str(self.settings)
        import kit_settings
        kit_settings._cache.clear()
        self.env = dict(os.environ)
        self.env.pop("NOTION_TOKEN", None)

    def tearDown(self):
        os.environ.pop("KIT_SETTINGS_DIR", None) if self.saved is None else os.environ.__setitem__("KIT_SETTINGS_DIR", self.saved)
        import kit_settings
        kit_settings._cache.clear()
        shutil.rmtree(self.tmp)

    def cli(self, *args, code=0):
        r = subprocess.run([sys.executable, str(APP / "tracker_cli.py"), *args], env=self.env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, code, r.stderr)
        return json.loads(r.stdout)


class FollowSettings(Folder):
    def test_followed_closely_and_auto_follow_are_settings(self):
        a = setup_model.read_answers(self.settings)
        self.assertEqual(a["fields"]["watched"], [])
        self.assertTrue(a["fields"]["auto_follow"])                     # on unless the user turns it off
        a["fields"]["watched"] = ["Fernhollow Health", "fernhollow health", " Lumenfold "]
        a["fields"]["auto_follow"] = False
        setup_model.write_answers(self.settings, a)
        co = json.loads((self.settings / "companies.json").read_text())["ats_tools"]
        self.assertEqual(co["WATCHED_COMPANIES"], ["Fernhollow Health", "Lumenfold"])
        self.assertIs(json.loads((self.settings / "criteria.json").read_text())["agent"]["AUTO_FOLLOW"], False)
        b = setup_model.read_answers(self.settings)
        self.assertEqual((b["fields"]["watched"], b["fields"]["auto_follow"]), (["Fernhollow Health", "Lumenfold"], False))
        # an older page that doesn't send the two answers changes neither
        del b["fields"]["watched"], b["fields"]["auto_follow"]
        setup_model.write_answers(self.settings, b)
        c = setup_model.read_answers(self.settings)
        self.assertEqual((c["fields"]["watched"], c["fields"]["auto_follow"]), (["Fernhollow Health", "Lumenfold"], False))

    def test_follow_closely_from_the_companies_page(self):
        import wizard
        self.assertTrue(wizard.company_watch({"name": "Lumenfold, Inc.", "on": True})["ok"])
        self.assertTrue(wizard.company_watch({"name": "Lumenfold", "on": True})["ok"])       # the same company, once
        self.assertEqual(setup_model.read_answers(self.settings)["fields"]["watched"], ["Lumenfold"])
        self.assertTrue(wizard.company_watch({"name": "lumenfold", "on": False})["ok"])
        self.assertEqual(setup_model.read_answers(self.settings)["fields"]["watched"], [])
        self.assertFalse(wizard.company_watch({"name": " "})["ok"])

    def test_board_found_from_a_name_is_offered_not_saved(self):
        import wizard
        asked = []

        def probe(platform, slug):
            asked.append((platform, slug))
            return (12, ["Made-up Role One", "Made-up Role Two", "", "Made-up Role Three", "A fourth"]) if (platform, slug) == ("lever", "lumenfold") else None
        before = (self.settings / "companies.json").read_text()
        r = wizard.find_board_by_name({"name": "Lumenfold"}, probe=probe)
        self.assertEqual(r["board"], {"name": "Lumenfold", "platform": "lever", "slug": "lumenfold"})
        self.assertEqual((r["label"], r["count"], r["sample"]), ("Lever", 12, ["Made-up Role One", "Made-up Role Two", "Made-up Role Three"]))
        self.assertEqual(r["link"], "https://jobs.lever.co/lumenfold")
        self.assertIn(("smartrecruiters", "lumenfold"), asked + [("smartrecruiters", "lumenfold")])
        self.assertEqual((self.settings / "companies.json").read_text(), before)            # nothing saved until the user says yes
        self.assertIsNone(wizard.find_board_by_name({"name": "Nobody Co"}, probe=lambda p, s: None)["board"])
        self.assertFalse(wizard.find_board_by_name({"name": ""}, probe=probe)["ok"])
        self.assertEqual(wizard.board_link("smartrecruiters", "Lumenfold"), "https://jobs.smartrecruiters.com/Lumenfold")


class ResumeYouHave(Folder):
    def docx(self):
        import docx
        d = docx.Document()
        d.add_paragraph("DANA EXAMPLE")
        d.add_paragraph("Northfield Stores | Senior Data Analyst | 2021 - Present")
        d.add_paragraph("Rebuilt the weekly pricing report; store managers got it two days sooner.", style="List Bullet")
        d.add_paragraph("\u2022 Responsible for dashboards")
        f = self.tmp / "old resume.docx"
        d.save(str(f))
        return f

    def test_saved_in_the_folder_and_read_as_text(self):
        import wizard
        import read_resume
        self.assertEqual(wizard.resume_status(), {"saved": False, "name": ""})
        self.assertIsNone(read_resume.saved_copy())                                         # nothing saved yet
        raw = self.docx().read_bytes()
        r = wizard.resume_save({"name": "C:\\Users\\dana\\My Resume (final).docx", "data": base64.b64encode(raw).decode()})
        self.assertEqual(r, {"ok": True, "name": "My current resume.docx"})
        saved = self.root / "Evidence Bank" / "My current resume.docx"
        self.assertEqual(saved.read_bytes(), raw)
        self.assertEqual(wizard.resume_status(), {"saved": True, "name": "My current resume.docx"})
        self.assertEqual(read_resume.saved_copy(), saved)                                   # the reader finds the same copy
        self.assertIn("- Responsible for dashboards", read_resume.read(saved)[0])
        # a newer file replaces the copy (one copy, the newest)
        self.assertTrue(wizard.resume_save({"name": "resume.txt", "data": base64.b64encode(b"Dana Example\n- Did a thing").decode()})["ok"])
        self.assertEqual(sorted(p.name for p in (self.root / "Evidence Bank").glob("My current resume.*")), ["My current resume.txt"])
        for bad in ({"name": "resume.exe", "data": "QQ=="}, {"name": "resume.docx", "data": "not base64!"},
                    {"name": "resume.pdf", "data": ""}, {"name": "../../settings/app.json", "data": "QQ=="}):
            self.assertFalse(wizard.resume_save(bad)["ok"], bad)
        self.assertTrue((self.settings / "app.json").exists())
        self.assertFalse((self.root / "Evidence Bank" / "app.json").exists())

    def test_reader_marks_bullets_and_says_what_it_cannot_read(self):
        import read_resume
        lines, note = read_resume.read(self.docx())
        self.assertEqual(lines, ["DANA EXAMPLE", "Northfield Stores | Senior Data Analyst | 2021 - Present",
                                 "- Rebuilt the weekly pricing report; store managers got it two days sooner.",
                                 "- Responsible for dashboards"])
        self.assertEqual(note, "")
        t = self.tmp / "r.md"
        t.write_text("Dana Example\n\n* Cut report time in half\n\u2013 2019 to 2021\n")
        self.assertEqual(read_resume.read(t)[0], ["Dana Example", "- Cut report time in half", "- 2019 to 2021"])
        for bad, words in ((self.tmp / "none.docx", "no file"), (self.tmp / "r.pages", "can't read")):
            if bad.suffix == ".pages":
                bad.write_text("x")
            with self.assertRaises(ValueError) as e:
                read_resume.read(bad)
            self.assertIn(words, str(e.exception))
        broken = self.tmp / "broken.docx"
        broken.write_bytes(b"not a word file")
        with self.assertRaises(ValueError) as e:
            read_resume.read(broken)
        self.assertIn("paste the resume's text", str(e.exception))


class ResearchQueue(Folder):
    def test_order_and_what_is_shown(self):
        import tracker_cli
        rows = [{"name": "Quillco", "needs_research": True, "watched": False, "top_fit": True, "open_roles": 1, "apps": [], "board": {}},
                {"name": "Tessaway", "needs_research": False, "watched": True, "top_fit": True, "open_roles": 3, "apps": [], "board": {}},
                {"name": "Lumenfold", "needs_research": True, "watched": True, "top_fit": False, "open_roles": 0,
                 "apps": [{"role": "Made-up Role", "status": "Interested"}, {"role": "Old Role", "status": "Closed"}],
                 "board": {"url": "https://jobs.lever.co/lumenfold"}, "careers": "https://lumenfold.example.com/careers", "field": "Retail"},
                {"name": "Harborline", "needs_research": True, "watched": False, "top_fit": True, "open_roles": 4, "apps": [], "board": {}}]
        q = tracker_cli.research_queue(rows, limit=2)
        self.assertEqual(q["waiting"], 3)
        self.assertEqual([c["name"] for c in q["companies"]], ["Lumenfold", "Harborline"])   # followed closely first, then most open roles
        first = q["companies"][0]
        self.assertEqual((first["why"], first["roles"], first["job_board"]),
                         ("you follow it closely", ["Made-up Role"], "https://jobs.lever.co/lumenfold"))
        self.assertNotIn("notes", json.dumps(q).lower())

    def test_a_followed_company_waits_until_approved_research_is_saved(self):
        co = json.loads((self.settings / "companies.json").read_text())
        co["ats_tools"]["WATCHED_COMPANIES"] = ["Lumenfold"]
        (self.settings / "companies.json").write_text(json.dumps(co))
        q = self.cli("research-queue")
        self.assertEqual([c["name"] for c in q["companies"]], ["Lumenfold"])
        saved = self.cli("company", "--name", "Lumenfold", "--set", "posture=Remote-first", "--set", "risk=Low",
                         "--set", "pto=Flexible, 15 day minimum", "--set", "sources=company careers page; a news article",
                         "--set", "researched=2026-11-02")
        self.assertTrue(saved["ok"], saved)
        row = self.cli("company", "--name", "lumenfold")
        self.assertEqual((row["risk"], row["sources"], row["researched"], row["watched"]),
                         ("Low", "company careers page; a news article", "2026-11-02", True))
        self.assertEqual(row["verdict"], "Not reviewed yet")                                 # the verdict is the user's alone
        self.assertEqual(self.cli("research-queue")["waiting"], 0)
        self.assertFalse(self.cli("company", "--name", "Lumenfold", "--set", "researched=last week", code=1)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
