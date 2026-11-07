#!/usr/bin/env python3
"""Build a cover letter .docx in the resume's format from a plain-text letter.

The letter's words come from the user's bank cards and dated statements, and
the selection file's `letter_sources` names the source of each body
paragraph (the gate checks it). This script only lays the words out: the
same name line, headline, contact line, font, sizes, and margins as the
resume built from the same selection file, then the date and the letter.

Usage:
    python3 build_letter.py <selection.json> <letter.md> [--version N] [--no-render]

letter.md holds the letter as plain paragraphs separated by blank lines
(greeting, body, sign-off). Markdown emphasis and headings aren't used.
The output is the selection's resume file name with "Resume" changed to
"CoverLetter", in the selection's folder, at version N (default: the
selection's own version).
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_resume as br   # noqa: E402


def letter_name(sel_output, version=None):
    stem = Path(sel_output).stem
    if "_Resume_" not in stem and not stem.endswith("_Resume"):
        raise SystemExit("the selection's output name has no _Resume_ part to swap for _CoverLetter_")
    stem = stem.replace("_Resume", "_CoverLetter", 1)
    if version is not None:
        stem = re.sub(r"_v\d+$", "", stem) + f"_v{version}"
    return stem + ".docx"


def paragraphs(text):
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        line = " ".join(l.strip() for l in block.strip().splitlines())
        if line:
            out.append(line)
    return out


def build(sel, paras, index, today=None):
    b = br.Builder(index, allow_proposed=False)
    b.para(sel.get("name", "YOUR NAME"), bold=True, size=br.NAME_PT, after=0)
    b.para(b.resolve(sel["headline"])[0], bold=True, after=0)
    b.para(sel["contact"], after=12)
    d = today or date.today()
    b.para(f"{d:%B} {d.day}, {d.year}", after=12)
    for t in paras:
        b.para(t, after=8)
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("selection")
    ap.add_argument("letter")
    ap.add_argument("--version", type=int)
    ap.add_argument("--index")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    selp = Path(args.selection).resolve()
    sel = json.loads(selp.read_text(encoding="utf8"))
    index, _ = br.load_index(args.index)
    paras = paragraphs(Path(args.letter).read_text(encoding="utf8"))
    if not paras:
        sys.exit("the letter file is empty")
    out = selp.parent / letter_name(sel.get("output") or "", args.version)
    # same rule as the resume builder: the output stays beside its selection and is a .docx
    if out.resolve().parent != selp.parent or out.suffix.lower() != ".docx":
        sys.exit(f"refusing to write {out}")
    b = build(sel, paras, index)
    b.save(out)
    print(f"built {out}")
    print(f"paragraphs: {len(paras)}")
    if not args.no_render:
        n = br.render_pages(out)
        print(f"rendered pages: {n if n is not None else 'render failed'}")
        if n and n > 1:
            print("FLAG: a cover letter stays on one page; cut a sentence, never the font or margins")


if __name__ == "__main__":
    main()
