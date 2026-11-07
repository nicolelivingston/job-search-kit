"""Built-in tracker: answers the agent's Notion API calls from local files.

When settings/app.json says "tracker": "local" (the default for the kit),
ats_tools.request_with_retry hands every api.notion.com request to handle()
instead of the network. The agent code is unchanged, so scoring, rescoring,
stale-posting closes, and the snapshot behave exactly as they do with Notion.

Data lives in <data folder>/tracker/<database>.json, one file per database,
in Notion's own page shape (properties with a "type" and a value). Writes are
atomic (write a temp file, then replace), so a crash never leaves a half file.

Supported: POST /v1/pages, GET and PATCH /v1/pages/{id}, GET /v1/databases/{id},
POST /v1/databases/{id}/query with property filters (title, rich_text, select,
status, multi_select, number, date, checkbox, url, relation), and/or compounds,
last_edited_time timestamp filters, sorts, and cursor pagination.
"""
import json
import os
import re
import contextlib
import time
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

DB_NAMES = {}          # database id -> file stem, filled by configure()
_DATA = None
_STORE = {}            # file stem -> {"pages": {id: page}}
_SEEN = {}             # file stem -> (mtime_ns, size) when it was last read


@contextlib.contextmanager
def file_lock(path, timeout=30.0):
    """Hold an exclusive lock on `<path>.lock` across processes (the daily run,
    the tracker page, and the plugin's tracker commands can all write)."""
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock, "a+")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"the tracker is busy ({lock.name}); try again in a minute")
                time.sleep(0.05)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def configure(data_dir, applications_id, companies_id):
    global _DATA
    _DATA = Path(data_dir) / "tracker"
    _DATA.mkdir(parents=True, exist_ok=True)
    DB_NAMES.clear()
    DB_NAMES[applications_id] = "applications"
    DB_NAMES[companies_id] = "companies"
    _STORE.clear()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _stem(db_id):
    return DB_NAMES.get(db_id) or re.sub(r"[^A-Za-z0-9_-]", "", db_id) or "unknown"


def _stamp(f):
    try:
        st = f.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


class TrackerDamaged(RuntimeError):
    """A tracker file on disk can't be read (cut off mid-write, edited by hand)."""


def _load(stem, fresh=False):
    """The store for one tracker file. Re-read from disk when another process
    has changed the file since this one last read it, or when `fresh`."""
    f = _DATA / f"{stem}.json"
    stamp = _stamp(f)
    if fresh or stem not in _STORE or (stamp is not None and _SEEN.get(stem) != stamp):
        if f.exists():
            try:
                _STORE[stem] = json.loads(f.read_text(encoding="utf-8"))
            except ValueError as e:
                # Never start over on a damaged file: the next save would replace
                # every row. Stop and say how to get the rows back.
                raise TrackerDamaged(
                    f"The tracker file {f} is damaged ({e}). Nothing was changed. Daily backups are in the "
                    f"data folder's backups folder (python backup.py restore <file> --only tracker), or send an "
                    f"error report for help.") from None
        else:
            _STORE[stem] = _STORE.get(stem, {"pages": {}})
        _SEEN[stem] = stamp
    return _STORE[stem]


def _save(stem):
    f = _DATA / f"{stem}.json"
    fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=f".{stem}-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_STORE[stem], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, f)
    _SEEN[stem] = _stamp(f)


def _find_page(page_id):
    for f in _DATA.glob("*.json"):
        stem = f.stem
        store = _load(stem)
        if page_id in store["pages"]:
            return stem, store["pages"][page_id]
    for stem, store in _STORE.items():
        if page_id in store["pages"]:
            return stem, store["pages"][page_id]
    return None, None


# --- property values -------------------------------------------------------
TEXT_TYPES = ("title", "rich_text")


def _norm_text(items):
    out = []
    for it in items or []:
        content = (it.get("text") or {}).get("content", it.get("plain_text", ""))
        link = (it.get("text") or {}).get("link")
        out.append({"type": "text", "text": {"content": content, "link": link},
                    "plain_text": content, "href": (link or {}).get("url") if link else None,
                    "annotations": it.get("annotations", {})})
    return out


def _norm_prop(name, value):
    """Turn a request-shaped property value into Notion's response shape."""
    kinds = [k for k in value if k not in ("type", "id")]
    if not kinds:
        return {"id": name, "type": "rich_text", "rich_text": []}
    kind = kinds[0]
    v = value[kind]
    if kind in TEXT_TYPES:
        v = _norm_text(v)
    elif kind in ("select", "status"):
        v = {"name": v["name"]} if v and v.get("name") else None
    elif kind == "multi_select":
        v = [{"name": x["name"]} for x in (v or [])]
    elif kind == "relation":
        v = [{"id": x["id"]} for x in (v or [])]
    elif kind == "date":
        v = {"start": v.get("start"), "end": v.get("end"), "time_zone": None} if v else None
    return {"id": name, "type": kind, kind: v}


def _plain(prop):
    t = prop.get("type")
    v = prop.get(t)
    if t in TEXT_TYPES:
        return "".join(x.get("plain_text", "") for x in v or [])
    if t in ("select", "status"):
        return v["name"] if v else None
    if t == "multi_select":
        return [x["name"] for x in v or []]
    if t == "relation":
        return [x["id"] for x in v or []]
    if t == "date":
        return v["start"] if v else None
    return v


# --- filters ---------------------------------------------------------------
def _match_prop(prop, kind, cond):
    val = _plain(prop) if prop else None
    for op, arg in cond.items():
        if op == "is_empty":
            if bool(val) and val != 0:
                return False
        elif op == "is_not_empty":
            if not val and val != 0:
                return False
        elif kind in ("title", "rich_text", "url", "email", "phone_number"):
            s = (val or "").lower(); a = (arg or "").lower()
            ok = {"equals": s == a, "does_not_equal": s != a, "contains": a in s,
                  "does_not_contain": a not in s, "starts_with": s.startswith(a),
                  "ends_with": s.endswith(a)}.get(op)
            if not ok:
                return False
        elif kind in ("select", "status"):
            ok = {"equals": val == arg, "does_not_equal": val != arg}.get(op)
            if not ok:
                return False
        elif kind == "multi_select" or kind == "relation":
            items = val or []
            ok = {"contains": arg in items, "does_not_contain": arg not in items}.get(op)
            if not ok:
                return False
        elif kind == "checkbox":
            if {"equals": bool(val) == arg, "does_not_equal": bool(val) != arg}.get(op) is not True:
                return False
        elif kind == "number":
            if val is None:
                return False
            ok = {"equals": val == arg, "does_not_equal": val != arg, "greater_than": val > arg,
                  "less_than": val < arg, "greater_than_or_equal_to": val >= arg,
                  "less_than_or_equal_to": val <= arg}.get(op)
            if not ok:
                return False
        elif kind in ("date", "created_time", "last_edited_time"):
            if not val:
                return False
            d, a = str(val)[:10], str(arg)[:10]
            ok = {"equals": d == a, "on_or_after": d >= a, "on_or_before": d <= a,
                  "after": d > a, "before": d < a}.get(op)
            if not ok:
                return False
        else:
            raise ValueError(f"local tracker: unsupported filter {kind}.{op}")
    return True


def _match(page, flt):
    if not flt:
        return True
    if "and" in flt:
        return all(_match(page, f) for f in flt["and"])
    if "or" in flt:
        return any(_match(page, f) for f in flt["or"])
    if "timestamp" in flt:
        ts = flt["timestamp"]
        return _match_prop({"type": "date", "date": {"start": page.get(ts)}}, "date", flt[ts])
    name = flt["property"]
    kind = next(k for k in flt if k != "property")
    return _match_prop(page["properties"].get(name), kind, flt[kind])


def _sort_key(page, s):
    if "timestamp" in s:
        v = page.get(s["timestamp"])
    else:
        p = page["properties"].get(s["property"])
        v = _plain(p) if p else None
    return (v is None, v if not isinstance(v, list) else str(v))


# --- responses -------------------------------------------------------------
class Response:
    def __init__(self, body, status=200, url=""):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)
        self.ok = status < 400
        self.url = url
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} local tracker: {self._body.get('message')}", response=self)


def _err(status, msg, url):
    return Response({"object": "error", "status": status, "message": msg}, status, url)


def handle(method, url, kwargs):
    if _DATA is None:
        raise RuntimeError("local tracker not configured")
    method = method.lower().rsplit("_", 1)[-1]   # requests.get -> "get"; tolerate wrapped names
    path = url.split("api.notion.com", 1)[1].split("?", 1)[0].rstrip("/")
    body = kwargs.get("json") or {}
    if isinstance(kwargs.get("data"), (str, bytes)):
        body = json.loads(kwargs["data"])
    m = re.fullmatch(r"/v1/databases/([^/]+)/query", path)
    if m and method == "post":
        stem = _stem(m.group(1))
        pages = [p for p in _load(stem)["pages"].values()
                 if not p.get("archived") and _match(p, body.get("filter"))]
        for s in reversed(body.get("sorts") or []):
            pages.sort(key=lambda p: _sort_key(p, s), reverse=(s.get("direction") == "descending"))
        if not body.get("sorts"):
            pages.sort(key=lambda p: p.get("created_time", ""), reverse=True)
        start = int(body.get("start_cursor") or 0)
        size = min(int(body.get("page_size") or 100), 100)
        chunk = pages[start:start + size]
        more = start + size < len(pages)
        return Response({"object": "list", "results": chunk, "has_more": more,
                         "next_cursor": str(start + size) if more else None}, 200, url)
    m = re.fullmatch(r"/v1/databases/([^/]+)", path)
    if m and method == "get":
        stem = _stem(m.group(1))
        props = {}
        for p in _load(stem)["pages"].values():
            for name, prop in p["properties"].items():
                props.setdefault(name, {"id": name, "name": name, "type": prop.get("type")})
        for name in SCHEMA.get(stem, ()):
            props.setdefault(name, {"id": name, "name": name, "type": "rich_text"})
        return Response({"object": "database", "id": m.group(1), "properties": props}, 200, url)
    if path == "/v1/pages" and method == "post":
        db = (body.get("parent") or {}).get("database_id", "")
        stem = _stem(db)
        pid = str(uuid.uuid4())
        now = _now()
        page = {"object": "page", "id": pid, "created_time": now, "last_edited_time": now,
                "parent": {"type": "database_id", "database_id": db}, "archived": False,
                "icon": body.get("icon"), "url": f"local://{stem}/{pid}",
                "properties": {n: _norm_prop(n, v) for n, v in (body.get("properties") or {}).items()}}
        with file_lock(_DATA / f"{stem}.json"):
            _load(stem, fresh=True)["pages"][pid] = page
            _save(stem)
        return Response(page, 200, url)
    m = re.fullmatch(r"/v1/pages/([^/]+)", path)
    if m:
        stem, page = _find_page(m.group(1))
        if page is None:
            return _err(404, "page not found", url)
        if method == "get":
            return Response(page, 200, url)
        if method == "patch":
            with file_lock(_DATA / f"{stem}.json"):
                page = _load(stem, fresh=True)["pages"].get(m.group(1))
                if page is None:
                    return _err(404, "page not found", url)
                for n, v in (body.get("properties") or {}).items():
                    page["properties"][n] = _norm_prop(n, v)
                if "icon" in body:
                    page["icon"] = body["icon"]
                if "archived" in body:
                    page["archived"] = bool(body["archived"])
                page["last_edited_time"] = _now()
                _save(stem)
            return Response(page, 200, url)
    return _err(400, f"local tracker: unsupported {method.upper()} {path}", url)


# Properties the agent checks for on the Applications database (mirrors
# job_search_agent.REQUIRED_APP_PROPERTIES), so a fresh tracker passes the
# schema check before its first row exists.
SCHEMA = {"applications": (
    "Role", "Company", "Job Posting", "Status", "Industry Flag", "Role Fit Score", "Source", "Notes",
    "Base Salary", "Remote Status", "Company Profile", "Posting Health", "Role Red Flags",
    "Research Tier", "Score Breakdown", "Fit Evidence", "Domain Tier", "Label Reason",
    "Overall Verdict", "Schedule Intensity", "Pay Basis", "Posted Date", "Posted Date Source",
    "Last Verified", "Posting Snapshot", "Date Applied", "Outcome Type", "Outcome Date")}
