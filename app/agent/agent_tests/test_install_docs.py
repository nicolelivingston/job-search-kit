"""Installing has to be findable and the same everywhere it is written down.

A new person lands on the README. It must show, before anything else it
describes, an Install section with one link that downloads the Windows
installer itself (not a page to hunt through), and plain numbered steps that
cover the two warnings Windows shows for a new program. The installer's file
name must be the same in the installer script, the install check, the release
workflow, and the documents, and the kit's own updater must accept it.
No network.
    python3 app/agent/agent_tests/test_install_docs.py
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent
sys.path.insert(0, str(APP))
import updater    # noqa: E402

REPO_URL = "https://github.com/nicolelivingston/job-search-kit"
# The same address works for every release, because the file name never changes.
FIXED_LINK = REPO_URL + "/releases/latest/download/JobSearchKit-Setup.exe"
# v0.1.1 came out before the fixed name, so until the next release the README
# links straight to that release's file. RELEASING.md says when to switch; take
# this line out then.
LAST_VERSIONED_LINK = REPO_URL + "/releases/download/v0.1.1/JobSearchKit-Setup-0.1.1.exe"


def read(rel):
    return (KIT / rel).read_text(encoding="utf-8")


class InstallerName(unittest.TestCase):
    def setUp(self):
        m = re.search(r"^OutputBaseFilename=(.+)$", read("installer/kit.iss"), re.M)
        self.assertTrue(m, "installer/kit.iss sets no OutputBaseFilename")
        self.exe = m.group(1).strip() + ".exe"

    def test_name_is_the_same_every_release(self):
        self.assertEqual(self.exe, "JobSearchKit-Setup.exe")     # no version in it, so one link works forever
        self.assertTrue(FIXED_LINK.endswith("/" + self.exe))

    def test_every_place_that_names_the_installer_agrees(self):
        self.assertIn(f'-Filter "{self.exe}"', read("installer/smoke_test_windows.ps1"))
        release = read(".github/workflows/release.yml")
        self.assertIn(f"dist/{self.exe}\n", release)             # attached to the release
        self.assertIn(f'-Filter "{self.exe}"', release)          # and the same file is the one scanned
        self.assertIn(f"`{self.exe}`", release)                  # named in the note at the top of the release page
        self.assertIn(f"`{self.exe}`", read("RELEASING.md"))
        for rel in ("installer/smoke_test_windows.ps1", ".github/workflows/release.yml", ".github/workflows/checks.yml",
                    "installer/build_windows.ps1", "SUPPORT.md"):
            self.assertNotRegex(read(rel), r"JobSearchKit-Setup-[*<{]", f"{rel} still expects a version in the file name")

    def test_the_updater_takes_the_fixed_name(self):
        release = {"tag_name": "v9.9.9", "published_at": "2026-01-01T00:00:00Z", "assets": [
            {"name": "job-search-kit.plugin"}, {"name": self.exe}, {"name": "SHA256SUMS.txt"}, {"name": "SHA256SUMS.txt.sig"}]}
        with mock.patch.object(updater.json, "load", return_value=release):
            _, exe, sums, sig, _ = updater.latest_release(opener=lambda *a, **k: mock.MagicMock())
        self.assertEqual((exe["name"], sums["name"], sig["name"]), (self.exe, "SHA256SUMS.txt", "SHA256SUMS.txt.sig"))
        good = "ab" * 32
        self.assertEqual(updater.expected_hash(f"{good}  {self.exe}\ncd  job-search-kit.plugin\n", self.exe), good)


class ReadmeInstallSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = read("README.md")
        m = re.search(r"^## Install on Windows\n(.*?)(?=^## )", cls.readme, re.M | re.S)
        cls.section = m.group(1) if m else ""

    def test_install_comes_before_everything_the_readme_describes(self):
        self.assertTrue(self.section, "README.md has no '## Install on Windows' section")
        first_heading = re.search(r"^## (.+)$", self.readme, re.M).group(1)
        self.assertEqual(first_heading, "Install on Windows")

    def test_one_link_downloads_the_installer_itself(self):
        links = re.findall(r"\]\((https://[^)\s]+\.exe)\)", self.section)
        self.assertEqual(len(links), 1, "exactly one installer link, so there is nothing to choose between")
        self.assertIn(links[0], (FIXED_LINK, LAST_VERSIONED_LINK))
        self.assertTrue(self.section.lstrip().startswith("**[Download the installer]("), "the link is the first thing in the section")

    def test_steps_cover_what_windows_shows_a_new_program(self):
        steps = re.findall(r"^\d+\. .+$", self.section, re.M)
        self.assertGreaterEqual(len(steps), 4)
        self.assertLessEqual(len(steps), 6, "keep it short")
        text = " ".join(steps)
        for phrase in ("Keep", "Windows protected your PC", "More info", "Run anyway", "Finish"):
            self.assertIn(phrase, text)
        self.assertIn("Code button", self.section)               # the usual wrong turn: downloading the source code

    def test_plugin_link_and_release_note_point_at_real_places(self):
        self.assertIn(REPO_URL + "/releases/latest/download/job-search-kit.plugin", self.section)
        release = read(".github/workflows/release.yml")
        self.assertIn("dist/job-search-kit.plugin\n", release)   # that link's file is attached to every release
        self.assertIn(REPO_URL + "#install-on-windows", release)  # the release page sends people back to these steps


class ReleaseHousekeeping(unittest.TestCase):
    def test_plugin_version_comes_from_the_release(self):
        import json
        version = json.loads(read("plugin/.claude-plugin/plugin.json"))["version"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertIn("plugin.json", read("installer/build_windows.ps1"))        # stamped with the tag at build time
        self.assertIn("plugin.json", read("installer/smoke_test_windows.ps1"))   # and the install check compares the two

    def test_whats_new_is_written_down_and_checked(self):
        changelog = read("CHANGELOG.md")
        sections = re.findall(r"^## (\d+\.\d+\.\d+)$", changelog, re.M)
        self.assertTrue(sections, "CHANGELOG.md has no '## X.Y.Z' section")
        self.assertEqual(sections, sorted(sections, key=updater.parse, reverse=True), "newest release first")
        release = read(".github/workflows/release.yml")
        self.assertIn('grep -qxF "## $v" CHANGELOG.md', release)                 # a tag with no section stops the release
        self.assertIn("CHANGELOG.md", read("RELEASING.md"))


if __name__ == "__main__":
    unittest.main()
