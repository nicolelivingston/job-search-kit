#!/usr/bin/env python3
"""Command-line access to the built-in tracker, for the Claude plugin.

The plugin's skills read and update tracker rows through this script instead
of editing the tracker's JSON by hand. Output is JSON on stdout. Works with
the built-in tracker ("tracker": "local" in settings/app.json); a Notion user
updates Notion directly.

    python tracker_cli.py list [--open]
    python tracker_cli.py find --company "Acme" [--role "Product"]
    python tracker_cli.py show <row id>
    python tracker_cli.py update <row id> [--status S] [--verdict V] [--notes N | --append-notes N]
                                 [--outcome O] [--set "Field=value" ...]
    python tracker_cli.py add (--url URL | --text-file FILE) [--title T] [--company C]
    python tracker_cli.py fetch --url URL --out "Applications/<Company> (drafting)/posting.md"
    python tracker_cli.py contacts list
    python tracker_cli.py contacts add --name N [--company C] [--role R] [--last YYYY-MM-DD] [--notes N]
    python tracker_cli.py company --name "Acme" [--set "glassdoor=4.1" --set "verdict=Watch list" ...]
    python tracker_cli.py check-groups

`check-groups` loads keyword-groups.json the way the daily run does, checks
every group's shape, and scores a sample posting with it. It exits with
status 1 and a plain message if anything is wrong.

`show` prints every field of one row (including Drafting Started and the
version counts). `--append-notes` adds a dated line to Notes instead of
replacing them. `add` prints the new row's id. `list --open` leaves out rows
with a closing outcome (rejected, withdrawn, declined, closed). A failed
update exits with status 1.

`--set` writes one of the tracker's fields (an unknown name is refused): a whole number or decimal becomes a number,
YYYY-MM-DD becomes a date, anything else becomes text. The plugin uses it for
Drafting Started, Resume Versions, Cover Letter Versions, Resume Version Used,
Hours Spent, Posting Age At Send, and Contact Before Applying.

`company` shows one company's research, or with `--set` fills it in (the
company is added if it isn't there). Fields: posture, verdict, risk, field,
health, dni, glassdoor (1 to 5), match (percent), bonus, perks, pto,
pto_weak (yes or no), growth, career, values, green, red, careers (a link).
Choices are the Companies page's own words (the Help page lists them).
"""
import argparse
import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "agent"))
import wizard  # noqa: E402

# Fields the plugin writes with --set beyond the agent's own columns.
SET_FIELDS = {"Drafting Started", "Resume Versions", "Cover Letter Versions", "Resume Version Used",
              "Hours Spent", "Cycle Days", "Posting Age At Send", "Contact Before Applying",
              "Opened", "Follow-up Date", "Next Step"}
OPEN_STATUSES = ("Interested", "Drafting Resume", "Applied", "Interviewing")
CLOSING_OUTCOME = re.compile(r"reject|withdr|declin|closed|no response|ghost", re.I)


def _pages():
    f = wizard.kit_settings.data_dir() / "tracker" / "applications.json"
    return json.loads(f.read_text(encoding="utf-8"))["pages"] if f.exists() else {}


def _prop(value):
    v = value.strip()
    if re.fullmatch(r"-?\d+", v):
        return {"number": int(v)}
    if re.fullmatch(r"-?\d+\.\d+", v):
        return {"number": float(v)}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return {"date": {"start": v}}
    return {"rich_text": [{"text": {"content": v[:1900]}}]}


def cmd_list(args):
    rows = wizard.tracker_rows()["rows"]
    if args.open:
        rows = [r for r in rows if r["Status"] in OPEN_STATUSES
                and not CLOSING_OUTCOME.search(r.get("Outcome Type") or "")]
    return rows


def cmd_show(args):
    page = _pages().get(args.id)
    if not page:
        return {"ok": False, "message": f"no tracker row {args.id}"}
    return {"ok": True, "id": args.id, **{k: wizard._plain(v) for k, v in page["properties"].items()}}


def cmd_find(args):
    rows = wizard.tracker_rows()["rows"]
    c, r_ = args.company.lower(), (args.role or "").lower()
    return [r for r in rows if c in (r["Company"] or "").lower() and r_ in (r["Role"] or "").lower()]


def cmd_update(args):
    body = {"id": args.id}
    for k in ("status", "verdict", "notes", "outcome"):
        if getattr(args, k) is not None:
            body[k] = getattr(args, k)
    if args.append_notes:
        page = _pages().get(args.id)
        if not page:
            return {"ok": False, "id": args.id, "message": f"no tracker row {args.id}"}
        old = wizard._plain(page["properties"].get("Notes")) or ""
        from datetime import date
        body["notes"] = (old + "\n" if old else "") + f"{date.today().isoformat()}: {args.append_notes}"
    ok, message = True, None
    if len(body) > 1:
        r = wizard.tracker_update(body)
        ok, message = r["ok"], r.get("error")
    if args.set:
        page = _pages().get(args.id)
        if not page:
            return {"ok": False, "id": args.id, "message": f"no tracker row {args.id}"}
        from local_tracker import SCHEMA
        known = set(SCHEMA["applications"]) | set(page["properties"]) | SET_FIELDS
        props = {}
        for item in args.set:
            if "=" not in item:
                raise SystemExit(f"--set needs Field=value, got {item!r}")
            name, value = item.split("=", 1)
            if name.strip() not in known:
                return {"ok": False, "id": args.id, "message": f"no tracker field named {name.strip()!r}; "
                        "field names are case-sensitive (see `show` for a row's fields)"}
            props[name.strip()] = _prop(value)
        a = wizard.agent()
        r = a["lt"].handle("patch", f"https://api.notion.com/v1/pages/{args.id}", {"json": {"properties": props}})
        ok = ok and r.status_code < 300
    out = {"ok": ok, "id": args.id}
    if message:
        out["message"] = message
    return out


def cmd_add(args):
    body = {"url": args.url or "", "title": args.title or "", "company": args.company or ""}
    if args.text_file:
        body["text"] = Path(args.text_file).read_text(encoding="utf-8")
    return wizard.tracker_add(body)


def fetch_posting(url, out, fetch=None):
    """Save a posting's text as posting.md. The only way Claude pulls a posting in
    the Job Search folder (its own web tools are off there): public addresses only,
    and the file goes only under the folder's Applications/."""
    from datetime import date
    root = wizard.settings_dir().parent.resolve()
    dest = Path(out)
    dest = (dest if dest.is_absolute() else Path.cwd() / dest).resolve()
    apps = root / "Applications"
    if apps not in dest.parents or dest.suffix.lower() != ".md":
        return {"ok": False, "message": f"the posting file must be a .md file under {apps}"}
    a = wizard.agent()
    try:
        text = a["jsa"].clean_posting_text((fetch or wizard.safe_fetch)(url))
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "message": f"couldn't open that link ({e}); ask the user to paste the posting text"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"Source: {url}\nPulled: {date.today().isoformat()}\n\n{text}\n", encoding="utf-8")
    return {"ok": True, "file": str(dest), "characters": len(text)}


def cmd_fetch(args):
    return fetch_posting(args.url, args.out)


def cmd_contacts(args):
    if args.action == "list":
        return wizard.contacts_get()
    if not args.name:
        raise SystemExit("contacts add needs --name")
    row = {k: v for k, v in (("name", args.name), ("company", args.company), ("role", args.role),
                              ("last", args.last), ("notes", args.notes)) if v}
    import local_tracker
    f = wizard.contacts_file()
    with local_tracker.file_lock(f):   # read and write under one lock so a page save can't land between
        rows = wizard.contacts_get()
        rows.append(row)
        f.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "contact": row}


COMPANY_FIELDS = ("posture", "verdict", "risk", "pto_weak", *wizard.RESEARCH)


def cmd_company(args):
    """Show or fill in one company's research (made if it isn't there yet).
    Field names and choices are the Companies page's own (Help page)."""
    rows = wizard.companies_rows()["rows"]
    row = next((c for c in rows if c["name"].lower() == args.name.strip().lower()), None)
    if not args.set:
        return {"ok": bool(row), **(row or {"message": f"no company named {args.name}"})}
    body = {"id": (row or {}).get("id", ""), "name": args.name.strip()}
    for item in args.set:
        if "=" not in item:
            raise SystemExit(f"--set needs field=value, got {item!r}")
        k, v = (x.strip() for x in item.split("=", 1))
        if k not in COMPANY_FIELDS:
            raise SystemExit(f"unknown company field {k!r}; one of: {', '.join(COMPANY_FIELDS)}")
        body[k] = v.lower() in ("yes", "true", "1") if k == "pto_weak" else v
    if not body["id"]:
        made = wizard.company_save({"name": body["name"]})
        if not made["ok"]:
            return made
        body["id"] = made["id"]
    return wizard.company_save(body)


def cmd_check_groups(args):
    """Load keyword-groups.json as the daily run does, check each group's shape,
    and score a sample posting. Session 3 runs this before it closes."""
    import kit_settings
    path = kit_settings.keyword_groups_file()
    try:
        import fit_scoring
    except Exception as e:   # bad JSON, a bad pattern, or a missing file
        return {"ok": False, "file": str(path), "message": f"keyword groups don't load: {type(e).__name__}: {e}"}
    shapes = {"WORK_FAMILIES": ("label", "cards", "points", "words"),
              "GAP_FAMILIES": ("label", "points", "words"),
              "MINIMUM_FAMILIES": ("label", "words")}
    problems, counts = [], {}
    for name, parts in shapes.items():
        groups = getattr(fit_scoring, name, None) or []
        counts[name] = len(groups)
        for i, g in enumerate(groups, 1):
            if not isinstance(g, tuple) or len(g) != len(parts):
                problems.append(f"{name} group {i} needs {len(parts)} parts ({', '.join(parts)}); it has "
                                f"{len(g) if isinstance(g, (tuple, list)) else 'a different shape'}")
                continue
            if not isinstance(g[0], str) or not g[0].strip():
                problems.append(f"{name} group {i}: the label is missing")
            if not hasattr(g[-1], "search"):
                problems.append(f"{name} group {i} ({g[0]}): the last part must be a word list")
            if "points" in parts and not isinstance(g[parts.index("points")], (int, float)):
                problems.append(f"{name} group {i} ({g[0]}): points must be a number")
    if problems:
        return {"ok": False, "file": str(path), "message": "; ".join(problems)}
    try:
        fit_scoring.score_posting("Sample role", "A sample posting used to check the keyword groups. "
                                  "Remote. Requirements: experience leading cross-functional work.")
    except Exception as e:
        return {"ok": False, "file": str(path), "message": f"scoring a sample posting failed: {type(e).__name__}: {e}"}
    if not counts["WORK_FAMILIES"]:
        return {"ok": False, "file": str(path), "groups": counts, "message": "WORK_FAMILIES is empty; session 3 fills it"}
    return {"ok": True, "file": str(path), "groups": counts}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("find"); p.add_argument("--company", required=True); p.add_argument("--role")
    p.set_defaults(fn=cmd_find)
    p = sub.add_parser("show"); p.add_argument("id"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("update"); p.add_argument("id")
    for k in ("status", "verdict", "outcome"):
        p.add_argument("--" + k)
    g = p.add_mutually_exclusive_group(); g.add_argument("--notes"); g.add_argument("--append-notes")
    p.add_argument("--set", action="append"); p.set_defaults(fn=cmd_update)
    p = sub.add_parser("fetch"); p.add_argument("--url", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("contacts"); p.add_argument("action", choices=("list", "add"))
    for k in ("name", "company", "role", "last", "notes"):
        p.add_argument("--" + k)
    p.set_defaults(fn=cmd_contacts)
    p = sub.add_parser("company"); p.add_argument("--name", required=True); p.add_argument("--set", action="append")
    p.set_defaults(fn=cmd_company)
    p = sub.add_parser("check-groups"); p.set_defaults(fn=cmd_check_groups)
    p = sub.add_parser("add"); p.add_argument("--url"); p.add_argument("--text-file")
    p.add_argument("--title"); p.add_argument("--company"); p.set_defaults(fn=cmd_add)
    args = ap.parse_args(argv)
    out = args.fn(args)
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    if isinstance(out, dict) and out.get("ok") is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
