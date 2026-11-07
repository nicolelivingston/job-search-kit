"""Tracker writes from several programs at once (the daily run, the tracker
page, the plugin's tracker commands) all survive: each write re-reads the
file under a cross-process lock, and readers see other programs' changes.
No network.
    python3 app/agent/agent_tests/test_tracker_concurrency.py
"""
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]

WORKER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import local_tracker as lt
    lt.configure(sys.argv[2], "APPS", "COS")
    role, n, start = sys.argv[3], int(sys.argv[4]), float(sys.argv[5])
    while time.time() < start:
        time.sleep(0.005)
    if role == "add":
        for i in range(n):
            r = lt.handle("post", "https://api.notion.com/v1/pages",
                          {"json": {"parent": {"database_id": "APPS"},
                                    "properties": {"Role": {"title": [{"text": {"content": f"{sys.argv[6]}-{i}"}}]}}}})
            assert r.status_code == 200
    else:
        for i in range(n):
            r = lt.handle("patch", f"https://api.notion.com/v1/pages/{sys.argv[6]}",
                          {"json": {"properties": {f"Field {i}": {"rich_text": [{"text": {"content": str(i)}}]}}}})
            assert r.status_code == 200, r.text
""")


class Concurrency(unittest.TestCase):
    def test_parallel_writers_lose_nothing(self):
        import time
        sys.path.insert(0, str(AGENT))
        import local_tracker as lt
        with tempfile.TemporaryDirectory() as d:
            lt.configure(d, "APPS", "COS")
            seed = lt.handle("post", "https://api.notion.com/v1/pages",
                             {"json": {"parent": {"database_id": "APPS"}, "properties": {}}}).json()["id"]
            w = Path(d) / "worker.py"
            w.write_text(WORKER)
            start = time.time() + 1.5
            procs = [subprocess.Popen([sys.executable, str(w), str(AGENT), d, "add", "25", str(start), f"w{k}"])
                     for k in range(4)]
            procs.append(subprocess.Popen([sys.executable, str(w), str(AGENT), d, "patch", "25", str(start), seed]))
            for p in procs:
                self.assertEqual(p.wait(timeout=120), 0)
            pages = json.loads((Path(d) / "tracker" / "applications.json").read_text())["pages"]
            self.assertEqual(len(pages), 1 + 4 * 25)
            self.assertEqual(len([k for k in pages[seed]["properties"] if k.startswith("Field ")]), 25)
            # this process's cached copy sees the other programs' writes
            q = lt.handle("post", "https://api.notion.com/v1/databases/APPS/query", {"json": {"page_size": 100}}).json()
            self.assertTrue(q["has_more"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
