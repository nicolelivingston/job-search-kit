"""Tests for evergreen / repost detection and the already-tracked check.

Run:  python3 agent_tests/test_posting_health.py

Cases come from the 2026-10-16 tracker audit: Northwind's US + Canada twins were
being flagged as reposts, tracker-seeded rows were counted as posting IDs, and
closed/rejected rows came back as new Interested rows. No network calls.
"""

import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import job_search_agent as jsa   # noqa: E402

TODAY = date(2026, 10, 16)
T = TODAY.isoformat()
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
    if detail and not ok:
        print("         %s" % detail)


def job(id_, loc, title="Senior Product Manager, Consumer Payments", company="northwind",
        published="2026-10-08", url=None):
    return {"id": id_, "location": loc, "title": title, "company": company,
            "published": published,
            "url": url or f"https://job-boards.greenhouse.io/{company}/jobs/{id_.split('-')[-1]}"}


def run(jobs, history=None):
    h = history if history is not None else {}
    key = None
    for j in jobs:
        key = jsa.record_sighting(h, j, T)
    return jsa.assess_posting_health(h, key, TODAY, jobs[-1])


print("1. Country twins are not reposts")
note, flag, skip, _ = run([job("gh-northwind-9100003003", "Remote US"),
                           job("gh-northwind-9100005003", "Remote Canada")])
check("US + Canada twin not flagged", not flag, note)

print("2. Tracker-seeded ids don't count as posting IDs")
h = {"northwind::senior product manager, consumer payments": {
    "ids": {"tracker-3f74ad72": "2026-10-12"}, "locations": {}}}
note, flag, _, _ = run([job("gh-northwind-9100003003", "Remote US"),
                        job("gh-northwind-9100005003", "Remote Canada")], h)
check("the old false positive (3 IDs, 2 locations) now clears", not flag, note)

print("3. Real repost in the same location is flagged")
h = {"acme::senior product manager": {
    "ids": {"gh-acme-100001": "2026-10-01"}, "locations": {"remote us": "2026-10-01"},
    "id_locs": {"gh-acme-100001": "remote us"}}}
note, flag, skip, _ = run([job("gh-acme-100777", "Remote US", title="Senior Product Manager",
                               company="acme")], h)
check("second ID, same location, flags", flag and "reposted" in (note or ""), note)
check("two IDs does not skip the write", not skip)

print("4. Age uses original publish date")
note, flag, _, _ = run([job("gh-northwind-7694938003", "Remote US",
                            title="Staff Product Manager, Northwind Bank", published="2026-04-14")])
check("185 days open flags", flag and "185 days" in (note or ""), note)
note, flag, _, _ = run([job("gh-northwind-7780490003", "Remote US",
                            title="Director, Product Management", published="2026-06-25")])
check("113 days open gets an age note but no flag", (not flag) and "113 days" in (note or ""), note)
note, flag, _, _ = run([job("gh-x-1", "Remote US", title="PM", company="x", published="")])
check("missing publish date: no note, no flag", note is None and not flag)

print("5. City spray, but not country-remote labels")
jobs = [job(f"lever-veeva-{i}", loc, title="Product Manager - RIM", company="veeva")
        for i, loc in enumerate(["Boston, MA", "Radnor, PA", "Toronto", "Pleasanton, CA"])]
note, flag, _, _ = run(jobs)
check("4 cities flags", flag and "4 different locations" in (note or ""), note)
jobs = [job(f"gh-y-{i}", loc, title="PM", company="y")
        for i, loc in enumerate(["Remote US", "Remote - Canada", "Remote UK", "Remote, Mexico"])]
note, flag, _, _ = run(jobs)
check("4 country-remote labels don't flag", not flag, note)

print("6. Workday re-post suffix and pipeline titles")
z = "https://exampleco.wd5.myworkdayjobs.com/Exampleco_External/job/Remote-USA/Principal-Product-Manager--Listing-Product_P100001-2"
note, flag, _, _ = run([job("workday-exampleco-x", "Remote-USA", title="Principal PM, Listing",
                            company="exampleco", published="", url=z)])
check("_P100001-2 flags", flag and "-2" in (note or ""), note)
note, flag, _, _ = run([job("workday-exampleco-y", "Remote-USA", title="Principal PM, Rental",
                            company="exampleco", published="", url=z[:-2] + "-1")])
check("-1 suffix does not flag", not flag, note)
for t in ("Product Manager (Senior/Staff/Principal)",
          "Open Call for Founders / Founding Teams - Product Management and Engineering"):
    note, flag, _, _ = run([job("gh-z-9", "Remote US", title=t, company="z")])
    check(f"pipeline title flags: {t[:40]}", flag, note)
note, flag, _, _ = run([job("gh-z-8", "Remote US", title="Senior PM, Data Pipeline", company="z")])
check("'Data Pipeline' title does not flag", not flag, note)

print("7. posting_key matches the same job across URL shapes")
pk = jsa.posting_key
check("greenhouse board vs careers wrapper",
      pk("https://job-boards.greenhouse.io/quillco/jobs/9100001")
      == pk("https://quillco.careers/job/?gh_jid=9100001"))
check("boxco two domains",
      pk("https://jobs.boxco.com/listing/9100002?gh_jid=9100002")
      == pk("https://www.boxco.jobs/en/jobs/9100002/product-manager/"))
check("ashby uuid",
      pk("https://jobs.ashbyhq.com/exampleco/00000000-0000-4000-8000-000000000001")
      == "00000000-0000-4000-8000-000000000001")
check("workday suffixes collapse to base req",
      pk(z) == pk(z[:-2] + "-3") == "p100001")
check("different greenhouse jobs differ",
      pk("https://job-boards.greenhouse.io/northwind/jobs/9100003003")
      != pk("https://job-boards.greenhouse.io/northwind/jobs/9100005003"))
check("empty url -> None", pk(None) is None and pk("") is None)

print("8. history keeps id_locs through save/load")
h = {}
jsa.record_sighting(h, job("gh-a-1", "Remote US"), T)
import json, tempfile
orig = jsa.POSTING_HISTORY_FILE
with tempfile.TemporaryDirectory() as d:
    jsa.POSTING_HISTORY_FILE = pathlib.Path(d) / "h.json"
    jsa.save_history(h, TODAY)
    back = json.loads(jsa.POSTING_HISTORY_FILE.read_text())
jsa.POSTING_HISTORY_FILE = orig
entry = next(iter(back.values()))
check("id_locs persisted", entry.get("id_locs") == {"gh-a-1": "remote us"}, entry)

fails = RESULTS.count(False)
print(f"\n{len(RESULTS)} checks, {fails} failures")
sys.exit(1 if fails else 0)
