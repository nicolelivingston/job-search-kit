"""Built-in tracker (kit): main() runs end to end with "tracker": "local",
writes rows to local files instead of Notion, never duplicates a posting,
reads the rows back for rescoring, and closes a posting after it disappears
from its board on two runs, unless the board still answers for that one
posting (then the row stays open, marked Unlisted). Also unit-tests the
filter engine. No network.
    python3 app/agent/agent_tests/test_local_tracker.py
"""
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
KIT = AGENT.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import person   # noqa: E402

CHILD = textwrap.dedent(r'''
    import io, json, re, sys
    from contextlib import ExitStack, redirect_stdout
    from unittest import mock
    sys.path.insert(0, sys.argv[1])
    import job_search_agent as jsa, invariants, local_tracker
    assert jsa.TRACKER_MODE == "local" and jsa.NOTION_TOKEN == "local-tracker"
    jobs = json.loads(sys.argv[2])
    still_answers = set(json.loads(sys.argv[3]))   # job numbers the board still has, on or off its public list
    class R:
        status_code = 200; ok = True
        def __init__(self, url): self.url = url; self.text = "<html>Fully remote.</html>"; self.content = self.text.encode(); self.headers = {}; self.body = {}
        def json(self): return self.body
        def raise_for_status(self): pass
    def fake_get(url, **kw):
        assert "api.notion.com" not in url, "Notion call reached the network"
        r = R(url)
        one = re.search(r"boards-api\.greenhouse\.io/v1/boards/[^/]+/jobs/(\d+)$", url)
        if one:   # the agent asking the board about one posting
            if one.group(1) in still_answers:
                r.body = {"id": int(one.group(1)), "title": "a posting"}
            else:
                r.status_code = 404
        return r
    def fake_post(url, **kw):
        raise AssertionError("unexpected POST to " + url)
    patches = [mock.patch.object(jsa, "fetch_remotive", return_value=[]),
               mock.patch.object(jsa, "fetch_remoteok", return_value=[]),
               mock.patch.object(jsa, "fetch_all_confirmed", return_value=[dict(j) for j in jobs]),
               mock.patch.object(jsa, "fetch_board_feeds", return_value=[]),
               mock.patch.object(jsa, "fetch_linkedin_alerts", return_value=[]),
               mock.patch.object(jsa, "screen_candidates", return_value=""),
               mock.patch.object(jsa, "notify"),
               mock.patch.object(jsa, "maybe_refresh_market_snapshot"),
               mock.patch.object(jsa.requests, "get", fake_get),
               mock.patch.object(jsa.requests, "post", fake_post),
               mock.patch.object(invariants, "run_after_agent")]
    out = io.StringIO()
    with ExitStack() as st:
        for p in patches: st.enter_context(p)
        st.enter_context(redirect_stdout(out))
        jsa.main(quick=False)
    print("RUN_OK")
''')

JOB = person.sample_job(id="gh-acme-1")   # a posting the test person these tests run as would want
OTHER = dict(JOB, id="gh-acme-2", title=JOB["title"] + ", Billing",
             url="https://job-boards.greenhouse.io/acme/jobs/2222222222")


def _settings(tmp):
    s = Path(tmp) / "settings"
    src = Path(os.environ.get("KIT_SETTINGS_DIR") or (KIT / "dev-settings"))
    shutil.copytree(src, s)
    (s / "app.json").write_text(json.dumps({"tracker": "local"}))
    paths = json.loads((s / "paths.json").read_text()) if (s / "paths.json").exists() else {}
    paths["data_dir"] = str(Path(tmp) / "data")
    # keyword groups live next to the user's bank; bring a copy along
    bank = (src / paths["bank_dir"]).resolve() if paths.get("bank_dir") else None
    kg_src = (src / paths["keyword_groups"]) if paths.get("keyword_groups") else (bank / "keyword-groups.json" if bank else src / "keyword-groups.json")
    shutil.copy(kg_src, s / "keyword-groups.json")
    paths["keyword_groups"] = "keyword-groups.json"
    if bank:
        paths["bank_dir"] = str(bank)
    (s / "paths.json").write_text(json.dumps(paths))
    for k in ("NOTION_DATABASE_ID", "NOTION_COMPANIES_DATABASE_ID"):
        c = json.loads((s / "criteria.json").read_text())
        c["agent"].pop(k, None)
        (s / "criteria.json").write_text(json.dumps(c))
    return s


class LocalTrackerRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings = _settings(self.tmp)
        self.data = Path(self.tmp) / "data"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_agent(self, jobs, still_answers=()):
        env = dict(os.environ, KIT_SETTINGS_DIR=str(self.settings))
        env.pop("NOTION_TOKEN", None)
        r = subprocess.run([sys.executable, "-c", CHILD, str(AGENT), json.dumps(jobs), json.dumps(list(still_answers))],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertIn("RUN_OK", r.stdout, r.stdout[-2000:] + r.stderr[-3000:])

    def apps(self):
        f = self.data / "tracker" / "applications.json"
        return list(json.loads(f.read_text())["pages"].values()) if f.exists() else []

    def plain(self, page, name):
        p = page["properties"].get(name) or {}
        t = p.get("type"); v = p.get(t)
        if t in ("title", "rich_text"):
            return "".join(x["plain_text"] for x in v or [])
        if t in ("select", "status"):
            return v and v["name"]
        return v

    def test_end_to_end(self):
        self.run_agent([JOB])
        rows = self.apps()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(self.plain(row, "Company"), "Acme")
        self.assertEqual(self.plain(row, "Status"), "Interested")
        self.assertIsNotNone(self.plain(row, "Role Fit Score"))
        self.assertTrue(self.plain(row, "Research Tier"))
        self.assertTrue(self.plain(row, "Label Reason"))
        companies = json.loads((self.data / "tracker" / "companies.json").read_text())["pages"]
        self.assertEqual(len(companies), 1)
        # second run with the same posting: no duplicate
        self.run_agent([JOB])
        self.assertEqual(len(self.apps()), 1)
        # posting gone from its board for two runs (the board itself was
        # fetched, with a different posting on it, and no longer has this one): closed
        self.run_agent([OTHER])
        self.run_agent([OTHER])
        self.assertEqual(self.plain(self.first(), "Status"), "Closed")
        # state files went to the data folder, not the app folder
        self.assertTrue((self.data / "seen_jobs.json").exists())

    def first(self):
        return [p for p in self.apps() if self.plain(p, "Job Posting") == JOB["url"]][0]

    def test_a_posting_off_the_public_list_stays_open(self):
        number = JOB["url"].rsplit("/", 1)[1]
        self.run_agent([JOB])
        # off the board's public list for two runs, but the board still answers for it
        self.run_agent([OTHER], still_answers=[number])
        self.run_agent([OTHER], still_answers=[number])
        row = self.first()
        self.assertEqual(self.plain(row, "Status"), "Interested")
        self.assertEqual(self.plain(row, "Posting Health"), "Unlisted")
        self.assertTrue(self.plain(row, "Last Verified"))
        # listed again: the mark clears
        self.run_agent([JOB, OTHER], still_answers=[number])
        row = self.first()
        self.assertEqual(self.plain(row, "Status"), "Interested")
        self.assertIsNone(self.plain(row, "Posting Health"))
        # then really gone: closed after two runs
        self.run_agent([OTHER])
        self.run_agent([OTHER])
        self.assertEqual(self.plain(self.first(), "Status"), "Closed")


class FilterEngine(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(AGENT))
        import local_tracker
        self.lt = local_tracker
        self.tmp = tempfile.mkdtemp()
        local_tracker.configure(self.tmp, "apps-db", "co-db")
        mk = lambda props: local_tracker.handle("post", "https://api.notion.com/v1/pages",
                                                {"json": {"parent": {"database_id": "apps-db"}, "properties": props}}).json()
        self.a = mk({"Role": {"title": [{"text": {"content": "Senior PM"}}]}, "Status": {"status": {"name": "Interested"}},
                     "Overall Verdict": {"select": {"name": "Pursue"}}, "Role Fit Score": {"number": 82},
                     "Notes": {"rich_text": [{"text": {"content": "Board lookup 2026-10-30"}}]},
                     "Posted Date": {"date": {"start": "2026-10-29"}}, "Company Profile": {"relation": [{"id": "c1"}]}})
        self.b = mk({"Role": {"title": [{"text": {"content": "Product Manager"}}]}, "Status": {"status": {"name": "Applied"}},
                     "Role Fit Score": {"number": 40}, "Posted Date": {"date": {"start": "2026-09-01"}}})

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def q(self, flt=None, sorts=None, size=None):
        body = {"filter": flt} if flt else {}
        if sorts: body["sorts"] = sorts
        if size: body["page_size"] = size
        return self.lt.handle("post", "https://api.notion.com/v1/databases/apps-db/query", {"json": body}).json()

    def ids(self, res):
        return {p["id"] for p in res["results"]}

    def test_filters(self):
        A, B = self.a["id"], self.b["id"]
        self.assertEqual(self.ids(self.q({"property": "Status", "status": {"equals": "Interested"}})), {A})
        self.assertEqual(self.ids(self.q({"or": [{"property": "Status", "status": {"equals": "Interested"}},
                                                 {"property": "Status", "status": {"equals": "Applied"}}]})), {A, B})
        self.assertEqual(self.ids(self.q({"property": "Overall Verdict", "select": {"is_empty": True}})), {B})
        self.assertEqual(self.ids(self.q({"property": "Notes", "rich_text": {"contains": "board lookup"}})), {A})
        self.assertEqual(self.ids(self.q({"property": "Notes", "rich_text": {"does_not_contain": "Board"}})), {B})
        self.assertEqual(self.ids(self.q({"property": "Posted Date", "date": {"on_or_after": "2026-10-01"}})), {A})
        self.assertEqual(self.ids(self.q({"property": "Company Profile", "relation": {"contains": "c1"}})), {A})
        self.assertEqual(self.ids(self.q({"and": [{"property": "Role Fit Score", "number": {"greater_than": 50}},
                                                  {"property": "Role", "title": {"contains": "senior"}}]})), {A})
        self.assertEqual(self.ids(self.q({"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": "2000-01-01"}})), {A, B})

    def test_sort_pagination_patch_and_404(self):
        r = self.q(sorts=[{"property": "Role Fit Score", "direction": "descending"}], size=1)
        self.assertEqual(r["results"][0]["id"], self.a["id"])
        self.assertTrue(r["has_more"])
        r2 = self.lt.handle("post", "https://api.notion.com/v1/databases/apps-db/query",
                            {"json": {"sorts": [{"property": "Role Fit Score", "direction": "descending"}],
                                      "page_size": 1, "start_cursor": r["next_cursor"]}}).json()
        self.assertEqual(r2["results"][0]["id"], self.b["id"])
        self.assertFalse(r2["has_more"])
        p = self.lt.handle("patch", f"https://api.notion.com/v1/pages/{self.b['id']}",
                           {"json": {"properties": {"Status": {"status": {"name": "Closed"}}}}}).json()
        self.assertEqual(p["properties"]["Status"]["status"]["name"], "Closed")
        self.assertEqual(p["properties"]["Role"]["title"][0]["plain_text"], "Product Manager")
        on_disk = json.loads((Path(self.tmp) / "tracker" / "applications.json").read_text())
        self.assertEqual(on_disk["pages"][self.b["id"]]["properties"]["Status"]["status"]["name"], "Closed")
        self.assertEqual(self.lt.handle("get", "https://api.notion.com/v1/pages/nope", {}).status_code, 404)
        schema = self.lt.handle("get", "https://api.notion.com/v1/databases/apps-db", {}).json()["properties"]
        self.assertIn("Last Verified", schema)


if __name__ == "__main__":
    unittest.main(verbosity=2)
