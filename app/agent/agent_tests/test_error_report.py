"""Error report: the saved report carries error lines and run facts only, with
email addresses, phone numbers, home folders, link paths, tokens, the user's
own name and contact line, and every tracker company and role scrubbed out;
it never carries INFO lines (so no posting titles), settings values, posting
text, file contents, or tracker rows; and the email step attaches the file
through the platform's mail app or falls back to a mailto draft. No network,
no mail app.
    python3 app/agent/agent_tests/test_error_report.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent
PERSON = KIT / "examples" / "priya-healthtech-pm"


class ErrorReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        s = cls.tmp / "settings"
        shutil.copytree(PERSON / "settings", s)
        p = json.loads((s / "paths.json").read_text())
        p["bank_dir"] = str((PERSON / "Evidence Bank").resolve())
        p["data_dir"] = str(cls.tmp / "data")
        (s / "paths.json").write_text(json.dumps(p))
        app = json.loads((s / "app.json").read_text())
        app["support_email"] = "builder@example.com"
        (s / "app.json").write_text(json.dumps(app))
        (cls.tmp / "master-selection.json").write_text(json.dumps(
            {"name": "PRIYA RAMAN", "contact": "Columbus, OH (Remote) | 555-0101 | priya.raman@example.com | linkedin.com/in/example-priya"}))
        data = cls.tmp / "data"
        data.mkdir()
        home = str(Path.home())
        (data / "tracker").mkdir()
        (data / "tracker" / "applications.json").write_text(json.dumps({"pages": {"p1": {"id": "p1", "properties": {
            "Role": {"type": "title", "title": [{"plain_text": "Director of Clinic Scheduling"}]},
            "Company": {"type": "rich_text", "rich_text": [{"plain_text": "Good Fit Clinics"}]},
            "Status": {"type": "status", "status": {"name": "Interested"}}}}}}))
        (data / "agent.log").write_text("\n".join(
            [f"INFO line {i}" for i in range(500)] +
            [f"INFO run started for Priya Raman in {home}/Documents/Job Search",
             "INFO new posting: Senior Product Manager, Patient Access at Riverside Health",
             "INFO fetched https://boards.example.com/jobs/12345?src=mail for Good Fit Clinics",
             "WARNING Board fetch slow for Good Fit Clinics (Director of Clinic Scheduling)",
             "ERROR Notion write failed: contact priya.raman@example.com or 555-0101 or (614) 555-0199",
             "ERROR request failed with Authorization: Bearer ntn_1234567890abcdefXYZ and NOTION_TOKEN=secret_abcdefghij",
             "Traceback (most recent call last):",
             '  File "job_search_agent.py", line 10, in run',
             "    posting_text = 'We are hiring a Senior Product Manager at Riverside Health'",
             "KeyError: 'Status'",
             "INFO run finished"]))
        (data / "alerts.jsonl").write_text(json.dumps({"time": "2026-10-31T08:00:00", "title": "Run failed", "message": "see log"}) + "\n")
        os.environ["KIT_SETTINGS_DIR"] = str(s)
        os.environ.pop("NOTION_TOKEN", None)
        sys.path.insert(0, str(APP))
        import kit_settings
        kit_settings._cache.clear()
        import error_report
        cls.er = error_report

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_report_is_scrubbed_and_bounded(self):
        report = self.er.save_report()
        self.assertTrue(report.exists())
        self.assertEqual(report.parent, self.tmp / "data")
        text = report.read_text()
        for leak in ("priya.raman@example.com", "555-0101", "555-0199", "PRIYA RAMAN", "Priya Raman", str(Path.home()),
                     "/jobs/12345", "builder@example.com",
                     "Good Fit Clinics", "Clinic Scheduling",              # tracker company and role
                     "Riverside Health", "Patient Access", "new posting",  # posting titles live in INFO lines
                     "ntn_1234567890abcdefXYZ", "secret_abcdefghij",       # tokens
                     "INFO line 499", "INFO run finished"):                # no INFO lines at all
            self.assertNotIn(leak, text, leak)
        self.assertIn("[email]", text)
        self.assertIn("[phone]", text)
        self.assertIn("[redacted]", text)
        self.assertIn("[secret]", text)
        self.assertIn("WARNING Board fetch slow", text)
        self.assertIn("Traceback", text)
        self.assertIn("KeyError", text)
        self.assertIn("Run failed", text)
        self.assertIn("Settings files present: app.json", text)
        self.assertNotIn("TITLE_KEYWORDS", text)         # no settings values
        self.assertNotIn("Synthetic test person", text)  # no file contents (the bank's first line)

    def test_scrub_handles_repr_paths_and_exception_payloads(self):
        s = self.er.scrub
        out = s(r"FileNotFoundError: [Errno 2] No such file: 'C:\\Users\\example\\Job Search\\Applications\\Acme Corp (drafting)\\posting.md'", home=r"C:\Users\example")
        self.assertNotIn("example", out)
        self.assertNotIn("Acme Corp", out)
        self.assertIn("FileNotFoundError: [message left out]", out)
        out = s("ValueError: invalid literal for int() with base 10: 'We are hiring a Senior Product Manager'", home="/Users/example")
        self.assertEqual(out, "ValueError: [message left out]")
        out = s("    raise KeyError('Status')  # fine", home="/Users/example")
        self.assertIn("raise KeyError", out)                 # only an exception *line* is trimmed, not code mentioning one
        out = s("  File \"C:\\\\Users\\\\example\\\\x.py\", line 3", home=r"C:\Users\example")
        self.assertNotIn("Users\\\\example", out)
        self.assertTrue(out.startswith('  File "~'), out)

    def test_email_attaches_or_falls_back(self):
        report = self.tmp / "data" / "r.txt"
        report.write_text("x")
        calls = []

        class R:
            returncode = 0

        def ok(cmd, **kw):
            calls.append((cmd, kw.get("env", {}))); return R()

        self.assertEqual(self.er.open_email(report, "builder@example.com", platform_name="win32", run=ok), "attached")
        cmd, env = calls[-1]
        self.assertIn("Outlook.Application", cmd[-1])
        self.assertNotIn("builder@example.com", cmd[-1])     # values travel in the environment, never in the script text
        self.assertEqual(env["KIT_TO"], "builder@example.com")
        self.assertEqual(env["KIT_REPORT"], str(report))
        self.assertEqual(self.er.open_email(report, "O'Brien <x@example.com>; Remove-Item C:\\", platform_name="darwin", run=ok), "attached")
        cmd, env = calls[-1]
        self.assertIn("osascript", cmd[0])
        self.assertNotIn("Remove-Item", cmd[-1])

        opened = []
        self.er.webbrowser.open = lambda link: opened.append(link)
        self.er._open_folder = lambda p: None

        def fail(cmd, **kw):
            raise OSError("no mail app")

        self.assertEqual(self.er.open_email(report, "builder@example.com", platform_name="win32", run=fail), "mailto")
        self.assertTrue(opened[-1].startswith("mailto:builder@example.com?subject="))
        self.assertIn("r.txt", opened[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
