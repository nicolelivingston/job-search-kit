"""Run profiler and dry-run switch for the job search agent (Oct 29, 2026).

One choke point, ats_tools.request_with_retry, reports every HTTP call here.
This module:

  * counts Notion API calls by kind (query, page read, page create, page
    patch, schema) and board/feed fetches,
  * times each pipeline stage main() wraps in `stage("name")`,
  * in dry-run mode (AGENT_DRY_RUN=1 or --dry-run) answers every Notion
    write with a fake 200 and records the intended write to
    dry_run_writes.jsonl, so a code change can be checked by reading the
    diff instead of by watching Notion,
  * flags any write that would set Overall Verdict = Applying or Passed (the
    agent never sets either; those are the user's alone),
  * appends one JSON line per run to run_stats.jsonl and prints a summary.

No network calls of its own. Import cost is nil, so every script can use it.
"""

import json
import os
import re
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import data_dir as _ks_data_dir  # agent state lives in the data folder

HERE = Path(__file__).parent
STATS_FILE = _ks_data_dir() / "run_stats.jsonl"
DRY_RUN_FILE = _ks_data_dir() / "dry_run_writes.jsonl"

DRY_RUN = os.environ.get("AGENT_DRY_RUN", "") == "1" or "--dry-run" in sys.argv[1:]

_PAGE_RE = re.compile(r"/v1/pages/([0-9a-f-]{32,36})")
_QUERY_RE = re.compile(r"/v1/databases/[0-9a-f-]+/query")
_DB_RE = re.compile(r"/v1/databases/[0-9a-f-]+$")


class _Stats:
    def __init__(self):
        self.reset()

    def reset(self):
        self.started = time.time()
        self.calls = Counter()      # notion:query, notion:page_read, notion:page_create, notion:page_patch, notion:schema, board, feed, other
        self.stages = {}            # name -> seconds
        self.violations = []        # human-readable strings
        self.dry_writes = 0
        self.extra = {}             # anything main() wants to record (counts)

    # -- classification -------------------------------------------------
    @staticmethod
    def classify(method, url):
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            host = ""
        if host == "api.notion.com":
            if _QUERY_RE.search(url):
                return "notion:query"
            if _DB_RE.search(url):
                return "notion:schema"
            if url.rstrip("/").endswith("/v1/pages"):
                return "notion:page_create"
            if _PAGE_RE.search(url):
                return "notion:page_patch" if method == "patch" else "notion:page_read"
            return "notion:other"
        host = url.split("/")[2] if "://" in url else url
        if any(h in host for h in ("greenhouse", "lever.co", "ashbyhq", "myworkdayjobs")):
            return "board"
        if any(h in host for h in ("remotive", "remoteok", "weworkremotely", "himalayas", "workingnomads")):
            return "feed"
        return "other"

    # -- hooks ----------------------------------------------------------
    def note(self, method, url, kwargs):
        kind = self.classify(method, url)
        self.calls[kind] += 1
        if kind.startswith("notion:page_") and method in ("post", "patch"):
            self._check_write(url, kwargs.get("json") or {})

    def _check_write(self, url, payload):
        props = payload.get("properties") or {}
        verdict = (props.get("Overall Verdict") or {}).get("select") or {}
        if verdict and verdict.get("name") in ("Applying", "Passed", "Pursue", "Pass"):
            self.violations.append(f"write would set Overall Verdict = {verdict.get('name')}: {url}")

    def dry_response(self, method, url, kwargs):
        """A fake success for a Notion write in dry-run mode."""
        payload = kwargs.get("json") or {}
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "method": method,
               "url": url, "payload": payload}
        try:
            with DRY_RUN_FILE.open("a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except OSError:
            pass
        self.dry_writes += 1
        return _FakeResponse({"id": "dry-run-" + str(self.dry_writes), "object": "page",
                              "properties": payload.get("properties", {})})

    # -- stages ---------------------------------------------------------
    @contextmanager
    def stage(self, name):
        t0 = time.time()
        before = self.calls.copy()
        try:
            yield
        finally:
            self.stages[name] = {
                "seconds": round(time.time() - t0, 1),
                "notion_calls": sum(v for k, v in (self.calls - before).items() if k.startswith("notion:")),
            }

    # -- reporting ------------------------------------------------------
    def summary_line(self):
        n = {k.split(":")[1]: v for k, v in self.calls.items() if k.startswith("notion:")}
        total = sum(n.values())
        parts = ", ".join(f"{k} {v}" for k, v in sorted(n.items()))
        slow = sorted(self.stages.items(), key=lambda kv: -kv[1]["seconds"])[:3]
        slow_txt = ", ".join(f"{k} {v['seconds']}s/{v['notion_calls']} calls" for k, v in slow)
        line = (f"Profile: {round(time.time() - self.started)}s total; Notion {total} calls ({parts}); "
                f"boards {self.calls['board']}, feeds {self.calls['feed']}; slowest: {slow_txt}")
        if DRY_RUN:
            line += f"; DRY RUN, {self.dry_writes} write(s) recorded to dry_run_writes.jsonl"
        if self.violations:
            line += f"; VIOLATIONS {len(self.violations)}"
        return line

    def write(self, run_kind="full"):
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "run": run_kind,
               "seconds": round(time.time() - self.started, 1), "dry_run": DRY_RUN,
               "calls": dict(self.calls), "stages": self.stages,
               "violations": self.violations, **self.extra}
        try:
            with STATS_FILE.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass
        return rec


class _FakeResponse:
    status_code = 200

    def __init__(self, body):
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


STATS = _Stats()


def read_recent(days=7):
    """Recent run records, oldest first. Used by invariants.py."""
    out = []
    try:
        for line in STATS_FILE.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return out
    cutoff = time.time() - days * 86400
    return [r for r in out if datetime.fromisoformat(r["ts"]).timestamp() >= cutoff]
