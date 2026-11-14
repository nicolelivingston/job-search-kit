#!/usr/bin/env python3
"""
Fit scoring for the job-search agent.
-------------------------------------
A 0-100 score for every posting, built from two sources the user owns:

  1. The user's criteria in the settings folder (hard rules, pay floor and
     target, excluded industries and companies, title skips, domains, level
     rules). Hard-rule fails produce an automatic Poor fit with the reason, so
     they never reach the LLM routines or the user's review.
  2. The evidence bank (one card per story). Work-type points come from
     keyword families mapped to the cards, and the matched card IDs are
     written back as "Fit Evidence" so tailoring starts from the right
     bullets instead of from scratch.

Everything here is pure functions over text. No network, no tokens. The
agent runs it on every posting it writes and re-runs it on tracker rows that
were scored by an older rubric (any row whose Score Breakdown does not start
with the current version).

Score is 0-100 and is stored as Role Fit Score = score / 10 so 7+ / 8+ views
keep working. Tiers:

  A  score >= 70, no hard fail   full information every run (LLM research)
  B  score 50-69, no hard fail   light: posting liveness, company refresh
                                 only when stale
  C  hard fail or score < 50     no LLM spend, ever; row kept with reason

Edit the keyword families and weights in the settings freely; keep
RUBRIC_VERSION in step so rescoring picks up the change.

Version notes
  v2.0  Evidence Bank rubric replaces the first score.
  v2.1  "24/7" counts as on-call duty only with duty wording nearby (it was
        skipping postings over "24/7 GP access" in benefits).
  v2.2  Hybrid-posture company: a posting that itself says remote is a
        Possible fit instead of a Poor fit (the company stays open unless an
        office mandate is verified from the company's own words). Developer
        tooling is judged by the role, not the company.
  v2.3  Countable minimums cap the score (one missing -> Tier B, two or more
        -> Tier C).
  v2.4  Found when a posting scored work 0/30: its stored text was an old,
        HTML-escaped capture of the intro only. The agent now replaces stale captures (see job_search_agent.py
        snapshot_is_stale) and scores cleaned text.
  v2.6  Countable minimum added: backend API / data model ownership.
  v2.7  No posted base pay caps the score at 49 (Tier C, no research spend)
        when the user turns that on. A dollar amount in the text counts as
        posted, since the salary extractor can miss ranges.
  v2.8  An excluded industry is a hard Poor fit (title, text, or company
        name).
  v2.9  A confirmed gap counts as required if ANY mention sits near
        requirement wording (was: first mention only). Found on a posting
        with the minimum in a second mention.
  v3.0  Freshness: +5 posted within 7 days, +3 within 14, 0 to 30, -5 to 60,
        -10 older (rank fresher good fits higher).
  v3.1  Bare 'data modeling' dropped from the backend API / data model
        minimum (a posting listed it as an AI-tools task and was capped at
        69).
  v3.2  Unresearched company scores 5 of 20 (was 10, neutral).
  v3.3  Every row gets a verdict (blank verdicts sat on the best near-misses,
        because the one-missing-minimum cap of 69 kept them out of Tier A).
        The agent writes a fit label; the user writes their own decision.
        Only hard-rule Poor fits (and the user's Passed) are closed; a Poor
        fit for no pay, 2+ missing minimums, or weak fit stays open.
  v3.4, v3.5  (Not in the kit.)
  v3.6  Verdict names: the agent writes Strong fit / Possible fit / Poor fit;
        the user writes Applying / Passed. Old names carry over once
        (OLD_VERDICTS).
  v3.7  Five scorer fixes. (1) Domain: no Domain on the Companies row (or no
        row) is 0 domain points and "domain unknown", never a keyword guess
        (benefits text like "401(k)" was scoring developer-tooling companies
        20/20 as a finance domain). (2) Required sections: every bullet
        under a Required / Minimum / Requirements / Qualifications / What
        we're looking for heading is a stated minimum, so a confirmed gap
        anywhere in that block is a full miss (a posting scored 90 with four
        misses in "Required Skills and Experience").
        REQUIRED_BLOCK_FAMILIES (keyword-groups.json) hold gaps counted in a
        required block only. (3) Industry minimums: "N years" or "experience
        in" an industry outside the user's field is a miss
        (OUT_OF_DOMAIN_INDUSTRIES). (4) Staffing: a posting with no benefits
        named and a flat single-number salary is capped at Possible fit.
        (5) A databases / data / platform / infrastructure / API / developer
        title at a company tagged with the infrastructure domain is Possible
        fit at most.
  v3.8  Strong fit was out of reach (no open row reached it). (1) A years
        minimum one year over what the user can claim (YEARS_GRACE) is met,
        not a miss; the breakdown still says so. (2) One missing minimum no
        longer blocks Strong fit when the score before the cap is
        ONE_MISS_STRONG_MIN or higher: no cap, Strong fit, and the miss is
        named in the Label Reason. Under that, one miss still caps at 69.
        (3) A Poor fit verdict kept from the daily refresh screen also caps
        the written score at 4.9 and Tier C, so score and label agree.
  v3.9  Required-section families can name whole gap areas (a field of
        systems the user hasn't worked in). Counted only inside a required
        section, since the same words in Responsibilities describe the work,
        not a minimum.
  v4.0  Required-item coverage (Strong fit on roles that aren't, and a worry
        that real fits are hidden). Until now a required item the user can't
        claim was caught only when a hand-written family existed for it, one
        new family per false Strong fit. Now: (1) cleaned text keeps bullet
        and paragraph boundaries (" • "), so a required block can be read
        item by item; (2) required-section headings are recognized in the
        forms boards actually use (What you'll bring, You have, Who you are,
        About you, What we need from you, all-caps headings); (3) every item
        in a required block is classified: a stated minimum or confirmed gap
        (a miss, as before), a years line, a soft item (plus, ideally,
        preferred), an item the Evidence Bank vouches for (VOUCH_WORDS,
        VOUCH_FIELD_WORDS, VOUCH_GENERIC), or an item it can't vouch for.
        The phrase after "knowledge of" / "experience with" is what must be
        vouched for, so "clinical trial processes" is not covered by the
        word "onboarding" later in the sentence. Two unvouched items cap the
        score at 69 (Possible fit) and are quoted in the breakdown; four, or
        half the items, cap at 49 (Poor fit). REQUIRED_COVERAGE turns the
        pass off. (4) The uncapped score is kept (score_uncapped, and
        "uncapped NN" in the breakdown) so capped rows can still be ranked
        and a near miss can alert (job_search_agent).
  v4.1  Posting boilerplate is never a requirement, and equal-opportunity
        text never trips a rule. (1) Required-item coverage skips
        disclaimers, hiring-scam notices, equal-opportunity and
        accommodation text, pay and benefits lines, time off, physical
        demands, application-process lines, and company-values lines; the
        required block also stops at more section endings (Additional
        information, Physical demands, Time off, Who we are, Our mission or
        culture, Date of posting). Benefits text after the requirements was
        being quoted as requirements the user couldn't meet and capping good
        fits. (2) A hard rule or an excluded-industry word that only appears
        inside an equal-opportunity statement ("race, religion, ... military
        or veteran status") no longer counts. Excluding an industry such as
        defense was closing nearly every US posting on arrival, because the
        statement names veterans and military service.
  v4.2  Two cases that hid a requirement or a catch. (1) A required-section
        heading with more words on its own line ("What You Bring To The
        Team", "What you'll need in this role") no longer ends its own
        section: the end of the section is looked for after the heading's
        line, so its items are read. Before, such a heading returned no
        items, and a requirement the user can't claim went unseen.
        (2) Remote with a catch also covers "not remote-only", in-person
        working sessions, and quarterly get-togethers (new phrases in the
        remote-catch rule; older settings folders get them on the next run).
        The stored posting text also keeps any sentence a remote rule would
        quote from the part of the intro it cuts
        (job_search_agent.make_snapshot), so a rescore still sees it.
"""

import html
import re
from datetime import date, datetime, timedelta

RUBRIC_VERSION = "v4.2"

# Verdicts (v3.3). The agent writes AGENT_VERDICTS on every row;
# HUMAN_VERDICTS are the user's alone and are never overwritten.
AGENT_VERDICTS = ("Strong fit", "Possible fit", "Poor fit")
HUMAN_VERDICTS = ("Applying", "Passed")
RETIRED_VERDICTS = ("Watch", "Watch (no decision)", "Ask me first")
# v3.6 (Nov 2, 2026): old name -> new name, applied once to every row by
# job_search_agent.migrate_verdict_names.
OLD_VERDICTS = {"Apply": "Strong fit", "Your call": "Possible fit", "Skip": "Poor fit",
                "Pursue": "Applying", "Pass": "Passed", "Watch": "Possible fit",
                "Watch (no decision)": "Possible fit", "Ask me first": "Possible fit"}

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _rx(*phrases):
    """Case-insensitive alternation of whole-word phrases."""
    parts = []
    for p in phrases:
        if p.startswith("~"):          # raw regex, no word anchors
            parts.append(p[1:])
        else:
            parts.append(r"\b" + re.escape(p).replace(r"\ ", r"\s+") + r"\b")
    return re.compile("|".join(parts), re.I)


SEP = " • "   # v4.0: bullet and paragraph boundary kept in cleaned text
_BLOCK_TAG_RE = re.compile(
    r"<\s*/\s*(?:li|p|div|h[1-6]|tr|ul|ol|section|blockquote|td)\s*>|<\s*br\s*/?\s*>|<\s*li\b[^>]*>", re.I)


def _clean(text):
    """Cleaned posting text. Greenhouse descriptions arrive entity-encoded
    (&lt;p&gt;); unescape twice (some are double-encoded) before stripping
    tags. v4.0: block-level tags and line breaks become " • " so a required
    section can be read item by item (the old cleaning ran every bullet into
    one sentence). Text that was cleaned before v4.0 has no separators and is
    split on sentence boundaries instead."""
    text = html.unescape(html.unescape(text or ""))
    text = _BLOCK_TAG_RE.sub(SEP, text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\r\n]+", SEP, text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\s*•\s*){2,}", SEP, text)
    # markdown markers from a posting saved as .md (## heading, - bullet, **bold**)
    text = re.sub(r"(?:^|(?<=• ))(?:#{1,6}\s*|[-*]\s+)", "", text)
    text = text.replace("**", "")
    return text.strip(" •")


def _snippet(text, m, width=70):
    a = max(0, m.start() - width)
    b = min(len(text), m.end() + width)
    return ("..." if a else "") + text[a:b].strip() + ("..." if b < len(text) else "")


REQUIREMENT_WORDS = _rx("required", "requirement", "must have", "must", "minimum", "qualifications",
                        "what we look for", "what we're looking for", "what you'll bring", "what you bring",
                        "looking for someone", "looking for a", "track record",
                        "you have", "you bring", "you'll need", "you will need",
                        "experience with", "experience in", "years of", "proven",
                        "strong background", "deep experience", "expertise in")


def _near_requirement(text, m, window=160, req_spans=None):
    if req_spans and _in_spans(m, req_spans):
        return True
    a, b = max(0, m.start() - window), min(len(text), m.end() + window)
    return bool(REQUIREMENT_WORDS.search(text[a:b]))


# v3.7: every bullet under a Required / Minimum / What
# we're looking for heading is a stated minimum. Cleaned text has no line
# breaks, so a heading is found by its capitalized wording, and the block runs
# to the next section heading (Preferred, Nice to have, Benefits, pay, About...)
# or REQ_BLOCK_MAX characters, whichever comes first.
_REQ_HEAD_WORDS = (
    r"(?:Required|Requirements|Minimum (?:qualifications|requirements)|Basic qualifications|Qualifications|"
    r"What (?:we're|we are|we’re) looking for|What we look for|What we need(?: from you)?|"
    r"What (?:you'll|you’ll|you will|you) (?:need|bring)(?: to [A-Za-z.&' ]{2,30})?|What you need to succeed|"
    r"Who you are|About you|You have|You bring|You are|You'll have|You’ll have|You should have|"
    r"Great fit if|You'll be a great fit|We're looking for|We are looking for|We'd love|"
    r"Skills (?:and|&) experience|Experience (?:and|&) skills|Your experience|Your background|"
    r"What it takes|(?:The |Our )?ideal candidate|What makes you a great fit|To be successful|Must[- ]haves?)")
REQ_HEAD_RE = re.compile(
    r"(?<!Preferred )(?<!Desired )(?<!Bonus )(?<!Additional )(?<!Nice-to-have )"
    # the pre-v4.0 form: a capitalized heading anywhere in run-together text
    r"\b(?:Required\b|Requirements\b|Minimum (?i:qualifications|requirements)\b|"
    r"Basic (?i:qualifications)\b|Qualifications\b|"
    r"What (?i:we're|we are|we’re) (?i:looking for)\b|What (?i:we look for)\b|"
    r"What (?i:you'll need|you will need|you need|you'll bring|you’ll bring|you bring|we need from you)\b|"
    r"Who (?i:you are)\b|About (?i:you)\b|Must[- ](?i:haves?)\b)"
    # v4.0: a heading that is its own segment (after " • " or at the start), any case
    r"|(?:(?<=• )|^)(?i:" + _REQ_HEAD_WORDS + r")\s*:?\s*(?=•|$)")
REQ_END_RE = re.compile(
    r"\b(?:Preferred|Nice[- ]to[- ](?i:haves?)|Bonus|Desired|Benefits|Perks|Even (?i:better)|Extra (?i:credit)|"
    r"What (?i:we offer)|What (?i:you'll get|you’ll get)|Compensation|Pay (?i:transparency|range)|"
    r"Salary|Base (?i:salary|pay)|The (?i:base|target|expected) (?i:salary|pay|base|range)|"
    r"About (?i:us|the|our)|Why (?i:join|you'll love|you’ll love|work|us)|Our (?i:benefits|process|team|values|hiring)|"
    r"Responsibilities|What (?i:you'll do|you’ll do|you will do)|In (?i:this role)|Not (?i:a fit)|"
    r"Interview (?i:process)|Hiring (?i:process)|Application (?i:process)|What (?i:to expect)|How (?i:we work)|The (?i:team)|"
    r"Equal (?i:opportunity|employment)|We (?i:are an equal)|How (?i:to apply)|Location|"
    # v4.1: more section endings (benefits, time off, physical demands, culture)
    r"Additional (?i:information|details)|Physical (?i:demands|requirements)|Work (?i:environment|schedule)|"
    r"(?:Paid )?Time (?i:off)|Vacation|Holidays|Who (?i:we are)|Our (?i:mission|culture|story|commitment)|"
    r"Life (?i:at)|Date (?i:of posting)|Diversity|Inclusion)\b"
    r"|#LI|(?:\b[A-Z]{3,}\b[ ,]+){2,}[A-Z]{3,}\b")   # an all-caps heading (WHAT TO EXPECT IN THE INTERVIEW PROCESS)
REQ_BLOCK_MAX = 3000

# v4.2: more words on a heading's own line ("What You Bring To The Team",
# "What you'll need in this role"). They are part of the heading, not the end
# of its section, even when they spell an end marker such as "The Team".
_HEAD_TAIL_RE = re.compile(r" (?i:to|for|in|on|as|at|with|of|and|&)(?: [A-Za-z'’&/-]+){0,5}\s*(?=•|:|\n|$)")


def required_spans(text):
    """(start, end) character spans of the posting's required sections."""
    spans = []
    for h in REQ_HEAD_RE.finditer(text or ""):
        start = h.start()
        if spans and start < spans[-1][1]:
            continue
        tail = _HEAD_TAIL_RE.match(text, h.end())
        e = REQ_END_RE.search(text, tail.end() if tail else h.end())
        end = min(e.start() if e else len(text), start + REQ_BLOCK_MAX)
        spans.append((start, end))
    return spans


def _in_spans(m, spans):
    return any(a <= m.start() < b for a, b in spans)


# ---------------------------------------------------------------------------
# HARD RULES  (the user's criteria)
# Each entry: (code, regex, action, reason-template). action is "skip" or
# "ask". The reason quotes the posting's wording, which is what the user asked
# for on remote-with-a-catch phrasing.
# ---------------------------------------------------------------------------

import sys as _ks_sys, os as _ks_os
_ks_sys.path.insert(0, _ks_os.path.dirname(_ks_os.path.dirname(_ks_os.path.abspath(__file__))))
from kit_settings import setting as _S  # personal settings live in the settings folder, not the code

HARD_RULES = _S("fit_scoring.HARD_RULES", rx=_rx)

# Excluded industries are a hard no. Checked on title, posting text, and
# company name; always a Poor fit.
EXCLUDED_INDUSTRY_RE = _S("fit_scoring.EXCLUDED_INDUSTRY_RE", rx=_rx)
EXCLUDED_COMPANIES = _S("fit_scoring.EXCLUDED_COMPANIES", rx=_rx)

# Title-level signals, checked on the title alone (the user's skip and ask
# lists in the settings).
TITLE_SKIP = _S("fit_scoring.TITLE_SKIP", rx=_rx)
TITLE_ASK = _S("fit_scoring.TITLE_ASK", rx=_rx)

TRAVEL_RE = re.compile(r"travel[^.%]{0,60}?(\d{1,2})\s*%|(\d{1,2})\s*%[^.%]{0,30}?travel", re.I)
TRAVEL_SKIP_PCT = _S("fit_scoring.TRAVEL_SKIP_PCT")

INDUSTRY_EXCEPTION_RE = _S("fit_scoring.INDUSTRY_EXCEPTION_RE", rx=_rx)
# Hard-rule codes (HARD_RULES) whose match the exception words above turn into
# a "your call" instead of a Poor fit.
INDUSTRY_RULE_CODES = set(_S("fit_scoring.INDUSTRY_RULE_CODES", default=["industry"]))

# v4.1: an equal-opportunity statement lists protected classes ("race, color,
# religion, ... military or veteran status"). A rule word that only appears
# there (military, religion, political, government) says nothing about the
# job, so matches inside such a sentence are ignored. A sentence counts as
# equal-opportunity text when it names at least EEO_MIN_MARKERS of these.
EEO_MARKER_RX = re.compile(
    r"\b(?:race|colou?r|religio\w*|creed|sex|gender identity|gender expression|sexual orientation|"
    r"national origin|ancestry|age|disabilit\w*|veterans?|military (?:service|status)|marital status|"
    r"pregnancy|genetic information|citizenship status|protected (?:class\w*|status|characteristic\w*|by)|"
    r"without regard|equal (?:employment )?opportunit\w*|uniformed services|political (?:affiliation|activities))\b", re.I)
EEO_MIN_MARKERS = 3
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;•])\s+|\n+")


def _eeo_spans(body):
    """(start, end) spans of the sentences in body that are equal-opportunity text."""
    spans, pos = [], 0
    for part in _SENTENCE_SPLIT.split(body or ""):
        start = (body or "").find(part, pos)
        if start < 0:
            continue
        pos = start + len(part)
        if len({m.group(0).lower() for m in EEO_MARKER_RX.finditer(part)}) >= EEO_MIN_MARKERS:
            spans.append((start, pos))
    return spans


def search_outside_eeo(rx, body, spans=None):
    """The first match of rx in body that isn't inside equal-opportunity text, or None."""
    if not rx or not body:
        return None
    spans = _eeo_spans(body) if spans is None else spans
    for m in rx.finditer(body):
        if not any(a <= m.start() < b for a, b in spans):
            return m
    return None


def strip_eeo(text):
    """text with its equal-opportunity sentences removed (for keyword checks)."""
    spans = _eeo_spans(text)
    if not spans:
        return text or ""
    out, last = [], 0
    for a, b in spans:
        out.append(text[last:a]); last = b
    out.append(text[last:])
    return " ".join(out)

PAY_HARD_FLOOR = _S("fit_scoring.PAY_HARD_FLOOR")
PAY_TARGET = _S("fit_scoring.PAY_TARGET")


def _k(n):
    """150000 -> "$150k" for reason text."""
    return f"${n / 1000:g}k"


BENEFITS_RULES = _S("fit_scoring.BENEFITS_RULES", default=True)   # skip companies weak on PTO and health benefits
TITLE_SKIP_LABEL = _S("fit_scoring.TITLE_SKIP_LABEL", default="Title is on your skip list")
EXCLUDED_INDUSTRY_LABEL = _S("fit_scoring.EXCLUDED_INDUSTRY_LABEL", default="Excluded industry")   # the reason shown when a posting hits the excluded-industry rule

# Work arrangement (kit). "remote" keeps the original fully-remote rules
# exactly. "remote_or_hybrid" and "any" accept hybrid or onsite work inside
# the user's commute area, within their office-day limit.
WORK = _S("fit_scoring.WORK_ARRANGEMENT", default={"mode": "remote"})
WORK_MODE = WORK.get("mode", "remote")
COMMUTE_RE = _rx(*WORK.get("commute_areas", [])) if WORK.get("commute_areas") else None
MAX_OFFICE_DAYS = WORK.get("max_office_days")
ONSITE_OK = bool(WORK.get("onsite_ok")) and WORK_MODE == "any"
RELOCATION_OK = bool(WORK.get("relocation_ok"))
DAYS_RE = re.compile(r"\b(\d|one|two|three|four|five)\+?\s*days?\s*(?:a|per|/|each|every)?\s*week", re.I)
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
ONSITE_RE = _rx("fully onsite", "fully on-site", "100% onsite", "100% on-site", "in office five days",
                "in-office five days", "5 days in office", "five days in office", "onsite role", "on-site role",
                "this role is onsite", "this role is on-site", "office-based")
RELOCATION_RE = _rx("relocation required", "must relocate", "willing to relocate", "relocation assistance")


def office_check(body, location="", remote_hint=False):
    """Non-remote modes only. Returns (verdict, reason) or (None, None).
    A posting known to be remote (remote_hint) or saying remote with no
    hybrid or onsite wording passes; otherwise the office location and days
    are checked against the user's commute area and limit."""
    where = f"{location} {body}"
    in_area = bool(COMMUTE_RE and COMMUTE_RE.search(where))
    if (remote_hint or POSTING_REMOTE_RE.search(body)) and not HYBRID_WORDS.search(body) and not ONSITE_RE.search(body):
        return None, None
    if RELOCATION_RE.search(body) and not in_area and not RELOCATION_OK:
        return "skip", "Relocation required and you aren't relocating"
    onsite = ONSITE_RE.search(body)
    if onsite:
        if not ONSITE_OK:
            return "skip", f"Fully onsite and you want remote or hybrid: \"{_snippet(body, onsite, 50)}\""
        if not in_area:
            return "skip", f"Onsite outside your commute area: \"{_snippet(body, onsite, 50)}\""
        return None, None
    hybrid = HYBRID_WORDS.search(body)
    if not hybrid:
        return None, None
    if not in_area:
        if COMMUTE_RE is None:
            return "ask", "Hybrid; add your commute area in setup to judge the office location"
        return "skip", f"Hybrid office outside your commute area: \"{_snippet(body, hybrid, 50)}\""
    d = DAYS_RE.search(body)
    if d and MAX_OFFICE_DAYS is not None:
        n = int(_NUM.get(d.group(1).lower(), d.group(1)))
        if n > MAX_OFFICE_DAYS:
            return "skip", f"{n} office days a week, over your limit of {MAX_OFFICE_DAYS}"
    if not d and MAX_OFFICE_DAYS is not None:
        return "ask", "Hybrid in your area but office days aren't stated; confirm"
    return None, None


HYBRID_WORDS = _rx("hybrid", "in-office", "in office", "office days", "return to office",
                   "~\\b(\\d|one|two|three|four|five)\\+?\\s*days?\\s*(per|a|/|each)\\s*week\\b")


POSTING_REMOTE_RE = _S("fit_scoring.POSTING_REMOTE_RE", rx=_rx)


def hard_screen(title, text, salary_min=None, company=None, remote_hint=False, company_name="",
                eeo_aware=True):
    """Returns (verdict, reasons). verdict is 'skip', 'ask', or None (clean).
    reasons is a list of short strings, each quoting the posting where useful.
    remote_hint: the caller already knows the posting is remote (location
    field or Remote Status), used for the hybrid-company rule."""
    reasons, verdict = [], None
    t = title or ""
    body = text or ""

    def worst(v):
        nonlocal verdict
        if v == "skip" or (v == "ask" and verdict is None):
            verdict = v

    m = TITLE_SKIP.search(t)
    if m:
        worst("skip"); reasons.append(f"{TITLE_SKIP_LABEL}: '{m.group(0)}'")
    m = TITLE_ASK.search(t)
    if m:
        worst("ask"); reasons.append(f"Title needs your call (dev tooling / head-of): '{m.group(0)}'")

    # v4.1: rule words inside equal-opportunity text don't count. eeo_aware=False
    # reproduces the old reading, used once by the agent's repair pass.
    eeo = _eeo_spans(body) if eeo_aware else []
    for code, rx, action, label in HARD_RULES:
        if WORK_MODE != "remote" and code in ("remote-hybrid", "remote-catch"):
            continue   # office rules for hybrid and onsite users run in office_check below
        m = search_outside_eeo(rx, body, eeo)
        if not m:
            continue
        if code in INDUSTRY_RULE_CODES and INDUSTRY_EXCEPTION_RE.search(body):
            worst("ask"); reasons.append(f"Excluded term near one of your exception words: '{m.group(0)}'")
            continue
        if code == "on-call" and re.fullmatch(r"24\s*[/x]\s*7", m.group(0), re.I):
            # "24/7" on its own is usually a benefit ("24/7 GP access", "24/7
            # EAP") or product copy ("customers rely on us 24/7"). Only count
            # it as duty when the sentence puts the user on the hook.
            win = body[max(0, m.start() - 100): m.end() + 100]
            if not re.search(r"\b(on[- ]call|rotation|coverage|shift|respond|escalation|incident|"
                             r"be available|availability|support (team|duty|role)|pager)\b", win, re.I):
                continue
        if code == "remote-hybrid":
            win = body[max(0, m.start() - 120): m.end() + 120]
            # "remote or hybrid" / "fully remote; hybrid optional" lets the
            # candidate choose. Ask instead of skip when remote is offered in
            # the same breath.
            if re.search(r"\b(or|optional|if you prefer|choose|flexib)\w*\b", win, re.I) and re.search(r"remote", win, re.I):
                worst("ask"); reasons.append(f"{label}? wording: \"{_snippet(body, m, 60)}\"")
                continue
            # Boilerplate about OTHER teams ("roles in our GTM team are hired
            # for in-person hybrid") says nothing about this role. Ask.
            if re.search(r"\b(gtm|sales|some roles|certain roles|other roles|roles in our|"
                         r"some teams|certain teams|depending on (the )?(role|team))\b", win, re.I):
                worst("ask"); reasons.append(f"Hybrid mentioned for other teams; confirm this role: \"{_snippet(body, m, 60)}\"")
                continue
        worst(action)
        reasons.append(f"{label}: \"{_snippet(body, m, 60)}\"")

    gm = (EXCLUDED_COMPANIES.search(company_name or "") or EXCLUDED_INDUSTRY_RE.search(t)
          or search_outside_eeo(EXCLUDED_INDUSTRY_RE, body, eeo))
    if gm:
        worst("skip"); reasons.append(f"{EXCLUDED_INDUSTRY_LABEL}: '{gm.group(0)}' (hard no)")

    tm = TRAVEL_RE.search(body)
    if tm:
        pct = int(tm.group(1) or tm.group(2))
        if pct >= TRAVEL_SKIP_PCT:
            worst("skip"); reasons.append(f"Travel {pct}%")
        else:
            worst("ask"); reasons.append(f"Travel {pct}% stated")

    if salary_min is not None and salary_min < PAY_HARD_FLOOR:
        worst("skip"); reasons.append(f"Base ${salary_min:,.0f} under {_k(PAY_HARD_FLOOR)} floor")

    if WORK_MODE != "remote":
        ov, orsn = office_check(body, remote_hint=remote_hint)
        if ov:
            worst(ov); reasons.append(orsn)

    if company:
        posture = (company.get("remote_posture") or "")
        if posture.startswith("Hybrid") and WORK_MODE == "remote":
            # A hybrid-leaning company stays open unless an office mandate
            # is verified from the company's own words (then its
            # Verdict is Do not pursue, handled below). A posting there is
            # Skip unless the posting itself says remote, in which case the user
            # decides. "Says remote" = remote wording in the text or the
            # caller's remote_hint (location / Remote Status), with no
            # hybrid wording tripped above.
            hybrid_in_text = any(r.startswith("Fails fully-remote rule") for r in reasons)
            says_remote = remote_hint or bool(POSTING_REMOTE_RE.search(body))
            if says_remote and not hybrid_in_text:
                worst("ask"); reasons.append("Company rated Hybrid / RTO risk but this posting says remote; confirm office expectations")
            else:
                worst("skip"); reasons.append("Company rated Hybrid / RTO risk in Companies")
        pto, health = company.get("pto") or "", company.get("health") or ""
        if not BENEFITS_RULES:
            pto = health = ""
        if pto == "Weak" and health == "Weak":
            worst("skip"); reasons.append("Weak on both PTO and health benefits")
        elif (pto == "Weak" or health == "Weak") and salary_min is not None and salary_min < PAY_TARGET:
            worst("skip"); reasons.append(f"One Weak benefit and base under {_k(PAY_TARGET)} (two cuts to the same thing)")
        cverdict = company.get("verdict") or ""
        if cverdict == "Do not pursue":
            worst("skip"); reasons.append("Company verdict is Do not pursue")

    # Skip-causing reasons first, so the Label Reason leads with the decider.
    ask_prefixes = ("Title needs your call", "Remote with a catch", "Hybrid mentioned for other teams",
                    "Travel", "Excluded term near", "Fails fully-remote rule?",
                    "Company rated Hybrid / RTO risk but")
    if verdict == "skip":
        reasons.sort(key=lambda r: r.startswith(ask_prefixes) and not r.startswith("Travel ") or
                     (r.startswith("Travel ") and "stated" in r))
    return verdict, reasons


# ---------------------------------------------------------------------------
# WORK-TYPE MATCH  (evidence bank story cards)  0-30
# Each family: (label, card ids, points, regex). Points are awarded once per
# family; the total is capped at 30. The card ids are written to Fit Evidence.
# ---------------------------------------------------------------------------

WORK_FAMILIES = _S("fit_scoring.WORK_FAMILIES", rx=_rx)
WORK_CAP = _S("fit_scoring.WORK_CAP")

# ---------------------------------------------------------------------------
# CONFIRMED GAPS  (skill: "Confirmed gaps, do not re-litigate")  up to -24
# Full penalty when the phrase sits near requirement language; half otherwise.
# ---------------------------------------------------------------------------

GAP_FAMILIES = _S("fit_scoring.GAP_FAMILIES", rx=_rx)
GAP_CAP = _S("fit_scoring.GAP_CAP")


# ---------------------------------------------------------------------------
# COUNTABLE MINIMUMS
# A required qualification the user cannot claim. Counted only when the phrase sits
# near requirement language. One missing caps the score at 69 (Tier B); two or
# more cap it at 49 (Tier C, no spend) and the reason says why, so a high
# company or pay score can no longer carry a posting the user can't meet.
# Added after three postings scored 8+ while missing two required items each.
# ---------------------------------------------------------------------------

YEARS_CLAIMABLE = _S("fit_scoring.YEARS_CLAIMABLE")     # the number of years of experience in the field the user can claim
YEARS_GRACE = _S("fit_scoring.YEARS_GRACE", default=1)   # v3.8: a years minimum this far over what you can claim is met, not a miss
ONE_MISS_STRONG_MIN = _S("fit_scoring.ONE_MISS_STRONG_MIN", default=80)   # v3.8: one miss still reaches Strong fit at this score before the cap
MIN_CAP_ONE = _S("fit_scoring.MIN_CAP_ONE")
MIN_CAP_TWO = _S("fit_scoring.MIN_CAP_TWO")
NO_PAY_CAP = _S("fit_scoring.NO_PAY_CAP")           # Tier C when the user ranks unposted pay lower
PAY_IN_TEXT_RE = re.compile(r"\$\s?\d{2,3}(?:,\d{3}|\.\d+\s?k|\s?k)\b", re.I)

YEARS_PM_RE = re.compile(_S("fit_scoring.YEARS_RE"), re.I)   # "N+ years of <the user's field>" near requirement words
YEARS_LABEL = _S("fit_scoring.YEARS_LABEL", default="years of experience in your field")

MINIMUM_FAMILIES = _S("fit_scoring.MINIMUM_FAMILIES", rx=_rx)

# v3.7: requirements counted only inside a required section (the same words
# in Responsibilities describe the work, not a minimum). Filled from the user's
# confirmed gaps in keyword-groups.json; empty by default.
REQUIRED_BLOCK_FAMILIES = _S("fit_scoring.REQUIRED_BLOCK_FAMILIES", rx=_rx, default=[])

# v3.7: "N years" or "experience in" an industry outside the user's field is a
# miss. The list is the user's (criteria.json); empty turns the rule off.
_OUT_OF_DOMAIN = _S("fit_scoring.OUT_OF_DOMAIN_INDUSTRIES", default=[])
OUT_OF_DOMAIN_INDUSTRY_RX = _rx(*_OUT_OF_DOMAIN) if _OUT_OF_DOMAIN else None
OUT_OF_DOMAIN_LABEL = _S("fit_scoring.OUT_OF_DOMAIN_LABEL", default="industry experience outside your field")
INDUSTRY_LEAD_RE = re.compile(r"\b(?:experience|years?|yrs|background|expertise|track record)\b[^.;:]{0,90}$", re.I)


def industry_minimums(text, req_spans=None):
    out, seen = [], set()
    if OUT_OF_DOMAIN_INDUSTRY_RX is None:
        return out
    for m in OUT_OF_DOMAIN_INDUSTRY_RX.finditer(text):
        lead = text[max(0, m.start() - 100): m.start()]
        if not INDUSTRY_LEAD_RE.search(lead):
            continue
        if not _near_requirement(text, m, req_spans=req_spans):
            continue
        # one miss per requirement sentence, however many industries it names
        sent_key = text.rfind(".", 0, m.start())
        if sent_key in seen:
            continue
        seen.add(sent_key)
        out.append(f"{OUT_OF_DOMAIN_LABEL}: {m.group(0)} ('{_snippet(text, m, 50)}')")
    return out


def years_near_miss(text, req_spans=None):
    """v3.8: a stated years minimum within YEARS_GRACE of what the user can
    claim. Counted as met; returned so the breakdown can say so. None if none."""
    if req_spans is None:
        req_spans = required_spans(text)
    for m in YEARS_PM_RE.finditer(text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if YEARS_CLAIMABLE < n <= YEARS_CLAIMABLE + YEARS_GRACE and _near_requirement(text, m, req_spans=req_spans):
            return f"{n}+ {YEARS_LABEL} asked, {YEARS_CLAIMABLE} claimable: counted as met (within {YEARS_GRACE} year)"
    return None


def missing_minimums(text, req_spans=None):
    """Return a list of required qualifications the user can't claim, each as a
    short label, judged against the posting text near requirement language or
    inside a required section (v3.7)."""
    if req_spans is None:
        req_spans = required_spans(text)
    out = []
    for m in YEARS_PM_RE.finditer(text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n > YEARS_CLAIMABLE + YEARS_GRACE and _near_requirement(text, m, req_spans=req_spans):
            out.append(f"{n}+ {YEARS_LABEL} (claimable: {YEARS_CLAIMABLE})")
            break
    for label, rx in MINIMUM_FAMILIES:
        # any mention counts (v3.7), not just the first
        for m in rx.finditer(text):
            if _near_requirement(text, m, req_spans=req_spans):
                out.append(f"{label} ('{_snippet(text, m, 50)}')")
                break
    for label, rx in REQUIRED_BLOCK_FAMILIES:
        for m in rx.finditer(text):
            if _in_spans(m, req_spans):
                out.append(f"{label} ('{_snippet(text, m, 50)}')")
                break
    out += industry_minimums(text, req_spans)
    return out

# ---------------------------------------------------------------------------
# REQUIRED-ITEM COVERAGE  (v4.0, Nov 7, 2026)
# The hand-written families above catch the gaps someone has already named.
# This pass reads the required block item by item and says which items the
# Evidence Bank can vouch for and which it can't, so a requirement nobody wrote
# a regex for (an ERP, a clinical workflow, an ad platform) still shows up,
# quoted, in the breakdown. Two unvouched items cap the row at Possible fit;
# four, or half the items, cap it at Poor fit. The caps are deliberately
# transparent: the quoted items are what the user glances at to confirm or
# overrule.
# ---------------------------------------------------------------------------

SOFT_ITEM_RX = re.compile(r"\b(?:plus|bonus|nice to have|nice-to-have|ideally|preferred|preferably|"
                          r"not required|optional|helpful|would be great|a bonus)\b", re.I)
YEARS_ITEM_RX = re.compile(r"\b\d{1,2}\s*\+?\s*(?:years|yrs)\b", re.I)
# The phrase a requirement is actually about: what follows "knowledge of",
# "experience with", and the like. Only this phrase (its first words) has to be
# vouched for, so a familiar word later in the sentence can't cover an
# unfamiliar subject ("clinical trial processes, including site onboarding").
REQ_LEAD_RX = re.compile(
    r"\b(?:knowledge of|experience (?:with|in|of|across|building|shipping|leading|managing|owning|working|"
    r"supporting|driving|using|developing|launching|delivering|scaling|designing)|expertise (?:in|with)|"
    r"background (?:in|with)|familiarity with|proficiency (?:in|with)|understanding of|exposure to|"
    r"fluency (?:in|with)|history of|track record (?:of|in))\s+(.{3,160})", re.I)
REQ_HEAD_WORDS_N = 4   # words of the lead phrase that must carry the vouch
REQ_LEAD_MAX_START = 40  # the lead must open the item; a later "experience using" is not its subject

# What the bank can vouch for. Three word lists, all the user's:
#   VOUCH_WORDS        the stories, tools, and domain terms in the Evidence Bank
#                      (keyword-groups.json; when it isn't set, every phrase in
#                      WORK_FAMILIES, plus the titles and domain keywords from
#                      setup, stands in for it)
#   VOUCH_FIELD_WORDS  the everyday nouns of the user's field ("accounts",
#                      "renewals" for customer success; "campaign" for a
#                      marketer), which vouch for a lead phrase but never
#                      count on their own anywhere else in the item
#   VOUCH_GENERIC      the soft-skill and logistics asks every posting makes;
#                      the default below is field-neutral
# "data", "process", "systems", "controls", and "platform" on their own vouch
# for nothing: they are the words a foreign requirement is dressed in.
def _phrases(key, default=None):
    """The plain phrases behind a $rx setting (the regex builder is bypassed)."""
    try:
        v = _S(key, rx=lambda *ph: list(ph), default=default)
    except KeyError:
        return []
    out = []
    for item in v or []:
        if isinstance(item, (list, tuple)):
            for x in item:
                if isinstance(x, list):
                    out += [str(p) for p in x]
        elif isinstance(item, str):
            out.append(item)
    return out


_VOUCH_WORDS = _S("fit_scoring.VOUCH_WORDS", default=None)
if not _VOUCH_WORDS:
    _VOUCH_WORDS = (_phrases("fit_scoring.WORK_FAMILIES") + _phrases("fit_scoring.DOMAIN_KEYWORDS")
                    + list(_S("agent.TITLE_KEYWORDS", default=[]) or []))
_VOUCH_FIELD = _S("fit_scoring.VOUCH_FIELD_WORDS", default=[]) or []
VOUCH_GENERIC_WORDS = _S("fit_scoring.VOUCH_GENERIC", default=[
    "communicat", "collaborat", "written", "verbal", "presentation", "present", "storytell", "judgment",
    "decision", "decisions", "problem solving", "problem-solving", "analytical", "customer-centric",
    "customer-focused", "customer obsessed", "customer-obsessed", "user-centric", "empathy", "curious",
    "curiosity", "humility", "learn", "fast-paced", "fast paced", "self-starter", "self starter", "ownership",
    "owner", "own", "bias for action", "autonomy", "independently", "independent", "team player", "mentor",
    "coach", "remote", "async", "distributed", "degree", "bachelor", "english", "time zone", "travel",
    "authorized", "authorization to work", "years", "experience", "track record", "outcomes", "results",
    "execution", "iterate", "iteration", "incremental", "mvp", "hypothes", "validate", "technical",
    "systems thinking", "system thinking", "software", "web", "detail", "organized", "organised", "proactive",
    "comfortable", "thrive", "passion", "passionate", "excited", "excitement", "enthusiasm", "drive", "driven",
    "point of view", "opinion", "opinions", "trade-off", "tradeoff", "prioritize", "hands-on"])
VOUCH_STRONG_RX = _rx(*_VOUCH_WORDS) if _VOUCH_WORDS else None
VOUCH_SPECIFIC_RX = _rx(*(_VOUCH_WORDS + list(_VOUCH_FIELD))) if (_VOUCH_WORDS or _VOUCH_FIELD) else None
VOUCH_GENERIC_RX = _rx(*VOUCH_GENERIC_WORDS) if VOUCH_GENERIC_WORDS else None
REQUIRED_COVERAGE = _S("fit_scoring.REQUIRED_COVERAGE", default=True)   # the v4.0 item-by-item pass; off = no coverage caps

COVERAGE_MIN_WORDS = 6
# v4.1: posting boilerplate that can sit inside or after the required block.
# None of it is a requirement, so it never counts as an unvouched item.
BOILERPLATE_ITEM_RX = re.compile(
    r"\b(?:job description is not (?:designed|intended)|not (?:designed|intended) to (?:cover|be) (?:or contain )?a comprehensive|"
    r"duties,? responsibilities,? and activities may change|hiring scams?|recruiting scams?|recruitment scams?|"
    r"beware of scams|equal (?:employment )?opportunit\w*|without regard to|protected by (?:applicable )?law|"
    r"reasonable accommodations?|request (?:a|an) accommodation|individuals? with (?:a )?disabilit\w*|"
    r"applicable (?:federal|state|local) laws?|pay transparency|salary range|base salary range|"
    r"compensation (?:range|practices)|incentive plans?|e-verify|candidate privacy|privacy notice|"
    r"opens in a new tab|"
    r"vacation|paid (?:holidays?|sick leave|time off|parental leave)|sick leave|accrual|accrued|prorated|"
    r"401\(?k\)?|health(?:care)? (?:insurance|benefits)|benefits? (?:package|eligib\w*|include)|"
    r"eligib\w+ for (?:equity|benefits|vacation)|peer equity|internal equity|cost of labor|placed into the range|"
    r"repeating motions|stationary position|lift up to|dedicated,? (?:and )?secure work (?:area|space)|"
    r"interviews will be conducted|date of posting|application window|"
    r"applications? (?:are|will be) (?:assessed|reviewed|accepted)|apply (?:today|now|via)|"
    r"if you think you(?:'|’)re the right fit|applying for jobs can feel|how your data is processed|"
    r"careers (?:page|site)|we are proud to be|great place to work|best places to work|best workplaces|"
    r"equal opportunities|expect this position to be filled)\b", re.I)
COVERAGE_CAP_TWO = 2       # unvouched items that cap at MIN_CAP_ONE (Possible fit)
COVERAGE_CAP_FOUR = 4      # unvouched items that cap at MIN_CAP_TWO (Poor fit)
COVERAGE_CAP_SHARE = 0.5   # or this share of the substantive items, with at least 3 items


def required_items(text, req_spans=None):
    """The substantive items of the required block(s): bullets when the text
    keeps " • " boundaries (v4.0 cleaning), sentences otherwise. Headings,
    prices, and very short fragments are dropped."""
    if req_spans is None:
        req_spans = required_spans(text)
    out = []
    for a, b in req_spans:
        block = text[a:b]
        parts = [p.strip(" -*") for p in block.split("•")]
        if len(parts) <= 2:
            parts = [p.strip(" -*") for p in re.split(r"(?<=[.;])\s+(?=[A-Z])", block)]
        for p in parts:
            words = p.split()
            if len(words) < COVERAGE_MIN_WORDS or p.startswith("#") or "$" in p:
                continue
            if BOILERPLATE_ITEM_RX.search(p):
                continue   # disclaimer, benefits, process, or values line (v4.1)
            if sum(c.isupper() for c in p) > len(p) * 0.5:
                continue   # an all-caps heading
            if REQ_HEAD_RE.match(p):
                p = REQ_HEAD_RE.sub("", p, count=1).strip(" :")
                if len(p.split()) < COVERAGE_MIN_WORDS:
                    continue
            out.append(p)
    return out


def req_lead_phrase(item):
    """The first REQ_HEAD_WORDS_N words of what the item is about, or None when
    the item has no "knowledge of / experience with" lead."""
    m = REQ_LEAD_RX.search(item)
    if not m or m.start() > REQ_LEAD_MAX_START:
        return None
    return " ".join(re.split(r"\s+", m.group(1).strip())[:REQ_HEAD_WORDS_N])


def classify_required_item(item):
    """'miss' (a stated minimum or confirmed gap), 'years', 'soft', 'vouched',
    or 'unvouched'. The lead phrase, when there is one, is what must be vouched."""
    if SOFT_ITEM_RX.search(item):
        return "soft"
    for _label, rx in MINIMUM_FAMILIES + REQUIRED_BLOCK_FAMILIES:
        if rx.search(item):
            return "miss"
    for _label, _pts, rx in GAP_FAMILIES:
        if rx.search(item):
            return "miss"
    if OUT_OF_DOMAIN_INDUSTRY_RX is not None and OUT_OF_DOMAIN_INDUSTRY_RX.search(item):
        return "miss"
    if YEARS_ITEM_RX.search(item):
        return "years"
    lead = req_lead_phrase(item)
    if lead is not None:
        if _hit(VOUCH_SPECIFIC_RX, lead) or _hit(VOUCH_STRONG_RX, item):
            return "vouched"
        return "unvouched"
    if _hit(VOUCH_SPECIFIC_RX, item) or _hit(VOUCH_GENERIC_RX, item):
        return "vouched"
    return "unvouched"


def _hit(rx, text):
    return bool(rx is not None and rx.search(text))


def required_coverage(text, req_spans=None):
    """Classify every required item. Returns a dict with counts, the unvouched
    items (trimmed), and the cap to apply: None, MIN_CAP_ONE, or MIN_CAP_TWO."""
    if not REQUIRED_COVERAGE or VOUCH_SPECIFIC_RX is None:
        return {"items": 0, "vouched": 0, "unvouched": [], "miss": 0, "soft": 0, "cap": None}
    items = required_items(text, req_spans)
    classes = [classify_required_item(i) for i in items]
    unvouched = [i for i, c in zip(items, classes) if c == "unvouched"]
    substantive = [i for i, c in zip(items, classes) if c in ("vouched", "unvouched", "miss")]
    cap = None
    n = len(unvouched)
    if n >= COVERAGE_CAP_FOUR or (len(substantive) >= 3 and n >= 2 and n / len(substantive) >= COVERAGE_CAP_SHARE):
        cap = MIN_CAP_TWO
    elif n >= COVERAGE_CAP_TWO:
        cap = MIN_CAP_ONE
    return {"items": len(items), "vouched": classes.count("vouched"), "unvouched": unvouched,
            "miss": classes.count("miss"), "soft": classes.count("soft"), "cap": cap}


def coverage_note(cov):
    if not cov["unvouched"]:
        return ""
    quoted = "; ".join("'" + u[:90].rstrip(" .") + ("...'" if len(u) > 90 else "'") for u in cov["unvouched"][:4])
    head = f"Required items your Evidence Bank can't vouch for ({len(cov['unvouched'])} of {cov['items']})"
    if cov["cap"] == MIN_CAP_TWO:
        head += f", capped at {MIN_CAP_TWO} (Poor fit)"
    elif cov["cap"] == MIN_CAP_ONE:
        head += f", capped at {MIN_CAP_ONE} (Possible fit)"
    return head + ": " + quoted + "."

# ---------------------------------------------------------------------------
# DOMAIN  0-20   (the fields that interest the user most)
# ---------------------------------------------------------------------------

DOMAIN_SCORES = _S("fit_scoring.DOMAIN_SCORES")
DOMAIN_UNKNOWN = _S("fit_scoring.DOMAIN_UNKNOWN")

DOMAIN_KEYWORDS = _S("fit_scoring.DOMAIN_KEYWORDS", rx=_rx)

# Settled Tier precedents, company name -> tier (the wizard's top and good
# companies).
TIER_PRECEDENTS = _S("fit_scoring.TIER_PRECEDENTS")
# Confidentiality tiers by Domain tag (optional, see SETTINGS.md): companies
# tagged with a SAME_DOMAINS label get Tier 1, ADJACENT_DOMAINS Tier 2.
# DRAG_DOMAINS tags pull a mixed company's domain points down.
SAME_DOMAINS = set(_S("fit_scoring.SAME_DOMAINS", default=[]))
ADJACENT_DOMAINS = set(_S("fit_scoring.ADJACENT_DOMAINS", default=[]))
DRAG_DOMAINS = set(_S("fit_scoring.DRAG_DOMAINS", default=[]))


def domain_score(title, text, company_domains=None):
    """Returns (points, domain label used)."""
    return _domain_score_base(title, text, company_domains)


DOMAIN_NONE_LABEL = "domain unknown (no Domain set on the Companies row)"
# v3.7: with DOMAIN_GUESS off, no Domain on the Companies row means 0 domain
# points, never a keyword guess (benefits text like "401(k)" was scoring
# developer-tooling companies 20/20 as a finance domain). The kit keeps the
# guess on by default, since a new user's Companies rows start without fields.
DOMAIN_GUESS = _S("fit_scoring.DOMAIN_GUESS", default=True)


def _domain_score_base(title, text, company_domains=None):
    if not company_domains:
        if not DOMAIN_GUESS:
            return 0, DOMAIN_NONE_LABEL
        pts, label = _domain_keyword_guess(title, text)
        if pts is None:
            return DOMAIN_UNKNOWN, "unknown"
        return pts, label
    if company_domains:
        scored = [(DOMAIN_SCORES.get(d, DOMAIN_UNKNOWN), d) for d in company_domains]
        # A drag domain tag (settings DRAG_DOMAINS) pulls a mixed company
        # down; otherwise take the best tag.
        if any(d in DRAG_DOMAINS for d in company_domains) and len(company_domains) > 1:
            best = max(scored)
            return max(0, best[0] - 6), f"{best[1]} (with {', '.join(d for d in company_domains if d != best[1])})"
        return max(scored)


def _domain_keyword_guess(title, text):
    """Best keyword guess at a domain. Used only for the confidentiality tier
    of a company with no Domain set, never for points (v3.7)."""
    blob = f"{title} {text}"
    best = (None, None)
    for label, rx in DOMAIN_KEYWORDS:
        if rx.search(blob):
            pts = DOMAIN_SCORES[label]
            if best[0] is None or pts > best[0]:
                best = (pts, label)
    return best


def domain_tier(company_name, company_domains=None, title="", text=""):
    """Confidentiality tier for tailoring (Tier 1 tightest)."""
    name = (company_name or "").strip().lower()
    for tier, names in TIER_PRECEDENTS.items():
        if any(name.startswith(n) for n in names):
            return f"Tier {tier} - " + ("same domain" if tier == 1 else "adjacent regulated")
    doms = set(company_domains or [])
    if doms & SAME_DOMAINS:
        return "Tier 1 - same domain"
    if doms & ADJACENT_DOMAINS:
        return "Tier 2 - adjacent regulated"
    if not doms:
        # v3.7: no Domain set is never a Tier 1 default. A keyword hint of a
        # same or adjacent domain keeps the tighter Tier 2 handling.
        pts, label = _domain_keyword_guess(title, text)
        if label in SAME_DOMAINS or label in ADJACENT_DOMAINS:
            return "Tier 2 - adjacent regulated"
    return "Tier 3 - outside domain"


# ---------------------------------------------------------------------------
# LEVEL  0-15
# ---------------------------------------------------------------------------

LEVEL_RULES = _S("fit_scoring.LEVEL_RULES", rx=_rx)


def level_score(title):
    t = re.sub(r"\bsr\.?(?=\s)", "senior", title or "", flags=re.I)
    for pts, rx in LEVEL_RULES:
        if rx.search(t):
            return pts
    return 4


# ---------------------------------------------------------------------------
# PAY  0-15
# ---------------------------------------------------------------------------

def pay_score(salary_min):
    if salary_min is None:
        return 6, "no salary range posted (research; counts against transparency)"
    if salary_min >= PAY_TARGET:
        return 15, f"${salary_min:,.0f} base at or above {_k(PAY_TARGET)}"
    if salary_min >= PAY_HARD_FLOOR:
        return 8, f"${salary_min:,.0f} base in the {_k(PAY_HARD_FLOOR)}-{_k(PAY_TARGET)[1:]} band (everything else must be near perfect)"
    return 0, f"${salary_min:,.0f} under floor"


# ---------------------------------------------------------------------------
# COMPANY  0-20  (from the Companies row when the posting is linked to one)
# ---------------------------------------------------------------------------

# v3.2: an unresearched company no longer gets the
# benefit of the doubt (was 10 of 20, now 5), so researched companies outrank
# unknowns. The daily research step researches any such company whose row
# still scores 65+, and the agent rescores those rows every run until it has.
UNRESEARCHED_COMPANY_PTS = _S("fit_scoring.UNRESEARCHED_COMPANY_PTS")
UNRESEARCHED_NOTE = "no company research yet"


POSTURE_POINTS = _S("fit_scoring.POSTURE_POINTS", default={"Structurally remote (no HQ)": 9, "Remote-first with offices": 6, "Unknown": 4})


def company_score(company):
    if not company:
        return UNRESEARCHED_COMPANY_PTS, UNRESEARCHED_NOTE
    pts, notes = 0, []
    posture = company.get("remote_posture") or "Unknown"
    pts += POSTURE_POINTS.get(posture, 0)
    notes.append(posture)
    risk = company.get("risk") or "Not researched"
    pts += {"Low": 6, "Some concerns": 3, "Not researched": 3, "High": 0}.get(risk, 3)
    notes.append(f"risk {risk}")
    pto, health = company.get("pto") or "Unknown", company.get("health") or "Unknown"
    weak = (pto == "Weak") + (health == "Weak")
    pts += {0: 5, 1: 2, 2: 0}[weak]
    notes.append(f"PTO {pto}, health {health}")
    return pts, "; ".join(notes)


# ---------------------------------------------------------------------------
# POSTED-DATE HELPERS  (used by the agent's backfill)
# ---------------------------------------------------------------------------

_WORKDAY_POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago|30\+\s+days\s+ago)", re.I)


def workday_posted_to_date(posted_text, today=None):
    """'Posted 3 Days Ago' -> (ISO date, approximate flag). '30+ Days Ago' is a
    ceiling, so it returns today-30 with approximate=True."""
    today = today or date.today()
    m = _WORKDAY_POSTED.search(posted_text or "")
    if not m:
        return None, False
    s = m.group(1).lower()
    if s == "today":
        return today.isoformat(), False
    if s == "yesterday":
        return (today - timedelta(days=1)).isoformat(), False
    if s.startswith("30+"):
        return (today - timedelta(days=30)).isoformat(), True
    n = int(m.group(2))
    return (today - timedelta(days=n)).isoformat(), False


# ---------------------------------------------------------------------------
# SCORE
# ---------------------------------------------------------------------------

# v3.0 (rank fresher good fits higher). Posting age from the row's Posted
# Date nudges the score so the tracker's sort puts new postings first among
# similar fits. Unknown age is neutral.
FRESHNESS_BANDS = _S("fit_scoring.FRESHNESS_BANDS")


def freshness_points(age_days):
    if age_days is None or age_days < 0:
        return 0, ""
    for limit, pts, note in FRESHNESS_BANDS:
        if limit is None or age_days <= limit:
            return pts, (f"{note}, {age_days} days" if note else "")
    return 0, ""


# v3.7: a listing that names no benefits and posts one flat salary figure
# reads like a staffing agency's repost. Capped at Possible fit.
BENEFITS_NAMED_RX = _rx("benefits", "benefit", "health insurance", "medical", "dental", "vision",
                        "401(k)", "401k", "retirement plan", "pto", "paid time off", "vacation",
                        "parental leave", "equity", "stock options", "wellness", "insurance coverage")
PAY_RANGE_RE = re.compile(r"\$\s?\d[\d,.]*\s?k?\s*(?:-|–|—|to)\s*(?:\$|usd)?\s?\d[\d,.]*", re.I)
STAFFING_CAP = MIN_CAP_ONE
STAFFING_MIN_UNCUT = 8500   # job_search_agent.SNAPSHOT_MAX is 9000


def staffing_signal(text, salary_text=""):
    """True when no benefits are named and pay is one flat figure."""
    pay_blob = f"{salary_text or ''} {text or ''}"
    # A snapshot cut near its 9,000-character limit may have lost the
    # benefits section, so absence proves nothing there.
    if len(text or "") >= STAFFING_MIN_UNCUT:
        return False
    if BENEFITS_NAMED_RX.search(text or ""):
        return False
    if not PAY_IN_TEXT_RE.search(pay_blob) or PAY_RANGE_RE.search(pay_blob):
        return False
    return True


def score_posting(title, text, salary_min=None, company=None, company_name="",
                  evergreen=False, today=None, remote_hint=False, age_days=None,
                  salary_text=""):
    """Full v2 evaluation.

    company: optional dict from the Companies row with keys remote_posture,
    risk, pto, health, verdict, domains (list).
    remote_hint: the posting is known remote from its location field or the
    row's Remote Status (see hard_screen).
    Returns a dict:
      score (0-100), fit_10 (0-10, one decimal), tier ('A'|'B'|'C'),
      verdict ('Strong fit'|'Possible fit'|'Poor fit', never None), hard_skip (bool),
      skip_why (str or None), reasons (list), breakdown (str),
      evidence (str), domain_tier (str), schedule (str or None)
    """
    text = _clean(text)
    blob = f"{title} {text}"
    company = company or {}
    req_spans = required_spans(text)

    hv, reasons = hard_screen(title, text, salary_min, company, remote_hint=remote_hint,
                              company_name=company_name)

    # Work-type match
    work_pts, matched = 0, []
    for label, cards, pts, rx in WORK_FAMILIES:
        if rx.search(blob):
            work_pts += pts
            matched.append((label, cards))
    work_pts = min(work_pts, WORK_CAP)

    # Confirmed-gap penalties
    gap_pts, gaps = 0, []
    for label, pts, rx in GAP_FAMILIES:
        hits = list(rx.finditer(text))
        if hits:
            # Every mention counts, not just the first: one growth posting
            # names activation in Responsibilities first and again under
            # Minimum Requirements (v2.9).
            full = any(_near_requirement(text, h, req_spans=req_spans) for h in hits)
            p = pts if full else max(1, pts // 2)
            gap_pts += p
            gaps.append(f"{label} (-{p}{'' if full else ', not stated as required'})")
    gap_pts = min(gap_pts, GAP_CAP)

    dom_pts, dom_label = domain_score(title, text, company.get("domains"))
    lvl_pts = level_score(title)
    pay_pts, pay_note = pay_score(salary_min)
    co_pts, co_note = company_score(company)
    evergreen_pen = 5 if evergreen else 0

    score = work_pts - gap_pts + dom_pts + lvl_pts + pay_pts + co_pts - evergreen_pen
    fresh_pts, fresh_note = freshness_points(age_days)
    score = max(0, min(100, score + fresh_pts))
    score_uncapped = score   # v4.0: kept for ranking capped rows and near-miss alerts

    # Countable minimums: required items the user can't claim (confirmed gaps stated
    # as required count too). One caps at Tier B, two or more at Tier C.
    missing = missing_minimums(text, req_spans)
    missing += [g.split(" (-")[0] for g in gaps if "not stated as required" not in g]
    min_note = ""
    near = years_near_miss(text, req_spans)
    if near:
        min_note = near[0].upper() + near[1:] + "."
    one_miss_strong = False
    if len(missing) >= 2:
        score = min(score, MIN_CAP_TWO)
        min_note = (min_note + " " if min_note else "") + f"Missing {len(missing)} countable minimums, capped at {MIN_CAP_TWO} (recommend against): " + "; ".join(missing) + "."
    elif len(missing) == 1 and score >= ONE_MISS_STRONG_MIN:
        one_miss_strong = True
        min_note = (min_note + " " if min_note else "") + (
            f"Missing 1 countable minimum, not capped (score {ONE_MISS_STRONG_MIN}+ before the cap): {missing[0]}.")
    elif len(missing) == 1:
        score = min(score, MIN_CAP_ONE)
        min_note = (min_note + " " if min_note else "") + f"Missing 1 countable minimum, capped at {MIN_CAP_ONE}: {missing[0]}."

    caps_hit = []
    # v4.0: required items the bank can't vouch for (see required_coverage)
    cov = required_coverage(text, req_spans)
    if cov["cap"] is not None:
        score = min(score, cov["cap"])
        caps_hit.append(f"{len(cov['unvouched'])} required item(s) the bank can't vouch for")
    if cov["unvouched"]:
        min_note = (min_note + " " if min_note else "") + coverage_note(cov)
    if staffing_signal(text, salary_text):
        score = min(score, STAFFING_CAP)
        caps_hit.append("staffing-agency signal")
        min_note = (min_note + " " if min_note else "") + (
            f"No benefits named and one flat salary figure (staffing-agency signal), capped at {STAFFING_CAP}.")

    # v2.7: no posted base pay drops a posting to the
    # lowest tier. The salary extractor is a heuristic, so a dollar amount
    # anywhere in the text counts as posted and the cap is skipped.
    pay_posted = salary_min is not None or bool(PAY_IN_TEXT_RE.search(text))
    if not pay_posted:
        score = min(score, NO_PAY_CAP)
        min_note = (min_note + " " if min_note else "") + f"No base pay posted, capped at {NO_PAY_CAP} (Tier C)."

    # v3.3: every row gets a verdict. Tier still sets
    # research spend; the verdict says what to do with the row.
    hard_skip = hv == "skip"
    skip_why = None
    if hard_skip:
        tier, verdict = "C", "Poor fit"
    else:
        tier = "A" if score >= 70 else ("B" if score >= 50 else "C")
        if len(missing) >= 2:
            verdict, skip_why = "Poor fit", f"missing {len(missing)} required"
        elif cov["cap"] == MIN_CAP_TWO:
            verdict, skip_why = "Poor fit", f"{len(cov['unvouched'])} required items outside your evidence"
        elif not pay_posted:
            verdict, skip_why = "Poor fit", "no base pay posted"
        elif score < 50:
            verdict, skip_why = "Poor fit", "weak fit"
        elif tier == "A" and hv != "ask":
            verdict = "Strong fit"
        else:
            verdict = "Possible fit"

    schedule = None
    if any(r.startswith("On-call") for r in reasons):
        schedule = "Heavy / on-call"
    elif re.search(r"work-life balance|work life balance|flexible (hours|schedule)|no on-call|async", text, re.I):
        schedule = "Steady"

    breakdown = (f"{RUBRIC_VERSION} score {score}/100 = work {work_pts}/30 "
                 f"- gaps {gap_pts} + domain {dom_pts}/20 ({dom_label}) + level {lvl_pts}/15 "
                 f"+ pay {pay_pts}/15 ({pay_note}) + company {co_pts}/20 ({co_note})"
                 + (f" - evergreen {evergreen_pen}" if evergreen_pen else "")
                 + (f" {'+' if fresh_pts > 0 else '-'} freshness {abs(fresh_pts)} ({fresh_note})" if fresh_pts else "")
                 + (f" (uncapped {score_uncapped})" if score_uncapped != score else "")
                 + f". Tier {tier}.")
    if min_note:
        breakdown += " " + min_note
    if gaps:
        breakdown += " Gaps: " + "; ".join(gaps) + "."
    if reasons:
        breakdown += " Screen: " + " | ".join(reasons)

    evidence = "; ".join(f"{label} [{cards}]" for label, cards in matched) or "No Evidence Bank family matched; read the posting."

    return {
        "score": score, "fit_10": round(score / 10, 1), "tier": tier, "verdict": verdict,
        "hard_skip": hard_skip, "skip_why": skip_why,
        "ask": hv == "ask",
        "reasons": reasons, "breakdown": breakdown[:1900], "evidence": evidence[:1900],
        "domain_tier": domain_tier(company_name, company.get("domains"), title, text),
        "schedule": schedule, "missing_minimums": missing, "caps": caps_hit,
        "score_uncapped": score_uncapped, "unvouched": cov["unvouched"],
        "one_miss_strong": one_miss_strong and verdict == "Strong fit",
        "parts": {"work": work_pts, "gaps": gap_pts, "domain": dom_pts, "level": lvl_pts,
                  "pay": pay_pts, "company": co_pts},
    }


def label_reason(result, today=None):
    """One-to-three sentence Label Reason for Notion, ending with the stamp the
    weekly triage uses so the two agree."""
    today = today or date.today()
    stamp = f" Scored {today.isoformat()} by agent {RUBRIC_VERSION}."
    verdict = result["verdict"]
    if verdict == "Poor fit" and result.get("hard_skip", True):
        return ("Poor fit: " + "; ".join(result["reasons"]))[:1800] + stamp
    missing = result.get("missing_minimums") or []
    miss_note = (f" Missing {len(missing)} required: " + "; ".join(m.split(" ('")[0] for m in missing) + ".") if missing else ""
    ask_note = (" Needs your call: " + "; ".join(result["reasons"]) + ".") if result.get("ask") else ""
    head = f"Tier {result['tier']}, {result['score']}/100."
    if verdict == "Poor fit":
        lead = f"Poor fit ({result.get('skip_why') or 'low fit'}), left open. "
    elif verdict == "Strong fit" and missing:
        lead = f"Strong fit with one gap to address: {missing[0].split(' (')[0]}. "
    elif verdict == "Strong fit":
        lead = "Strong fit: meets every stated requirement. "
    else:
        why = []
        if missing:
            why.append(f"missing {len(missing)} required")
        if result.get("ask"):
            why.append("a judgment call")
        why += result.get("caps") or []
        if not why:
            why.append("moderate fit")
        uncapped = result.get("score_uncapped", result["score"])
        if uncapped >= ONE_MISS_STRONG_MIN and len(missing) <= 1 and len(result.get("unvouched") or []) <= 2:
            # v4.0: a Strong-fit score held back by one gap reads as a near miss, so it isn't lost among 60 Possible fits
            lead = f"Possible fit, near miss ({uncapped}/100 before the cap; " + ", ".join(why) + "). "
        else:
            lead = "Possible fit (" + ", ".join(why) + "). "
    return (lead + head + miss_note + ask_note + " " + result["evidence"])[:1800] + stamp


TIER_NAMES = {"A": "A - full info every run", "B": "B - light refresh", "C": "C - no spend"}
