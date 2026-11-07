"""Setup wizard and tracker page: the local server serves the page, saves
setup answers into the settings files, saves Advanced values, scores a
pasted posting into the built-in tracker, updates a row's status and the
user's call, keeps contacts, finds a job board from a careers link, and
refuses requests from other websites: no per-launch key, a Host header that
isn't 127.0.0.1:<port> (DNS rebinding), or a foreign Origin. Links in the
tracker are http(s) only and Add a Posting refuses private addresses and
connects only to the address it checked. Runs the server for real on
127.0.0.1 against a temporary copy of a test person's settings. No network.
    python3 app/agent/agent_tests/test_wizard.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent
PERSON = KIT / "examples" / "priya-healthtech-pm"


class Wizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        s = Path(cls.tmp) / "settings"
        shutil.copytree(PERSON / "settings", s)
        p = json.loads((s / "paths.json").read_text())
        p["bank_dir"] = str((PERSON / "Evidence Bank").resolve())
        p["data_dir"] = str(Path(cls.tmp) / "data")
        (s / "paths.json").write_text(json.dumps(p))
        cls.settings, cls.data = s, Path(cls.tmp) / "data"
        import socket
        with socket.socket() as so:
            so.bind(("127.0.0.1", 0)); cls.port = so.getsockname()[1]
        env = dict(os.environ, KIT_SETTINGS_DIR=str(s), KIT_CONFIG_DIR=str(Path(cls.tmp) / "config"))
        env.pop("NOTION_TOKEN", None)
        cls.proc = subprocess.Popen([sys.executable, str(APP / "wizard.py"), "--no-browser", "--port", str(cls.port)],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = cls.proc.stdout.readline()           # "Job Search Kit is open at http://127.0.0.1:PORT/?t=TOKEN#setup ..."
        cls.token = line.split("?t=", 1)[1].split("#", 1)[0]
        for _ in range(50):
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{cls.port}/api/status", headers={"X-Kit-Token": cls.token})
                urllib.request.urlopen(req, timeout=1); break
            except Exception:
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(5)
        shutil.rmtree(cls.tmp)

    def call(self, path, body=None, origin=None, token=None, host=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        headers = {"Content-Type": "application/json", "X-Kit-Token": self.token if token is None else token}
        if origin:
            headers["Origin"] = origin
        if host:
            headers["Host"] = host
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw.decode())
        except urllib.error.HTTPError as e:
            raw = e.read() or b"{}"
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")

    def test_1_page_and_status(self):
        code, page = self.call("/?t=" + self.token, token="")
        self.assertEqual(code, 200)
        self.assertIn("Job Search Kit", page)
        self.assertNotIn("—", page)   # no em dashes in what the user reads
        for needle in ("What stays here, what goes to Claude", "What you promise", "answer honestly",
                       "Every bullet on your resume is true", "connects to no email account"):
            self.assertIn(needle, page, needle)   # the plain-language privacy and honesty page
        code, st = self.call("/api/status")
        self.assertTrue(st["configured"])

    def test_2_answers_saved(self):
        _, a = self.call("/api/answers")
        a["pay"]["floor"] = 141000
        a["rules"]["direct_reports_ok"] = True
        a["where"].update(mode="remote_or_hybrid", commute_areas=["Columbus"], max_office_days=2)
        code, r = self.call("/api/answers", a)
        self.assertEqual((code, r.get("ok")), (200, True), r)
        c = json.loads((self.settings / "criteria.json").read_text())
        self.assertEqual(c["fit_scoring"]["PAY_HARD_FLOOR"], 141000)
        self.assertEqual(c["fit_scoring"]["WORK_ARRANGEMENT"]["commute_areas"], ["columbus"])
        self.assertNotIn("people-manager", [h["$tuple"][0] for h in c["fit_scoring"]["HARD_RULES"]])
        _, back = self.call("/api/answers")
        self.assertEqual(back["pay"]["floor"], 141000)

    def test_2b_preferences_step(self):
        _, a = self.call("/api/answers")
        a["prefs"]["tools"] = ["Excel", "Jira"]
        a["prefs"]["voice"]["avoid_habits"] = ["em_dash"]
        a["prefs"]["permissions"]["update_tracker"] = "ask"
        code, r = self.call("/api/answers", a)
        self.assertEqual((code, r.get("ok")), (200, True), r)
        p = json.loads((self.settings / "preferences.json").read_text())
        self.assertEqual((p["tools"], p["permissions"]["update_tracker"]), (["Excel", "Jira"], "ask"))
        self.assertIs(json.loads((self.settings / "resume.json").read_text())["presend_gate"]["FLAG_EM_DASH"], True)
        page = (APP / "wizard_page.html").read_text(encoding="utf-8")
        self.assertIn('custom:"prefs"', page)
        self.assertNotIn("\u2014", page, "no em dashes on the page")

    def test_3_advanced(self):
        code, r = self.call("/api/advanced", {"agent.FRESH_DAYS": "21"})
        self.assertTrue(r["ok"])
        _, v = self.call("/api/advanced")
        self.assertEqual(v["agent.FRESH_DAYS"], 21)

    def test_4_tracker_add_update(self):
        text = ("Remote (US). Own clinic scheduling and front desk workflow. Requirements: 4+ years of product "
                "management. Base salary $150,000 to $170,000.")
        code, r = self.call("/api/tracker/add", {"title": "Product Manager, Scheduling", "company": "ClinicFlow (example)", "text": text})
        self.assertTrue(r.get("ok"), r)
        self.assertIn(r["tier"], "ABC")
        _, t = self.call("/api/tracker")
        row = next(x for x in t["rows"] if x["Company"] == "ClinicFlow (example)")
        self.assertEqual(row["Status"], "Interested")
        self.assertEqual(row["Base Salary"], 150000)
        code, r = self.call("/api/tracker/update", {"id": row["id"], "status": "Applied", "verdict": "Applying"})
        self.assertTrue(r["ok"])
        _, t = self.call("/api/tracker")
        row = next(x for x in t["rows"] if x["id"] == row["id"])
        self.assertEqual((row["Status"], row["Overall Verdict"]), ("Applied", "Applying"))
        self.assertTrue(row["Date Applied"])
        _, r = self.call("/api/tracker/add", {"title": "Senior PM", "company": "X", "text": "Hybrid: 4 days per week in our Boston office."})
        self.assertEqual((r["verdict"], r["hard_skip"]), ("Poor fit", True))
        _, r = self.call("/api/tracker/add", {"title": "Senior PM", "company": "X", "text": "Location: Remote (US)\nOwn the roadmap. Base $150,000 to $170,000."})
        self.assertFalse(r["hard_skip"])
        _, t = self.call("/api/tracker")
        self.assertEqual(next(x for x in t["rows"] if x["id"] == r["id"])["Remote Status"], "Fully Remote")
        _, r = self.call("/api/tracker/add", {})
        self.assertFalse(r["ok"])

    def test_4b_statuses_new_tag_and_drawer_fields(self):
        _, t = self.call("/api/tracker")
        self.assertEqual(t["statuses"], ["Interested", "Drafting Resume", "Applied", "Interviewing", "Offer", "Closed", "Rejected"])
        self.assertEqual([g for g, _ in t["groups"]], ["To Do", "In Progress", "Complete"])
        # a posting the daily check added is New until opened; one the user added never is
        self.assertFalse(any(r["is_new"] for r in t["rows"] if r["Source"] == "Added by you"))
        f = self.data / "tracker" / "applications.json"
        apps = json.loads(f.read_text())
        src = next(iter(apps["pages"].values()))
        from datetime import datetime, timezone
        new = json.loads(json.dumps(src)); new["id"] = "daily-check-row"
        new["created_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        new["properties"]["Source"] = {"type": "select", "select": {"name": "Greenhouse"}}
        new["properties"]["Status"] = {"type": "status", "status": {"name": "Interested"}}
        new["properties"].pop("Opened", None)
        apps["pages"]["daily-check-row"] = new
        f.write_text(json.dumps(apps))
        _, t = self.call("/api/tracker")
        row = next(r for r in t["rows"] if r["id"] == "daily-check-row")
        self.assertTrue(row["is_new"]); self.assertGreaterEqual(t["new_count"], 1)
        self.assertTrue(self.call("/api/tracker/update", {"id": "daily-check-row", "opened": True})[1]["ok"])
        _, t = self.call("/api/tracker")
        self.assertFalse(next(r for r in t["rows"] if r["id"] == "daily-check-row")["is_new"])
        # the edit panel's fields
        _, r = self.call("/api/tracker/update", {"id": "daily-check-row", "status": "Rejected", "follow_up": "2026-11-07",
                                                 "applied": "2026-10-20", "versions": "2", "next": "Thank-you note", "notes": "n"})
        self.assertTrue(r["ok"], r)
        _, t = self.call("/api/tracker")
        row = next(r for r in t["rows"] if r["id"] == "daily-check-row")
        self.assertEqual((row["Status"], row["Follow-up Date"], row["Date Applied"], row["Resume Versions"], row["Next Step"], row["Outcome Type"]),
                         ("Rejected", "2026-11-07", "2026-10-20", 2, "Thank-you note", "Rejected"))
        self.assertFalse(self.call("/api/tracker/update", {"id": "daily-check-row", "status": "Maybe"})[1]["ok"])
        self.assertFalse(self.call("/api/tracker/update", {"id": "daily-check-row", "follow_up": "next week"})[1]["ok"])
        self.assertFalse(self.call("/api/tracker/update", {"id": "daily-check-row", "versions": "two"})[1]["ok"])

    def test_4c_companies(self):
        _, c = self.call("/api/companies")
        cf = next(x for x in c["rows"] if x["name"] == "ClinicFlow (example)")   # from the daily check, or a board in setup
        self.assertEqual(cf["board"]["label"], "Greenhouse")
        self.assertEqual(cf["board"]["url"], "https://job-boards.greenhouse.io/clinicflow-example")
        _, r = self.call("/api/companies/save", {"name": "Contoso Care (example)"})
        self.assertTrue(r["ok"], r)
        cid = r["id"]
        self.assertFalse(self.call("/api/companies/save", {"name": "contoso care (example)"})[1]["ok"])   # no duplicates
        _, r = self.call("/api/companies/save", {"id": cid, "posture": "Fully remote", "verdict": "Not a fit", "risk": "High",
                                                 "health": "2", "glassdoor": "4.1", "match": "5%", "growth": "Growing",
                                                 "green": "Remote since founding", "pto_weak": True, "careers": "https://careers.example.com/contoso"})
        self.assertTrue(r["ok"], r)
        _, c = self.call("/api/companies")
        row = next(x for x in c["rows"] if x["id"] == cid)
        self.assertEqual((row["posture"], row["verdict"], row["risk"], row["health"], row["glassdoor"], row["match"], row["growth"], row["pto_weak"]),
                         ("Fully remote", "Not a fit", "High", 2.0, 4.1, 5.0, "Growing", True))
        # stored in the values fit scoring already reads
        page = json.loads((self.data / "tracker" / "companies.json").read_text())["pages"][cid]["properties"]
        self.assertEqual(page["Remote Posture"]["select"]["name"], "Structurally remote (no HQ)")
        self.assertEqual(page["Verdict"]["select"]["name"], "Do not pursue")
        self.assertEqual(page["Health Benefits"]["select"]["name"], "Weak")
        self.assertEqual(page["PTO"]["select"]["name"], "Weak")
        for bad in ({"verdict": "Maybe"}, {"health": "7"}, {"careers": "javascript:alert(1)"}, {"growth": "Huge"}):
            self.assertFalse(self.call("/api/companies/save", {"id": cid, **bad})[1]["ok"], bad)
        # add from the page with a careers link: the board goes into the daily check's settings
        _, r = self.call("/api/companies/add", {"name": "Example Corp", "url": "https://job-boards.greenhouse.io/examplecorp"})
        self.assertTrue(r["ok"], r)
        boards = json.loads((self.settings / "companies.json").read_text())["ats_tools"]["CONFIRMED_COMPANIES"]
        self.assertIn({"name": "Example Corp", "platform": "greenhouse", "slug": "examplecorp"}, boards)
        # Workday stays off until the user turns it on for that company
        co = json.loads((self.settings / "companies.json").read_text())
        co["ats_tools"]["CONFIRMED_COMPANIES"].append({"name": "Woodgrove (example)", "platform": "workday",
                                                       "slug": {"tenant": "woodgrove", "instance": "wd5", "board": "External"}})
        (self.settings / "companies.json").write_text(json.dumps(co))
        _, c = self.call("/api/companies")
        wd = next(x for x in c["rows"] if x["name"] == "Woodgrove (example)")
        self.assertEqual((wd["board"]["label"], wd["board"]["workday_ok"]), ("Workday", False))
        self.assertTrue(self.call("/api/companies/workday", {"name": "Woodgrove (example)", "ok": True})[1]["ok"])
        boards = json.loads((self.settings / "companies.json").read_text())["ats_tools"]["CONFIRMED_COMPANIES"]
        self.assertTrue(next(b for b in boards if b["name"] == "Woodgrove (example)")["workday_ok"])

    def test_4d_theme_colors_and_suggest(self):
        _, st = self.call("/api/status")
        self.assertEqual(st["theme"], "auto")
        self.assertEqual(st["status_colors"]["Rejected"], "red")
        _, r = self.call("/api/ui", {"theme": "dark", "status_colors": {"Interested": "pink"}})
        self.assertTrue(r["ok"], r)
        app = json.loads((self.settings / "app.json").read_text())
        self.assertEqual((app["theme"], app["status_colors"]["Interested"]), ("dark", "pink"))
        self.assertFalse(self.call("/api/ui", {"theme": "neon"})[1]["ok"])
        self.assertFalse(self.call("/api/ui", {"status_colors": {"Interested": "url(x)"}})[1]["ok"])
        self.call("/api/ui", {"theme": "auto"})
        # no support address set: the page offers GitHub only, and the address never reaches the page
        self.assertFalse(self.call("/api/suggest", {"what": "x"})[1]["ok"])
        _, page = self.call("/?t=" + self.token, token="")
        self.assertIn("job-search-kit/issues/new", page)
        self.assertNotIn("support_email\"", page)

    def test_5_contacts(self):
        self.call("/api/contacts", [{"name": "Sam Example", "company": "ClinicFlow (example)", "role": "Recruiter", "last": "2026-10-30", "notes": ""}])
        _, rows = self.call("/api/contacts")
        self.assertEqual(rows[0]["name"], "Sam Example")

    def test_6_detect_board_from_link(self):
        _, r = self.call("/api/detect", {"url": "https://job-boards.greenhouse.io/examplecorp", "name": "Example Corp"})
        self.assertEqual(r["board"], {"name": "Example Corp", "platform": "greenhouse", "slug": "examplecorp"})

    def test_7_other_websites_refused(self):
        code, _ = self.call("/api/answers", {"x": 1}, origin="https://evil.example")
        self.assertEqual(code, 403)
        # no key, wrong key, stale page URL without the key
        self.assertEqual(self.call("/api/tracker", token="")[0], 403)
        self.assertEqual(self.call("/api/tracker", token="not-the-key")[0], 403)
        self.assertEqual(self.call("/", token="")[0], 403)
        self.assertEqual(self.call("/api/tracker/update", {"id": "x", "status": "Closed"}, token="")[0], 403)
        # DNS rebinding: a website's hostname resolving to 127.0.0.1 shows up as a foreign Host header
        self.assertEqual(self.call("/api/tracker", host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(self.call("/api/tracker", host=f"localhost:{self.port}")[0], 403)
        self.assertEqual(self.call("/api/tracker")[0], 200)

    def test_8_links_http_only_and_no_private_addresses(self):
        text = "Remote (US). Product manager. 4+ years of product management. $150,000."
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "http://127.0.0.1:8080/x", "http://localhost/x",
                    "http://10.0.0.5/x", "http://192.168.1.1/x", "http://169.254.169.254/latest/meta-data",
                    "http://[::1]/x", "http://user:pw@example.com/x", "http://printer.local/x"):
            _, r = self.call("/api/tracker/add", {"title": "PM", "company": "Bad Link Co", "text": text, "url": bad})
            self.assertFalse(r["ok"], bad)
            self.assertIn("link", r["message"])
        _, t = self.call("/api/tracker")
        self.assertFalse(any(x["Company"] == "Bad Link Co" for x in t["rows"]))
        # a stored link that isn't http(s) is never handed to the page
        apps = json.loads((self.data / "tracker" / "applications.json").read_text())
        pid = next(iter(apps["pages"]))
        apps["pages"][pid]["properties"]["Job Posting"] = {"type": "url", "url": "javascript:alert(1)"}
        (self.data / "tracker" / "applications.json").write_text(json.dumps(apps))
        _, t = self.call("/api/tracker")
        self.assertEqual(next(x for x in t["rows"] if x["id"] == pid)["Job Posting"], "")

    def test_9_folder_choice(self):
        _, f = self.call("/api/folder")
        self.assertEqual(set(f) >= {"documents", "local", "documents_synced", "needs_folder"}, True)
        self.assertFalse(f["needs_folder"])        # this test person already has settings
        dest = Path(self.tmp) / "chosen" / "Job Search"
        code, r = self.call("/api/folder", {"choice": "custom", "path": str(dest), "acknowledged": True})
        self.assertTrue(r.get("ok"), r)
        self.assertTrue((dest / "settings" / "paths.json").exists())
        self.assertTrue((dest / "Evidence Bank" / "Evidence Bank.md").exists())
        self.assertTrue((dest / "data").is_dir())
        _, st = self.call("/api/status")
        self.assertEqual(Path(st["settings"]), (dest / "settings").resolve())
        self.assertFalse(st["needs_ack"])   # confirmed on the privacy page before the folder existed
        self.assertEqual(json.loads((dest / "settings" / "app.json").read_text())["acknowledged"]["terms"], "beta-as-is-1")

    def test_11_last_run_and_stale_banner(self):
        from datetime import datetime, timedelta
        f = self.data / "run_stats.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        _, t = self.call("/api/tracker")
        self.assertIsNone(t["last_run"]["ts"])
        old = (datetime.now() - timedelta(hours=40)).isoformat(timespec="seconds")
        f.write_text(json.dumps({"ts": old, "run": "full", "dry_run": False}) + "\n")
        _, t = self.call("/api/tracker")
        self.assertTrue(t["last_run"]["stale"])
        new = datetime.now().isoformat(timespec="seconds")
        with f.open("a") as fh:
            fh.write(json.dumps({"ts": new, "run": "quick", "dry_run": False}) + "\n")
            fh.write(json.dumps({"ts": new, "run": "full", "dry_run": True}) + "\n")   # dry runs don't count
        _, t = self.call("/api/tracker")
        self.assertEqual((t["last_run"]["run"], t["last_run"]["stale"]), ("quick", False))
        _, page = self.call("/?t=" + self.token, token="")
        self.assertIn("No successful check in over a day and a half", page)

    def test_12_frames_size_and_idle(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/?t={self.token}")
        with urllib.request.urlopen(req, timeout=30) as r:
            self.assertEqual(r.headers["X-Frame-Options"], "DENY")
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        code, r = self.call("/api/tracker/add", {"text": "x" * 1_100_000})
        self.assertEqual(code, 413)
        self.assertFalse(r["ok"])
        # the page server stops itself after the idle limit
        sys.path.insert(0, str(APP))
        import threading
        import time
        import wizard
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), wizard.Handler)
        wizard.start_idle_watch(srv, minutes=0.01, every=0.05)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        t.join(timeout=10)
        self.assertFalse(t.is_alive(), "idle server should have stopped")
        srv.server_close()

    def test_10_beta_terms_acknowledged(self):
        _, st = self.call("/api/status")
        self.assertTrue(st["needs_ack"])
        _, r = self.call("/api/acknowledge", {})
        self.assertTrue(r["ok"])
        _, st = self.call("/api/status")
        self.assertFalse(st["needs_ack"])
        app = json.loads((self.settings / "app.json").read_text())
        self.assertEqual(app["acknowledged"]["terms"], "beta-as-is-1")
        _, page = self.call("/?t=" + self.token, token="")
        self.assertIn(">Beta<", page)
        self.assertIn("provided as is", page)


class TrackerPageHelpers(unittest.TestCase):
    """Pieces of the tracker page that need no server."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("KIT_SETTINGS_DIR", str(PERSON / "settings"))
        sys.path.insert(0, str(APP))
        import wizard
        cls.w = wizard

    def test_health_rating_feeds_the_benefits_rule(self):
        hs = self.w.health_select
        self.assertEqual([hs(1), hs(2), hs(2.5), hs(4), hs(None)], ["Weak", "Weak", "Average", "Strong", None])

    def test_board_links(self):
        bl = self.w.board_link
        self.assertEqual(bl("lever", "acme"), "https://jobs.lever.co/acme")
        self.assertEqual(bl("ashby", "acme"), "https://jobs.ashbyhq.com/acme")
        self.assertEqual(bl("workday", {"tenant": "acme", "instance": "wd1", "board": "Careers"}), "https://acme.wd1.myworkdayjobs.com/Careers")
        self.assertEqual(bl("custom", "x"), "")

    def test_new_tag_rules(self):
        from datetime import date
        today = date(2026, 11, 10)
        base = {"Status": "Interested", "Source": "Greenhouse", "created": "2026-11-08", "Opened": ""}
        self.assertTrue(self.w._is_new(base, today))
        for change in ({"Opened": "2026-11-09"}, {"Source": "Added by you"}, {"Status": "Applied"}, {"created": "2026-10-01"}):
            self.assertFalse(self.w._is_new({**base, **change}, today), change)

    def test_suggestion_email_opens_mail_app_with_hidden_address(self):
        opened = []
        orig = self.w.kit_settings.app_settings
        self.w.kit_settings.app_settings = lambda: {"support_email": "helper@example.com"}
        try:
            r = self.w.suggest_email({"what": "Sort by deadline\nmore", "why": "Saves time"}, opener=opened.append)
        finally:
            self.w.kit_settings.app_settings = orig
        self.assertTrue(r["ok"])
        self.assertTrue(opened[0].startswith("mailto:helper@example.com?subject=Job%20Search%20Kit%20idea%3A%20Sort%20by%20deadline"))
        self.assertIn("Saves%20time", opened[0])
        self.assertNotIn("helper@example.com", json.dumps(r))   # never handed back to the page


class FetchPinning(unittest.TestCase):
    """Add a Posting connects only to the address it checked (no DNS-rebinding race)."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("KIT_SETTINGS_DIR", str(PERSON / "settings"))
        sys.path.insert(0, str(APP))
        sys.path.insert(0, str(APP / "agent"))
        import wizard
        cls.w = wizard

    def test_fetch_uses_the_checked_address(self):
        calls, seen = [], []
        answers = iter([["93.184.216.34"], ["10.0.0.5"]])   # public for the check, private if asked again

        def resolve(host):
            calls.append(host)
            return next(answers)

        def get(url, ip):
            seen.append(ip)
            return 200, {}, "posting text"
        self.assertEqual(self.w.safe_fetch("https://jobs.example.com/1", resolve=resolve, get=get), "posting text")
        self.assertEqual(seen, ["93.184.216.34"])
        self.assertEqual(len(calls), 1)

    def test_redirect_to_private_refused(self):
        def resolve(host):
            return ["10.0.0.5"] if host == "inside.example.com" else ["93.184.216.34"]

        def get(url, ip):
            self.assertNotEqual(ip, "10.0.0.5")
            return 302, {"Location": "http://inside.example.com/admin"}, ""
        with self.assertRaises(ValueError):
            self.w.safe_fetch("https://jobs.example.com/1", resolve=resolve, get=get)

    def test_error_status_and_size_cap(self):
        pub = lambda h: ["93.184.216.34"]
        with self.assertRaises(ValueError):
            self.w.safe_fetch("https://jobs.example.com/x", resolve=pub, get=lambda u, ip: (404, {}, ""))
        big = self.w.safe_fetch("https://jobs.example.com/x", resolve=pub,
                                get=lambda u, ip: (200, {}, "a" * (self.w.MAX_PAGE + 10)))
        self.assertEqual(len(big), self.w.MAX_PAGE)

    def test_pinned_get_keeps_hostname(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        got = {}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                got["host"], got["path"] = self.headers.get("Host"), self.path
                body = "café".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.handle_request, daemon=True).start()
        try:
            status, _, text = self.w._pinned_get(f"http://jobs.example.com:{port}/p?q=1", "127.0.0.1")
        finally:
            srv.server_close()
        self.assertEqual((status, text), (200, "café"))
        self.assertEqual(got, {"host": f"jobs.example.com:{port}", "path": "/p?q=1"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
