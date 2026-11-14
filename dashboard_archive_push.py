"""Incrementally sync recent verified archive rows from a GitHub Actions artifact."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

import requests

API = "https://api.github.com"
REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
SOURCE_RUN_ID = os.getenv("SOURCE_RUN_ID", "").strip()
INGEST_URL = os.getenv("DASHBOARD_INGEST_URL", "").strip().rstrip("/")
INGEST_TOKEN = os.getenv("DASHBOARD_INGEST_TOKEN", "").strip()
ARTIFACT_NAME = "meta-daily-analytics-history"
BATCH_SIZE = 1000
SYNC_DAYS = min(max(int(os.getenv("DASHBOARD_SYNC_DAYS", "7")), 1), 30)
ARCHIVE = "link-runtime/daily_video_views.jsonl"


def _session():
    return requests.Session()


def request_with_retry(session, method, url, **kwargs):
    for attempt in range(5):
        try:
            response = getattr(session, method)(url, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 4:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            try:
                delay = min(max(float(retry_after), 0), 30) if retry_after else min(2 ** attempt, 8)
            except ValueError:
                delay = min(2 ** attempt, 8)
        except requests.RequestException:
            if attempt == 4:
                raise
            delay = min(2 ** attempt, 8)
        time.sleep(delay)
    raise RuntimeError("request_retry_exhausted")


def _get(session, url):
    response = request_with_retry(session, "get", url, headers={
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, timeout=(10, 90))
    return response


def read_source_rows(session):
    if SOURCE_RUN_ID:
        if not REPOSITORY or not GITHUB_TOKEN:
            raise RuntimeError("github_source_configuration_missing")
        artifacts_url = f"{API}/repos/{REPOSITORY}/actions/runs/{int(SOURCE_RUN_ID)}/artifacts"
        artifacts = _get(session, artifacts_url).json().get("artifacts", [])
        artifact = next((item for item in artifacts if item.get("name") == ARTIFACT_NAME and not item.get("expired")), None)
        if not artifact:
            raise RuntimeError("source_artifact_unavailable")
        archive = _get(session, artifact["archive_download_url"]).content
        archive_sha = hashlib.sha256(archive).hexdigest()
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = [name for name in bundle.namelist() if name.endswith("daily_video_views.jsonl")]
            if len(names) != 1:
                raise RuntimeError("source_archive_shape_invalid")
            rows, invalid_rows = _parse_jsonl(bundle.read(names[0]).decode("utf-8", errors="replace"))
        return rows, invalid_rows, archive_sha
    if os.path.exists(ARCHIVE):
        with open(ARCHIVE, encoding="utf-8") as source:
            rows, invalid_rows = _parse_jsonl(source.read())
        digest = hashlib.sha256(open(ARCHIVE, "rb").read()).hexdigest()
        return rows, invalid_rows, digest
    raise RuntimeError("source_archive_unavailable")


def _parse_jsonl(contents):
    rows, invalid = [], []
    for line in contents.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            invalid.append({"_review_reason": "invalid_json", "_raw_line": line[:4000]})
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            invalid.append({"_review_reason": "row_not_object", "_invalid_value": row})
    return rows, invalid


def recent_rows(rows, days=SYNC_DAYS):
    dates = []
    for row in rows:
        try:
            dates.append(date.fromisoformat(str(row.get("period", ""))[:10]))
        except ValueError:
            continue
    if not dates:
        return [], None
    latest = max(dates)
    start = latest - timedelta(days=days - 1)
    selected = [row for row in rows if _in_window(row, start, latest)]
    return selected, latest.isoformat()


def deduplicate_rows(rows):
    unique = {}
    for row in rows:
        fields = ("period", "account", "platform", "entity_type", "entity_id", "metric")
        if all(row.get(field) is not None for field in fields):
            key = json.dumps([row.get(field) for field in fields], ensure_ascii=False, separators=(",", ":"))
        else:
            key = "review:" + hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        old = unique.get(key)
        if old is None or str(row.get("measured_at") or "") > str(old.get("measured_at") or ""):
            unique[key] = row
    return list(unique.values()), len(rows) - len(unique)


def _in_window(row, start, end):
    try:
        day = date.fromisoformat(str(row.get("period", ""))[:10])
    except ValueError:
        return False
    return start <= day <= end


def main():
    if not INGEST_URL or not INGEST_TOKEN:
        print("dashboard_sync=blocked_missing_ingest_configuration")
        return 2
    started_at = datetime.now(timezone.utc).isoformat()
    session = _session()
    try:
        all_rows, invalid_lines, archive_sha = read_source_rows(session)
        rows, latest_period = recent_rows(all_rows)
        if latest_period is None:
            print("dashboard_sync=failed reason=no_valid_periods")
            return 1
        rows_in_window = len(rows)
        rows.extend(invalid_lines)
        rows, deduplicated = deduplicate_rows(rows)
        accepted = review_queued = rejected = 0
        for offset in range(0, len(rows), BATCH_SIZE):
            response = request_with_retry(session, "post",
                INGEST_URL + "/api/archive", json={"rows": rows[offset:offset + BATCH_SIZE]},
                headers={"Authorization": "Bearer " + INGEST_TOKEN}, timeout=(10, 90),
            )
            ack = response.json()
            accepted += int(ack.get("accepted", 0))
            review_queued += int(ack.get("review_queued", 0))
            rejected += int(ack.get("rejected", 0))
            print(f"dashboard_sync_progress={min(offset + BATCH_SIZE, len(rows))}/{len(rows)}")
        report = {
            "source": "github-actions-daily-sync", "archive_sha256": archive_sha,
            "rows_seen": len(all_rows) + len(invalid_lines), "rows_deduplicated": deduplicated,
            "rows_accepted": accepted, "rows_review_queued": review_queued,
            "rows_rejected": rejected, "dry_run": False,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "details": {"latest_period": latest_period, "sync_window_days": SYNC_DAYS,
                        "rows_in_window": rows_in_window, "invalid_lines": len(invalid_lines)},
        }
        audit = request_with_retry(session, "post",
            INGEST_URL + "/api/archive/import-run", json=report,
            headers={"Authorization": "Bearer " + INGEST_TOKEN}, timeout=(10, 90),
        )
        if audit.json().get("recorded") is not True:
            print("dashboard_sync=failed reason=audit_record_missing")
            return 1
        print(f"dashboard_sync=ok period={latest_period} rows={len(rows)} accepted={accepted} review={review_queued} rejected={rejected}")
        return 0
    except Exception as exc:
        # Do not log credentials, raw metrics, archive URLs, or source records.
        print(f"dashboard_sync=failed error_type={type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
