#!/usr/bin/env python3
"""One-time (re-runnable) seeder for posting_history.json.

Reads every row of the Notion Applications tracker and records each as one
sighting of its company+title, dated by the row's creation date, so the
ghost-posting detector in job_search_agent.py starts with the last month of
history instead of learning from zero. Rows in an active status also set
last_written, which stops a repost from creating a duplicate tracker row.

Safe to re-run: it merges into the existing history file and never removes
sightings the agent has recorded on its own.
"""

import json
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from job_search_agent import (  # noqa: E402
    NOTION_DATABASE_ID, NOTION_TOKEN, POSTING_HISTORY_FILE, load_history,
    norm_title, request_with_retry,
)

ACTIVE_STATUSES = {"Interested", "Drafting Resume", "Applied", "Interviewing", "Offer"}


def plain(prop, kind):
    items = prop.get(kind, [])
    return "".join(part.get("plain_text", "") for part in items)


def main():
    if not NOTION_TOKEN:
        sys.exit("NOTION_TOKEN not set; cannot seed.")
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}",
               "Notion-Version": "2022-06-28",
               "Content-Type": "application/json"}
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    history = load_history()
    added = 0
    payload = {"page_size": 100}
    while True:
        resp = request_with_retry(requests.post, url, headers=headers,
                                  json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            role = plain(props.get("Role", {}), "title")
            company = plain(props.get("Company", {}), "rich_text")
            if not role or not company:
                continue
            created = (page.get("created_time", "") or "")[:10]
            status = (props.get("Status", {}).get("status") or {}).get("name", "")
            key = f"{company.strip().lower()}::{norm_title(role)}"
            entry = history.setdefault(key, {"ids": {}, "locations": {}})
            pseudo_id = f"tracker-{page['id']}"
            if pseudo_id not in entry["ids"]:
                entry["ids"][pseudo_id] = created
                added += 1
            if status in ACTIVE_STATUSES:
                lw = entry.get("last_written")
                entry["last_written"] = max(lw, created) if lw else created
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    POSTING_HISTORY_FILE.write_text(json.dumps(history, indent=1, sort_keys=True))
    print(f"Seeded {added} sighting(s); history now tracks {len(history)} company+title keys.")


if __name__ == "__main__":
    main()
