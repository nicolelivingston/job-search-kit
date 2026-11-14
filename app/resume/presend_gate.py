#!/usr/bin/env python3
"""Pre-send gate, mechanical checks (v2, October 20, 2026).

Runs the scriptable parts of the pre-send gate (Rules File section 8) against
a .docx, .md, or .txt file.

Usage: python3 presend_gate.py <document> [<document> ...] [--index bank-index.json] [--selection selection.json]

What changed in v2:
- Bank trace. Every bullet paragraph on a .docx page is matched against the
  Evidence Bank index (bank-index.json, built by bank_index.py from the
  evidence bank). Exact match to an approved entry: reported with its ID. Near
  match: flagged with the words that differ. No match: flagged as untraced.
  A match to a proposed, interview-only, or superseded entry: flagged.
- Term checks (timing, vocabulary, retired wording) no longer fire inside a
  bullet that exactly matches an approved bank entry, because that wording
  was already cleared when it went into the bank. They still fire on
  everything else: the profile, a bridge sentence, cover letters.
- Scale figures that must appear once per resume are counted.
- The retired list carries the Oct 18 and Oct 20 additions to the Retired
  Claims Log.

This script flags; it does not clear. A flag is guilty until justified
against the bank. The judgment checks (duty test, source every claim, cut
test, uncharitable reading, attribution, tier tightening) still happen in
review.

Sources: the evidence bank, Rules File.md, Retired Claims Log.md, all in the
evidence bank folder (set in settings/paths.json). Since Oct 24, 2026
the gate reads quoted wording out of Retired Claims Log.md itself and adds it
to the hand list below, and a cover letter is checked for a `letter_sources`
map in the selection file beside it (one source per body paragraph).
"""

import argparse
import difflib
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

INDEX_CANDIDATES = [   # the user's bank (settings) first; a bank beside the kit only as a fallback
    *([_ks_bank_dir() / "bank-index.json"] if _ks_bank_dir() else []),
    Path(__file__).resolve().parents[2] / "Evidence Bank" / "bank-index.json",
]
RETIRED_LOG_CANDIDATES = [c.with_name("Retired Claims Log.md") for c in INDEX_CANDIDATES]

# Phrases quoted in the log that are replacements or too short to match
# safely as substrings. The hand list below stays as the floor; the log adds
# to it (Oct 24, 2026: the log moved to markdown so the gate can read it).
_LOG_MIN_CHARS = 18
_LOG_REPLACEMENT_RE = re.compile(r'\b(?:use|say|rounds to|other than|replaced by|cleared shape|cleared as)\b[^"]{0,30}"$', re.I)


def retired_from_log(path=None):
    """Quoted wording from Retired Claims Log.md, minus replacements and short
    fragments. Returns (phrases, path or None)."""
    for cand in ([Path(path)] if path else RETIRED_LOG_CANDIDATES):
        if cand.exists():
            text = cand.read_text(encoding="utf8", errors="replace")
            break
    else:
        return [], None
    phrases = []
    # In table rows only the "Retired wording" column (the second) counts, so a
    # quoted "Say instead" replacement is never read as retired (Nov 1, 2026).
    kept = []
    for line in text.splitlines():
        cells = line.strip().strip("|").split("|") if line.lstrip().startswith("|") else None
        kept.append(cells[1] if cells and len(cells) >= 2 else ("" if cells else line))
    text = "\n".join(kept)
    for m in re.finditer(r'"([^"\n]{4,160})"', text):
        start = max(0, m.start() - 40)
        before = text[start:m.start() + 1]
        if _LOG_REPLACEMENT_RE.search(before):
            continue  # a sanctioned replacement, not a retired phrase
        phrase = m.group(1).strip().rstrip(".;,")
        if len(phrase) < _LOG_MIN_CHARS or phrase.endswith("...") or "..." in phrase:
            continue
        phrases.append(phrase)
    return sorted(set(phrases), key=str.lower), cand

# Gate item 1: forward-looking internal timing.
import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S  # personal settings live in the settings folder, not the code

TIMING_TERMS = _S("presend_gate.TIMING_TERMS")
RETIRE_RE = re.compile(r"\bretir\w*", re.I)
SANCTIONED_RETIRE = _S("presend_gate.SANCTIONED_RETIRE")

# Gate item 2: internal vocabulary and retired wording.
VOCAB_TERMS = _S("presend_gate.VOCAB_TERMS")
CREDENTIAL_OK = _S("presend_gate.CREDENTIAL_OK")
FLAG_EM_DASH = _S("presend_gate.FLAG_EM_DASH", default=False)   # flag em dashes on the page (a voice choice; off unless the user sets it)
RETIRED_PHRASES = _S("presend_gate.RETIRED_PHRASES")
ABBREVIATIONS = _S("presend_gate.ABBREVIATIONS")
# Fine on paper: FINRA, KPI, SQL, UI, UX, AI.
ONCE_PER_RESUME = _S("presend_gate.ONCE_PER_RESUME")

SPEC_FONT = _S("presend_gate.SPEC_FONT")
SPEC_BODY_PT = _S("presend_gate.SPEC_BODY_PT")
SPEC_NAME_PT = _S("presend_gate.SPEC_NAME_PT")
SPEC_HEADING_PT = _S("presend_gate.SPEC_HEADING_PT")
PAGE_LIMIT = _S("presend_gate.PAGE_LIMIT", default=2)              # tailored resume pages (Rules File section 6, set in Start Here session 3)
LAST_PAGE_FILL_LIMIT = _S("presend_gate.LAST_PAGE_FILL", default=0.75)   # how full the last allowed page may be here, so Word doesn't spill

EVENT_WORDS = r"(launch\w*|releas\w*|cutover|migrat\w*|pilot\w*|retir\w*|shut\s*down|shutdown|decommission\w*|deliver\w*|ship\w*|went live|go.?live)"
DATE_WORDS = r"((19|20)\d\d|Q[1-4]\b|H[12]\b|first half|second half|January|February|March|April|May|June|July|August|September|October|November|December)"
YEAR_NEAR_EVENT = re.compile(rf"(?:{EVENT_WORDS}[^.\n]{{0,40}}\b{DATE_WORDS})|(?:\b{DATE_WORDS}[^.\n]{{0,40}}{EVENT_WORDS})", re.I)
NUMBER_RE = re.compile(r"(?<![A-Za-z(\d])(\d[\d,.]*\+?%?)")
# Figures written as words (Nov 1, 2026 dry run: "a third", "doubled" slipped past the digit check).
WORD_FIGURE_RE = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|"
    r"hundreds?|thousands?|millions?|billions?|dozens?|half|halved|thirds?|quarters?|"
    r"doubled?|doubling|tripled?|tripling|twice|three-fold|threefold|tenfold)\b", re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\b\d{3}[\s.-])?\b\d{3}[\s.-]\d{4}\b")
PLACEHOLDER_RE = re.compile(r"<[^<>]{1,80}>")


# ---------------------------------------------------------------- bank index
def load_index(path=None):
    p = Path(path) if path else next((c for c in INDEX_CANDIDATES if c.exists()), None)
    if not p or not p.exists():
        return None, None
    data = json.loads(p.read_text(encoding="utf8"))
    return data["entries"], p


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(".").strip().lower()


def word_diff(a: str, b: str) -> str:
    aw, bw = a.split(), b.split()
    sm = difflib.SequenceMatcher(None, aw, bw)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        out.append(f"page '{' '.join(aw[i1:i2])}' vs bank '{' '.join(bw[j1:j2])}'")
    return "; ".join(out)[:300]


# ---------------------------------------------------------------- docx reading
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_paragraphs(path: Path):
    """Return list of (text, is_bullet) from the document body, in order.

    Reads every w:t inside each paragraph, wherever it sits (tables, content
    controls, tracked insertions, smart tags, simple fields), so no text on the
    page is invisible to the trace (Nov 1, 2026 dry run). Deleted text
    (w:delText) is not shown in Word and is skipped."""
    from docx import Document  # local import so .md/.txt runs don't need it
    doc = Document(str(path))
    styles = {s.style_id: s.name for s in doc.styles}
    out = []
    for p in doc.element.body.iter(W_NS + "p"):
        if any(a.tag == W_NS + "p" for a in p.iterancestors()):
            continue  # a paragraph nested in a text box is read with its own paragraph
        t = "".join((x.text or "") if x.tag == W_NS + "t" else " " for x in p.iter(W_NS + "t", W_NS + "tab")).strip()
        if not t:
            continue
        pPr = p.find(W_NS + "pPr")
        num = pPr is not None and pPr.find(W_NS + "numPr") is not None
        st = pPr.find(W_NS + "pStyle") if pPr is not None else None
        sname = styles.get(st.get(W_NS + "val"), "") if st is not None else ""
        out.append((t, num or sname.lower().startswith("list")))
    return out


def extract_docx_xml(path: Path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf8")
        structural = []
        if "<w:tbl>" in xml:
            structural.append("contains a TABLE (w:tbl), ATS parsing risk")
        if "txbxContent" in xml:
            structural.append("contains a TEXT BOX, ATS parsing risk")
        if re.search(r"<w:(ins|del)\b", xml):
            structural.append("contains TRACKED CHANGES; accept or reject them all, then rebuild from the selection")
        for tag, what in (("sdt", "a CONTENT CONTROL"), ("smartTag", "a SMART TAG"), ("fldSimple", "a FIELD"),
                          ("fldChar", "a FIELD"), ("altChunk", "an EMBEDDED DOCUMENT")):
            if re.search(rf"<w:{tag}\b", xml):
                structural.append(f"contains {what} (w:{tag}); the builder never makes one, so the file was edited by hand")
        for name in z.namelist():
            if name.startswith("word/header") or name.startswith("word/footer"):
                hf = z.read(name).decode("utf8")
                if re.sub(r"<[^>]+>", "", hf).strip():
                    structural.append(f"non-empty header/footer ({name}), content there is often unparsed")
    return structural


def formatting_checks(path: Path):
    issues = []
    with zipfile.ZipFile(path) as z:
        doc = z.read("word/document.xml").decode("utf8")
        styles = z.read("word/styles.xml").decode("utf8") if "word/styles.xml" in z.namelist() else ""
    fonts = set(re.findall(r'w:ascii="([^"]+)"', doc + styles))
    other = sorted(f for f in fonts if f.lower() != SPEC_FONT.lower() and not f.lower().startswith("symbol") and "wingdings" not in f.lower())
    if other:
        issues.append(f"fonts other than {SPEC_FONT} present: {', '.join(other)}")
    if SPEC_FONT.lower() not in " ".join(fonts).lower():
        issues.append(f"{SPEC_FONT} not found in document or styles")
    sizes = sorted({int(x) / 2 for x in re.findall(r'<w:sz w:val="(\d+)"', doc)})
    allowed = {SPEC_BODY_PT, SPEC_NAME_PT, SPEC_HEADING_PT}
    odd = [sz for sz in sizes if sz not in allowed]
    if odd:
        issues.append(f"font sizes outside spec ({SPEC_BODY_PT}/{SPEC_HEADING_PT}/{SPEC_NAME_PT} pt): {', '.join(str(x) for x in odd)}")
    if sizes and max(sizes) < SPEC_NAME_PT:
        issues.append(f"no {SPEC_NAME_PT} pt run found (name line)")
    if "<w:cols " in doc and re.search(r'<w:cols w:num="([2-9])"', doc):
        issues.append("multi-column section present (spec is one column)")
    if "<w:drawing>" in doc or "<w:pict>" in doc:
        issues.append("image or drawing present (spec is text only)")
    typed_bullets = len(re.findall(r"<w:t[^>]*>\s*[•\-–]\s", doc))
    if typed_bullets:
        issues.append(f"{typed_bullets} paragraph(s) start with a typed bullet character; use real list bullets")
    colors = set(re.findall(r'<w:color w:val="([0-9A-Fa-f]{6})"', doc))
    colored = sorted(c for c in colors if c.upper() not in {"000000", "AUTO"})
    if colored:
        issues.append(f"colored text present ({', '.join(colored)}); spec is black on white")
    m = re.search(r'<w:pgMar [^>]*w:left="(\d+)"[^>]*w:right="(\d+)"', doc) or re.search(r'<w:pgMar [^>]*w:right="(\d+)"[^>]*w:left="(\d+)"', doc)
    if m:
        vals = {int(m.group(1)), int(m.group(2))}
        if any(abs(v - 1008) > 30 for v in vals):
            issues.append(f"side margins {sorted(vals)} twips; spec is 0.7 inch (1008)")
    return issues


LAST_PAGE_FILL = None


def page_count(path: Path):
    n, err = _page_count(path)
    return (n, err) if n is not None or err and "not installed" in err else _page_count(path)   # retry a failed render once


def _page_count(path: Path):
    from platform_support import find_soffice
    soffice = find_soffice()
    if not soffice:
        return None, "soffice not installed; render the file and count pages manually"
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(path)],
                       capture_output=True, timeout=180)
        pdfs = list(Path(td).glob("*.pdf"))
        if not pdfs:
            return None, "PDF render failed; count pages manually"
        global LAST_PAGE_FILL
        LAST_PAGE_FILL = None
        try:
            import pdfplumber
            with pdfplumber.open(str(pdfs[0])) as pdf:
                pg = pdf.pages[-1]
                ws = pg.extract_words()
                if ws:
                    LAST_PAGE_FILL = max(w["bottom"] for w in ws) / pg.height
        except Exception:
            pass
        pdfinfo = shutil.which("pdfinfo")
        if pdfinfo:
            out = subprocess.run([pdfinfo, str(pdfs[0])], capture_output=True, text=True).stdout
            m = re.search(r"Pages:\s+(\d+)", out)
            if m:
                return int(m.group(1)), None
        data = pdfs[0].read_bytes()
        n = len(re.findall(rb"/Type\s*/Page[^s]", data))
        return (n if n > 0 else None), None


# ---------------------------------------------------------------- the page against its selection
SELECTION_OVERRIDE = None   # --selection on the command line
CURRENT_MASTER = False      # set by selection_trace from the selection's "master": true
INDEX_PATH = None           # where bank-index.json was found (Part C is read from the bank beside it)


def find_selection(path: Path):
    """The selection file beside a document whose `output` names it (any version),
    or the one passed with --selection."""
    if SELECTION_OVERRIDE:
        return SELECTION_OVERRIDE, json.loads(SELECTION_OVERRIDE.read_text(encoding="utf8"))
    stem = re.sub(r"_v\d+$", "", path.stem).replace("_CoverLetter", "_Resume", 1)   # a letter's selection is its resume's
    for j in sorted(path.parent.glob("*.json"), reverse=True):
        try:
            sel = json.loads(j.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        out = sel.get("output") if isinstance(sel, dict) else None
        if isinstance(out, str) and re.sub(r"_v\d+$", "", Path(out).stem) == stem:
            return j, sel
    return None, None


def selection_trace(path: Path, paras, index):
    """Every line on a resume comes from the bank through its selection file.

    Rebuilds the page from the selection and flags any line on the document
    that the selection doesn't produce (a hand edit). Then checks the
    selection itself: the headline, profile, scope, education, credentials,
    and role lines are bank IDs; core expertise and tools are terms from
    A.core and A.tools; group labels and the bridge carry no figures; the
    bridge names the card it rests on; and on a tailored resume, no bullet
    comes from a card whose Tier line excludes the application's tier.
    Returns (flags, notes)."""
    flags, notes = [], []
    if "coverletter" in path.name.lower().replace("_", "").replace(" ", "") or path.suffix.lower() != ".docx":
        return flags, notes
    j, sel = find_selection(path)
    if not sel:
        flags.append("[6 trace] no selection file beside it names this document in `output`; only its bullets could be traced")
        return flags, notes
    idx = {e["id"]: e for e in index}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_resume
    b = build_resume.Builder(idx, allow_proposed=sel.get("allow_proposed", False))
    try:
        b.build(sel)
    except SystemExit as e:
        flags.append(f"[6 trace] {j.name} doesn't build cleanly: {e}")
        return flags, notes
    except (KeyError, TypeError, ValueError) as e:
        flags.append(f"[6 trace] {j.name} is missing or misshapes a field: {e!r}")
        return flags, notes
    from collections import Counter
    expected = Counter(norm(p_.text) for p_ in b.doc.paragraphs if p_.text.strip())
    on_page = Counter(norm(t) for t, _ in paras)
    for t, is_bullet in paras:
        if norm(t) not in expected:
            flags.append(f"[6 trace] line not produced by {j.name} (edited by hand?) -> {t[:120]}")
    for k, n in on_page.items():
        if k in expected and n > expected[k]:
            flags.append(f"[6 trace] line appears {n} times but {j.name} makes it {expected[k]} time(s) -> {k[:120]}")
    missing = [k for k in expected if on_page.get(k, 0) < expected[k]]
    if missing:
        flags.append(f"[6 trace] {len(missing)} line(s) {j.name} makes are missing from the page (deleted by hand?): " + "; ".join(m[:60] for m in missing[:3]))
    if [norm(t) for t, _ in paras] != [norm(p_.text) for p_ in b.doc.paragraphs if p_.text.strip()] and not missing \
            and all(on_page[k] == expected[k] for k in expected):
        flags.append(f"[6 trace] the page's lines are in a different order than {j.name} builds them (moved by hand?)")

    # placeholders and the name line (Nov 1, 2026 dry run: template text gated clean)
    for t, _ in paras:
        if PLACEHOLDER_RE.search(t):
            flags.append(f"[6 trace] template placeholder left on the page -> {t[:120]}")
    name = str(sel.get("name") or "").strip()
    if not name or name.upper() in ("YOUR NAME", "<YOUR NAME>"):
        flags.append("[6 trace] the selection has no name (set \"name\" to your name as it goes on the page)")
    contact = str(sel.get("contact") or "")
    if re.search(r"[.;!?]\s+[A-Z]|\b(led|built|managed|owned|launched|grew|delivered|years?)\b", contact, re.I):
        flags.append(f"[6 trace] the contact line reads like a claim; it holds only location, phone, email, and links -> {contact[:120]}")

    used = Counter(b.used)
    dup = sorted(u for u, n in used.items() if n > 1 and u.startswith(("E", "P")))
    if dup:
        flags.append("[6 trace] the same bullet ID is used twice: " + ", ".join(dup))
    per_story = Counter(idx[u].get("story") for u in b.used if u.startswith(("E", "P")))

    def is_id(v):
        if isinstance(v, dict):
            v = v.get("id")
        return isinstance(v, str) and v in idx
    for key in ("headline", "education", "credentials"):
        if key in sel and not is_id(sel[key]):
            flags.append(f"[6 trace] {key} is typed into the selection, not a bank ID")
    is_master = sel.get("master") is True   # the master is marked in its selection, never by file name
    global CURRENT_MASTER
    CURRENT_MASTER = is_master
    tier = sel.get("tier")
    sel_notes = sel.get("notes") if isinstance(sel.get("notes"), dict) else {}
    if "notes" in sel and not isinstance(sel.get("notes"), dict):
        flags.append("[6 trace] notes must be a set of named fields (posting, tier, bridge_source, ...), not one block of text")
    prof = sel.get("profile")
    if not is_id(prof):
        flags.append("[6 trace] profile is typed into the selection, not a bank ID")
    if isinstance(prof, dict) and prof.get("bridge"):
        bridge = str(prof["bridge"]).strip()
        if re.search(r"\d", bridge) or WORD_FIGURE_RE.search(bridge):
            flags.append("[6 trace] the bridge sentence has a figure; figures come only from bank bullets")
        if len(bridge.split()) > 35 or len(re.findall(r"[.!?](\s|$)", bridge)) > 1:
            flags.append("[6 trace] the bridge is more than one short sentence (35 words at most)")
        src = str(sel_notes.get("bridge_source", ""))
        cards = []
        for c in re.findall(r"\bE\d{2}(?:\.\d+)?\b", src):
            if c not in cards and any(k == c or k.startswith(c + ".") for k in idx):
                cards.append(c)
        if not cards:
            flags.append("[6 trace] the bridge sentence has no card behind it: notes.bridge_source must name a bank card (E01 or E01.2)")
        else:
            notes.append(f"[6 trace] bridge rests on {', '.join(cards)}; check it claims only what those cards say")
            if tier in (1, 2, 3) and not is_master:
                off = [c for c in cards if all(idx[k].get("tiers") and tier not in idx[k]["tiers"]
                                               for k in idx if k == c or k.startswith(c + "."))]
                if off:
                    flags.append(f"[tier] the bridge rests on card(s) limited to other tiers: {', '.join(off)}")
    if sel.get("banner") and not is_master:
        flags.append(f"[6 trace] a banner is typed text for the master only; take it off this page -> {str(sel['banner'])[:100]}")
    elif sel.get("banner"):
        notes.append(f"[6 trace] master banner: {str(sel['banner'])[:100]}")
    for kind in ("roles", "earlier"):
        for r in sel.get(kind) or []:
            if not is_id(r.get("id")):
                what = r.get("title") or r.get("id") or "no title"
                flags.append(f"[6 trace] a role in {kind} is typed in or not in the bank ({str(what)[:50]}); employer, title, and dates belong in the bank's Part A (A.role / A.earlier)")
            if r.get("scope") and not is_id(r["scope"]):
                flags.append("[6 trace] a scope line is typed in, not a bank ID")
            for g in r.get("groups") or []:
                label = g.get("label", "")
                if re.search(r"\d", label) or WORD_FIGURE_RE.search(label):
                    flags.append(f"[6 trace] group label has a figure -> {label[:80]}")

    def terms(text):
        return {norm(x) for x in re.split(r"\s[•|]\s|,\s*", text) if x.strip()}
    core = set().union(*[terms(e["text"]) for e in index if e["id"].startswith("A.core") and e["on_paper_ok"]] or [set()])
    ce = sel.get("core_expertise")
    if isinstance(ce, str) and not is_id(ce):
        ce = [x for x in re.split(r"\s[•|]\s|,\s*", ce) if x.strip()]   # typed as one line: check each term
    if isinstance(ce, list):
        extra = [x for x in ce if norm(str(x)) not in core]
        if extra:
            flags.append("[6 trace] core expertise terms not in A.core: " + ", ".join(map(str, extra)))
    tools = sel.get("tools")
    if not is_id(tools):
        have = set().union(*[terms(e["text"]) for e in index if e["id"].startswith("A.tools") and e["on_paper_ok"]] or [set()])
        text = tools.get("text", "") if isinstance(tools, dict) else str(tools or "")
        extra = sorted(terms(text) - have)
        if not have:
            flags.append("[6 trace] tools are typed in and the bank has no A.tools line to check them against")
        elif extra:
            flags.append("[6 trace] tools not in A.tools: " + ", ".join(extra))

    if not is_master:
        heavy = [s for s, n in per_story.items() if n > 3]
        if heavy:
            flags.append("[6 trace] more than three bullets from one story: " + "; ".join(str(s)[:50] for s in heavy))
        if isinstance(tier, str) and tier.strip() in ("1", "2", "3"):
            flags.append(f"[tier] tier is written as text (\"{tier}\"); write it as the number {tier.strip()}")
        elif tier not in (1, 2, 3):
            flags.append("[tier] the selection has no tier (1, 2, or 3), so card tier limits can't be checked")
        else:
            off = [u for u in b.used if idx[u].get("tiers") and tier not in idx[u]["tiers"]]
            if off:
                flags.append(f"[tier] tier {tier} page uses bullets from cards limited to other tiers: {', '.join(off)}")
    notes.append(f"[6 trace] every line checked against {j.name}")
    return flags, notes


# ---------------------------------------------------------------- the gate
def is_letter(path: Path) -> bool:
    return "coverletter" in path.name.lower().replace("_", "").replace(" ", "")


SIGNOFF_RE = re.compile(r"^(sincerely|best|best regards|kind regards|regards|warmly|warm regards|thank you|thanks|respectfully|with thanks|cheers)\b", re.I)


def letter_body(paras):
    """The body paragraphs of a letter: everything after the greeting ("Dear ...")
    and before the sign-off. Without a greeting, every paragraph after the
    name, headline, contact, and date lines."""
    texts = [t for t, _ in paras]
    start = next((i + 1 for i, t in enumerate(texts) if re.match(r"^(dear|hello|hi|to)\b", t, re.I)), None)
    if start is None:
        start = next((i + 1 for i, t in enumerate(texts) if re.match(r"^[A-Z][a-z]+ \d{1,2}, (19|20)\d\d$", t)), 0)
    body = []
    for t in texts[start:]:
        if SIGNOFF_RE.match(t):
            break
        body.append(t)
    return body


def part_c_figures():
    """Every figure written in the bank's Part C table (first column), normalized."""
    if not INDEX_PATH:
        return None
    try:
        src = json.loads(INDEX_PATH.read_text(encoding="utf8")).get("source")
        text = (INDEX_PATH.parent / src).read_text(encoding="utf8")
    except (OSError, ValueError, TypeError):
        return None
    m = re.search(r"^# Part C\b.*?$(.*?)(?=^# Part |\Z)", text, re.M | re.S)
    if not m:
        return None
    figs = set()
    for line in m.group(1).splitlines():
        if line.lstrip().startswith("|") and not re.match(r"^\s*\|\s*-", line):
            cell = line.strip().strip("|").split("|")[0]
            figs |= {n.rstrip(".,") for n in NUMBER_RE.findall(cell)}
    return figs


def letter_sources_check(path: Path, paras, index=None):
    """Cover letters are the untraced path (Oct 24, 2026 audit). The selection
    file that built the letter must carry a `letter_sources` map with one entry
    per body paragraph: the bank card or the user's dated statement it rests
    on. Since Nov 1, 2026 every paragraph between the greeting and the sign-off
    counts, card IDs must exist and fit the application's tier, and every
    figure in the letter must be in the bank's Part C. Returns (flags, notes)."""
    flags, notes = [], []
    if not is_letter(path):
        return flags, notes
    body = letter_body(paras)
    fallback = None
    j, sel = find_selection(path)
    if not sel:
        sels = sorted(path.parent.glob("selection-*.json"), reverse=True)
        if not sels:
            flags.append(f"[6 trace] letter: no selection file beside it, so its paragraphs have no recorded sources ({len(body)} body paragraphs)")
            return flags, notes
        j = sels[0]
        try:
            sel = json.loads(j.read_text(encoding="utf8"))
        except (OSError, ValueError) as e:
            flags.append(f"[6 trace] letter: could not read {j.name}: {e}")
            return flags, notes
        fallback = f"[6 trace] letter: no selection names its resume, so {j.name} (the newest) was used; pass --selection to choose"
    sources = sel.get("letter_sources") or {}
    if not isinstance(sources, dict) or not sources:
        flags.append(f"[6 trace] letter: {j.name} has no letter_sources; add one line per paragraph (card ID or dated statement) for {len(body)} body paragraphs")
        return flags, notes
    filled = [k for k, v in sources.items() if not k.startswith("_")
              and isinstance(v, str) and v.strip() and not v.strip().startswith("<")]
    if len(filled) < len(body):
        flags.append(f"[6 trace] letter: {len(body)} body paragraphs but letter_sources lists {len(filled)} in {j.name}; every paragraph names its card or your dated statement")
    else:
        notes.append(f"[6 trace] letter: {len(filled)} sourced paragraph(s) in {j.name}: " + "; ".join(f"{k}: {sources[k][:60]}" for k in filled))
    unsourced_words = [k for k, v in sources.items() if not k.startswith("_") and isinstance(v, str) and re.search(r"\b(assumed|inferred|guess)", v, re.I)]
    if unsourced_words:
        flags.append("[6 trace] letter: paragraphs marked assumed or inferred: " + ", ".join(unsourced_words))
    if index is not None:
        idx = {e["id"]: e for e in index}
        tier = sel.get("tier") if not sel.get("master") else None
        for k in filled:
            for c in re.findall(r"\b(?:P-)?E\d{2}(?:\.\d+[a-z]?)?\b", sources[k]):
                hits = [e for i, e in idx.items() if i == c or i.startswith(c + ".")]
                if not hits:
                    flags.append(f"[6 trace] letter: {k} names {c}, which isn't in the bank")
                elif tier in (1, 2, 3) and all(e.get("tiers") and tier not in e["tiers"] for e in hits):
                    flags.append(f"[tier] letter: {k} rests on {c}, a card limited to other tiers (this application is tier {tier})")
                elif all(not e["on_paper_ok"] for e in hits):
                    flags.append(f"[6 trace] letter: {k} rests on {c}, which isn't approved for paper")
    figs = part_c_figures()
    text = " ".join(body)
    nums = sorted({n.rstrip(".,") for n in NUMBER_RE.findall(PHONE_RE.sub(" ", text))} - set("0123456789"))
    nums = [n for n in nums if not re.fullmatch(r"(19|20)\d\d", n.rstrip("+%"))]
    if figs is None:
        if nums:
            notes.append("[3 numbers] letter figures to check against Part C (Part C not found): " + ", ".join(nums))
    else:
        missing = [n for n in nums if n not in figs]
        if missing:
            flags.append("[3 numbers] letter: figure(s) not in bank Part C: " + ", ".join(missing))
    words = sorted({w.lower() for w in WORD_FIGURE_RE.findall(text)})
    if words:
        notes.append("[3 numbers] letter: figures in words, check each against Part C: " + ", ".join(words))
    if fallback:
        notes.append(fallback)
    return flags, notes



# Gate item 13: unnecessary repetition. The same phrase or
# idea said twice reads as padding to an outside reader and has slipped through
# more than once. Mechanical part: any run of four or more words that appears in
# two different paragraphs (the name, contact, headline, dates, and section
# headings are skipped), and any content word of six or more letters that appears
# in three or more paragraphs. The judgment part (does the page tell one story a
# reader with none of the user's context can follow?) is the rubric reviewer's
# "outsider read".
_REPEAT_SKIP = re.compile(_S("presend_gate.REPEAT_SKIP_RE"))   # header lines left out of the repeat check (name, contact, section titles)
_REPEAT_STOP = set(_S("presend_gate.REPEAT_STOPWORDS"))   # common words the repeat check ignores

def repetition_check(paras):
    flags, notes = [], []
    body = [t for t, _ in paras if not _REPEAT_SKIP.search(t) and len(t.split()) >= 6]
    def words(s):
        return [w for w in re.findall(r"[a-z0-9'+-]+", s.lower())]
    seen = {}
    for i, t in enumerate(body):
        ws = words(t)
        grams = set(" ".join(ws[k:k+4]) for k in range(len(ws) - 3))
        for g in grams:
            seen.setdefault(g, set()).add(i)
    dup = sorted(g for g, s in seen.items() if len(s) > 1)
    # collapse overlapping grams into the longest shared runs
    runs, used = [], set()
    for g in dup:
        if any(g in r for r in runs):
            continue
        runs.append(g)
    for g in runs[:12]:
        idx = sorted(seen[g])
        flags.append(f"[13 repeat] '{g}' appears in paragraphs {idx[0]+1} and {idx[1]+1} (body paragraphs, in order)")
    counts = {}
    for i, t in enumerate(body):
        for w in set(words(t)):
            if len(w) >= 6 and w not in _REPEAT_STOP and not w[0].isdigit():
                counts.setdefault(w, set()).add(i)
    heavy = sorted((w, len(s)) for w, s in counts.items() if len(s) >= 3)
    if heavy:
        notes.append("[13 repeat] words in three or more paragraphs (check each is earning its place): " + ", ".join(f"{w} ({n})" for w, n in heavy[:15]))
    return flags, notes

def page_rules(pages, fill, is_master, limit=None, fill_limit=None):
    """The page-count rules for a resume. Word lays out longer than LibreOffice
    (one resume was 2 pages here and 3 in Word; another fit in Word with its
    last line at 74% of page 2), so a resume at its page limit
    must end by LAST_PAGE_FILL of the last page here to leave Word room. The
    master has no limit. Returns (flags, notes)."""
    limit = PAGE_LIMIT if limit is None else limit
    fill_limit = LAST_PAGE_FILL_LIMIT if fill_limit is None else fill_limit
    flags, notes = [], []
    word = "one page" if limit == 1 else f"{limit} pages"
    level = "OK" if pages <= limit or is_master else f"FLAG, resumes stay at {word}"
    notes.append(f"[12 pages] rendered page count: {pages} ({level})")
    if is_master:
        return flags, notes
    if pages > limit:
        flags.append(f"[12 pages] {pages} pages rendered; resumes stay at {word}")
    elif pages == limit and fill is not None:
        notes.append(f"[12 pages] last line at {fill:.0%} of page {pages} (limit {fill_limit:.0%})")
        if fill > fill_limit:
            flags.append(f"[12 pages] page {pages} is {fill:.0%} full; Word will likely spill onto another page. Cut a bullet (limit {fill_limit:.0%})")
    return flags, notes


def posting_map_check(path: Path, paras):
    """Gate item 14: the page's group order follows the posting's own order of
    emphasis, and the first group answers one of the posting's top two themes.
    Reads `notes.posting_map` from the selection file beside a resume and
    prints the map against the page's group labels. Notes, not flags: the
    order is a judgment the rubric reviewer confirms (Step 3a); a resume still
    in drafting with no map is the one flag."""
    flags, notes = [], []
    if is_letter(path):
        return flags, notes
    j, sel = find_selection(path)
    if not sel:
        sels = sorted(path.parent.glob("selection-*.json"), reverse=True)
        if not sels:
            return flags, notes
        try:
            j, sel = sels[0], json.loads(sels[0].read_text(encoding="utf8"))
        except (OSError, ValueError):
            return flags, notes
    if sel.get("master") is True or not sel.get("roles"):
        return flags, notes
    notes_field = sel.get("notes")
    pmap = notes_field.get("posting_map") if isinstance(notes_field, dict) else None
    if not isinstance(pmap, list) or not pmap or any(str(m.get("ask", "")).startswith("<") for m in pmap if isinstance(m, dict)):
        msg = (f"[14 order] {j.name} has no filled posting_map: 3 to 5 themes in the posting's own order of emphasis, "
               f"each with the group on the page that answers it (application-materials, step 7a)")
        (flags if "(drafting)" in path.parent.name else notes).append(msg)
        return flags, notes
    groups = [str(g.get("label", "")).strip().rstrip(":") for g in (sel["roles"][0].get("groups") or [])]
    page_ids = set()
    for g in (sel["roles"][0].get("groups") or []):
        page_ids.update(g.get("bullets") or [])
    order_ok, last_pos, lines = True, -1, []
    for m in sorted((m for m in pmap if isinstance(m, dict)), key=lambda m: m.get("rank", 99)):
        answer = str(m.get("answer", "")).strip().rstrip(":")
        missing = [i for i in (m.get("ids") or []) if i not in page_ids]
        pos = next((i for i, g in enumerate(groups) if g.lower() == answer.lower()), None)
        where = f"group {pos + 1}" if pos is not None else ("off page" if answer.lower().startswith(("letter", "honest gap")) else "no such group")
        if pos is not None:
            if pos < last_pos:
                order_ok = False
            last_pos = max(last_pos, pos)
        lines.append(f"{m.get('rank', '?')}. {str(m.get('ask', ''))[:50]} -> {answer or '?'} ({where}{'; not on page: ' + ', '.join(missing) if missing else ''})")
    notes.append("[14 order] posting map vs page: " + " | ".join(lines))
    if not order_ok:
        notes.append("[14 order] group order on the page does not follow the posting map's order; justify in the selection notes or reorder")
    top_two = {str(m.get("answer", "")).strip().rstrip(":").lower() for m in pmap if isinstance(m, dict) and m.get("rank", 99) <= 2}
    if groups and groups[0].lower() not in top_two:
        notes.append(f"[14 order] first group '{groups[0]}' does not answer one of the posting's top two themes; the lead story must")
    return flags, notes


def run_gate(path: Path, index):
    global CURRENT_MASTER
    CURRENT_MASTER = False
    flags, notes = [], []
    structural = []
    approved_lines = set()   # normalized texts of lines that matched an approved bank entry
    suppressed = []

    if path.suffix.lower() == ".docx":
        paras = docx_paragraphs(path)
        structural = extract_docx_xml(path)
        lines = [t for t, _ in paras]
    else:
        text = path.read_text(encoding="utf8", errors="replace")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        paras = [(l, l.startswith(("- ", "• ", "* "))) for l in lines]

    lf, ln = letter_sources_check(path, paras, index)
    flags.extend(lf)
    notes.extend(ln)
    mf, mn = posting_map_check(path, paras)
    flags.extend(mf)
    notes.extend(mn)
    if index is not None:
        sf, sn = selection_trace(path, paras, index)
        flags.extend(sf)
        notes.extend(sn)
    rf, rn = repetition_check(paras)
    flags.extend(rf)
    notes.extend(rn)

    # ---- bank trace (docx bullets, plus md/txt list lines)
    if index is not None:
        by_norm = {}
        for e in index:
            by_norm.setdefault(norm(e["text"]), []).append(e)
        traced = []
        for t, is_bullet in paras:
            if not is_bullet:
                continue
            key = norm(re.sub(r"^[-•*]\s+", "", t))
            hits = by_norm.get(key)
            if hits:
                e = hits[0]
                traced.append(f"{e['id']} ({e['status']})")
                if e["on_paper_ok"]:
                    approved_lines.add(key)
                else:
                    flags.append(f"[6 trace] {e['id']} is {e['status']}; not for a page that may be sent -> {t[:120]}")
                continue
            best, score = None, 0.0
            for k, es in by_norm.items():
                r = difflib.SequenceMatcher(None, key, k).ratio()
                if r > score:
                    best, score = es[0], r
            if best and score >= 0.6:
                flags.append(f"[6 trace] near match to {best['id']} ({score:.2f}), wording drifted: {word_diff(key, norm(best['text']))}")
            else:
                flags.append(f"[6 trace] untraced bullet (no bank entry within reach) -> {t[:140]}")
        if traced:
            notes.append("[6 trace] bullets traced: " + ", ".join(traced))
        # non-bullet paragraphs that match a Part A entry (headline, profile, core expertise, credentials, tools)
        for t, is_bullet in paras:
            if is_bullet:
                continue
            k = norm(t)
            hits = by_norm.get(k)
            if hits:
                e = hits[0]
                if e["on_paper_ok"]:
                    approved_lines.add(k)
                else:
                    flags.append(f"[6 trace] {e['id']} is {e['status']}; not for a page that may be sent -> {t[:120]}")
                if e["id"].startswith("A.profile"):
                    notes.append(f"[6 trace] profile matches {e['id']} ({e['status']})")
        # a core-expertise line made of approved terms in any order or subset
        core_terms = set()
        for e in index:
            if e["id"].startswith("A.core") and e["on_paper_ok"]:
                core_terms |= {norm(x) for x in re.split(r"\s[•|]\s", e["text"])}
        for t, is_bullet in paras:
            if is_bullet or ("•" not in t and "|" not in t) or len(t) > 400:
                continue
            terms = [norm(x) for x in re.split(r"\s[•|]\s", t)]
            if len(terms) >= 3 and all(x in core_terms for x in terms):
                approved_lines.add(norm(t))
                notes.append(f"[6 trace] core expertise: {len(terms)} terms, all from A.core")
            elif len(terms) >= 3 and sum(x in core_terms for x in terms) >= len(terms) - 2:
                extra = [x for x in terms if x not in core_terms]
                notes.append(f"[6 trace] core expertise has terms not in A.core (need your OK): {', '.join(extra)}")
        # a profile with a bridge sentence appended
        profiles = [e for e in index if e["id"].startswith("A.profile")]
        for t, is_bullet in paras:
            if is_bullet or len(t) < 200:
                continue
            k = norm(t)
            if k not in by_norm and any(k.startswith(norm(p["text"])[:120]) for p in profiles):
                notes.append("[6 trace] profile is a bank profile plus a bridge sentence; verify the bridge against the posting and the bank")
            break
    else:
        notes.append("[6 trace] bank-index.json not found; run bank_index.py so bullets can be traced mechanically")

    # ---- term checks
    for i, line in enumerate(lines, 1):
        low = line.lower()
        key = norm(re.sub(r"^[-•*]\s+", "", line))
        # retired wording is flagged everywhere, even inside an approved bullet: a phrase
        # retired after the bullet was approved must come out of the bank (Nov 1, 2026)
        for t in RETIRED_PHRASES:
            if t.lower() in low:
                flags.append(f"[2 retired] line {i}: '{t}' -> {line[:140]}")
        if key in approved_lines:
            # name what would have fired, for the summary
            for t in TIMING_TERMS + VOCAB_TERMS:
                if t.lower() in low:
                    suppressed.append(f"'{t}' in line {i}")
            if RETIRE_RE.search(line) and not SANCTIONED_RETIRE.search(line):
                suppressed.append(f"'retire*' in line {i}")
            continue
        for t in TIMING_TERMS:
            if t in low:
                flags.append(f"[1 timing] line {i}: '{t}' -> {line[:140]}")
        if RETIRE_RE.search(line) and not SANCTIONED_RETIRE.search(line):
            flags.append(f"[1 timing] line {i}: 'retire*' outside a sanctioned shape -> {line[:140]}")
        if YEAR_NEAR_EVENT.search(line):
            flags.append(f"[1 timing] line {i}: four-digit year near an internal event -> {line[:140]}")
        for t in VOCAB_TERMS:
            if re.search(rf"\b{re.escape(t.lower())}", low):
                if CREDENTIAL_OK.search(line):
                    continue   # a credential name as issued may carry a listed term
                flags.append(f"[2 vocab] line {i}: '{t}' -> {line[:140]}")
        for a in ABBREVIATIONS:
            ab = a.strip()
            if re.search(rf"(?<![A-Za-z]){re.escape(ab)}s?(?![a-z])", line):
                if f"({ab})" in line:
                    continue   # the spelled-out name with its abbreviation in parentheses
                flags.append(f"[2 abbreviation] line {i}: '{ab}' (spell out on paper) -> {line[:140]}")
        if FLAG_EM_DASH and "—" in line:
            flags.append(f"[11 em-dash] line {i}: em dash -> {line[:140]}")
        if re.search(r"(^|[;.] )I\b", line) and not line.lower().startswith(("master source", "dear", "review draft")):
            notes.append(f"[11 'I'] line {i}: standalone 'I' (forbidden in resume bullets, fine in cover letters) -> {line[:120]}")

    full = "\n".join(lines)
    for fig in ONCE_PER_RESUME:
        n = full.count(fig)
        if n > 1:
            flags.append(f"[3 figure-once] '{fig}' appears {n} times; a scale figure appears once per resume")

    numbers = sorted({n.rstrip(".,") for n in NUMBER_RE.findall(PHONE_RE.sub(" ", full))} - set("0123456789"))
    numbers = [n for n in numbers if not re.fullmatch(r"(19|20)\d\d", n.rstrip("+%"))
               and not re.fullmatch(r"\d{3}\.\d{3}\.\d{4}", n) and n not in ("365", "99")]
    if numbers:
        notes.append("[3 numbers] every figure must be in bank Part C and match exactly: " + ", ".join(numbers))
    words = sorted({w.lower() for w in WORD_FIGURE_RE.findall(full)})
    if words and not is_letter(path):
        notes.append("[3 numbers] figures in words (check each is in Part C or an approved bullet): " + ", ".join(words))

    pages = None
    if path.suffix.lower() == ".docx":
        pages, page_err = page_count(path)
        if page_err:
            notes.append(f"[12 pages] {page_err}")
        if pages is not None:
            is_master = CURRENT_MASTER
            if is_letter(path):
                if pages > 1:
                    flags.append(f"[12 pages] cover letter runs {pages} pages; letters stay at one")
                else:
                    notes.append("[12 pages] rendered page count: 1 (OK)")
        if pages is not None and not is_letter(path):
            pf, pn = page_rules(pages, LAST_PAGE_FILL, CURRENT_MASTER)
            flags.extend(pf)
            notes.extend(pn)
    for st in structural:
        flags.append(f"[ATS structure] {st}")
    if path.suffix.lower() == ".docx":
        for issue in formatting_checks(path):
            flags.append(f"[format] {issue}")

    print(f"\n================ GATE: {path.name} ================")
    if flags:
        print(f"{len(flags)} FLAG(S), each guilty until justified against the bank:")
        for f in flags:
            print("  " + f)
    else:
        print("No mechanical flags.")
    if suppressed:
        print(f"({len(suppressed)} term hit(s) inside approved bank bullets not flagged, since that wording was cleared when it entered the bank: "
              + ", ".join(suppressed) + ")")
    if notes:
        print("Review notes:")
        for n in notes:
            print("  " + n)
    print("Manual checks still required: duty test per bullet; cut test on proprietary detail;")
    print("uncharitable-reading and jargon tests; attribution; domain-tier tightening; no criticism of another team;")
    print("the outsider read (can a reader with none of your context follow why to hire you for THIS role?).")
    return 1 if flags else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("documents", nargs="+")
    ap.add_argument("--index")
    ap.add_argument("--selection", help="the selection file that built the document, when its output name differs")
    args = ap.parse_args()
    global SELECTION_OVERRIDE
    SELECTION_OVERRIDE = Path(args.selection) if args.selection else None
    index, ipath = load_index(args.index)
    global INDEX_PATH
    INDEX_PATH = ipath
    if ipath:
        print(f"bank index: {ipath}")
    log_phrases, lpath = retired_from_log()
    if lpath:
        added = [t for t in log_phrases if t.lower() not in {x.lower() for x in RETIRED_PHRASES}]
        RETIRED_PHRASES.extend(added)
        print(f"retired log: {lpath} ({len(added)} phrase(s) added to the hand list)")
    rc = 0
    for arg in args.documents:
        rc |= run_gate(Path(arg), index)
    sys.exit(rc)


if __name__ == "__main__":
    main()
