"""The test person these tests are running as: the settings folder named in
KIT_SETTINGS_DIR (one of the made-up people in examples/, or the builder's
own dev-settings). The same tests run as every example person, so anything a
test needs that depends on a person's answers comes from here: a posting
that person would want, with a title on their list, years they can claim,
and pay over their target.

Not a test file (run_all.py only picks up test_*.py).
"""
import json
import os
from pathlib import Path

KIT = Path(__file__).resolve().parents[3]


def settings_dir():
    return Path(os.environ.get("KIT_SETTINGS_DIR") or (KIT / "dev-settings"))


def criteria():
    return json.loads((settings_dir() / "criteria.json").read_text(encoding="utf-8"))


def wanted_title(senior=True):
    """A job title on this person's list, e.g. "Senior Product Manager"."""
    title = criteria()["agent"]["TITLE_KEYWORDS"][0].title()
    return ("Senior " + title) if senior else title


def sample_job(**changes):
    """A posting this person would want: fully remote, a title on their list,
    years they can claim, and pay over their target."""
    fs = criteria()["fit_scoring"]
    low = int(fs["PAY_TARGET"]) + 10000
    high = low + 30000
    years = min(5, int(fs.get("YEARS_CLAIMABLE") or 5))
    job = {"id": "smoke-1", "title": wanted_title(), "company": "Acme",
           "url": "https://job-boards.greenhouse.io/acme/jobs/1234567890", "location": "Remote (US)",
           "description": f"Fully remote. Requirements: {years}+ {fs.get('YEARS_LABEL', 'years of experience')}. "
                          f"Base salary ${low:,} to ${high:,}.",
           "salary_text": f"${low:,} - ${high:,}", "source": "Company Site", "published": "2026-10-28"}
    job.update(changes)
    return job
