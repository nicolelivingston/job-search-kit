"""Synthetic test people (examples/): each one's postings score the way their
expected.json says (traps caught: missing skill or certification, too few
years, hybrid, on-call, contract, direct reports, office days over the
limit, hybrid or onsite outside the commute area; hybrid and onsite inside
it pass for the people who accept them); their master resume builds and passes the
pre-send gate clean; and a draft with planted problems (an invented bullet, an
interview-only bullet, a proposed bullet, retired wording) gets every one
flagged. Also checks that nothing from the personal system (company names, IDs,
contact details) appears anywhere in the kit. No network.
    python3 app/agent/agent_tests/test_personas.py
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
APP = AGENT.parent
KIT = APP.parent
EXAMPLES = sorted(p for p in (KIT / "examples").iterdir() if (p / "expected.json").exists())

SCORE = textwrap.dedent(r'''
    import sys, json, datetime
    from pathlib import Path
    root = Path(sys.argv[2]); sys.path.insert(0, sys.argv[1])
    import fit_scoring as fs, job_search_agent as jsa
    exp = json.loads((root / "expected.json").read_text())
    out = []
    for e in exp["postings"]:
        text = (root / "Applications" / e["folder"] / "posting.md").read_text()
        r = fs.score_posting(e["title"], text, salary_min=e["salary_min"], company_name=e["company"],
                             today=datetime.date(2026, 10, 31), age_days=3)
        job = {"title": e["title"], "location": "Remote (US)", "description": text, "salary_text": ""}
        out.append({"verdict": r["verdict"], "hard_skip": bool(r.get("hard_skip")), "reasons": r["reasons"], "missing": r["missing_minimums"],
                    "evidence": r["evidence"], "score": r["score"], "title_reject": jsa.get_rejection_reason(job),
                    "label": fs.label_reason(r, datetime.date(2026, 10, 31))})
    off = jsa.get_rejection_reason({"title": exp["off_title"], "location": "Remote (US)", "description": "", "salary_text": ""})
    locs = [[loc, jsa.location_rejection_reason(loc)] for loc, _ in exp["locations"]]
    print(json.dumps({"postings": out, "off": off, "locs": locs}))
''')


def env_for(settings):
    e = dict(os.environ, KIT_SETTINGS_DIR=str(settings))
    e.pop("NOTION_TOKEN", None)
    return e


class PersonaScoring(unittest.TestCase):
    def test_each_person(self):
        self.assertEqual(len(EXAMPLES), 3)
        for root in EXAMPLES:
            with self.subTest(person=root.name):
                r = subprocess.run([sys.executable, "-c", SCORE, str(AGENT), str(root)], capture_output=True,
                                   text=True, env=env_for(root / "settings"), timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                got = json.loads(r.stdout.strip().splitlines()[-1])
                exp = json.loads((root / "expected.json").read_text())
                self.assertTrue(got["off"], f"{exp['off_title']} should be rejected for {root.name}")
                for (loc, ok), (_, why) in zip(exp["locations"], got["locs"]):
                    self.assertEqual(why is None, ok, f"{root.name}: location {loc!r} -> {why}")
                for e, g in zip(exp["postings"], got["postings"]):
                    where = f"{root.name} / {e['folder']}"
                    self.assertIsNone(g["title_reject"], where)
                    self.assertEqual(bool(g.get("hard_skip")), e["skip"], f"{where}: verdict {g['verdict']} {g['reasons']}")
                    self.assertIn(g["verdict"], ("Strong fit", "Possible fit", "Poor fit"), where)
                    if e.get("reason_contains"):
                        self.assertTrue(any(e["reason_contains"].lower() in x.lower() for x in g["reasons"]), where)
                    for m in e.get("missing_contains", []):
                        self.assertTrue(any(x.startswith(m) for x in g["missing"]), f"{where}: {g['missing']}")
                    if e.get("missing") == []:
                        self.assertEqual(g["missing"], [], where)
                    if e.get("evidence_contains"):
                        self.assertIn(e["evidence_contains"], g["evidence"], where)
                first3 = got["postings"][:3]
                clean = [x for x in first3 if not x["missing"] and not x["hard_skip"]]
                self.assertEqual(first3[2]["score"], max(x["score"] for x in clean),
                                 f"{root.name}: the good fit should score highest of the clean postings")
                # v3.8: a posting missing one requirement may still outscore it (a
                # near miss at 80+ before the cap is Strong fit), but never silently:
                # its label names the gap.
                for x in first3:
                    if x["missing"] and x["score"] > first3[2]["score"]:
                        self.assertEqual(x["verdict"], "Strong fit", x)
                        self.assertIn("one gap to address", x["label"], x)


class PersonaResumes(unittest.TestCase):
    def run_py(self, script, settings, *args):
        return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True,
                              env=env_for(settings), timeout=170)

    def test_master_clean_and_traps_flagged(self):
        try:
            import docx  # noqa: F401
        except ImportError:
            self.skipTest("python-docx not installed")
        for root in EXAMPLES:
            with self.subTest(person=root.name), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / root.name
                shutil.copytree(root, work)
                settings = work / "settings"
                r = self.run_py(APP / "resume" / "bank_index.py", settings)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                sel = work / "master-selection.json"
                out = work / "master.docx"
                r = self.run_py(APP / "resume" / "build_resume.py", settings, sel, "--out", out, "--no-render")
                self.assertTrue(out.exists(), r.stdout + r.stderr)
                gate = self.run_py(APP / "resume" / "presend_gate.py", settings, out, "--selection", sel)
                self.assertIn("No mechanical flags", gate.stdout, gate.stdout[-3000:])
                # planted problems
                bank = (work / "Evidence Bank" / "Evidence Bank.md").read_text()
                line = lambda tag: next(l.split(":", 1)[1].strip() for l in bank.splitlines() if l.startswith("- E") and f"[{tag}]" in l)
                retired = (work / "settings" / "resume.json").read_text()
                retired_phrase = json.loads(retired)["presend_gate"]["RETIRED_PHRASES"][0]
                planted = {
                    "invented": "Built Kubernetes deployment pipelines that cut cloud costs for every product team.",
                    "interview-only": line("interview-only"),
                    "proposed": line("proposed"),
                    "retired": f"Partnered across teams and {retired_phrase} in one year.",
                }
                from docx import Document
                d = Document(str(out))
                bullets = [p for p in d.paragraphs if p._p.pPr is not None and p._p.pPr.numPr is not None]
                if not bullets:
                    bullets = [p for p in d.paragraphs if p.style.name.lower().startswith("list")]
                self.assertTrue(bullets, "no bullet paragraphs found in the built master")
                anchor = bullets[-1]
                for text in planted.values():
                    new = copy.deepcopy(anchor._p)
                    anchor._p.addnext(new)
                    from docx.text.paragraph import Paragraph
                    para = Paragraph(new, anchor._parent)
                    for run in para.runs[1:]:
                        run._r.getparent().remove(run._r)
                    para.runs[0].text = text
                trap = work / "trap.docx"
                d.save(str(trap))
                g = self.run_py(APP / "resume" / "presend_gate.py", settings, trap, "--selection", sel).stdout
                self.assertIn("line not produced by", g)
                self.assertIn("untraced bullet", g, g[-3000:])
                self.assertIn("is interview-only", g)
                self.assertIn("is proposed", g)
                self.assertIn("[2 retired]", g)


class NoLeaks(unittest.TestCase):
    """Nothing personal in the public kit. Two layers:
    - always: the author's name words appear nowhere except LICENSE and the release repo URL;
      no email addresses outside documented placeholders; no phone numbers outside 555 examples;
      no 32-hex IDs (Notion); no /Users/<name> or C:\\Users\\<name> paths
    - with dev-settings/leak-markers.json (the maintainer's machine only): every marker
      (company names, IDs, contact details) appears in no tracked or untracked kit file
    The pre-commit and pre-push hooks (dev/install_hooks.sh) run this plus a full-history scan.
    """
    AUTHOR_WORDS = ("nic" + "ole", "living" + "ston")   # joined so this file passes its own check
    ALLOWED_AUTHOR_FILES = {"LICENSE"}
    ALLOWED_AUTHOR_TEXT = ("github.com/nicolelivingston/job-search-kit", "nicolelivingston/job-search-kit")
    EMAIL_OK = ("example.com", "users.noreply.github.com", "linkedin.com", "you@gmail.com", "vtext.com")

    def _files(self):
        tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=KIT,
                                 capture_output=True, text=True).stdout.splitlines()
        for rel in tracked:
            if rel.startswith("dev-settings/") or rel.startswith("dev/") or rel in ("HANDOFF.md", "PORT-LOG.md", "SOURCE_COMMIT"):
                continue   # builder files that never go in the public repo (.gitignore)
            f = KIT / rel
            if f.is_file() and f.suffix.lower() not in (".png", ".ico", ".docx", ".pyc"):
                yield rel, f.read_text(encoding="utf-8", errors="ignore")

    def test_author_name_only_in_license_and_repo_url(self):
        import re
        bad = []
        for rel, text in self._files():
            if rel in self.ALLOWED_AUTHOR_FILES:
                continue
            scrubbed = text
            for ok in self.ALLOWED_AUTHOR_TEXT:
                scrubbed = scrubbed.replace(ok, "")
            for w in self.AUTHOR_WORDS:
                if re.search(r"(?<![A-Za-z0-9])" + w + r"(?![A-Za-z0-9])", scrubbed, re.I):
                    bad.append((rel, w))
        self.assertEqual(bad, [])

    def test_no_contact_details_or_ids(self):
        import re
        hits = []
        for rel, text in self._files():
            for m in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
                if not m.lower().endswith(self.EMAIL_OK):
                    hits.append((rel, m))
            for m in re.findall(r"(?<!\d)\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", text):
                if "555" not in m:
                    hits.append((rel, m))
            for m in re.findall(r"(?<![0-9a-fA-F])[0-9a-f]{32}(?![0-9a-fA-F])", text):
                hits.append((rel, m))
            for m in re.findall(r"(?:/Users/|[A-Za-z]:\\Users\\)(?!<)[A-Za-z0-9_.-]+", text):
                if m.split("Users")[-1].strip("/\\").lower() not in ("example", "you", "me"):
                    hits.append((rel, m))
        self.assertEqual(hits, [])

    def test_examples_and_templates_carry_nothing_personal(self):
        markers_file = KIT / "dev-settings" / "leak-markers.json"
        if not markers_file.exists():
            self.skipTest("no dev-settings/leak-markers.json on this machine")
        import re
        markers = json.loads(markers_file.read_text())
        hits = []
        for rel, text in self._files():
            if rel in self.ALLOWED_AUTHOR_FILES:
                continue
            scrubbed = text
            for ok in self.ALLOWED_AUTHOR_TEXT:
                scrubbed = scrubbed.replace(ok, "")
            for m in markers:
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(m) + r"(?![A-Za-z0-9])", scrubbed, re.I):
                    hits.append((rel, m))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
