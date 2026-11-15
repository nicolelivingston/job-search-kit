"""The daily check follows company job boards it finds on its own: a fitting
posting from a job site queues its company; the next full run follows the
company's own board only when the posting's link is on it or the same role is
listed there (a guessed address without the role is never followed); found
boards are read with the user's own picks and never shadow them; a stopped
board stays stopped; a quiet one is dropped. Companies the user follows
closely get an alert for any fresh posting, whatever its fit. SmartRecruiters
boards are read, with one detail request per posting on the user's title
list. Runs as the test person in KIT_SETTINGS_DIR with made-up companies and
no network.
    python3 app/agent/agent_tests/test_company_follow.py
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import person  # noqa: E402
import ats_tools  # noqa: E402
import lead_resolver  # noqa: E402
import company_follow as cf  # noqa: E402

TODAY = date(2026, 11, 2)
TITLE = person.wanted_title()
OTHER = "Facilities Coordinator"


def job(company, title=TITLE, url="https://jobsite.example.com/listing/9100001", **more):
    return {"id": f"feed-{company}", "company": company, "title": title, "url": url, "location": "Remote (US)", **more}


def fit(verdict="Strong fit", **more):
    return {"verdict": verdict, "tier": "A" if verdict == "Strong fit" else "B", "score": 80, **more}


class Follow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (ats_tools.FOUND_BOARDS_FILE, ats_tools.CONFIRMED_COMPANIES, ats_tools.CUSTOM_SITE_COMPANIES,
                      ats_tools.WATCHED_COMPANIES, cf.AUTO_FOLLOW, cf.AUTO_FOLLOW_MAX)
        ats_tools.FOUND_BOARDS_FILE = self.tmp / "found_boards.json"
        ats_tools.CONFIRMED_COMPANIES = [{"name": "Ledgerly", "platform": "greenhouse", "slug": "ledgerly"}]
        ats_tools.CUSTOM_SITE_COMPANIES = []
        ats_tools.WATCHED_COMPANIES = ["Fernhollow Health"]
        cf.AUTO_FOLLOW = True
        self.boards = {("ashby", "lumenfold"): [{"title": TITLE, "url": "https://jobs.ashbyhq.com/lumenfold/00000000-0000-4000-8000-000000000001"}],
                       ("greenhouse", "tessaway"): [{"title": OTHER, "url": "https://job-boards.greenhouse.io/tessaway/jobs/9100002"}]}
        self.asked = []

    def tearDown(self):
        (ats_tools.FOUND_BOARDS_FILE, ats_tools.CONFIRMED_COMPANIES, ats_tools.CUSTOM_SITE_COMPANIES,
         ats_tools.WATCHED_COMPANIES, cf.AUTO_FOLLOW, cf.AUTO_FOLLOW_MAX) = self.saved

    def fetch(self, platform, slug):
        self.asked.append((platform, slug))
        return self.boards.get((platform, slug), [])

    def queue(self):
        return [q["company"] for q in cf.load()["queue"]]

    def test_only_fitting_postings_from_job_sites_are_queued(self):
        written = [(job("Lumenfold"), fit(), None, None),
                   (job("Tessaway"), fit("Possible fit"), None, None),
                   (job("Quillco"), fit("Poor fit"), None, None),                       # doesn't fit
                   (job("Harborline"), fit(hard_skip=True), None, None),                 # a rule ruled it out
                   (job("Ledgerly"), fit(), None, None),                                 # the user already follows it
                   (job("Northfield", ats_platform="greenhouse"), fit(), None, None),    # came from a followed board
                   (job("Jobgether"), fit(), None, None),                                # a reposter, not an employer
                   (job("Fernhollow Health"), fit("Poor fit"), None, None),                # followed closely: queued anyway
                   (job("Lumenfold, Inc."), fit(), None, None)]                         # same company, once
        self.assertEqual(cf.enqueue(written, TODAY), 3)
        self.assertEqual(self.queue(), ["Lumenfold", "Tessaway", "Fernhollow Health"])
        cf.AUTO_FOLLOW = False
        self.assertEqual(cf.enqueue([(job("Paylane"), fit(), None, None)], TODAY), 0)

    def test_a_board_is_followed_only_when_it_is_confirmed(self):
        cache = {}
        # the posting's own link is on a board: certain
        self.assertEqual(cf.find_board("Harborline", TITLE, "https://jobs.lever.co/harborline/00000000-0000-4000-8000-000000000002",
                                       cache=cache, today=TODAY, fetch=self.fetch),
                         ("lever", "harborline", cf.HOW_LINK))
        self.assertEqual(self.asked, [])
        # the same role on a board at an address guessed from the name
        self.assertEqual(cf.find_board("Lumenfold", TITLE, cache=cache, today=TODAY, fetch=self.fetch)[:2], ("ashby", "lumenfold"))
        # a board at the guessed address without the role could be another company's: not followed
        self.assertIsNone(cf.find_board("Tessaway", TITLE, cache=cache, today=TODAY, fetch=self.fetch))
        self.assertIsNone(cache["tessaway"]["platform"])
        # ...and not asked about again for two weeks
        self.asked.clear()
        self.assertIsNone(cf.find_board("Tessaway", TITLE, cache=cache, today=TODAY + timedelta(days=3), fetch=self.fetch))
        self.assertEqual(self.asked, [])
        cf.find_board("Tessaway", TITLE, cache=cache, today=TODAY + timedelta(days=15), fetch=self.fetch)
        self.assertTrue(self.asked)
        # Workday is opt-in per company and never followed this way
        self.assertIsNone(cf.find_board("Paylane", TITLE, "https://paylane.wd5.myworkdayjobs.com/Careers/job/Remote/x_R-9100003",
                                        cache={}, today=TODAY, fetch=self.fetch))

    def test_the_full_run_follows_what_it_can_confirm(self):
        cf.enqueue([(job("Lumenfold"), fit(), None, None), (job("Tessaway"), fit(), None, None)], TODAY)
        self.assertEqual(cf.process_queue(TODAY, fetch=self.fetch, cache={}), ["Lumenfold"])
        data = cf.load()
        self.assertEqual(data["queue"], [])
        b = data["boards"][0]
        self.assertEqual((b["name"], b["platform"], b["slug"], b["status"], b["how"]),
                         ("Lumenfold", "ashby", "lumenfold", "on", cf.HOW_ROLE))
        followed = ats_tools.followed_companies()
        self.assertEqual([c["name"] for c in followed], ["Ledgerly", "Lumenfold"])   # the user's picks first
        self.assertTrue(followed[1]["found"])
        # the lead matcher knows the board too
        self.assertIn(("ashby", "lumenfold"), [(p, s) for p, s, _o, _n in lead_resolver.known_boards("Lumenfold Inc")])
        # already followed: a later posting there isn't queued again
        self.assertEqual(cf.enqueue([(job("Lumenfold"), fit(), None, None)], TODAY), 0)

    def test_limits_per_run_and_in_all(self):
        for i, name in enumerate(("Lumenfold", "Quillco", "Harborline")):
            self.boards[("greenhouse", name.lower())] = [{"title": TITLE, "url": ""}]
        self.boards.pop(("ashby", "lumenfold"))
        cf.enqueue([(job(n), fit(), None, None) for n in ("Lumenfold", "Quillco", "Harborline")], TODAY)
        self.assertEqual(cf.process_queue(TODAY, limit=2, fetch=self.fetch, cache={}), ["Lumenfold", "Quillco"])
        self.assertEqual(self.queue(), ["Harborline"])                      # waits for the next day
        cf.AUTO_FOLLOW_MAX = 2
        self.assertEqual(cf.process_queue(TODAY, fetch=self.fetch, cache={}), [])
        self.assertEqual(self.queue(), ["Harborline"])                      # the list is full: kept, not lost

    def test_a_stopped_board_stays_stopped_and_a_quiet_one_is_dropped(self):
        cf.enqueue([(job("Lumenfold"), fit(), None, None)], TODAY)
        cf.process_queue(TODAY, fetch=self.fetch, cache={})
        self.assertTrue(cf.set_status("lumenfold", False))
        self.assertEqual([c["name"] for c in ats_tools.followed_companies()], ["Ledgerly"])
        self.assertEqual(cf.enqueue([(job("Lumenfold"), fit(), None, None)], TODAY), 0)   # never followed again on its own
        self.assertFalse(cf.set_status("Nobody Co", True))
        cf.set_status("Lumenfold", True)
        fetched = [{"company": "Lumenfold", "title": TITLE, "ats_platform": "ashby"}]
        ok = lambda t: t == TITLE
        later = TODAY + timedelta(days=30)
        self.assertEqual(cf.note_matches(fetched, ok, later), [])
        self.assertEqual(cf.load()["boards"][0]["last_match"], later.isoformat())
        quiet = [{"company": "Lumenfold", "title": OTHER, "ats_platform": "ashby"}]
        self.assertEqual(cf.note_matches(quiet, ok, later + timedelta(days=cf.AUTO_FOLLOW_STALE_DAYS - 1)), [])
        self.assertEqual(cf.note_matches(quiet, ok, later + timedelta(days=cf.AUTO_FOLLOW_STALE_DAYS)), ["Lumenfold"])
        self.assertEqual(ats_tools.followed_companies(), ats_tools.CONFIRMED_COMPANIES)

    def test_found_boards_never_shadow_the_users_picks_and_a_bad_file_is_ignored(self):
        ats_tools.FOUND_BOARDS_FILE.write_text(json.dumps({"boards": [
            {"name": "Ledgerly", "platform": "ashby", "slug": "ledgerly", "status": "on"},          # same company as a pick
            {"name": "Ledgerly Labs", "platform": "greenhouse", "slug": "Ledgerly", "status": "on"},  # same board as a pick
            {"name": "Paylane", "platform": "workday", "slug": {"tenant": "paylane"}, "status": "on"},
            {"name": "Quillco", "platform": "lever", "slug": "quillco", "status": "on"}]}))
        self.assertEqual([c["name"] for c in ats_tools.followed_companies()], ["Ledgerly", "Quillco"])   # and never Workday
        ats_tools.FOUND_BOARDS_FILE.write_text("{not json")
        self.assertEqual(ats_tools.followed_companies(), ats_tools.CONFIRMED_COMPANIES)
        self.assertEqual(cf.load(), {"boards": [], "queue": []})

    def test_digest_lines(self):
        self.assertIsNone(cf.digest_section([], []))
        text = cf.digest_section(["Lumenfold"], ["Quillco"])
        self.assertIn("- Lumenfold", text)
        self.assertIn("Quillco", text)
        self.assertIn("Companies page", text)


class FollowedClosely(unittest.TestCase):
    """Any fresh posting at a company the user follows closely is called out."""

    def setUp(self):
        os.environ.pop("NOTION_TOKEN", None)
        import job_search_agent as jsa
        self.jsa = jsa
        self.saved = ats_tools.WATCHED_COMPANIES
        ats_tools.WATCHED_COMPANIES = ["Fernhollow Health, Inc."]

    def tearDown(self):
        ats_tools.WATCHED_COMPANIES = self.saved

    def test_alert_whatever_the_fit(self):
        jsa = self.jsa
        fresh = TODAY.isoformat()
        poor = {"tier": "C", "verdict": "Poor fit", "score": 31, "evidence": ""}
        written = [(job("Fernhollow Health", published=fresh), poor, None, None),
                   (job("Quillco", published=fresh), poor, None, None),
                   (job("Fernhollow Health", title=TITLE + " II", published="2026-08-01"), poor, None, None)]   # not fresh
        got = jsa.fresh_alert_candidates(written, history={}, today=TODAY)
        self.assertEqual([m[0]["company"] for m in got], ["Fernhollow Health"])
        subject, body = jsa.fresh_alert_message(got)
        self.assertTrue(subject.startswith("[Followed company] Fernhollow Health"), subject)
        self.assertIn("because you follow this company closely", body)
        strong = {"tier": "A", "verdict": "Strong fit", "score": 88, "evidence": ""}
        subject, body = jsa.fresh_alert_message(jsa.fresh_alert_candidates(
            [(job("Fernhollow Health", published=fresh), strong, None, None)], history={}, today=TODAY))
        self.assertTrue(subject.startswith("[Fresh Tier A]"), subject)     # a strong fit is still labeled as one
        self.assertNotIn("because you follow", body)
        self.assertTrue(cf.is_watched("fernhollow health"))
        self.assertFalse(cf.is_watched("Fernhollow Logistics"))


class SmartRecruiters(unittest.TestCase):
    def setUp(self):
        self.saved = (ats_tools.request_with_retry, ats_tools.DETAIL_TITLE_RE)
        import re
        ats_tools.DETAIL_TITLE_RE = re.compile(re.escape(TITLE), re.I)
        self.calls = []

        class R:
            def __init__(self, data):
                self._d = data
            def raise_for_status(self):
                pass
            def json(self):
                return self._d
        listing = {"totalFound": 2, "content": [
            {"id": "910000000000001", "name": TITLE, "releasedDate": "2026-10-30T09:00:00.000Z",
             "location": {"city": "Denver", "region": "CO", "country": "us", "remote": True}},
            {"id": "910000000000002", "name": OTHER, "releasedDate": "2026-10-01T09:00:00.000Z",
             "location": {"city": "Austin", "country": "us"}}]}
        detail = {"postingUrl": "https://jobs.smartrecruiters.com/Lumenfold/910000000000001-made-up-role",
                  "jobAd": {"sections": {"jobDescription": {"text": "<p>Fully remote. Base salary $120,000 to $140,000.</p>"},
                                         "qualifications": {"text": "<ul><li>Five years in the field</li></ul>"}}}}

        def fake(fn, url, **kw):
            self.calls.append(url)
            return R(detail if url.rstrip("/").endswith("910000000000001") else listing)
        ats_tools.request_with_retry = fake

    def tearDown(self):
        ats_tools.request_with_retry, ats_tools.DETAIL_TITLE_RE = self.saved

    def test_board_is_read_with_one_detail_call_per_title_on_the_list(self):
        jobs = ats_tools.fetch_smartrecruiters("Lumenfold")
        self.assertEqual(len(jobs), 2)
        mine, other = jobs
        self.assertEqual((mine["id"], mine["location"], mine["published"]),
                         ("sr-Lumenfold-910000000000001", "Remote, Denver, CO, us", "2026-10-30"))
        self.assertIn("Base salary $120,000", mine["description"])
        self.assertNotIn("<", mine["description"])
        self.assertTrue(mine["url"].startswith("https://jobs.smartrecruiters.com/Lumenfold/910000000000001"))
        self.assertEqual(other["description"], "")                                  # not on the title list: no detail call
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(lead_resolver.board_from_url("https://jobs.smartrecruiters.com/Lumenfold/910000000000001"),
                         ("smartrecruiters", "Lumenfold"))
        self.assertIn("smartrecruiters", ats_tools.FETCHERS)
        self.assertIn("smartrecruiters", lead_resolver.PROBE_PLATFORMS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
