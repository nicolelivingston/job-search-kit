"""Every setting the code reads is listed in SETTINGS.md, so nothing becomes
a hidden choice the user can't see or change. No network.
    python3 app/agent/agent_tests/test_settings_catalog.py
"""
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
KIT = APP.parent


class Catalog(unittest.TestCase):
    def test_every_setting_is_catalogued(self):
        used = set()
        for f in list((APP / "agent").glob("*.py")) + list((APP / "resume").glob("*.py")):
            used |= set(re.findall(r'_S\("([a-z_]+\.[A-Z_]+)"', f.read_text(encoding="utf-8")))
        catalog = (KIT / "SETTINGS.md").read_text(encoding="utf-8")
        missing = sorted(k for k in used if f"`{k}`" not in catalog and f"`{k}." not in catalog)
        self.assertGreater(len(used), 50)
        self.assertEqual(missing, [], f"add these to SETTINGS.md: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
