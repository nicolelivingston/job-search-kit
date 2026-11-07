"""Turns a user's plain setup answers into their settings files, and reads
the settings back into answers so the wizard can show and edit them.

The wizard only ever writes the keys it owns (see SETTINGS.md, "Setup
questions"); every other key in the settings files is kept as it was.

    answers = read_answers(settings_dir)
    answers["pay"]["floor"] = 130000
    write_answers(settings_dir, answers)
"""
import copy
import json
import re
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
TEMPLATE = KIT / "templates" / "settings"
FILES = ("criteria.json", "companies.json", "resume.json", "app.json", "paths.json", "preferences.json")

# "How Claude works for you" (setup step 8). The Claude plugin reads preferences.json;
# two answers also reach the gate: the em dash habit (presend_gate.FLAG_EM_DASH) and a
# fixed page count (presend_gate.PAGE_LIMIT). See SETTINGS.md.
PREF_CHOICES = {"resume_pages": ("auto", "one", "two"), "bullet_length": ("short", "medium", "detailed"),
                "feedback": ("blunt", "balanced", "gentle"), "drafts": ("one", "options"),
                "decisions": ("list", "conversation"), "obvious_calls": ("decide_and_tell", "ask_first"),
                "file_format": ("word",)}   # PDF may come back in a later version
TONES = ("", "plain", "warm", "formal", "match")
HABITS = ("em_dash", "not_x_its_y", "lists_of_three", "buzzwords", "hope_this_finds_you", "repeat_ending",
          "gushing", "resume_cliches", "heavy_bold", "emojis", "rhetorical_questions", "stacked_hedges")
PERMISSIONS = ("update_tracker", "draft_messages", "draft_form_answers", "save_fixes")
LEVELS = ("can", "ask", "never")
PAGES = {"one": 1, "two": 2}
POSTURE = {"remote": {"Structurally remote (no HQ)": 9, "Remote-first with offices": 6, "Unknown": 4},
           "other": {"Structurally remote (no HQ)": 7, "Remote-first with offices": 7, "Hybrid / RTO risk": 6, "Unknown": 4}}
INTEREST = {"high": 20, "medium": 12, "low": 4, "no": 0}
NO_CAP = 100
FEEDS = {
    "product": "https://weworkremotely.com/categories/remote-product-jobs.rss",
    "customer support": "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
    "data": "https://weworkremotely.com/categories/remote-data-jobs.rss",
    "design": "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "marketing": "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
    "programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "management and finance": "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
}


def _rx(phrases):
    return {"$rx": [p for p in phrases if p] or ["~^$"]}


def _rx_list(v):
    if isinstance(v, dict) and "$rx" in v:
        return [p for p in v["$rx"] if p != "~^$"]
    return []


def _alt_re(words):
    words = [w for w in words if w]
    if not words:
        return {"$re": "^$", "flags": ["I"]}
    return {"$re": r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", "flags": ["I"]}


def _alt_words(v):
    m = re.match(r"^\\b\((.*)\)\\b$", (v or {}).get("$re", ""))
    return [re.sub(r"\\(.)", r"\1", w) for w in m.group(1).split("|")] if m else []


def _load(d):
    d = Path(d)
    out = {}
    for f in FILES:
        p = d / f if (d / f).exists() else TEMPLATE / f
        out[f] = json.loads(p.read_text(encoding="utf-8"))
    return out


def read_answers(settings_dir):
    s = _load(settings_dir)
    c, co, r, app = s["criteria.json"], s["companies.json"], s["resume.json"], s["app.json"]
    ag, fs, g, b = c["agent"], c["fit_scoring"], r["presend_gate"], r["build_resume"]
    rules = [h["$tuple"][0] for h in fs["HARD_RULES"]]
    work = fs.get("WORK_ARRANGEMENT", {"mode": "remote"})
    levels = {pts: _rx_list(rx) for pts, rx in (x["$tuple"] for x in fs["LEVEL_RULES"])}
    domains = []
    kw = {name: _rx_list(rx) for name, rx in (x["$tuple"] for x in fs["DOMAIN_KEYWORDS"])}
    for name, pts in fs["DOMAIN_SCORES"].items():
        interest = min(INTEREST, key=lambda k: abs(INTEREST[k] - pts))
        domains.append({"name": name, "interest": interest, "keywords": kw.get(name, []), "points": pts, "was": interest})
    feed = next((k for k, v in FEEDS.items() if c["board_feeds"]["WWR_FEEDS"][:1] == [v]), "product")
    years_m = re.search(r"\(\?:((?:[^()]|\([^)]*\))*)\)\)?$", fs.get("YEARS_RE", ""))
    return {
        "work": {
            "titles": ag["TITLE_KEYWORDS"],
            "field": ag.get("ROLE_FAMILY_LABEL", "").strip(),
            "never_titles": ag["ROLE_REJECT_KEYWORDS"],
            "skip_title_words": _rx_list(fs["TITLE_SKIP"]),
            "ask_title_words": _rx_list(fs["TITLE_ASK"]),
            "level_at": levels.get(15, []), "level_below": next((v for k, v in levels.items() if k not in (15, 0)), []),
            "level_junior": levels.get(0, []),
            "years": fs.get("YEARS_CLAIMABLE", 0),
            "years_words": [re.sub(r"\\(.)", r"\1", w.replace(r"\b", "")) for w in (years_m.group(1).split("|") if years_m else [])],
        },
        "where": {
            "mode": work.get("mode", "remote"), "home": work.get("home", ""),
            "commute_areas": work.get("commute_areas", []), "max_office_days": work.get("max_office_days"),
            "onsite_ok": bool(work.get("onsite_ok")), "relocation_ok": bool(work.get("relocation_ok")),
        },
        "rules": {
            "direct_reports_ok": "people-manager" not in rules,
            "on_call_ok": "on-call" not in rules, "contract_ok": "contract" not in rules,
            "travel_max_pct": fs["TRAVEL_SKIP_PCT"],
            "excluded_industries": ag["EXCLUDE_KEYWORDS"], "excluded_companies": _rx_list(fs["EXCLUDED_COMPANIES"]),
            "exception_words": ag["INDUSTRY_EXCEPTION_KEYWORDS"], "benefits_rule": bool(fs.get("BENEFITS_RULES", True)),
        },
        "pay": {"floor": fs["PAY_HARD_FLOOR"], "target": fs["PAY_TARGET"], "rank_no_pay_lower": fs["NO_PAY_CAP"] < NO_CAP},
        "fields": {"domains": domains, "current_field": next(iter(fs.get("SAME_DOMAINS") or []), ""), "feed": feed,
                   "boards": co["ats_tools"]["CONFIRMED_COMPANIES"], "custom_sites": co["ats_tools"]["CUSTOM_SITE_COMPANIES"]},
        "resume": {"font": b["FONT"], "body_pt": b["BODY_PT"], "name_pt": b["NAME_PT"], "heading_pt": b["HEADING_PT"],
                   "margin_in": b["MARGIN_IN"], "line_spacing": b["LINE_SPACING"],
                   "avoid_words": g["VOCAB_TERMS"], "abbreviations": g["ABBREVIATIONS"], "retired": g["RETIRED_PHRASES"],
                   "once_per_resume": g["ONCE_PER_RESUME"], "name": "", "headline": ""},
        "run": {"full": app.get("schedule", {}).get("full", "08:00"), "quick": app.get("schedule", {}).get("quick", []),
                "tracker": app.get("tracker", "local"), "auto_update": app.get("auto_update", True) is not False},
        "prefs": _read_prefs(s["preferences.json"], g),
    }


def _template_prefs():
    return json.loads((TEMPLATE / "preferences.json").read_text(encoding="utf-8"))


def _words(v, limit=200):
    out, seen = [], set()
    for x in v if isinstance(v, list) else []:
        t = str(x).strip()[:300]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:limit]


def _clean_prefs(p, base):
    """The wizard's answers, checked against the allowed choices; anything unknown keeps
    its saved (or default) value, and keys the wizard doesn't own are kept as they were."""
    d = _template_prefs()
    out = copy.deepcopy(base)
    p = p if isinstance(p, dict) else {}
    out["tools"] = _words(p.get("tools", base.get("tools")))
    fr_in, fr_old = p.get("format_rules") or {}, base.get("format_rules") or {}
    out["format_rules"] = {k: bool(fr_in.get(k, fr_old.get(k, dv))) for k, dv in d["format_rules"].items()}
    out["own_rules"] = _words(p.get("own_rules", base.get("own_rules")))
    for k, allowed in PREF_CHOICES.items():
        v = p.get(k, base.get(k))
        out[k] = v if v in allowed else (base.get(k) if base.get(k) in allowed else d[k])
    vi, vo = p.get("voice") or {}, base.get("voice") or {}
    tone = vi.get("tone", vo.get("tone", ""))
    habits = set(vi.get("avoid_habits", vo.get("avoid_habits")) or [])
    out["voice"] = {"what_bugged_you": str(vi.get("what_bugged_you", vo.get("what_bugged_you", "")) or "").strip()[:2000],
                    "avoid_habits": [h for h in HABITS if h in habits],
                    "oxford_comma": bool(vi.get("oxford_comma", vo.get("oxford_comma", False))),
                    "contractions": bool(vi.get("contractions", vo.get("contractions", False))),
                    "keep_my_wording": bool(vi.get("keep_my_wording", vo.get("keep_my_wording", False))),
                    "tone": tone if tone in TONES else ""}
    pi, po = p.get("permissions") or {}, base.get("permissions") or {}
    out["permissions"] = {}
    for k in PERMISSIONS:
        v = pi.get(k, po.get(k))
        out["permissions"][k] = v if v in LEVELS else d["permissions"][k]
    out["keep_general"] = _words(p.get("keep_general", base.get("keep_general")))
    out["saved_fixes"] = _words(p.get("saved_fixes", base.get("saved_fixes")), limit=500)
    out["talk_it_through"] = bool(p.get("talk_it_through", base.get("talk_it_through", True)))
    out.setdefault("talked_through", d["talked_through"])   # written by the plugin, never by the wizard
    return out


def _read_prefs(saved, gate):
    p = _clean_prefs(saved, {**_template_prefs(), **(saved or {})})
    if gate.get("FLAG_EM_DASH") and "em_dash" not in p["voice"]["avoid_habits"]:
        p["voice"]["avoid_habits"] = [h for h in HABITS if h in set(p["voice"]["avoid_habits"]) | {"em_dash"}]
    return p


def apply_answers(settings, a):
    """Return a new settings dict ({file: data}) with the answers applied."""
    s = copy.deepcopy(settings)
    c, co, r, app = s["criteria.json"], s["companies.json"], s["resume.json"], s["app.json"]
    ag, fs, g, b = c["agent"], c["fit_scoring"], r["presend_gate"], r["build_resume"]
    w, wh, ru, pay, fi, rs, run = (a[k] for k in ("work", "where", "rules", "pay", "fields", "resume", "run"))

    titles = [t.strip().lower() for t in w["titles"] if t.strip()]
    ag["TITLE_KEYWORDS"] = titles
    ag["ROLE_TITLE_RE"] = _alt_re(titles)
    ag["ROLE_FAMILY_LABEL"] = (w.get("field", "").strip() + " ") if w.get("field", "").strip() else ""
    never = [t.strip().lower() for t in w["never_titles"] if t.strip()]
    ag["ROLE_REJECT_KEYWORDS"] = never
    ag["ROLE_BAD_RE"] = _alt_re(never)
    fs["TITLE_SKIP"] = _rx([t.lower() for t in w["skip_title_words"]])
    fs["TITLE_ASK"] = _rx([t.lower() for t in w["ask_title_words"]])
    at, below, junior = (list(map(str.lower, w[k])) for k in ("level_at", "level_below", "level_junior"))
    # keep point values the wizard doesn't ask about (the middle level's points, the above-level tier)
    mid = next((x["$tuple"][0] for x in fs.get("LEVEL_RULES", []) if x["$tuple"][0] not in (15, 0)), 5)
    fs["LEVEL_RULES"] = [{"$tuple": [15, _rx(at)]}, {"$tuple": [mid, _rx(below)]}, {"$tuple": [0, _rx(junior)]}]
    above = [x for x in ag.get("LEVEL_TIERS", []) if x["$tuple"][0] == 3]
    ag["LEVEL_TIERS"] = above + [{"$tuple": [2, at]}, {"$tuple": [1, below]}]
    fs["YEARS_CLAIMABLE"] = int(w["years"] or 0)
    yw = [x.strip().lower() for x in w["years_words"] if x.strip()] or titles or ["experience"]
    fs["YEARS_RE"] = r"(\d{1,2})\s*\+?\s*(?:or more\s+)?(?:years|yrs)[^.;\n]{0,80}?(?:" + "|".join(re.escape(x) for x in yw) + ")"
    fs["YEARS_LABEL"] = f"years of {yw[0]}"

    mode = wh["mode"]
    fs["WORK_ARRANGEMENT"] = {"mode": mode, "home": wh.get("home", ""),
                              "commute_areas": [x.strip().lower() for x in wh.get("commute_areas", []) if x.strip()],
                              "max_office_days": wh.get("max_office_days"), "onsite_ok": bool(wh.get("onsite_ok")) and mode == "any",
                              "relocation_ok": bool(wh.get("relocation_ok"))}
    fs["POSTURE_POINTS"] = POSTURE["remote" if mode == "remote" else "other"]

    base_rules = {h["$tuple"][0]: h for h in (json.loads((TEMPLATE / "criteria.json").read_text())["fit_scoring"]["HARD_RULES"]
                                               + fs["HARD_RULES"])}
    for code in ("people-manager", "on-call", "contract"):
        if code not in base_rules:
            base_rules[code] = _default_rule(code)
    keep = ["remote-hybrid", "remote-catch"]
    if not ru["on_call_ok"]: keep.append("on-call")
    if not ru["contract_ok"]: keep.append("contract")
    if not ru["direct_reports_ok"]: keep.append("people-manager")
    fs["HARD_RULES"] = [base_rules[k] for k in keep if k in base_rules]
    fs["TRAVEL_SKIP_PCT"] = int(ru["travel_max_pct"])
    ind = [x.strip().lower() for x in ru["excluded_industries"] if x.strip()]
    ag["EXCLUDE_KEYWORDS"] = ind
    ag["DOMAIN_REJECT_KEYWORDS"] = ind
    fs["EXCLUDED_INDUSTRY_RE"] = _rx(ind)
    fs["EXCLUDED_COMPANIES"] = _rx([x.strip().lower() for x in ru["excluded_companies"] if x.strip()])
    exc = [x.strip().lower() for x in ru["exception_words"] if x.strip()]
    ag["INDUSTRY_EXCEPTION_KEYWORDS"] = exc
    fs["INDUSTRY_EXCEPTION_RE"] = _rx(exc)
    fs["BENEFITS_RULES"] = bool(ru["benefits_rule"])
    fs["TITLE_SKIP_LABEL"] = "Title is on your skip list"
    ag.setdefault("ASK_FLAG_LABEL", "Ask Me First")

    ag["SALARY_FLOOR"] = fs["PAY_HARD_FLOOR"] = int(pay["floor"] or 0)
    fs["PAY_TARGET"] = int(pay["target"] or pay["floor"] or 0)
    fs["NO_PAY_CAP"] = 49 if pay["rank_no_pay_lower"] else NO_CAP

    doms = [d for d in fi["domains"] if d.get("name", "").strip()]
    # keep an existing score unless the user changed that field's interest level
    fs["DOMAIN_SCORES"] = {d["name"].strip(): (d["points"] if d.get("points") is not None and d.get("was") == d["interest"]
                                               else INTEREST[d["interest"]]) for d in doms}
    fs["DOMAIN_KEYWORDS"] = [{"$tuple": [d["name"].strip(), _rx([k.strip().lower() for k in d["keywords"] if k.strip()])]}
                             for d in doms if any(k.strip() for k in d["keywords"])]
    # Same field as the user's current job: tailoring for a company tagged with it is the
    # most careful (confidentiality Tier 1). Only a field the user listed counts.
    # TIER_PRECEDENTS (companies tiered by name) is Advanced and not touched here.
    cur = str(fi.get("current_field") or "").strip().lower()
    fs["SAME_DOMAINS"] = [d["name"].strip() for d in doms if d["name"].strip().lower() == cur][:1]
    c["board_feeds"] = {"WWR_FEEDS": [FEEDS.get(fi.get("feed", "product"), FEEDS["product"])]}
    co["ats_tools"]["CONFIRMED_COMPANIES"] = fi["boards"]
    co["ats_tools"]["CUSTOM_SITE_COMPANIES"] = fi["custom_sites"]

    for k, v in (("FONT", "font"), ("BODY_PT", "body_pt"), ("NAME_PT", "name_pt"), ("HEADING_PT", "heading_pt"),
                 ("MARGIN_IN", "margin_in"), ("LINE_SPACING", "line_spacing")):
        b[k] = rs[v]
    g["SPEC_FONT"], g["SPEC_BODY_PT"], g["SPEC_NAME_PT"], g["SPEC_HEADING_PT"] = rs["font"], rs["body_pt"], rs["name_pt"], rs["heading_pt"]
    g["VOCAB_TERMS"], g["ABBREVIATIONS"] = rs["avoid_words"], rs["abbreviations"]
    g["RETIRED_PHRASES"], g["ONCE_PER_RESUME"] = rs["retired"], rs["once_per_resume"]
    if rs.get("name"):
        heads = r"Executive Profile|Core Expertise|Professional Experience|Earlier Experience|Education|Credentials|Tools and Technology|Dear |Thank you"
        extra = [re.escape(rs["name"].upper())] + ([re.escape(rs["headline"].split(" | ")[0]) + r" \|"] if rs.get("headline") else [])
        g["REPEAT_SKIP_RE"] = r"^(" + "|".join(extra) + "|" + heads + ")"

    upd = (app.get("schedule") or {}).get("update")
    app["schedule"] = {"full": run["full"], "quick": [q for q in run["quick"] if q]}
    if upd:
        app["schedule"]["update"] = upd   # not asked in setup; keep it
    if "auto_update" in run:
        app["auto_update"] = bool(run["auto_update"])
    app["tracker"] = run["tracker"]

    if "prefs" in a:   # setup step 8; an older page that doesn't send it leaves the file alone
        old = {**_template_prefs(), **(s.get("preferences.json") or {})}
        p = s["preferences.json"] = _clean_prefs(a["prefs"], old)
        g["FLAG_EM_DASH"] = "em_dash" in p["voice"]["avoid_habits"]
        if p["resume_pages"] in PAGES:
            g["PAGE_LIMIT"] = PAGES[p["resume_pages"]]   # "auto" leaves it to Start Here session 3
    return s


def _default_rule(code):
    t = json.loads((KIT / "templates" / "settings" / "criteria.json").read_text())
    for h in t["fit_scoring"]["HARD_RULES"]:
        if h["$tuple"][0] == code:
            return h
    return {"$tuple": [code, {"$rx": ["~^$"]}, "skip", code]}


def write_answers(settings_dir, answers):
    d = Path(settings_dir)
    d.mkdir(parents=True, exist_ok=True)
    new = apply_answers(_load(d), answers)
    # where the kit's code lives, so the Claude plugin can run the builder, gate, and tracker
    new.setdefault("paths.json", {})["kit_dir"] = str(Path(__file__).resolve().parents[1])
    for f, data in new.items():
        (d / f).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return new


ADVANCED = [("agent", "FRESH_DAYS", 14), ("agent", "FRESH_ALERT_DAYS", 2),
            ("agent", "EVERGREEN_AGE_DAYS", 150), ("agent", "AGE_NOTE_DAYS", 60), ("agent", "REPOST_WINDOW_DAYS", 90),
            ("agent", "GHOST_FLAG_IDS", 2), ("agent", "GHOST_FLAG_LOCATIONS", 4), ("agent", "GHOST_SKIP_IDS", 4)]


def read_advanced(settings_dir):
    c = _load(settings_dir)["criteria.json"]
    return {f"{sec}.{k}": c.get(sec, {}).get(k, d) for sec, k, d in ADVANCED}


def write_advanced(settings_dir, values):
    d = Path(settings_dir)
    s = _load(d)
    c = s["criteria.json"]
    for sec, k, dflt in ADVANCED:
        key = f"{sec}.{k}"
        if key in values and values[key] not in (None, ""):
            c.setdefault(sec, {})[k] = int(values[key])
    (d / "criteria.json").write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
