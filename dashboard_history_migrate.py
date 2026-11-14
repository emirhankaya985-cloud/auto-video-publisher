"""One-time migration of retained GitHub analytics artifacts into private Neon."""
import hashlib
import io
import json
import os
import sys
import zipfile

import requests

API = "https://api.github.com"
REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
TOKEN = os.getenv("GITHUB_TOKEN", "")
INGEST_URL = os.getenv("DASHBOARD_INGEST_URL", "").rstrip("/")
INGEST_TOKEN = os.getenv("DASHBOARD_INGEST_TOKEN", "")
MAX_RUNS = min(max(int(os.getenv("DASHBOARD_MIGRATION_RUNS", "100")), 1), 100)


def api_get(url):
    response = requests.get(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, timeout=(10, 60))
    response.raise_for_status()
    return response


def main():
    if not all((REPOSITORY, TOKEN, INGEST_URL, INGEST_TOKEN)):
        print("migration=blocked_missing_configuration")
        return 2
    runs_url = f"{API}/repos/{REPOSITORY}/actions/workflows/daily_stats.yml/runs?branch=main&status=success&per_page=100"
    runs = api_get(runs_url).json().get("workflow_runs", [])[:MAX_RUNS]
    candidates = []
    for run in runs:
        run_id = run.get("id")
        if not run_id:
            continue
        artifacts = api_get(f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts").json().get("artifacts", [])
        candidates.extend((run_id, a) for a in artifacts
                          if a.get("name") == "meta-daily-analytics-history" and not a.get("expired"))
    rows_by_key = {}
    for run_id, artifact in candidates:
        archive = api_get(artifact["archive_download_url"]).content
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            for name in bundle.namelist():
                if not name.endswith("daily_video_views.jsonl"):
                    continue
                for line in bundle.read(name).decode("utf-8").splitlines():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    key_fields = ("period", "account", "platform", "entity_type", "entity_id", "metric")
                    if not all(row.get(field) is not None for field in key_fields):
                        continue
                    key = json.dumps([row.get(field) for field in key_fields], ensure_ascii=False)
                    old = rows_by_key.get(key)
                    if old is None or str(row.get("measured_at") or "") > str(old.get("measured_at") or ""):
                        rows_by_key[key] = row
    rows = list(rows_by_key.values())
    acknowledged = 0
    for offset in range(0, len(rows), 300):
        response = requests.post(
            INGEST_URL + "/api/archive",
            json={"rows": rows[offset:offset + 300]},
            headers={"Authorization": "Bearer " + INGEST_TOKEN},
            timeout=(10, 60),
        )
        if response.status_code != 200:
            print(f"migration=failed http_status={response.status_code} processed={acknowledged}")
            return 1
        acknowledged += int(response.json().get("accepted", 0))
    print(f"migration=completed artifacts={len(candidates)} records_acknowledged={acknowledged}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"migration=failed error_type={type(exc).__name__}")
        raise SystemExit(1)
