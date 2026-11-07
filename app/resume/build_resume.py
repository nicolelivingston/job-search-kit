#!/usr/bin/env python3
"""Assemble a resume .docx from a selection file and the Evidence Bank index.

A selection file is a short JSON document that says which bank entries go
on the page and in what order. Nothing on the page is typed by hand except
the group labels and, if a posting needs it, one bridge sentence marked as
such. Formatting is fixed (Rules File section 6), so every resume built this
way looks the same and every bullet is the bank's wording.

Usage:
    python3 build_resume.py selection.json [--out file.docx] [--index bank-index.json]

Selection file shape (see Applications/<Company>/selection-<date>.json for real ones):
{
  "output": "First_Last_Resume_<Company>_<Role>_<date>_v1.docx",
  "allow_proposed": false,            // true only for review drafts, never for a file that gets sent
  "headline": "A.headline",           // an ID or literal text
  "contact": "City, ST (Remote) | ...",
  "banner": null,                      // master-only note, or null
  "master": false,                     // true only in master-selection.json (no page limit, no tier)
  "profile": "A.profile",             // ID, or {"id": "A.profile", "bridge": "one sentence, in the posting's words"}
  "core_expertise": ["Product Strategy & Roadmaps", "..."],   // or an ID like "A.core"
  "tier": 1,                           // 1, 2, or 3 (Rules File section 5); bullets from a card whose Tier line excludes it are refused
  "roles": [
    {"id": "A.role.t1",                // bank line "Employer | Title | Location | Mon YYYY - Present"
     "scope": "A.scope.t1",
     "groups": [{"label": "Platform launch and pilot:", "bullets": ["E03.1", "E03.3"]}]},
    {"id": "A.role.t2", "bullets": ["E09.5"]}
  ],
  "earlier": [
    {"id": "A.earlier.1"},              // bank line "Employer | Title | YYYY - YYYY", shown as "Title, Employer"
    {"id": "A.earlier.2", "bullets": ["E13.3"]}
  ],
  "education": "A.education",
  "credentials": "A.credentials",     // leave out when you have none
  "tools": "A.tools"                   // or {"text": "a subset of your A.tools line"}
}

Roles may still be typed in ({"employer", "title", "dates"}) for older selection
files, but the gate flags typed role lines: they belong in the bank's Part A.
A bullet entry may also be {"text": "...", "source": "why this is allowed"} for a
bridge sentence; the gate will still flag it as untraced so the reason is reviewed.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import bank_dir as _ks_bank_dir  # evidence bank folder from settings/paths.json

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S  # personal settings live in the settings folder, not the code

FONT = _S("build_resume.FONT")
BODY_PT = _S("build_resume.BODY_PT")
NAME_PT = _S("build_resume.NAME_PT")
HEADING_PT = _S("build_resume.HEADING_PT")
MARGIN_IN = _S("build_resume.MARGIN_IN")
LINE_SPACING = _S("build_resume.LINE_SPACING")
PAGE_LIMIT = _S("presend_gate.PAGE_LIMIT", default=2)   # tailored resume pages; the gate reads the same setting

INDEX_CANDIDATES = [   # the user's bank (settings) first; a bank beside the kit only as a fallback
    *([_ks_bank_dir() / "bank-index.json"] if _ks_bank_dir() else []),
    Path(__file__).resolve().parents[2] / "Evidence Bank" / "bank-index.json",
]


def load_index(path=None):
    p = Path(path) if path else next((c for c in INDEX_CANDIDATES if c.exists()), None)
    if not p or not p.exists():
        raise SystemExit("bank-index.json not found; run bank_index.py first or pass --index")
    data = json.loads(p.read_text(encoding="utf8"))
    return {e["id"]: e for e in data["entries"]}, p


class Builder:
    def __init__(self, index, allow_proposed=False):
        self.index = index
        self.allow_proposed = allow_proposed
        self.tier = None
        self.used = []
        self.doc = Document()
        self._setup()

    # ---- document setup -------------------------------------------------
    def _setup(self):
        sec = self.doc.sections[0]
        sec.left_margin = sec.right_margin = Inches(MARGIN_IN)
        sec.top_margin = sec.bottom_margin = Inches(MARGIN_IN)
        st = self.doc.styles["Normal"]
        st.font.name = FONT
        st.font.size = Pt(BODY_PT)
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(a), FONT)
        pf = st.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(1)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = LINE_SPACING
        lb = self.doc.styles["List Bullet"]
        lb.font.name = FONT
        lb.font.size = Pt(BODY_PT)
        lb.paragraph_format.space_after = Pt(1)
        lb.paragraph_format.line_spacing = LINE_SPACING
        lb.paragraph_format.left_indent = Inches(0.25)
        lb.paragraph_format.first_line_indent = Inches(-0.2)

    # ---- helpers ----------------------------------------------------------
    def resolve(self, ref, kind="bullet"):
        """Return (text, id) for an ID, or (text, None) for literal text."""
        if isinstance(ref, dict):
            if "id" in ref:
                return self.resolve(ref["id"], kind)
            if "text" not in ref:
                raise SystemExit(f"a {kind} entry needs an \"id\" or a \"text\": {json.dumps(ref)[:80]}")
            if ref["text"] in self.index:   # {"text": "A.tools"} means the bank line, not the letters "A.tools"
                return self.resolve(ref["text"], kind)
            return ref["text"], None
        if ref in self.index:
            e = self.index[ref]
            if not e["on_paper_ok"] and not self.allow_proposed:
                raise SystemExit(f"{ref} is {e['status']}; it can't go on a page that may be sent. "
                                 f"Set allow_proposed for a review draft only.")
            if self.tier and e.get("tiers") and self.tier not in e["tiers"]:
                raise SystemExit(f"{ref} comes from a card limited to tier(s) {', '.join(map(str, e['tiers']))}; "
                                 f"this application is tier {self.tier}. Leave it off or pick another bullet.")
            self.used.append(ref)
            return e["text"], ref
        if re.match(r"^(E\d{2}\.\d+|P-E\d{2}\.\d+[a-z]?|A\.[A-Za-z0-9_.]+)$", ref):
            raise SystemExit(f"{ref} is not in the bank index")
        return ref, None

    def para(self, text, bold=False, size=BODY_PT, after=2, before=0, keep_with_next=False):
        p = self.doc.add_paragraph()
        r = p.add_run(text)
        r.bold = bold
        r.font.size = Pt(size)
        r.font.name = FONT
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.keep_with_next = keep_with_next
        return p

    def heading(self, text):
        self.para(text, bold=True, size=HEADING_PT, before=4, after=1, keep_with_next=True)

    def bullet(self, ref):
        text, _ = self.resolve(ref)
        p = self.doc.add_paragraph(style="List Bullet")
        r = p.add_run(text)
        r.font.size = Pt(BODY_PT)
        r.font.name = FONT
        p.paragraph_format.keep_together = True  # never split a bullet across pages (Oct 24, 2026)
        return p

    def role_lines(self, role, earlier=False):
        """(employer, title line, dates) for a role: from a bank line such as
        A.role.t1 "Employer | Title | Location | Mon YYYY - Present" (location
        optional), or typed into the selection (older selection files)."""
        if role.get("id"):
            text = self.resolve(role["id"])[0]
            parts = [x.strip() for x in text.split(" | ")]
            if len(parts) == 4:
                emp, title, loc, dates = parts
            elif len(parts) == 3:
                (emp, title, dates), loc = parts, ""
            else:
                raise SystemExit(f"{role['id']} needs the shape 'Employer | Title | Location | Dates' (location optional)")
            if earlier:
                return None, f"{title}, {emp}", dates
            return emp, (f"{title} | {loc}" if loc else title), dates
        return role.get("employer"), role["title"], role["dates"]

    # ---- sections ---------------------------------------------------------
    def build(self, sel):
        t = sel.get("tier")
        self.tier = t if isinstance(t, int) and t in (1, 2, 3) else None
        self.para(sel.get("name", "YOUR NAME"), bold=True, size=NAME_PT, after=0)
        for key in ("headline", "contact", "profile", "core_expertise", "roles", "education", "tools"):
            if key not in sel:
                raise SystemExit(f"the selection file has no \"{key}\"; copy it from templates/Applications/selection-template.json")
        self.para(self.resolve(sel["headline"])[0], bold=True, after=0)
        self.para(sel["contact"], after=4)
        if sel.get("banner"):
            self.para(sel["banner"], after=4)

        # "profile_heading" in the selection file ("Profile" reads better than
        # "Executive Profile" on a page aimed below the user's target level).
        self.heading(sel.get("profile_heading") or "Executive Profile")
        prof = sel["profile"]
        if isinstance(prof, dict) and "bridge" in prof:
            base = self.resolve(prof["id"], "profile")[0]
            bridge = prof["bridge"].strip()
            if prof.get("bridge_position") == "before_last":
                # The profile ends on its own career line, so the bridge goes
                # before the final sentence.
                head, sep, last = base.rstrip(".").rpartition(". ")
                text = (head + ". " + bridge.rstrip(".") + ". " + last + ".") if sep else (base.rstrip(".") + ". " + bridge)
            else:
                text = base.rstrip(".") + ". " + bridge
        else:
            text = self.resolve(prof, "profile")[0]
        self.para(text, after=4)

        self.heading("Core Expertise")
        ce = sel["core_expertise"]
        if isinstance(ce, list) and not all(isinstance(x, str) for x in ce):
            raise SystemExit("core_expertise is a list of terms from A.core, or the ID \"A.core\"")
        ce_text = self.resolve(ce)[0] if isinstance(ce, str) else " • ".join(ce)
        self.para(ce_text, after=4)

        self.heading("Professional Experience")
        for role in sel["roles"]:
            emp, title, dates = self.role_lines(role)
            if emp:
                self.para(emp, bold=True, after=0, before=4, keep_with_next=True)
            self.para(title, bold=True, after=0, keep_with_next=True)
            self.para(dates, after=2, keep_with_next=True)
            if role.get("scope"):
                self.bullet(role["scope"])
            for b in role.get("bullets", []):
                self.bullet(b)
            for g in role.get("groups", []):
                if not g.get("label"):
                    raise SystemExit("every group needs a \"label\" (or put its bullets under the role's \"bullets\")")
                self.para(g["label"], bold=True, after=1, before=2, keep_with_next=True)
                for b in g["bullets"]:
                    self.bullet(b)

        if sel.get("earlier"):
            self.heading("Earlier Experience")
            for role in sel["earlier"]:
                emp, title, dates = self.role_lines(role, earlier=True)
                if emp:
                    self.para(emp, bold=True, after=0, keep_with_next=True)
                self.para(title, bold=True, after=0, keep_with_next=True)
                self.para(dates, after=2)
                for b in role.get("bullets", []):
                    self.bullet(b)

        self.heading("Education")
        self.para(self.resolve(sel["education"])[0].rstrip("."), after=4)
        cred = sel.get("credentials")   # optional: leave the key out when there are none (Nov 1, 2026)
        if cred:
            text = self.resolve(cred)[0]
            if text.strip().strip('"').lower() not in ("none listed", "none", ""):
                self.heading("Credentials")
                self.para(text, after=4)
        tools = sel["tools"]
        if isinstance(tools, list):
            raise SystemExit("tools is \"A.tools\" or {\"text\": \"a subset of your A.tools line\"}, not a list")
        self.heading("Tools and Technology")
        self.para(self.resolve(tools)[0], after=0)

    def save(self, out: Path):
        self.doc.save(out)
        force_fonts(out)


def force_fonts(path: Path):
    """Rewrite every explicit font in styles.xml and document.xml to Arial (bullet glyph fonts excepted)."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in ("word/styles.xml", "word/document.xml"):
                xml = data.decode("utf8")
                def sub(m):
                    name = m.group(2)
                    if name.lower().startswith("symbol") or "wingdings" in name.lower():
                        return m.group(0)
                    return f'{m.group(1)}="{FONT}"'
                xml = re.sub(r'(w:ascii|w:hAnsi|w:cs|w:eastAsia)="([^"]+)"', sub, xml)
                xml = re.sub(r'\s(w:asciiTheme|w:hAnsiTheme|w:cstheme|w:eastAsiaTheme)="[^"]+"', "", xml)
                data = xml.encode("utf8")
            zout.writestr(item, data)
    tmp.replace(path)


def render_pages(path: Path):
    n = _render_pages(path)
    return n if n is not None else _render_pages(path)   # LibreOffice sometimes fails on a first start; try once more


def _render_pages(path: Path):
    from platform_support import find_soffice
    soffice = find_soffice()
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(path)],
                       capture_output=True, timeout=180)
        pdfs = list(Path(td).glob("*.pdf"))
        if not pdfs:
            return None
        pdfinfo = shutil.which("pdfinfo")
        if pdfinfo:
            out = subprocess.run([pdfinfo, str(pdfs[0])], capture_output=True, text=True).stdout
            m = re.search(r"Pages:\s+(\d+)", out)
            if m:
                return int(m.group(1))
        data = pdfs[0].read_bytes()
        return len(re.findall(rb"/Type\s*/Page[^s]", data))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("selection")
    ap.add_argument("--out")
    ap.add_argument("--index")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    sel = json.loads(Path(args.selection).read_text(encoding="utf8"))
    index, ipath = load_index(args.index)
    b = Builder(index, allow_proposed=sel.get("allow_proposed", False))
    b.build(sel)
    out = Path(args.out or sel.get("output") or "resume.docx")
    if not out.is_absolute():
        out = Path(args.selection).resolve().parent / out
    # the output stays beside its selection file and is always a .docx, so a selection file
    # written from untrusted text can't overwrite anything else (bank, master, settings)
    if not args.out and (out.resolve().parent != Path(args.selection).resolve().parent or out.suffix.lower() != ".docx"):
        sys.exit(f"refusing to write {out}: a selection's output must be a .docx in the same folder as the selection file")
    b.save(out)
    print(f"built {out}")
    print(f"bank entries used ({len(b.used)}): {', '.join(b.used)}")
    proposed = [u for u in b.used if not index[u]["on_paper_ok"]]
    if proposed:
        print(f"REVIEW DRAFT: contains {len(proposed)} entries not approved for paper: {', '.join(proposed)}")
    if not args.no_render:
        n = render_pages(out)
        print(f"rendered pages: {n if n is not None else 'render failed'}")
        if n and n > PAGE_LIMIT and sel.get("master") is not True:
            print(f"FLAG: more than {PAGE_LIMIT} page(s); cut a bullet, never the font or margins")


if __name__ == "__main__":
    main()
