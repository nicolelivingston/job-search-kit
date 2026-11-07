"""Kit platform support: Windows Task Scheduler XML and macOS launchd plists
are well formed and carry the right times, arguments, and missed-run
behavior; notifications build the right command on each platform and record
an alert for the tracker banner. Nothing is installed. No network.
    python3 app/agent/agent_tests/test_platform.py
"""
import json
import os
import plistlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
import schedule            # noqa: E402
import platform_support    # noqa: E402

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class Scheduler(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        p = mock.patch.object(schedule, "app_settings", return_value={})   # test the defaults
        p.start(); self.addCleanup(p.stop)

    def test_windows_xml(self):
        items = schedule.plan(platform="win32", python=r"C:\Kit\python\python.exe")
        self.assertEqual([n for n, _ in items], ["Job Search Kit (full)", "Job Search Kit (quick)", "Job Search Kit (update check)"])
        upd = ET.fromstring(items[2][1].replace('encoding="UTF-16"', ""))
        self.assertIn("updater.py", upd.find(".//t:Exec/t:Arguments", NS).text)   # the daily update check really is scheduled
        self.assertEqual([e.text[-8:] for e in upd.findall(".//t:CalendarTrigger/t:StartBoundary", NS)], ["09:30:00"])
        full = ET.fromstring(items[0][1].replace('encoding="UTF-16"', ""))
        starts = [e.text for e in full.findall(".//t:CalendarTrigger/t:StartBoundary", NS)]
        self.assertEqual([s[-8:] for s in starts], ["08:00:00"])
        self.assertEqual(full.find(".//t:StartWhenAvailable", NS).text, "true")
        args = full.find(".//t:Exec/t:Arguments", NS).text
        self.assertIn("PYTHONUTF8=1", args)
        self.assertIn(r"C:\Kit\python\python.exe", args)
        self.assertIn("agent.log", args)
        self.assertNotIn("--quick", args)
        quick = ET.fromstring(items[1][1].replace('encoding="UTF-16"', ""))
        self.assertEqual(len(quick.findall(".//t:CalendarTrigger", NS)), 4)
        self.assertIn("--quick", quick.find(".//t:Exec/t:Arguments", NS).text)

    def test_no_update_task_when_auto_update_is_off(self):
        from unittest import mock
        with mock.patch.object(schedule, "app_settings", return_value={"auto_update": False}):
            names = [n for n, _ in schedule.plan(platform="win32", python=r"C:\Kit\python\python.exe")]
        self.assertEqual(names, ["Job Search Kit (full)", "Job Search Kit (quick)"])

    def test_mac_plist(self):
        items = schedule.plan(platform="darwin", python="/usr/bin/python3")
        full = plistlib.loads(items[0][1].encode())
        self.assertEqual(full["Label"], "com.jobsearchkit.agent.full")
        self.assertEqual(full["StartCalendarInterval"], [{"Hour": 8, "Minute": 0}])
        self.assertTrue(full["ProgramArguments"][1].endswith("job_search_agent.py"))
        quick = plistlib.loads(items[1][1].encode())
        self.assertEqual(quick["ProgramArguments"][-1], "--quick")
        self.assertEqual([d["Hour"] for d in quick["StartCalendarInterval"]], [11, 14, 17, 20])
        upd = plistlib.loads(items[2][1].encode())
        self.assertEqual(upd["Label"], "com.jobsearchkit.agent.update-check")
        self.assertTrue(upd["ProgramArguments"][1].endswith("updater.py"))


class Notifications(unittest.TestCase):
    def test_commands(self):
        mac, _ = platform_support.notify_command("Title", 'Say "hi"', platform="darwin")
        self.assertEqual(mac[0], "osascript")
        self.assertIn('\\"hi\\"', mac[2])
        win, env = platform_support.notify_command("Title", "<b>x</b> & y", platform="win32")
        self.assertEqual(win[0], "powershell")
        self.assertEqual(env, {"KIT_TITLE": "Title", "KIT_MSG": "<b>x</b> & y"})   # escaped inside PowerShell
        self.assertIsNone(platform_support.notify_command("t", "m", platform="linux"))

    def test_alert_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            platform_support.record_alert("Job agent needs attention", "Run failed", d)
            line = json.loads((Path(d) / "alerts.jsonl").read_text().splitlines()[0])
            self.assertEqual(line["message"], "Run failed")


class Secrets(unittest.TestCase):
    def test_env_file_is_private_to_the_user(self):
        import stat
        import tempfile
        d = tempfile.mkdtemp()
        f = Path(d) / ".env"
        f.write_text("NOTION_TOKEN=secret_abcdefghijklmnop\n")
        self.assertEqual(platform_support.secure_private_file(f, platform="darwin"), "chmod600")
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        calls = []
        os.environ["USERNAME"] = "pat"
        platform_support.secure_private_file(f, run=lambda cmd, **k: calls.append(cmd), platform="win32")
        self.assertEqual(calls[0][:3], ["icacls", str(f), "/inheritance:r"])
        self.assertIn("pat:F", calls[0])
        self.assertEqual(platform_support.secure_private_file(Path(d) / "none", platform="darwin"), "missing")

    def test_tokens_never_reach_the_log(self):
        import io
        import logging
        token = "secret_abcdefghijklmnop"
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        log = logging.getLogger("kit.secret.test")
        log.setLevel(logging.INFO)
        log.addHandler(handler)
        log.addFilter(platform_support.SecretMask([token]))
        log.info("Notion rejected token %s with headers %s", token, {"Authorization": "Bearer " + token})
        log.error("raw " + token)
        handler.flush()
        self.assertNotIn(token, buf.getvalue())
        self.assertIn("[secret]", buf.getvalue())
        log.removeHandler(handler)


if __name__ == "__main__":
    unittest.main(verbosity=2)
