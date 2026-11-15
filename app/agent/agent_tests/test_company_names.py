#!/usr/bin/env python3
"""Company names are cleaned up without patterns that can stall on a long,
odd name (a name can come straight from the setup page). The cleanup must
give exactly what the old patterns gave, and stay quick. Every name here is
made up.

    python3 agent_tests/test_company_names.py
"""
import random
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lead_resolver as lr  # noqa: E402

# The old way, kept here only to compare against.
_OLD_LEGAL = re.compile(r"[,.]?\s*\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|gmbh)\b\.?", re.I)
_OLD_TAIL = re.compile(r"\b(holdings|group|technologies|technology|labs)\b\.?", re.I)


def old_clean(name, drop_tails):
    s = re.sub(r"\(.*?\)", " ", (name or "").lower())
    s = _OLD_LEGAL.sub(" ", s)
    if drop_tails:
        s = _OLD_TAIL.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def old_norm(name):
    return old_clean(name, True) or old_clean(name, False)


NAMES = [
    "Harborline, Inc", "Harborline, Inc.", "Baker's Corporation", "Quillco Labs", "Labs", "Quillco Labs.",
    "Lumenfold (formerly Tessaway) LLC", "Tessaway Co.", "Tessaway & Co", "Fernhollow Health Group, Ltd.",
    "PAYLANE  TECHNOLOGIES   INC", "Northfield.Co", "Northfield ,Inc", "Northfield . Inc.", "Ledgerly (US) (Remote)",
    "Ledgerly (unclosed", "Ledgerly ) odd ( order", "Ledgerly (line\nbreak) Inc", "A.B. Corp", "R&D Holdings Company",
    "co", "Inc.", "", None, "  ", "Company Company", "Incorporated_Inc", "Labs Group", "Group", "Quillco-Labs",
    "Café Lumenfold GmbH", "LUMENFOLD LİMİTED", "lumenfold ınc", "Lumenfold Holdingſ", "Tessaway 2 Technology.",
    "Lumenfold,Inc", "Lumenfold..Inc", "Lumenfold, \t Inc.. Labs.", "(all) (of) (it)", "((nested) one) Inc",
]
PIECES = ["inc", "Inc.", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "gmbh",
          "holdings", "group", "technologies", "technology", "labs", "lumenfold", "tessaway", "quillco", "x", "9",
          " ", "  ", "\t", "\n", ",", ".", "(", ")", "_", "-", "&", "'", "/", "é", "ı", "ſ", "İ", "K", "A", "ß"]


class SameAsBefore(unittest.TestCase):
    def test_named_cases(self):
        for name in NAMES:
            self.assertEqual(lr.norm_company(name), old_norm(name), repr(name))
            for tails in (True, False):
                self.assertEqual(lr._clean_company(name, tails), old_clean(name, tails), repr(name))

    def test_what_the_docstring_promises(self):
        self.assertEqual(lr.norm_company("Harborline, Inc"), "harborline")
        self.assertEqual(lr.norm_company("Baker's Corporation"), "bakers")
        self.assertEqual(lr.norm_company("Quillco Labs"), "quillco")
        self.assertEqual(lr.norm_company("Labs"), "labs")

    def test_many_made_up_strings(self):
        rnd = random.Random(20261115)
        for _ in range(20000):
            name = "".join(rnd.choice(PIECES) for _ in range(rnd.randint(0, 14)))
            for tails in (True, False):
                self.assertEqual(lr._clean_company(name, tails), old_clean(name, tails), repr(name))


class StaysQuick(unittest.TestCase):
    def test_long_odd_names_finish_at_once(self):
        n = 200000
        for name in ("(" * n, "(" * n + "\n)", " " * n + "inc", "," * n + " inc", "a " * n, "inc. " * (n // 5),
                     "(" + "x" * n, "labs" * n, "( " * n + ")"):
            t = time.time()
            lr.norm_company(name)
            self.assertLess(time.time() - t, 2.0, name[:12])


if __name__ == "__main__":
    unittest.main(verbosity=1)
