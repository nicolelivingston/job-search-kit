"""Resume tools: the bank index marks template placeholders so they never
reach paper, the scripts read the user's bank from settings before any bank
beside the kit, and the cover letter source check counts real sources only
(a template instruction key such as `_rule` is not a source). No network.
    python3 app/agent/agent_tests/test_resume_tools.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent
PERSON = KIT / "examples" / "priya-healthtech-pm"
os.environ.setdefault("KIT_SETTINGS_DIR", str(PERSON / "settings"))
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "resume"))
import bank_index      # noqa: E402
import presend_gate    # noqa: E402


class ResumeTools(unittest.TestCase):
    def test_template_placeholders_never_paper(self):
        entries = bank_index.parse(KIT / "templates" / "Evidence Bank" / "Evidence Bank.md")
        self.assertTrue(entries)
        for e in entries:
            self.assertEqual(e["status"], "placeholder", e["id"])
            self.assertFalse(e["on_paper_ok"], e["id"])

    def test_filled_lines_keep_their_status(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "bank.md"
            b.write_text("## E01 Story\n- E01.1 [primary]: Shipped the thing; it worked.\n"
                         "- E01.2 [proposed]: <not written yet>\n", encoding="utf8")
            got = {e["id"]: e["status"] for e in bank_index.parse(b)}
        self.assertEqual(got, {"E01.1": "primary", "E01.2": "placeholder"})

    def test_settings_bank_comes_first(self):
        import kit_settings
        want = kit_settings.bank_dir()
        self.assertEqual(bank_index.BANK_DIR_CANDIDATES[0], want)
        self.assertEqual(presend_gate.INDEX_CANDIDATES[0], want / "bank-index.json")

    def test_letter_rule_key_is_not_a_source(self):
        body = "This paragraph is long enough to count as a body paragraph of the letter, surely."
        paras = [(body, None)] * 4
        with tempfile.TemporaryDirectory() as d:
            sel = {"letter_sources": {"_rule": "One entry per paragraph.", "p1": "E01", "p2": "E02", "p3": "E03"}}
            (Path(d) / "selection-2026-11-01.json").write_text(json.dumps(sel))
            letter = Path(d) / "A_B_CoverLetter_X_v1.docx"
            flags, _ = presend_gate.letter_sources_check(letter, paras)
            self.assertTrue(any("4 body paragraphs but letter_sources lists 3" in f for f in flags), flags)
            sel["letter_sources"]["p4"] = "You, 2026-11-01: my words"
            (Path(d) / "selection-2026-11-01.json").write_text(json.dumps(sel))
            flags, notes = presend_gate.letter_sources_check(letter, paras)
            self.assertEqual(flags, [])
            self.assertIn("4 sourced", notes[0])


class TailoredTrace(unittest.TestCase):
    """A tailored resume is checked line by line against its selection file,
    role history and tools come from the bank, card tier limits hold, and a
    cover letter builds in the resume's format."""

    @classmethod
    def setUpClass(cls):
        try:
            import docx  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("python-docx not installed")
        import shutil
        cls.tmp = tempfile.mkdtemp()
        cls.work = Path(cls.tmp) / "p"
        shutil.copytree(PERSON, cls.work)
        cls.env = dict(os.environ, KIT_SETTINGS_DIR=str(cls.work / "settings"))
        cls.run_py(APP / "resume" / "bank_index.py")
        cls.index = {e["id"]: e for e in json.loads((cls.work / "Evidence Bank" / "bank-index.json").read_text())["entries"]}
        cls.limited = [i for i, e in cls.index.items() if e.get("tiers") and 1 not in e["tiers"] and e["on_paper_ok"]]
        cls.folder = cls.work / "Applications" / "Acme (drafting)"
        cls.folder.mkdir(parents=True)
        base = json.loads((cls.work / "master-selection.json").read_text())
        for r in base["roles"]:
            for g in r.get("groups", []):
                g["bullets"] = [b for b in g["bullets"] if b not in cls.limited]
        base.update(output="Test_Person_Resume_Acme_PM_2026-11-01_v1.docx", tier=1, master=False)
        # the posting map (gate item 14): themes in the posting's order, answered by the page's groups
        groups = base["roles"][0].get("groups", [])
        notes = base.get("notes") if isinstance(base.get("notes"), dict) else {}
        notes["posting_map"] = [{"rank": i + 1, "ask": f"theme {i + 1}", "answer": g.get("label", "").rstrip(":"),
                                 "ids": g.get("bullets", [])[:1]} for i, g in enumerate(groups[:3])]
        base["notes"] = notes
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp)

    @classmethod
    def run_py(cls, script, *args):
        import subprocess
        return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True,
                              env=cls.env, timeout=170)

    def gate(self, sel, edit=None):
        import copy as _c
        sel = _c.deepcopy(sel)
        (self.folder / "selection-2026-11-01.json").write_text(json.dumps(sel))
        r = self.run_py(APP / "resume" / "build_resume.py", self.folder / "selection-2026-11-01.json", "--no-render")
        out = self.folder / sel["output"]
        if r.returncode:
            return r
        if edit:
            from docx import Document
            d = Document(str(out))
            edit(d)
            d.save(str(out))
        return self.run_py(APP / "resume" / "presend_gate.py", out)

    def test_clean_tailored_page(self):
        self.assertTrue(self.limited, "the test person should have a tier-limited card")
        g = self.gate(self.base).stdout
        self.assertIn("No mechanical flags", g, g[-2500:])
        self.assertIn("every line checked against", g)

    def test_typed_and_invented_lines_flag(self):
        import copy as _c
        cases = {
            "profile is typed": dict(profile="Fifteen years leading 40 product managers."),
            "tools not in A.tools": dict(tools={"text": "Jira, SQL"}),
            "is typed in": dict(roles=[{**self.base["roles"][0], "id": None, "employer": "Example Company",
                                        "title": "Director of Product | Remote", "dates": "Jan 2015 - Present"}]),
            "has no card behind it": dict(profile={"id": "A.profile", "bridge": "Ships clinic tools."}),
        }
        for want, change in cases.items():
            with self.subTest(want=want):
                sel = {**_c.deepcopy(self.base), **change}
                g = self.gate(sel)
                self.assertIn(want, g.stdout + g.stderr, (g.stdout + g.stderr)[-2500:])
        sel = _c.deepcopy(self.base)
        sel["roles"][0]["groups"][0]["label"] = "Grew revenue 300%:"
        self.assertIn("group label has a figure", self.gate(sel).stdout)

    def test_hand_edit_flags(self):
        def edit(d):
            p = next(p for p in d.paragraphs if len(p.text) > 80 and p.style.name == "Normal")
            p.runs[0].text = p.runs[0].text + " Led 40 product managers."
        g = self.gate(self.base, edit).stdout
        self.assertIn("line not produced by", g, g[-2500:])

    def test_tier_limit_refused(self):
        import copy as _c
        sel = _c.deepcopy(self.base)
        sel["roles"][0]["groups"][0]["bullets"].append(self.limited[0])
        r = self.gate(sel)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("limited to tier", r.stdout + r.stderr)
        sel["tier"] = None
        self.assertIn("has no tier", self.gate(_c.deepcopy({**self.base, "tier": None})).stdout)

    def test_cover_letter_builds_and_gates(self):
        import copy as _c
        sel = _c.deepcopy(self.base)
        sel["letter_sources"] = {"_rule": "one per paragraph", "p1": "E01", "p2": "E02", "p3": "You, 2026-11-01: my words"}
        (self.folder / "selection-2026-11-01.json").write_text(json.dumps(sel))
        body = "This sentence is long enough to count as one body paragraph in the letter for the check."
        (self.folder / "letter.md").write_text("Dear Hiring Team,\n\n" + "\n\n".join([body] * 3) + "\n\nThank you,\nTest Person\n")
        r = self.run_py(APP / "resume" / "build_letter.py", self.folder / "selection-2026-11-01.json",
                        self.folder / "letter.md", "--no-render")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.folder / "Test_Person_CoverLetter_Acme_PM_2026-11-01_v1.docx"
        self.assertTrue(out.exists())
        g = self.run_py(APP / "resume" / "presend_gate.py", out).stdout
        self.assertIn("3 sourced paragraph", g, g[-2500:])
        self.assertNotIn("no 20 pt", g)

    def test_dry_run_holes_closed(self):
        """Nov 1, 2026 dry run: each of these gated clean before."""
        import copy as _c
        b = self.base
        cases = {
            "placeholder left on the page": dict(name="<YOUR NAME>"),
            "has no name": dict(name=""),
            "contact line reads like a claim": dict(contact="Remote | Led 40 product managers for 15 years"),
            "a banner is typed text": dict(banner="Award-winning leader"),
            "core expertise terms not in A.core": dict(core_expertise="Quantum Strategy • Moonshots"),
            "the bridge sentence has a figure": dict(profile={"id": "A.profile", "bridge": "Doubled clinic throughput."},
                                                     notes={"bridge_source": "E01"}),
            "more than one short sentence": dict(profile={"id": "A.profile", "bridge": "Ships clinic tools. Loves it."},
                                                 notes={"bridge_source": "E01"}),
            "notes must be a set of named fields": dict(notes="all good"),
            "tier is written as text": dict(tier="1"),
            "the same bullet ID is used twice": dict(roles=[{**b["roles"][0], "groups": [
                {"label": "Work:", "bullets": ["E01.1", "E01.1"]}]}]),
        }
        for want, change in cases.items():
            with self.subTest(want=want):
                g = self.gate({**_c.deepcopy(b), **change})
                self.assertIn(want, g.stdout + g.stderr, (g.stdout + g.stderr)[-2500:])
        sel = _c.deepcopy(b)
        sel["roles"][0]["groups"][0]["label"] = "Three launches:"
        self.assertIn("group label has a figure", self.gate(sel).stdout)
        if self.limited:
            card = self.limited[0].split(".")[0]
            sel = {**_c.deepcopy(b), "profile": {"id": "A.profile", "bridge": "Ships clinic tools."},
                   "notes": {"bridge_source": card}}
            self.assertIn("bridge rests on card(s) limited", self.gate(sel).stdout)
        # a master marker in the file name no longer turns off the tier check
        self.assertIn("has no tier", self.gate({**_c.deepcopy(b), "tier": None,
                                                 "output": "Test_Person_Resume_Mastercard_PM_2026-11-01_v1.docx"}).stdout)

    def test_hidden_and_reordered_text_flags(self):
        from docx.oxml import parse_xml
        W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        def tracked(d):
            p = d.paragraphs[-1]._p
            p.append(parse_xml(f'<w:ins {W} w:id="1" w:author="x"><w:r><w:t> Led 40 people.</w:t></w:r></w:ins>'))
        g = self.gate(self.base, tracked).stdout
        self.assertIn("TRACKED CHANGES", g)
        self.assertIn("line not produced by", g)
        def control(d):
            d.element.body.insert(0, parse_xml(f'<w:sdt {W}><w:sdtContent><w:p><w:r><w:t>Award winner</w:t></w:r></w:p></w:sdtContent></w:sdt>'))
        g = self.gate(self.base, control).stdout
        self.assertIn("CONTENT CONTROL", g)
        self.assertIn("Award winner", g)
        def dupe(d):
            import copy as _c
            p = next(p for p in d.paragraphs if p.style.name.startswith("List"))
            p._p.addnext(_c.deepcopy(p._p))
        self.assertIn("appears 2 times", self.gate(self.base, dupe).stdout)

    def test_retired_wording_flags_inside_approved_bullets(self):
        bullet = self.index[self.base["roles"][0]["groups"][0]["bullets"][0]]["text"]
        phrase = " ".join(bullet.split()[:4])
        log = self.work / "Evidence Bank" / "Retired Claims Log.md"
        old = log.read_text()
        try:
            log.write_text(old + f'\n| 2026-11-01 | "{phrase}" | retired | "use this instead, a cleared phrase" |\n')
            g = self.gate(self.base).stdout
            self.assertIn("[2 retired]", g, g[-2500:])
            self.assertNotIn("use this instead", g)
        finally:
            log.write_text(old)

    def test_builder_shapes(self):
        import copy as _c
        sel = _c.deepcopy(self.base)
        sel["tools"] = {"text": "A.tools"}
        sel.pop("credentials", None)
        (self.folder / "selection-2026-11-01.json").write_text(json.dumps(sel))
        r = self.run_py(APP / "resume" / "build_resume.py", self.folder / "selection-2026-11-01.json", "--no-render")
        self.assertEqual(r.returncode, 0, r.stderr)
        from docx import Document
        texts = [p.text for p in Document(str(self.folder / sel["output"])).paragraphs]
        self.assertNotIn("A.tools", texts)
        self.assertNotIn("Credentials", texts)
        sel["roles"][0]["groups"][0].pop("label")
        (self.folder / "selection-2026-11-01.json").write_text(json.dumps(sel))
        r = self.run_py(APP / "resume" / "build_resume.py", self.folder / "selection-2026-11-01.json", "--no-render")
        self.assertIn("needs a \"label\"", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_letter_sources_resolve_and_figures_trace(self):
        import copy as _c
        sel = _c.deepcopy(self.base)
        sel["letter_sources"] = {"p1": "E99", "p2": "E01", "p3": "You, 2026-11-01: my words"}
        if self.limited:
            sel["letter_sources"]["p2"] = self.limited[0].split(".")[0]
        (self.folder / "selection-2026-11-01.json").write_text(json.dumps(sel))
        body = "This sentence is long enough to count as one body paragraph in the letter for the check."
        letter = ["Dear Hiring Team,", body, "I cut wait times 37% and doubled throughput.", body, "Thank you,", "Test Person"]
        (self.folder / "letter.md").write_text("\n\n".join(letter))
        r = self.run_py(APP / "resume" / "build_letter.py", self.folder / "selection-2026-11-01.json",
                        self.folder / "letter.md", "--no-render")
        self.assertEqual(r.returncode, 0, r.stderr)
        g = self.run_py(APP / "resume" / "presend_gate.py", self.folder / "Test_Person_CoverLetter_Acme_PM_2026-11-01_v1.docx").stdout
        self.assertIn("E99, which isn't in the bank", g, g[-2500:])
        self.assertIn("not in bank Part C: 37%", g)
        self.assertIn("figures in words", g)
        self.assertIn("3 sourced", g)   # the short third paragraph counts as a body paragraph now
        if self.limited:
            self.assertIn("limited to other tiers", g)

    def test_tier_lines_parse_strictly(self):
        ok = {"all": [1, 2, 3], "1, 2": [1, 2], "2 and 3 only": [2, 3], "<all | 2, 3>": None}
        for raw, want in ok.items():
            self.assertEqual(bank_index.parse_tier(raw, "E01"), want, raw)
        for raw in ("not 1", "except 3", "", "most"):
            with self.assertRaises(SystemExit, msg=raw):
                bank_index.parse_tier(raw, "E01")
        with tempfile.TemporaryDirectory() as d:
            bk = Path(d) / "bank.md"
            bk.write_text("## E01 Story\nStatus: shipped | Role: my call\nTier: 2\n- E01.1 [primary]: Did it.\n", encoding="utf8")
            with self.assertRaises(SystemExit):
                bank_index.parse(bk)
            bk.write_text("## E01 Story\n**Status:** shipped | **Tier:** 2, 3\n- E01.1 [primary] [superseded]: Did it.\n", encoding="utf8")
            e = bank_index.parse(bk)[0]
            self.assertEqual((e["tiers"], e["status"], e["on_paper_ok"]), ([2, 3], "superseded", False))


class PageRules(unittest.TestCase):
    def test_limit_comes_from_settings(self):
        f, _ = presend_gate.page_rules(2, 0.3, False, limit=1, fill_limit=0.75)
        self.assertTrue(any("resumes stay at one page" in x for x in f), f)
        f, _ = presend_gate.page_rules(1, 0.9, False, limit=1, fill_limit=0.75)
        self.assertTrue(any("page 1 is 90% full" in x for x in f), f)
        f, _ = presend_gate.page_rules(2, 0.7, False, limit=2, fill_limit=0.75)
        self.assertEqual(f, [])
        f, _ = presend_gate.page_rules(4, 0.9, True, limit=2, fill_limit=0.75)
        self.assertEqual(f, [])   # the master has no page limit
        self.assertEqual((presend_gate.PAGE_LIMIT, presend_gate.LAST_PAGE_FILL_LIMIT), (2, 0.75))


class CheckGroups(unittest.TestCase):
    def test_good_and_broken_groups(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "p"
            shutil.copytree(PERSON, work)
            env = dict(os.environ, KIT_SETTINGS_DIR=str(work / "settings"))
            cli = [sys.executable, str(APP / "tracker_cli.py"), "check-groups"]
            r = subprocess.run(cli, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            kg = work / "Evidence Bank" / "keyword-groups.json"
            data = json.loads(kg.read_text())
            data["fit_scoring"]["WORK_FAMILIES"][0]["$tuple"].pop(1)
            kg.write_text(json.dumps(data))
            r = subprocess.run(cli, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.returncode, 1)
            self.assertIn("needs 4 parts", r.stdout)
            kg.write_text(kg.read_text() + ",")
            r = subprocess.run(cli, capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.returncode, 1)
            self.assertIn("don't load", r.stdout)



if __name__ == "__main__":
    unittest.main(verbosity=2)
