"""Dry-run or idempotently migrate retained analytics artifacts into private Neon."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone

import requests

from dashboard_server import classify_archive_row

API = "https://api.github.com"
REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
TOKEN = os.getenv("GITHUB_TOKEN", "")
INGEST_URL = os.getenv("DASHBOARD_INGEST_URL", "").rstrip("/")
INGEST_TOKEN = os.getenv("DASHBOARD_INGEST_TOKEN", "")
MODE = os.getenv("DASHBOARD_MIGRATION_MODE", "dry-run").strip().lower()
MAX_RUNS = min(max(int(os.getenv("DASHBOARD_MIGRATION_RUNS", "100")), 1), 100)
REPORT_PATH = os.getenv("DASHBOARD_MIGRATION_REPORT", "migration-report.json")


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


def api_get(session, url):
    response = request_with_retry(session, "get", url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, timeout=(10, 90))
    return response


def _row_key(row):
    fields = ("period", "account", "platform", "entity_type", "entity_id", "metric")
    if all(row.get(field) is not None for field in fields):
        return json.dumps([row.get(field) for field in fields], ensure_ascii=False, separators=(",", ":"))
    return "invalid:" + hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def collect_rows(session):
    url = f"{API}/repos/{REPOSITORY}/actions/workflows/daily_stats.yml/runs?branch=main&status=success&per_page=100"
    runs = api_get(session, url).json().get("workflow_runs", [])[:MAX_RUNS]
    artifacts = []
    for run in runs:
        run_id = run.get("id")
        if not run_id:
            continue
        response = api_get(session, f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts")
        artifacts.extend((run_id, item) for item in response.json().get("artifacts", [])
                         if item.get("name") == "meta-daily-analytics-history" and not item.get("expired"))

    deduplicated = {}
    raw_count = 0
    artifact_digests = []
    reasons, statuses, entities, metrics, source_errors, value_types = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    for run_id, artifact in artifacts:
        archive = api_get(session, artifact["archive_download_url"]).content
        artifact_digests.append(hashlib.sha256(archive).hexdigest())
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            for name in bundle.namelist():
                if not name.endswith("daily_video_views.jsonl"):
                    continue
                for line in bundle.read(name).decode("utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    raw_count += 1
                    try:
                        row = json.loads(line)
                    except ValueError:
                        reasons["invalid_json"] += 1
                        deduplicated[f"invalid-line:{run_id}:{raw_count}"] = {"_review_reason": "invalid_json", "_raw_line": line[:4000]}
                        continue
                    if not isinstance(row, dict):
                        reasons["row_not_object"] += 1
                        row = {"_invalid_value": row, "_review_reason": "row_not_object"}
                    normalized, reason = classify_archive_row(row)
                    if reason:
                        reasons[reason] += 1
                    else:
                        statuses[str(normalized.get("status"))] += 1
                        entities[str(normalized.get("entity_type"))] += 1
                        metrics[str(normalized.get("metric"))] += 1
                        value_types[type(normalized.get("value")).__name__] += 1
                        if normalized.get("status") != "ok":
                            source_errors[str(normalized.get("reason") or
                                               (str(normalized.get("source_api") or "unknown_api") + ":" +
                                                str(normalized.get("source_metric") or "unknown_metric")))] += 1
                    key = _row_key(row)
                    old = deduplicated.get(key)
                    observed = str(row.get("measured_at") or "")
                    if old is None or observed > str(old.get("measured_at") or ""):
                        deduplicated[key] = row
    rows = list(deduplicated.values())
    recognized = 0
    review = 0
    final_reasons = Counter()
    for row in rows:
        if row.get("_review_reason"):
            review += 1
            final_reasons[row["_review_reason"]] += 1
            continue
        _, reason = classify_archive_row(row)
        if reason:
            review += 1
            final_reasons[reason] += 1
        else:
            recognized += 1
    digest = hashlib.sha256("".join(sorted(artifact_digests)).encode()).hexdigest()
    report = {
        "source": "github-actions-history", "archive_sha256": digest,
        "artifacts": len(artifacts), "runs_inspected": len(runs),
        "rows_seen": raw_count, "rows_deduplicated": raw_count - len(rows),
        "unique_rows": len(rows), "recognized_rows": recognized,
        "review_rows": review, "review_reasons": dict(final_reasons),
        "source_validity_statuses": dict(statuses), "entity_types": dict(entities),
        "metrics": dict(metrics), "value_types": dict(value_types),
        "source_error_reasons": dict(source_errors), "started_at": datetime.now(timezone.utc).isoformat(),
    }
    return rows, report


def _post_json(session, url, payload):
    response = request_with_retry(session, "post", url, json=payload,
                            headers={"Authorization": "Bearer " + INGEST_TOKEN},
                            timeout=(10, 90))
    return response.json()


def main():
    if MODE not in {"dry-run", "apply"}:
        print("migration=failed reason=invalid_mode")
        return 2
    if not REPOSITORY or not TOKEN:
        print("migration=failed reason=missing_github_configuration")
        return 2
    if MODE == "apply" and (not INGEST_URL or not INGEST_TOKEN):
        print("migration=blocked_missing_ingest_configuration")
        return 2

    started = datetime.now(timezone.utc).isoformat()
    session = _session()
    rows, report = collect_rows(session)
    report["started_at"] = started
    report["dry_run"] = MODE == "dry-run"
    report["rows_accepted"] = 0
    report["rows_review_queued"] = report["review_rows"]
    report["rows_rejected"] = 0

    if MODE == "apply":
        accepted = review_queued = rejected = 0
        for offset in range(0, len(rows), 300):
            ack = _post_json(session, INGEST_URL + "/api/archive", {"rows": rows[offset:offset + 300]})
            accepted += int(ack.get("accepted", 0))
            review_queued += int(ack.get("review_queued", 0))
            rejected += int(ack.get("rejected", 0))
            print(f"migration_progress={min(offset + 300, len(rows))}/{len(rows)}")
        report.update(rows_accepted=accepted, rows_review_queued=review_queued, rows_rejected=rejected)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        ack = _post_json(session, INGEST_URL + "/api/archive/import-run", report)
        if ack.get("recorded") is not True:
            print("migration=failed reason=audit_record_missing")
            return 1
    else:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()

    with open(REPORT_PATH, "w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, sort_keys=True, indent=2)
    print("migration_report=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
    print("migration=" + ("dry_run_complete" if MODE == "dry-run" else "apply_complete"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Do not log URLs, API tokens, or raw source rows.
        print(f"migration=failed error_type={type(exc).__name__}")
        raise SystemExit(1)
