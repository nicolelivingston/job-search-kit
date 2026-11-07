#!/usr/bin/env python3
"""Build bank-index.json from the evidence bank (Evidence Bank.md by default).

Every bullet line in the bank has the shape

    - ID [tag] [tag...]: text

where ID is E05.5, P-E04.8, A.profile, A.scope.t23 and so on. This script
reads those lines, records the story heading each sits under, and writes a
JSON index next to the bank. The resume builder and the pre-send gate read
that index, so a bullet that is not in the bank cannot be assembled onto a
page and a bullet on a page that does not match the bank gets flagged.

Usage: python3 bank_index.py [path/to/Evidence Bank.md]
Default bank location: the canonical folder (see BANK_DIR candidates).
"""

import json
import re
import sys
from pathlib import Path
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import bank_dir as _ks_bank_dir  # evidence bank folder from settings/paths.json

BANK_DIR_CANDIDATES = [   # the user's bank (settings) first; a bank beside the kit only as a fallback
    *([_ks_bank_dir()] if _ks_bank_dir() else []),
    Path(__file__).resolve().parents[2] / "Evidence Bank",
]
from kit_settings import paths as _ks_paths
BANK_NAME = _ks_paths().get("bank_file", "Evidence Bank.md")   # the evidence bank file name (settings/paths.json)

ID_RE = r"(?P<id>E\d{2}\.\d+|P-E\d{2}\.\d+[a-z]?|A\.[A-Za-z0-9_.]+)"
TAG_RE = r"(?:\s*\[(?P<tags>[^\]]*)\])*"
LINE_RE = re.compile(r"^- " + ID_RE + r"(?P<tagblock>(?:\s*\[[^\]]*\])*)\s*:\s*(?P<text>.+?)\s*$")
STATUS_WORDS = ("primary", "alternate", "variant", "tailor-only", "interview-only", "proposed", "superseded")
ON_PAPER = {"primary", "alternate", "variant", "tailor-only", "fixed"}
RESTRICTIVE = ("superseded", "interview-only", "proposed", "tailor-only", "alternate", "variant", "primary")


def parse_tier(raw, story=None):
    """A card's Tier: "all", or the tiers it may appear on as digits ("1, 2",
    "2 and 3 only"). Anything else ("not 1", "except 3", blank) is an error, so a
    limit never silently becomes no limit (Nov 1, 2026 dry run)."""
    t = raw.strip().lower().rstrip(".")
    if t.startswith("<"):
        return None   # template text not filled in yet
    if t == "all":
        return [1, 2, 3]
    rest = re.sub(r"\b(and|or|only|tiers?)\b|[,&/+\s]", "", t)
    if not re.fullmatch(r"[123]+", rest or "x"):
        raise SystemExit(f"{story}: Tier must be \"all\" or the tiers it may appear on, like \"Tier: 1, 2\" or "
                         f"\"Tier: 2 and 3 only\"; got \"{raw.strip()}\"")
    return sorted({int(d) for d in rest})


def find_bank(arg=None):
    if arg:
        return Path(arg)
    for d in BANK_DIR_CANDIDATES:
        p = d / BANK_NAME
        if p.exists():
            return p
    raise SystemExit(f"{BANK_NAME} not found; pass its path.")


def parse(bank_path: Path):
    entries = []
    story = None
    tiers = None
    seen = set()
    for raw in bank_path.read_text(encoding="utf8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            story = line[3:].strip()
            tiers = None
            continue
        plain = line.replace("*", "").replace("_", " ").strip()
        if plain.startswith("Status:") and "Tier:" in plain:
            tiers = parse_tier(plain.split("Tier:", 1)[1].split("|")[0], story)
            continue
        if re.match(r"^(-\s*)?Tier\s*:", plain):
            raise SystemExit(f"{story}: the Tier goes on the card's Status line (\"Status: ... | Role: ... | Tier: all\"), not on its own line")
        if line.startswith("# Part"):
            story = line[2:].strip()
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        ident = m.group("id")
        tags = [t.strip() for t in re.findall(r"\[([^\]]*)\]", m.group("tagblock") or "")]
        status = "fixed"
        if m.group("text").lstrip().startswith("<"):
            tags = tags + ["placeholder"]   # template text not filled in yet: never paper
            status = "placeholder"
        found = []
        for t in ([] if status == "placeholder" else tags):
            m2 = re.match(r"\s*([a-z-]+)", t.lower())
            head = m2.group(1) if m2 else ""
            if head in STATUS_WORDS:
                found.append(head)
        if found:
            # the most restrictive tag wins: "[primary] [superseded]" is superseded (Nov 1, 2026)
            status = min(found, key=lambda h: RESTRICTIVE.index(h) if h in RESTRICTIVE else len(RESTRICTIVE))
        if ident in seen:
            raise SystemExit(f"duplicate ID in bank: {ident}")
        seen.add(ident)
        entries.append({
            "id": ident,
            "story": story,
            "tags": tags,
            "status": status,
            "on_paper_ok": status in ON_PAPER,
            "text": m.group("text"),
            **({"tiers": tiers} if tiers and ident[:1] in ("E", "P") else {}),
        })
    return entries


def main():
    bank = find_bank(sys.argv[1] if len(sys.argv) > 1 else None)
    entries = parse(bank)
    out = bank.with_name("bank-index.json")
    out.write_text(json.dumps({"source": bank.name, "entries": entries}, indent=1, ensure_ascii=False), encoding="utf8")
    by_status = {}
    for e in entries:
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
    print(f"{len(entries)} entries written to {out}")
    for k, v in sorted(by_status.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
