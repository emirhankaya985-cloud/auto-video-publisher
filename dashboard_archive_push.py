"""Push only the verified daily metrics archive to the private dashboard."""
import json
import os
import sys
from pathlib import Path

import requests

ARCHIVE = Path("link-runtime/daily_video_views.jsonl")
ENDPOINT = os.getenv("DASHBOARD_INGEST_URL", "").strip().rstrip("/")
TOKEN = os.getenv("DASHBOARD_INGEST_TOKEN", "").strip()


def main():
    if not ENDPOINT or not TOKEN:
        print("dashboard_sync=skipped_missing_secrets")
        return 0
    if not ARCHIVE.exists():
        print("dashboard_sync=skipped_archive_missing")
        return 0
    rows = []
    with ARCHIVE.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    accepted = 0
    for offset in range(0, len(rows), 300):
        response = requests.post(
            ENDPOINT + "/api/archive",
            json={"rows": rows[offset:offset + 300]},
            headers={"Authorization": "Bearer " + TOKEN},
            timeout=(5, 30),
        )
        if response.status_code != 200:
            print(f"dashboard_sync=failed http_status={response.status_code}")
            return 1
        try:
            accepted += int(response.json().get("accepted", 0))
        except (ValueError, TypeError, AttributeError):
            print("dashboard_sync=failed invalid_ack")
            return 1
    print(f"dashboard_sync=ok rows_acknowledged={accepted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
