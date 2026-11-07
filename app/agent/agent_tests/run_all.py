#!/usr/bin/env python3
"""Run every agent test file and exit non-zero if any fails.

    python3 Tooling/agent/agent_tests/run_all.py

Run it before committing any change under Tooling/agent/ and after any bug
The user finds by hand: the fix for a hand-found bug is not done until a test
here would have caught it (see Tooling/agent/TESTING.md).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
files = sorted(p for p in HERE.glob("test_*.py"))
failed = []
for f in files:
    print(f"\n### {f.name}")
    r = subprocess.run([sys.executable, str(f)], cwd=str(HERE.parent))
    if r.returncode != 0:
        failed.append(f.name)
print("\n" + ("ALL PASSED: %d files" % len(files) if not failed else "FAILED: " + ", ".join(failed)))
sys.exit(1 if failed else 0)
