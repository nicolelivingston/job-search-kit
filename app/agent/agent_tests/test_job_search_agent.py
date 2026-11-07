"""Regression tests for job_search_agent.py's Notion writes and fit scoring v2.

Kept outside tests/ on purpose: tests/ belongs to the frozen
application-generation foundation and its gate.

Run:  python3 agent_tests/test_job_search_agent.py

What this guards:
  1. Every property the agent writes exists in the Applications / Companies
     schema, with the right type and a real select/status option. This is the
     check that would have caught the removed "Job Summary" property and the
     "Fit Score" -> "Role Fit Score" rename.
  2. "Remote Status" comes from score_remote()'s classification, never a
     hardcoded value.
  3. Fit scoring v2 behaves: hard rules Skip, Evidence Bank families score,
     confirmed gaps penalize, tiers follow the thresholds, Pursue is never set.
  4. The rescoring pass never overrides a verdict the user set.

No network calls are made except the optional live-schema check at the end,
which runs only when NOTION_TOKEN is set and api.notion.com is reachable, and
only reads (GET database). It never writes.
"""

import inspect
import os
import pathlib
import re
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import job_search_agent as jsa   # noqa: E402
import fit_scoring as fs         # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
    if detail and not ok:
        print("         %s" % (detail,))


# ---------------------------------------------------------------------------
# Schema snapshot, taken from the live Notion databases on 2026-10-20 (after
# the fit scoring v2 properties were added). If a property is added/removed
# in Notion, update this snapshot on purpose.
# ---------------------------------------------------------------------------

TIERS = {"A - full info every run", "B - light refresh", "C - no spend"}

APPLICATIONS_SCHEMA = {
    "Role": {"type": "title"},
    "Company": {"type": "rich_text"},
    "Company Profile": {"type": "relation"},
    "Contact": {"type": "rich_text"},
    "Date Applied": {"type": "date"},
    "Role Fit Score": {"type": "number"},
    "Follow-up Date": {"type": "date"},
    "Industry Flag": {"type": "select", "options": {"Clear", "Ask Me First", "Excluded"}},
    "Job Posting": {"type": "url"},
    "Materials": {"type": "relation"},
    "Notes": {"type": "rich_text"},
    "Research Notes": {"type": "rich_text"},
    "Role Red Flags": {"type": "rich_text"},
    "Remote Status": {"type": "select", "options": {"Fully Remote", "Unverified", "Hybrid", "Onsite"}},
    "Resume Version Used": {"type": "rich_text"},
    "Source": {"type": "select", "options": {
        "LinkedIn", "Indeed", "We Work Remotely", "Built In", "FlexJobs",
        "Referral", "Company Site", "Other"}},
    "Status": {"type": "status", "options": {
        "Drafting Resume", "Interested", "Applied", "Interviewing", "Offer", "Closed", "Rejected"}},
    "Traceability": {"type": "relation"},
    "Base Salary": {"type": "number"},
    "Pay Basis": {"type": "select", "options": {"Base", "Total Compensation", "Not posted"}},
    "Posting Health": {"type": "select", "options": {"Suspected evergreen", "Verified real"}},
    "Posting Snapshot": {"type": "rich_text"},
    "Domain Tier": {"type": "select", "options": {
        "Tier 1 - same domain", "Tier 2 - adjacent regulated", "Tier 3 - outside domain"}},
    "Overall Verdict": {"type": "select", "options": {"Strong fit", "Possible fit", "Poor fit", "Applying", "Passed"}},
    "Label Reason": {"type": "rich_text"},
    "Schedule Intensity": {"type": "select", "options": {
        "Steady", "Some after-hours", "Heavy / on-call", "Unknown"}},
    # fit scoring v2, added 2026-10-20
    "Research Tier": {"type": "select", "options": TIERS},
    "Score Breakdown": {"type": "rich_text"},
    "Fit Evidence": {"type": "rich_text"},
    "Posted Date": {"type": "date"},
    "Posted Date Source": {"type": "select", "options": {
        "Board publish date", "Board approximate", "First seen by agent"}},
    "Last Verified": {"type": "date"},
    # rollups (read-only)
    "Company Risk": {"type": "rollup"}, "Company Verdict": {"type": "rollup"},
    "Company Remote Posture": {"type": "rollup"}, "Company Red Flags": {"type": "rollup"},
    "Glassdoor Rating": {"type": "rollup"}, "Domain": {"type": "rollup"},
}

COMPANIES_SCHEMA = {
    "Company": {"type": "title"},
    "ATS": {"type": "rich_text"},
    "Applications": {"type": "relation"},
    "Glassdoor Rating": {"type": "number"},
    "Growth Opportunity": {"type": "select", "options": {
        "Strong", "Some concerns", "Limited", "Not researched"}},
    "Interview Questions": {"type": "rich_text"},
    "Job Board URL": {"type": "url"},
    "Last Manual Check": {"type": "date"},
    "Monitoring": {"type": "select", "options": {
        "Auto (in agent feed)", "MANUAL CHECK NEEDED", "Not monitored - do not pursue"}},
    "Red Flags": {"type": "rich_text"},
    "Remote Posture": {"type": "select", "options": {
        "Structurally remote (no HQ)", "Remote-first with offices", "Hybrid / RTO risk", "Unknown"}},
    "Research Notes": {"type": "rich_text"},
    "Risk Level": {"type": "select", "options": {"Low", "Some concerns", "High", "Not researched"}},
    "Verdict": {"type": "select", "options": {
        "Applying", "Watch list", "Needs research", "Do not pursue", "Needs your OK"}},
    "Verdict Reason": {"type": "rich_text"},
    # fit scoring v2, added 2026-10-20
    "Research Tier": {"type": "select", "options": TIERS},
    "Last Researched": {"type": "date"},
    "Website": {"type": "url"},
}

READ_ONLY_TYPES = {"rollup", "formula", "created_time", "last_edited_time"}


def schema_problems(properties, schema):
    """List of problems with a Notion properties payload against a schema."""
    problems = []
    for name, value in properties.items():
        if name not in schema:
            problems.append("%r is not a property that exists" % name)
            continue
        spec = schema[name]
        if spec["type"] in READ_ONLY_TYPES:
            problems.append("%r is a read-only %s" % (name, spec["type"]))
            continue
        if spec["type"] not in value:
            problems.append("%r sent as %s, schema type is %s"
                            % (name, sorted(value), spec["type"]))
            continue
        if "options" in spec:
            chosen = (value[spec["type"]] or {}).get("name")
            if chosen not in spec["options"]:
                problems.append("%r option %r doesn't exist" % (name, chosen))
    return problems


# ---------------------------------------------------------------------------
# Capture harness: run the real write functions with the HTTP call replaced.
# ---------------------------------------------------------------------------

class _Resp:
    status_code = 200

    def __init__(self, page_id="captured-page"):
        self._id = page_id

    def json(self):
        return {"id": self._id, "results": [], "properties": {}, "icon": None}


def capture(fn, *args, **kwargs):
    """Call fn with request_with_retry swapped for a recorder; return payloads."""
    sent = []
    real_request, real_token = jsa.request_with_retry, jsa.NOTION_TOKEN

    def fake(request_fn, url, **kw):
        sent.append({"url": url, "json": kw.get("json")})
        return _Resp()

    jsa.request_with_retry = fake
    jsa.NOTION_TOKEN = "test-token-not-real"
    jsa.COMPANY_FIELDS_CACHE.clear()
    try:
        result = fn(*args, **kwargs)
    finally:
        jsa.request_with_retry, jsa.NOTION_TOKEN = real_request, real_token
    return result, sent


def make_job(location, description="", **extra):
    job = {
        "source": "Company Site", "id": "test-1", "title": "Senior Product Manager",
        "company": "ExampleCo", "url": "https://example.com/jobs/1",
        "location": location, "salary_text": "", "description": description,
        "notion_page_id": "company-page-id",
    }
    job.update(extra)
    return job


def application_props(job, flag="Clear", salary_min=None):
    result = fs.score_posting(job["title"], job["description"], salary_min=salary_min, company={})
    ok, sent = capture(jsa.write_to_notion, job, result, flag, salary_min,
                       company_page_id=job.get("notion_page_id"))
    posts = [s for s in sent if s["url"].endswith("/v1/pages") and s["json"] and "parent" in s["json"]]
    assert ok is True and len(posts) == 1, (ok, [s["url"] for s in sent])
    return posts[0]["json"]["properties"]


# ---------------------------------------------------------------------------
print("\n1. Applications payload matches the live schema")
# ---------------------------------------------------------------------------

cases = {
    "remote in location": make_job("Remote - US"),
    "remote only in description": make_job("United States", "This role is remote-friendly."),
    "no remote mention": make_job("United States", "Join our team."),
    "salary + unknown source": make_job("Remote", source="Remotive", salary_text="$150,000"),
    "workday posted text": make_job("Remote - US", posted_text="Posted 3 Days Ago"),
    "board publish date": make_job("Remote - US", published="2026-10-01T12:00:00Z"),
}
for label, job in cases.items():
    props = application_props(job, salary_min=150000 if "salary" in label else None)
    probs = schema_problems(props, APPLICATIONS_SCHEMA)
    check("no nonexistent/invalid property (%s)" % label, not probs, "; ".join(probs))

props = application_props(make_job("Remote"))
check("'Job Summary' is not sent", "Job Summary" not in props)
check("every REQUIRED_APP_PROPERTIES name exists in the schema snapshot",
      set(jsa.REQUIRED_APP_PROPERTIES) <= set(APPLICATIONS_SCHEMA),
      str(set(jsa.REQUIRED_APP_PROPERTIES) - set(APPLICATIONS_SCHEMA)))
check("Posted Date from board publish date",
      application_props(cases["board publish date"])["Posted Date"]["date"]["start"] == "2026-10-01")
wd = application_props(cases["workday posted text"])
check("Posted Date parsed from Workday 'Posted 3 Days Ago'",
      "Posted Date" in wd and wd["Posted Date Source"]["select"]["name"] == "Board publish date")

# ---------------------------------------------------------------------------
print("\n2. Companies stub payload matches the live schema")
# ---------------------------------------------------------------------------

_, sent = capture(jsa.create_company_page, "ExampleCo", "greenhouse / example")
probs = schema_problems(sent[0]["json"]["properties"], COMPANIES_SCHEMA)
check("no nonexistent/invalid property in Companies stub", not probs, "; ".join(probs))

# ---------------------------------------------------------------------------
print("\n3. Remote Status reflects score_remote(), never a constant")
# ---------------------------------------------------------------------------

REMOTE_MAP = getattr(jsa, "REMOTE_STATUS_BY_REMOTE_SCORE", None) or {}
expect = {
    "remote in location": (2, "Fully Remote"),
    "remote only in description": (1, None),
    "no remote mention": (0, None),
}
seen_values = set()
for label, (want_score, want_status) in expect.items():
    job = cases[label]
    got_score = jsa.score_remote(job)
    props = application_props(job)
    got_status = props.get("Remote Status", {}).get("select", {}).get("name")
    seen_values.add(got_status)
    check("%s: score_remote=%d" % (label, want_score), got_score == want_score,
          "got %r" % got_score)
    check("%s: Remote Status=%r" % (label, want_status), got_status == want_status,
          "got %r" % got_status)
check("Remote Status varies with the job (not hardcoded)", len(seen_values) > 1,
      "only saw %r" % seen_values)
check("no hardcoded Remote Status literal in write_to_notion",
      not re.search(r'"Remote Status"\s*:\s*\{\s*"select"\s*:\s*\{\s*"name"\s*:\s*"',
                    inspect.getsource(jsa.write_to_notion)))

# ---------------------------------------------------------------------------
print("\n4. Fit scoring v2")
# ---------------------------------------------------------------------------

STRONG = ("Senior Product Manager, Clinic Operations",
          "We build scheduling, intake, and capacity tools for outpatient clinics. You will own the "
          "roadmap and prioritization using usage data, run discovery with front desk staff, partner "
          "with compliance on patient privacy and role-based access, and "
          "lead cross-functional stakeholders through a migration. Fully remote, US. Base $160,000-$190,000.")
structural = {"remote_posture": "Structurally remote (no HQ)", "risk": "Low", "pto": "Strong",
              "health": "Strong", "verdict": "Applying", "domains": ["Wellness"]}
_tier1 = next(iter(fs.TIER_PRECEDENTS.get(1) or ["clinicflow"]))
r = fs.score_posting(*STRONG, salary_min=160000, company=structural, company_name=_tier1.title())
check("Tier 1 precedent applied (first Tier 1 company in the settings)", r["domain_tier"].startswith("Tier 1"), (_tier1, r["domain_tier"]))
check("a company with no precedent and no same-field tag is Tier 3", fs.domain_tier("Nowhere Co", ["Wellness"]).startswith("Tier 3"))
check("fit_10 is score/10 to one decimal", r["fit_10"] == round(r["score"] / 10, 1))

hybrid = fs.score_posting("Senior Product Manager", "This is a hybrid role, 3 days per week in our Austin office.",
                          salary_min=170000)
check("hybrid posting -> Skip, Tier C", hybrid["verdict"] == "Poor fit" and hybrid["tier"] == "C", hybrid["reasons"])
check("Skip reason quotes the posting", any("hybrid" in x.lower() for x in hybrid["reasons"]))

choice = fs.score_posting("Senior Product Manager", "You can work fully remote or hybrid from one of our hubs, your choice.")
check("'remote or hybrid' asks instead of skipping", choice["ask"] and not choice["hard_skip"], choice["reasons"])


mgr = fs.score_posting("Director of Product", "You will manage a team of product managers and own their performance reviews.")
check("people-manager language -> Skip", mgr["verdict"] == "Poor fit", mgr["reasons"])


oncall = fs.score_posting("Senior Product Manager", "Participates in an on-call rotation for production incidents.")
check("on-call -> Skip and Heavy schedule", oncall["verdict"] == "Poor fit" and oncall["schedule"] == "Heavy / on-call")
benefit = fs.score_posting("Senior Product Manager", "Benefits: private medical, 24/7 GP access, and a wellness stipend. Requirements: 8 years of product management.")
check("'24/7' in a benefits line is not on-call duty", not benefit["hard_skip"] and not any("24/7" in r for r in benefit["reasons"]), str(benefit["reasons"]))
duty = fs.score_posting("Senior Product Manager", "You will be available 24/7 for incident escalation during launches.")
check("'24/7' with duty wording still Skips", duty["verdict"] == "Poor fit" and any("24/7" in r for r in duty["reasons"]))

devtool = fs.score_posting("Senior Product Manager, Developer Platform", "Build SDKs and APIs for developers.", salary_min=180000)
check("dev tooling title -> Ask me first, not Skip", devtool["ask"] and not devtool["hard_skip"], devtool["reasons"])

travel = fs.score_posting("Senior Product Manager", "Remote. Travel up to 40% to customer sites.")
check("travel 40% -> Skip", travel["verdict"] == "Poor fit" and any("40%" in x for x in travel["reasons"]))
travel2 = fs.score_posting("Senior Product Manager", "Remote. Occasional travel, about 10%.")
check("travel 10% -> Ask (flag with number)", travel2["ask"] and not travel2["hard_skip"] and any("10%" in x for x in travel2["reasons"]))

# Countable minimums (2026-10-21): required items the user can't claim cap the score.
yrs = fs.score_posting("Senior Staff Product Manager", "Required qualifications: 9+ years of Product Management experience. Remote US. $203,000.", salary_min=203000)
check("9+ years PM required -> one missing minimum, Tier B cap (v3.8: 8+ is met)", yrs["score"] <= 69 and any("9+ years" in m for m in yrs["missing_minimums"]), yrs["breakdown"])
ok5 = fs.score_posting("Senior Product Manager", "Required: 5+ years of product management experience. Remote US. $180,000.", salary_min=180000)
check("5+ years PM is claimable", not ok5["missing_minimums"], ok5["breakdown"])
pref = fs.score_posting("Senior Product Manager", "Remote US. Nice to have: familiarity with card products. $180,000.", salary_min=180000)
check("card products as a nice-to-have is not a missing minimum", not pref["missing_minimums"], pref["breakdown"])

gap = fs.score_posting("Senior Product Manager, Growth",
                       "Required: 5+ years owning activation and retention funnels; expert in A/B testing and experimentation; monetization and pricing strategy experience.",
                       salary_min=180000)
check("gap penalty is capped", gap["parts"]["gaps"] <= fs.GAP_CAP)

evergreen = fs.score_posting(*STRONG, salary_min=160000, company=structural, evergreen=True)
check("suspected evergreen costs 5 points", evergreen["score"] == r["score"] - 5)

hyco = fs.score_posting("Senior Product Manager", "Fully remote role.", salary_min=170000,
                        company={"remote_posture": "Hybrid / RTO risk"})
check("hybrid company but the posting says remote -> Ask me first (v2.2 rule)",
      hyco["ask"] and not hyco["hard_skip"] and any("posting says remote" in x for x in hyco["reasons"]))
hyco2 = fs.score_posting("Senior Product Manager", "Requirements: 8 years of product management.", salary_min=170000,
                         company={"remote_posture": "Hybrid / RTO risk"})
check("hybrid company and the posting says nothing about remote -> Skip", hyco2["verdict"] == "Poor fit")
hyco3 = fs.score_posting("Senior Product Manager", "Requirements: 8 years of product management.", salary_min=170000,
                         company={"remote_posture": "Hybrid / RTO risk"}, remote_hint=True)
check("hybrid company, remote known from the location field -> Ask me first", hyco3["ask"] and not hyco3["hard_skip"])
hyco4 = fs.score_posting("Senior Product Manager", "Remote-first team. This role is hybrid, 3 days per week in Austin.",
                         salary_min=170000, company={"remote_posture": "Hybrid / RTO risk"})
check("hybrid company and hybrid wording in the posting -> Skip even with remote words", hyco4["verdict"] == "Poor fit")
hyco5 = fs.score_posting("Senior Product Manager", "Fully remote role.", salary_min=170000,
                         company={"remote_posture": "Hybrid / RTO risk", "verdict": "Do not pursue"})
check("verified mandate (company Do not pursue) still Skips a remote posting", hyco5["verdict"] == "Poor fit")
weak2 = fs.score_posting("Senior Product Manager", "Fully remote role.", salary_min=170000,
                         company={"remote_posture": "Structurally remote (no HQ)", "pto": "Weak", "health": "Weak"})
check("Weak on both PTO and health -> Skip", weak2["verdict"] == "Poor fit")
weak1 = fs.score_posting("Senior Product Manager", "Fully remote role.", salary_min=140000,
                         company={"remote_posture": "Structurally remote (no HQ)", "pto": "Weak", "health": "Strong"})
check("one Weak + base under the pay target -> Skip", weak1["verdict"] == "Poor fit")
weak1ok = fs.score_posting("Senior Product Manager", "Fully remote role.", salary_min=170000,
                           company={"remote_posture": "Structurally remote (no HQ)", "pto": "Weak", "health": "Strong"})
check("one Weak + base over the pay target -> not a hard Skip", not weak1ok["hard_skip"], weak1ok["reasons"])

check("level: Principal = 15", fs.level_score("Principal Product Manager") == 15)
check("level: PM II = 5", fs.level_score("Product Manager II, Payments") == 5)
check("pay: none posted = 6 with note", fs.pay_score(None)[0] == 6)
check("label_reason stamps the rubric version", fs.RUBRIC_VERSION in fs.label_reason(r, date(2026, 10, 21)))
check("Workday 'Posted 30+ Days Ago' is approximate", fs.workday_posted_to_date("Posted 30+ Days Ago", date(2026, 10, 21)) == ("2026-09-21", True))
check("Workday 'Posted Today'", fs.workday_posted_to_date("Posted Today", date(2026, 10, 21)) == ("2026-10-21", False))
check("legacy score_job still callable (industry flag + salary)",
      jsa.score_job(make_job("Remote", salary_text="$150,000"))[1] == "Clear")

# ---------------------------------------------------------------------------
print("\n4b. LinkedIn alert email parser")
# ---------------------------------------------------------------------------

import linkedin_alerts as la  # noqa: E402
_fixture = pathlib.Path(__file__).parent / "fixtures" / "linkedin_alert_sample.txt"
_leads = la.parse_alert_text(_fixture.read_text(), date(2026, 10, 21))
check("parses every job card with a View job link", len(_leads) == 5, str(len(_leads)))
_crlf = la.parse_alert_text(_fixture.read_text().replace("\n", "\r\n"), date(2026, 10, 21))
check("CRLF line endings (as delivered by Gmail) parse to the same cards",
      [j["id"] for j in _crlf] == [j["id"] for j in _leads] and _crlf[0]["company"] == "Maple Learning", str(len(_crlf)))
check("title / company / location from the first three lines",
      _leads[0]["title"].startswith("Principal Product Manager, Platform") and _leads[0]["company"] == "Maple Learning"
      and _leads[0]["location"] == "United States")
check("badge lines ignored, 'Your job alert for' header dropped", _leads[2]["company"] == "Harborview Health" and _leads[3]["location"] == "Springfield, OH")
check("clean URL without tracking params", _leads[0]["url"] == "https://www.linkedin.com/jobs/view/4000000001/")
check("posting_key matches the tracked tracking-param URL",
      jsa.posting_key(_leads[0]["url"]) == jsa.posting_key("https://www.linkedin.com/comm/jobs/view/4000000001/?trackingId=abc"))
check("alert date stored as approximate posted date",
      jsa.posted_date_properties(_leads[0], None, date(2026, 10, 21))["Posted Date Source"]["select"]["name"] == "Board approximate")
check("city-only LinkedIn locations fail the location filter", jsa.location_rejection_reason("Springfield, OH") is not None)
check("LinkedIn rows never auto-closed by the stale check", jsa._board_scope(_leads[0]["url"])[0] in ("linkedin.com", "www.linkedin.com"))
_listing = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
            b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"', b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Bin"']
check("All Mail and Trash found by special-use flag (renamed Trash folder honoured)",
      la.special_mailboxes(_listing) == {"All": '"[Gmail]/All Mail"', "Trash": '"[Gmail]/Bin"'})
check("empty LIST response falls back to Gmail's default folder names",
      la.special_mailboxes([]) == {"All": '"[Gmail]/All Mail"', "Trash": '"[Gmail]/Trash"'})
check("no credentials -> empty list, no exception",
      (lambda: (setattr(la, "GMAIL_ADDRESS", ""), la.fetch_linkedin_alerts())[1])() == [])

# ---------------------------------------------------------------------------
print("\n4c. Lead resolver (LinkedIn card -> company's own posting, zero tokens)")
# ---------------------------------------------------------------------------

import lead_resolver as lr  # noqa: E402

check("company names normalise across legal suffixes",
      lr.norm_company("Harborline, Inc") == lr.norm_company("Harborline") == "harborline"
      and lr.norm_company("Moody's Corporation") == "moodys")
check("same title with different punctuation is exact",
      lr.title_match("Principal Product Manager, Agentic AI", "Principal Product Manager - Agentic AI") == 1.0)
check("level words must agree (Senior PM is not PM)",
      lr.title_match("Product Manager", "Senior Product Manager") == 0.0
      and lr.title_match("Staff Product Manager, Search", "Principal Product Manager, Search") == 0.0)
check("role nouns must agree (Owner is not Manager)",
      lr.title_match("Senior Product Manager", "Senior Product Owner") == 0.0)
check("one title inside the other counts as a near match",
      lr.title_match("Principal Product Manager", "Principal Product Manager, Platform") == 0.9)
check("Sr. and Senior are the same word",
      lr.title_match("Sr. Product Manager, Payments", "Senior Product Manager, Payments") == 1.0)
check("slug guesses from a multi-word name",
      lr.company_slug_guesses("Chainlink Labs")[:3] == ["chainlinklabs", "chainlink-labs", "chainlink"])
check("board URL -> platform and slug", lr.board_from_url("https://jobs.ashbyhq.com/harborline") == ("ashby", "harborline"))

_board = [
    {"title": "Principal Product Manager, Hub", "company": "Harborline", "url": "https://jobs.ashbyhq.com/harborline/1", "location": "Remote - US"},
    {"title": "Principal Product Manager, Desktop", "company": "Harborline", "url": "https://jobs.ashbyhq.com/harborline/2", "location": "Remote - US"},
    {"title": "Staff Product Manager, Search", "company": "Harborline", "url": "https://jobs.ashbyhq.com/harborline/3", "location": "Remote - US"},
    {"title": "Staff Product Manager, Search", "company": "Harborline", "url": "https://jobs.ashbyhq.com/harborline/4", "location": "London"},
]
_status, _job, _cands = lr.best_match("Principal Product Manager", _board)
check("bare title against two suffixed variants is ambiguous, both offered",
      _status == "ambiguous" and _job is None and len(_cands) == 2)
_status, _job, _cands = lr.best_match("Staff Product Manager, Search", _board, prefer=jsa._prefer_us_remote)
check("same title in two locations: the US-remote copy is preferred",
      _status == "exact" and _job["url"].endswith("/3"))
_index = lr.build_index(_board + [{"title": "Senior PM", "company": "Harborline, Inc", "url": "x", "location": "Remote"}])
check("index groups company name variants together", len(_index) == 1 and len(_index["harborline"]) == 5)
_r = lr.resolve("Harborline, Inc", "Staff Product Manager, Search", index=_index, prefer=jsa._prefer_us_remote,
                today=date(2026, 10, 21), probe=False)
check("role already in today's fetch -> in_run, board copy returned",
      _r["status"] == "in_run" and _r["job"]["url"].endswith("/3"))
_r = lr.resolve("Nowhere Labs", "Principal Product Manager", index=_index, today=date(2026, 10, 21), cache={}, probe=False)
check("unknown company, no probe -> no_board with a Notes stamp",
      _r["status"] == "no_board" and _r["note"].startswith(lr.BOARD_STAMP))
check("'Chainlink Labs' and 'Chainlink' are the same company", lr.norm_company("Chainlink Labs") == lr.norm_company("Chainlink"))
_cache = {lr.norm_company("Nowhere Labs"): {"platform": None, "slug": None, "checked": "2026-10-15"}}
_r = lr.resolve("Nowhere Labs", "Principal Product Manager", today=date(2026, 10, 21), cache=_cache, probe=True)
check("a recent cached miss is not re-probed", _r["status"] == "no_board" and "checked 2026-10-15" in _r["note"])
_lead = {"source": "LinkedIn", "id": "linkedin-1", "title": "Staff Product Manager, Search", "company": "Harborline, Inc",
         "url": "https://www.linkedin.com/jobs/view/1/", "location": "United States", "salary_text": "",
         "description": "", "published": "2026-10-21", "published_approx": True}
lr.apply_match(_lead, dict(_board[2], description="Full posting text", published="2026-10-01", ats_platform="ashby", ats_slug="harborline"))
check("apply_match keeps the LinkedIn id, records the alert link, takes the board's facts",
      _lead["id"] == "linkedin-1" and _lead["linkedin_url"].startswith("https://www.linkedin.com/")
      and _lead["url"].endswith("/3") and _lead["description"] == "Full posting text"
      and _lead["published"] == "2026-10-01" and _lead["published_approx"] is False and _lead["source"] == "LinkedIn")
_lead["notes_extra"] = "Board lookup: matched ashby / harborline (candidate probe) 2026-10-21."
check("Notes carry the alert link and the board-lookup stamp",
      "Found via LinkedIn alert" in jsa.lead_notes(_lead) and lr.BOARD_STAMP in jsa.lead_notes(_lead))
check("resolve_tracked_leads filters on Source, empty snapshot, and the stamp",
      all(s in inspect.getsource(jsa.resolve_tracked_leads) for s in ('"equals": "LinkedIn"', '"is_empty": True', "BOARD_STAMP")))
_title_only = application_props(make_job("United States", description="", source="LinkedIn"))
check("a title-only row is tagged NO SNAPSHOT at write time (so it is rescored once text arrives)",
      _title_only["Score Breakdown"]["rich_text"][0]["text"]["content"].startswith(jsa.NO_SNAPSHOT_TAG))
_with_text = application_props(make_job("Remote - US", description="Requirements: 8 years of product management."))
check("a row with posting text is not tagged",
      not _with_text["Score Breakdown"]["rich_text"][0]["text"]["content"].startswith(jsa.NO_SNAPSHOT_TAG))
check("rescore_board_matched sweeps matched rows once (stamp filter)",
      all(s in inspect.getsource(jsa.rescore_board_matched) for s in ('": matched"', "SCORED_ON_TEXT", "Posting Snapshot")))

# ---------------------------------------------------------------------------
print("\n5. Rescoring never overrides the user's verdict")
# ---------------------------------------------------------------------------

def _page(verdict, label, snapshot="Fully remote. Hybrid 3 days per week in office.", salary=170000):
    return {"id": "p1", "properties": {
        "Role": {"title": [{"plain_text": "Senior Product Manager"}]},
        "Company": {"rich_text": [{"plain_text": "ExampleCo"}]},
        "Posting Snapshot": {"rich_text": [{"plain_text": snapshot}]},
        "Base Salary": {"number": salary},
        "Posting Health": {"select": None},
        "Company Profile": {"relation": []},
        "Overall Verdict": {"select": {"name": verdict} if verdict else None},
        "Label Reason": {"rich_text": [{"plain_text": label}] if label else []},
        "Domain Tier": {"select": None},
    }}


def rescore_with(pages):
    real_q = jsa.query_open_rows
    jsa.query_open_rows = lambda extra_filter=None: pages
    try:
        _, sent = capture(jsa.rescore_tracker, date(2026, 10, 21))
    finally:
        jsa.query_open_rows = real_q
    patches = [s["json"]["properties"] for s in sent if s["json"] and "properties" in s["json"] and "parent" not in s["json"]]
    return patches


p = rescore_with([_page("Applying", "I like this one")])[0]
check("Pursue row keeps its verdict and reason", "Overall Verdict" not in p and "Label Reason" not in p)
check("Pursue row still gets score, tier, evidence", {"Role Fit Score", "Research Tier", "Fit Evidence"} <= set(p))
p = rescore_with([_page("Watch", "the user: wait for the next cohort")])[0]
check("v3.3: retired Watch with the user's own note gets an agent verdict", p.get("Overall Verdict", {}).get("select", {}).get("name") in fs.AGENT_VERDICTS, str(p.get("Overall Verdict")))
check("...and the note is kept", "Label Reason" not in p)
p = rescore_with([_page("Passed", "the user: not for me")])[0]
check("v3.3: Pass keeps its verdict and reason", "Overall Verdict" not in p and "Label Reason" not in p)
p = rescore_with([_page("Ask me first", "No screenable qualifications. Screened 2026-10-19 by weekly triage")])[0]
check("machine-labelled row is re-decided (hybrid -> Skip)", p.get("Overall Verdict", {}).get("select", {}).get("name") == "Poor fit")
p = rescore_with([_page(None, "", snapshot="")])[0]
check("no snapshot: breakdown says so", p["Score Breakdown"]["rich_text"][0]["text"]["content"].startswith("NO SNAPSHOT"))
p = rescore_with([_page(None, "", snapshot="", salary=100000)])[0]
check("no snapshot but base under floor still Skips", p.get("Overall Verdict", {}).get("select", {}).get("name") == "Poor fit")
for pr in rescore_with([_page(None, "")]):
    probs = schema_problems(pr, APPLICATIONS_SCHEMA)
    check("rescore patch matches schema", not probs, "; ".join(probs))

# ---------------------------------------------------------------------------
print("\n6. Optional: live schema check (read-only GET)")
# ---------------------------------------------------------------------------

token = os.environ.get("NOTION_TOKEN", "")


def live_schema(db_id):
    import requests
    r = requests.get("https://api.notion.com/v1/databases/%s" % db_id, timeout=15,
                     headers={"Authorization": "Bearer %s" % token,
                              "Notion-Version": "2022-06-28"})
    r.raise_for_status()
    out = {}
    for name, p in r.json()["properties"].items():
        spec = {"type": p["type"]}
        if p["type"] in ("select", "status"):
            spec["options"] = {o["name"] for o in p[p["type"]]["options"]}
        out[name] = spec
    return out


if not token:
    print("  [SKIP] NOTION_TOKEN not set")
else:
    try:
        live_apps = live_schema(jsa.NOTION_DATABASE_ID)
        live_cos = live_schema(jsa.NOTION_COMPANIES_DATABASE_ID)
    except Exception as e:  # network blocked, offline, etc.
        print("  [SKIP] live check unavailable: %s" % e)
    else:
        for name, spec in APPLICATIONS_SCHEMA.items():
            live = live_apps.get(name)
            ok = live is not None and live["type"] == spec["type"] and \
                spec.get("options", set()) <= live.get("options", set())
            check("live Applications has %r as snapshot says" % name, ok, "live=%r" % live)
        for name, spec in COMPANIES_SCHEMA.items():
            live = live_cos.get(name)
            ok = live is not None and live["type"] == spec["type"] and \
                spec.get("options", set()) <= live.get("options", set())
            check("live Companies has %r as snapshot says" % name, ok, "live=%r" % live)

# --- v2.4 (2026-10-21): stale snapshots and access vocabulary --------------
check("v2.4: RUBRIC_VERSION moved past v2.3", fs.RUBRIC_VERSION not in ("v2.0", "v2.1", "v2.2", "v2.3"))
escaped_intro = "&lt;p&gt;Linus Yale patented the modern pin tumbler lock in 1861, and hotels took to it immediately.&lt;/p&gt;"
check("stale snapshot: HTML-escaped capture is replaced", jsa.snapshot_is_stale(escaped_intro, "Linus Yale ... What we need from you: 7+ years"))
check("stale snapshot: intro-only capture is replaced by a longer fresh one",
      jsa.snapshot_is_stale("Linus Yale patented the modern pin tumbler lock in 1861.", "x" * 400))
check("stale snapshot: a good capture is kept",
      not jsa.snapshot_is_stale("Intro [...] What we need from you: 7+ years of product management", "Intro [...] What we need from you: 7+ years of product management experience"))
check("stale snapshot: empty stored text is filled", jsa.snapshot_is_stale("", "fresh text"))
check("stale snapshot: nothing fresh means keep", not jsa.snapshot_is_stale(escaped_intro, ""))
check("rescore_page scores cleaned text", "clean_posting_text(_rt(p, \"Posting Snapshot\"))" in inspect.getsource(jsa.rescore_page))
check("refresh forces a rescore when it replaces a snapshot", "SNAPSHOT_REFRESHED_TAG" in inspect.getsource(jsa.refresh_open_rows))

# --- v2.5 (2026-10-24): audit fixes --------------------------------------
print("\n7. v2.5: stamps protected, Ask on Tier A only, 48-hour rule, Skip rows closed, aggregators, years")
check("RUBRIC_VERSION is v2.5 or later so the 8am run rescores", fs.RUBRIC_VERSION >= "v2.5")
nine = fs.score_posting("Senior Product Manager", "Requirements: 9+ years of product management experience. Fully remote.", salary_min=180000)
check("9+ years PM still counts as a miss", any("9+ years" in m for m in nine["missing_minimums"]), str(nine["missing_minimums"]))

# v3.3 (Nov 1, 2026): every row gets a verdict. The bug: strong
# near-misses (one missing minimum, capped at 69) sat blank at the top of the list.
near = fs.score_posting("Senior Product Manager, Clinic Operations",
    "Clinic scheduling and intake workflows for outpatient practices; discovery with front desk staff; "
    "evidence-based prioritization; cross-functional leadership; launch readiness. "
    "Requirements: 9+ years of product management experience. Fully remote. Base $190,000. "
    "Benefits: medical, dental, 401(k).",  # v3.7: no benefits plus one flat figure is a staffing signal
    salary_min=190000, company={"remote_posture": "Structurally remote (no HQ)", "risk": "Low", "pto": "Strong", "health": "Strong", "domains": ["Wellness"]})
check("a strong fit missing one minimum names it in the label", "Missing 1 required" in fs.label_reason(near, date(2026, 11, 1)), fs.label_reason(near))
for title, text, sal in [("Product Manager", "Remote.", None), ("Senior Product Manager", "Fully remote. Base $170,000.", 170000),
                         ("Associate Product Manager", "Remote-friendly; must be based in the United States.", None), STRONG + (160000,)]:
    rr = fs.score_posting(title, text, salary_min=sal)
    check("v3.3: verdict is never blank (%s)" % title, rr["verdict"] in fs.AGENT_VERDICTS, str(rr["verdict"]))
nopay = fs.score_posting("Senior Product Manager", "Fully remote. Legacy modernization.", salary_min=None)
check("v3.3: no posted pay is a soft Skip that stays open", nopay["verdict"] == "Poor fit" and not nopay["hard_skip"]
      and fs.label_reason(nopay).startswith("Poor fit (no base pay posted), left open"), fs.label_reason(nopay))
check("v3.3: soft Skip label matches SOFT_SKIP_LABEL", bool(jsa.SOFT_SKIP_LABEL.search(fs.label_reason(nopay))))
check("v3.3: hard Skip label does not", not jsa.SOFT_SKIP_LABEL.search("Skip: hybrid. Scored 2026-11-01 by agent v3.3."))
check("v3.6: hard Poor fit label does not", not jsa.SOFT_SKIP_LABEL.search("Poor fit: hybrid. Scored 2026-11-02 by agent v3.6."))
catch_a = fs.score_posting("Senior Product Manager, Clinic Operations",
    "Remote-friendly, must be based in the US. Clinic scheduling and intake workflows for outpatient practices; "
    "discovery with front desk staff; evidence-based prioritization; cross-functional leadership; "
    "launch readiness. Fully remote.", salary_min=190000, company={"remote_posture": "Structurally remote (no HQ)", "risk": "Low", "pto": "Strong", "health": "Strong", "domains": ["Wellness"]})
check("Tier A row with an ask reason carries the reason in its label", "Needs your call:" in fs.label_reason(catch_a), fs.label_reason(catch_a))

# Rescore keeps the refresh's screening text; the verdict is the agent's
screened = ("Tier A, 78/100. Clinic scheduling tools [E03]. Scored 2026-10-22 by agent v2.4. "
            "Qualifications screened 2026-10-23 by daily refresh: passes every stated minimum.")
p = rescore_with([_page("Watch", screened)])[0]
check("refresh-screened Watch row gets an agent verdict", p.get("Overall Verdict", {}).get("select", {}).get("name") in fs.AGENT_VERDICTS, str(p.get("Overall Verdict")))
lbl = p["Label Reason"]["rich_text"][0]["text"]["content"]
check("refresh-screened label text is kept", "Qualifications screened 2026-10-23 by daily refresh" in lbl, lbl)
p2 = rescore_with([_page("Possible fit", screened)])[0]
check("refresh's own Your call on a screened row stands", "Overall Verdict" not in p2, str(p2.get("Overall Verdict")))
check("...with the agent stamp refreshed to the current version", f"by agent {fs.RUBRIC_VERSION}" in lbl and "by agent v2.4" not in lbl, lbl)
check("merge_label replaces the stamp in place",
      jsa.merge_label("Needs your call: x. Scored 2026-10-20 by agent v2.3. Qualifications screened 2026-10-21 by daily refresh: ok.",
                      "whatever Scored 2026-10-24 by agent v2.5.") ==
      "Needs your call: x. Qualifications screened 2026-10-21 by daily refresh: ok. Scored 2026-10-24 by agent v2.5.")
check("'by daily refresh' counts as machine-written (so the refresh may re-stamp), never as the user's",
      bool(jsa.MACHINE_LABEL.search("Qualifications screened 2026-10-23 by daily refresh: ok")))
for old in ("Ask me first", "Watch (no decision)"):
    p = rescore_with([_page(old, "Needs your call: remote with a catch. Scored 2026-10-22 by agent v2.4.",
                            snapshot="Remote-friendly; must be based in the Bay Area. Associate level.", salary=None)])[0]
    check("v3.3: machine %s is replaced by an agent verdict" % old,
          p.get("Overall Verdict", {}).get("select", {}).get("name") in fs.AGENT_VERDICTS, str(p.get("Overall Verdict")))
    check("...and the patch matches schema", not schema_problems(p, APPLICATIONS_SCHEMA), "; ".join(schema_problems(p, APPLICATIONS_SCHEMA)))
legacy = _page("Ask me first", "Ask me first: strong adjacency, but requires 10+ years of PM experience.",
               snapshot="Remote-friendly; must be based in the Bay Area. Associate level.", salary=None)
legacy["properties"]["Notes"] = {"rich_text": [{"plain_text": "Captured by recurring job search on 2026-10-21."}]}
p = rescore_with([legacy])[0]
check("legacy capture-process Ask is replaced, label included", p.get("Overall Verdict", {}).get("select", {}).get("name") in fs.AGENT_VERDICTS and "Label Reason" in p)
mine = _page("Ask me first", "Ask me first: I want to read this one myself.")
p = rescore_with([mine])[0]
check("...the user's own note on an Ask is kept while the verdict moves", "Label Reason" not in p and p.get("Overall Verdict", {}).get("select", {}).get("name") in fs.AGENT_VERDICTS)
old48 = _page("Watch (no decision)", "No decision in 48 hours (asked 2026-10-24); dropped to Watch by agent 2026-10-26. Tier A, 79/100. Scored 2026-10-31 by agent v3.2.")
p = rescore_with([old48])[0]
check("v3.3: a retired 48-hour label is replaced, not kept (dry run, Nov 1)", "No decision in 48 hours" not in p["Label Reason"]["rich_text"][0]["text"]["content"],
      p["Label Reason"]["rich_text"][0]["text"]["content"][:80])
check("v3.3: the 48-hour rule is gone", not hasattr(jsa, "expire_unanswered_asks") and not hasattr(jsa, "NO_DECISION_VERDICT"))
real_q = jsa.query_open_rows
def _yc(score):
    pg = _page("Possible fit", "Your call (moderate fit).")
    pg["properties"]["Role Fit Score"] = {"number": score}
    return pg
try:
    jsa.query_open_rows = lambda extra_filter=None: [_yc(5.5), _yc(6.9)]
    waiting = jsa.list_your_call_rows()
finally:
    jsa.query_open_rows = real_q
check("Sunday digest lists Your call rows, best first", [w[2] for w in waiting] == [6.9, 5.5], str(waiting))

# New hard-rule fails land Closed; Skip rows get closed
hybrid = make_job("Remote (US)", description="This role is hybrid, 3 days per week in our Austin office. 5+ years product management.")
props_skip, _ = capture(jsa.write_to_notion, hybrid, fs.score_posting(hybrid["title"], hybrid["description"], salary_min=170000), "Clear", 170000, company_page_id="c1")
sk = [s_["json"]["properties"] for s_ in _ if s_["json"] and "parent" in s_["json"]]
check("hard-rule Skip is written with Status Closed", sk and sk[0]["Status"]["status"]["name"] == "Closed" and sk[0]["Overall Verdict"]["select"]["name"] == "Poor fit",
      str(sk[0]["Status"] if sk else sk))
props_ok, _ = capture(jsa.write_to_notion, make_job("Remote (US)", description="Fully remote. Legacy modernization. 5+ years product management."),
                      fs.score_posting("Senior Product Manager", "Fully remote. Legacy modernization. 5+ years product management.", salary_min=170000), "Clear", 170000, company_page_id="c1")
ok_ = [s_["json"]["properties"] for s_ in _ if s_["json"] and "parent" in s_["json"]]
check("a non-Skip row is still written Interested", ok_ and ok_[0]["Status"]["status"]["name"] == "Interested")
try:
    jsa.query_open_rows = lambda extra_filter=None: [_page("Poor fit", "Skip: hybrid. Scored 2026-10-22 by agent v2.4."), _page("Poor fit", "the user: no"),
                                                     _page("Passed", "the user: not for me"),
                                                     _page("Poor fit", "Skip (no base pay posted), left open. Tier C, 49/100. Scored 2026-11-01 by agent v3.3.")]
    n_closed, sent = capture(jsa.close_skipped_rows, date(2026, 10, 24))
finally:
    jsa.query_open_rows = real_q
check("close_skipped_rows closes hard Skips and Pass, leaves a soft Skip open", n_closed == 3 and all(s_["json"]["properties"]["Status"]["status"]["name"] == "Closed" for s_ in sent if s_["json"]), str(n_closed))

# Aggregators
import lead_resolver as lr2
check("Jobgether is an aggregator", lr2.is_aggregator("Jobgether") and lr2.is_aggregator("jobs via Dice"))
check("Bluefin Labs is not", not lr2.is_aggregator("Bluefin Labs"))
check("get_rejection_reason rejects aggregator 'companies'", "aggregator" in (jsa.get_rejection_reason(make_job("Remote (US)", company="Jobgether")) or ""))
r = lr2.resolve("Jobgether", "Principal Product Manager", index={}, today=date(2026, 10, 24), cache={}, probe=False)
check("lead_resolver never probes an aggregator board", r["status"] == "none" and "aggregator" in r["note"], r["note"])
check("Pathmark and Bankbridge are out of CONFIRMED_COMPANIES", not [c for c in __import__("ats_tools").CONFIRMED_COMPANIES if c["name"] in ("Pathmark", "Bankbridge")])
# digest freshness
job_fresh = make_job("Remote (US)", description="x"); job_fresh["published"] = "2026-10-20"
check("posting_age_days reads the board date", jsa.posting_age_days(job_fresh, None, date(2026, 10, 24)) == 4)
check("send_text_digest is silent when the gateway isn't configured", "return  # optional feature" in inspect.getsource(jsa.send_text_digest))

print("\n8. v2.8: an excluded industry is a hard Skip")
v, rs = fs.hard_screen("Senior Product Manager", "Fully remote. Own onboarding for new customers.", 180000, company_name="Sentrybase")
check("a clean posting is not flagged as an excluded industry", not any(fs.EXCLUDED_INDUSTRY_LABEL in r for r in rs), rs)

print("\n9. v2.9: a gap counts as required if any mention is near requirement wording")
qtext = (HERE / "fixtures" / "growth_posting_sample.txt").read_text() if "HERE" in globals() else (pathlib.Path(__file__).parent / "fixtures" / "growth_posting_sample.txt").read_text()
r = fs.score_posting("Lead Product Manager - Growth, Globex (Remote)", qtext, 165000, company_name="Globex", remote_hint=True)
check("Globex Growth: two required misses cap it below Tier A", r["tier"] != "A", r["breakdown"])

print("\n10. v3.0: fresher good fits rank higher")
ftext = "Fully remote. Own the clinic scheduling workflow for outpatient practices; partner with engineering, design, and compliance. 5+ years of product management. Base pay $180,000 - $220,000."
base = fs.score_posting("Senior Product Manager, Operations", ftext, 180000, company_name="Acme", remote_hint=True)
new = fs.score_posting("Senior Product Manager, Operations", ftext, 180000, company_name="Acme", remote_hint=True, age_days=3)
old = fs.score_posting("Senior Product Manager, Operations", ftext, 180000, company_name="Acme", remote_hint=True, age_days=80)
check("a 3-day-old posting outscores the same posting with unknown age", new["score"] == min(100, base["score"] + 5), (base["score"], new["score"]))
check("an 80-day-old posting scores 10 lower", old["score"] == max(0, base["score"] - 10), (base["score"], old["score"]))
check("freshness shows in the breakdown", "freshness" in new["breakdown"] and "freshness" in old["breakdown"])
check("freshness bands: 14 days +3, 30 days 0, 45 days -5", [fs.freshness_points(d)[0] for d in (14, 30, 45)] == [3, 0, -5])
check("rescore_page passes the row's Posted Date age", "age_days=_row_age_days(p, today)" in inspect.getsource(jsa.rescore_page))
check("rows crossing a freshness band edge are rescored daily", jsa.freshness_edge_days() == [8, 9, 15, 16, 31, 32, 61, 62], jsa.freshness_edge_days())
check("rescore_tracker queries the freshness edges", "freshness_edge_filters(today)" in inspect.getsource(jsa.rescore_tracker))
check("evaluate_job passes the posting age", "age_days=posting_age_days(" in inspect.getsource(jsa.evaluate_job))

print("\n11. v3.1 fixes (posting URL, data modeling false positive)")
import ats_tools as _at
check("redundant gh_jid query is dropped when the id is in the path",
      _at.clean_posting_url("https://example.com/careers/123/?gh_jid=123", 123) == "https://example.com/careers/123/")
check("a gh_jid-only URL keeps its query",
      _at.clean_posting_url("https://acme.com/careers?gh_jid=123", 123) == "https://acme.com/careers?gh_jid=123")
bw = "RESPONSIBILITIES Use AI tools to accelerate spec writing, competitive analysis, data modeling, and rapid prototyping This is an all-remote team. WHAT YOU BRING 4+ years experience in product management"
check("'data modeling' as an AI-tools task is not a missing minimum", not fs.missing_minimums(bw), fs.missing_minimums(bw))

print("\n12. v3.2: unresearched companies score lower and get rescored")
check("an unresearched company scores 5 of 20", fs.company_score({})[0] == 5)
check("rescore_tracker picks up rows still waiting on company research", "UNRESEARCHED_NOTE" in inspect.getsource(jsa.rescore_tracker))

# ---------------------------------------------------------------------------
failed = [n for n, ok in RESULTS if not ok]
print("\n%d checks, %d failures" % (len(RESULTS), len(failed)))
if failed:
    print("FAILED: " + "; ".join(failed))
    sys.exit(1)
