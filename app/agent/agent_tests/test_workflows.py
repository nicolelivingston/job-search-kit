"""GitHub workflow files must be valid YAML, every job needs a time limit, and
the installer must not open anything on a silent install. GitHub rejects a whole workflow
(zero jobs, no error in the run list) when one line doesn't parse, and the
kit's first push hit exactly that: an unquoted `--only-binary=:all: -r` in a
`run:` line. Uses PyYAML when it is installed; otherwise a plain-scalar check
that catches the same mistake (": " or a trailing ":" inside an unquoted value).
    python3 app/agent/agent_tests/test_workflows.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILES = sorted((ROOT / ".github").rglob("*.yml"))
KV = re.compile(r"^(\s*)(?:-\s+)?([A-Za-z0-9_.\-]+):(?:\s+(.*))?$")


def plain_scalar_problems(text):
    """Line numbers where an unquoted value holds a mapping indicator."""
    bad, block = [], None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if block is not None:
            if indent > block:
                continue
            block = None
        m = KV.match(line)
        if not m or not m.group(3):
            continue
        value = re.sub(r"\s+#.*$", "", m.group(3)).strip()
        if value[:1] in "|>":
            block = indent
            continue
        if value[:1] in "'\"{[&*!":
            continue
        if ": " in value or value.endswith(":"):
            bad.append(n)
    return bad


class Workflows(unittest.TestCase):
    def test_files_exist(self):
        self.assertTrue(FILES, "no workflow files found")

    def test_parse(self):
        try:
            import yaml
        except ImportError:
            yaml = None
        for f in FILES:
            text = f.read_text(encoding="utf-8")
            with self.subTest(file=f.name):
                if yaml:
                    yaml.safe_load(text)
                self.assertEqual(plain_scalar_problems(text), [], f"unquoted ': ' in {f.name}")

    def test_every_job_has_a_timeout(self):
        # A hung step (the first clean-install waited on the setup wizard)
        # otherwise runs to GitHub's 6-hour limit.
        for f in FILES:
            if f.parent.name != "workflows":
                continue
            text = f.read_text(encoding="utf-8")
            jobs = len(re.findall(r"^    runs-on:", text, re.M))
            with self.subTest(file=f.name):
                self.assertEqual(len(re.findall(r"^    timeout-minutes:", text, re.M)), jobs)

    def test_actions_are_pinned_to_commits(self):
        # A moved tag upstream must not change what runs here.
        for f in FILES:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = re.search(r"uses:\s*(\S+)", line)
                if m and not m.group(1).startswith("./"):
                    with self.subTest(file=f.name, line=n):
                        self.assertRegex(m.group(1), r"@[0-9a-f]{40}$")

    def test_security_scans_run_on_every_push(self):
        text = (ROOT / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
        for tool in ("bandit -q -r app", "pip-audit --disable-pip", "cyclonedx-json", "gitleaks git"):
            self.assertIn(tool, text)
        # the secret scanner is downloaded, so its checksum is checked before it runs
        self.assertRegex(text, r'echo "[0-9a-f]{64}  gitleaks.tgz" \| sha256sum -c -')
        self.assertIn("fetch-depth: 0", text)

    def test_publishing_waits_for_the_release_environment(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        publish = text[text.index("  publish:"):]
        self.assertIn("environment: release", publish)
        self.assertIn("job-search-kit-sbom.cdx.json", publish)

    def test_scanner_packages_are_hash_pinned(self):
        # One entry per package: the pin line plus its continuation lines. A package may
        # carry more than one hash (a wheel and a source file, as Dependabot writes them).
        text = (ROOT / "installer" / "requirements-security.txt").read_text().replace("\\\n", " ")
        entries = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        pins = [e for e in entries if "==" in e]
        self.assertTrue(pins)
        self.assertEqual(len(pins), len(entries), "every line is a pinned package")
        unhashed = [e.split()[0] for e in pins if "--hash=sha256:" not in e]
        self.assertEqual(unhashed, [], "every pinned package needs at least one hash")

    def test_installer_opens_nothing_on_a_silent_install(self):
        # Silent installs are the CI clean-install and every quiet update.
        # A [Run] postinstall entry without skipifsilent starts the wizard
        # there, and the install never returns.
        iss = (ROOT / "installer" / "kit.iss").read_text(encoding="utf-8")
        for line in iss.splitlines():
            if "postinstall" in line:
                self.assertIn("skipifsilent", line)

    def test_virustotal_step_handles_big_files_and_fails_closed(self):
        # The installer is over VirusTotal's 32 MB direct-upload limit, and a
        # failed upload once fell through to a pass.
        rel = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        start = rel.index("Scan with VirusTotal")
        step = rel[start:rel.index("actions/upload-artifact", start)]
        self.assertIn("files/upload_url", step)
        self.assertIn("VirusTotal upload failed", step)
        self.assertIn("didn't finish", step)
        # Any Microsoft flag stops a release; otherwise three engines do.
        self.assertIn('$flagged -contains "Microsoft"', step)
        self.assertIn("$flagged.Count -ge 3", step)

    def test_installer_shows_the_privacy_page(self):
        iss = (ROOT / "installer" / "kit.iss").read_text(encoding="utf-8")
        self.assertIn("InfoBeforeFile=PRIVACY.txt", iss)
        text = (ROOT / "installer" / "PRIVACY.txt").read_text(encoding="utf-8")
        self.assertIn("update", text)   # names the daily update check and how to turn it off

    def test_checker_catches_the_original_bug(self):
        broken = "steps:\n  - run: pip install --only-binary=:all: -r x.txt\n"
        fixed = "steps:\n  - run: 'pip install --only-binary=:all: -r x.txt'\n"
        block = "steps:\n  - run: |\n      echo a: b\n"
        self.assertEqual(plain_scalar_problems(broken), [2])
        self.assertEqual(plain_scalar_problems(fixed), [])
        self.assertEqual(plain_scalar_problems(block), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
