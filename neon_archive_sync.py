"""Direct, idempotent GitHub Actions daily archive -> existing social Neon.

No new Render service, media POST, fabricated platform identity or user secrets.
Runs only against a successful main-branch daily-report artifact, and commits
all rows plus its import receipt atomically. Unsupported rows stay in review.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit, unquote

from dashboard_archive_push import (
    API, ARTIFACT_NAME, _session, read_source_rows, recent_rows,
    deduplicate_rows, request_with_retry,
)
from dashboard_server import classify_archive_row

SOURCE = "github-actions-daily-neon-direct"
DAILY_WORKFLOW = "Hesap Bazli Izlenme Raporu"
REPOSITORY = "emirhankaya985-cloud/auto-video-publisher"
SYNC_LOCK = 985162026


def validate_neon_url(url):
    """Reject wrong database or non-Neon/non-TLS credential targets."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        dbname = unquote(parsed.path.lstrip("/"))
        if (parsed.scheme not in {"postgres", "postgresql"}
                or not hostname.endswith(".neon.tech")
                or dbname != "neondb"
                or not parsed.username or not parsed.password):
            raise ValueError("wrong_neon_connection_scope")
    except (TypeError, ValueError):
        raise ValueError("wrong_neon_connection_scope") from None
    return url


def verify_successful_main_run(session, *, run_id, github_token):
    if not str(run_id).isdigit() or not github_token or os.getenv("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("trusted_daily_run_id_required")
    response = request_with_retry(
        session, "get", f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}",
        headers={"Authorization": "Bearer " + github_token,
                 "Accept": "application/vnd.github+json"},
        timeout=(10, 30), allow_redirects=False,
    )
    run = response.json()
    if (not isinstance(run, dict) or str(run.get("id")) != str(run_id)
            or run.get("name") != DAILY_WORKFLOW
            or run.get("head_branch") != "main"
            or run.get("conclusion") != "success"
            or run.get("status") != "completed"):
        raise ValueError("daily_source_not_successful_main_report")
    return True


def normalize_for_neon(rows):
    """Do not convert missing or invalid values into zero or fake identities."""
    good, review = [], []
    for row in rows:
        record, reason = classify_archive_row(row)
        if not reason:
            value = record.get("value")
            if (record.get("status") not in {"ok", "error"}
                    or (record["status"] == "ok" and not record.get("measured_at"))
                    or (isinstance(value, float) and not math.isfinite(value))):
                reason = "invalid_verified_measurement"
        if reason:
            # Review only a redacted fingerprint, never raw text/URLs/tokens.
            raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            review.append((digest, reason, json.dumps({
                "_review_reason": reason, "row_fingerprint": digest,
            }, sort_keys=True)))
            continue
        good.append(record)
    return good, review


def _account_candidates(rows):
    """Most recent account metadata wins, video entity never becomes account ID."""
    accounts = {}
    for row in rows:
        key = row["source_key"]
        item = accounts.get(key)
        if item is None:
            item = {"account": row["account"], "platform": row["platform"],
                    "label": row["source_platform"] if row["source_platform"] != row["platform"] else None,
                    "status": "unknown", "measured_at": None, "last_verified": None,
                    "reason": None, "platform_account_id": None}
            accounts[key] = item
        if row.get("platform_account_id"):
            # Only an explicit platform-issued account ID may be persisted.
            item["platform_account_id"] = row["platform_account_id"]
        if row["entity_type"] != "account":
            continue
        measured = row.get("measured_at")
        if measured and (item["measured_at"] is None or measured >= item["measured_at"]):
            item["measured_at"] = measured
            item["status"] = row["status"]
            item["reason"] = (row.get("reason") if row["status"] != "ok" else None)
        if row["status"] == "ok" and measured:
            if item["last_verified"] is None or measured > item["last_verified"]:
                item["last_verified"] = measured
    return accounts


ACCOUNT_UPSERT = """
INSERT INTO social_accounts(
    account_name,platform,platform_account_id,status,last_verified_at,
    source_reason,source_key,platform_account_label
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT(source_key) DO UPDATE SET
    platform_account_id = COALESCE(EXCLUDED.platform_account_id, social_accounts.platform_account_id),
    status = CASE WHEN EXCLUDED.status='unknown' THEN social_accounts.status ELSE EXCLUDED.status END,
    last_verified_at = GREATEST(social_accounts.last_verified_at, EXCLUDED.last_verified_at),
    source_reason = CASE WHEN EXCLUDED.status='unknown' THEN social_accounts.source_reason ELSE EXCLUDED.source_reason END
RETURNING id
"""

MEASUREMENT_INSERT = """
INSERT INTO metric_snapshots(
    account_id,metric,value,status,reason,measured_at,period_date,source,
    measurement_key,entity_type,entity_id,video_id,post_id
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT(account_id,metric,entity_type,entity_id,measurement_key) DO NOTHING
"""


def ingest(conn, rows, review, *, source_run_id, archive_sha, latest_period,
           rows_seen, deduplicated, days, started):
    """One atomic transaction per source artifact, with replay protection."""
    if len(archive_sha) != 64 or any(c not in "0123456789abcdef" for c in archive_sha):
        raise ValueError("invalid_archive_sha")
    if not rows:
        raise ValueError("no_valid_archive_measurements")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), EXISTS(SELECT 1 FROM pg_stat_ssl WHERE pid=pg_backend_pid() AND ssl)")
            dbname, tls = cur.fetchone()
            if dbname != "neondb" or tls is not True:
                raise ValueError("wrong_neon_database_or_tls")
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (SYNC_LOCK,))
            cur.execute("""SELECT id FROM archive_import_runs
                WHERE source=%s AND archive_sha256=%s
                  AND details->>'source_run_id'=%s AND dry_run=false
                ORDER BY id DESC LIMIT 1""", (SOURCE, archive_sha, str(source_run_id)))
            row = cur.fetchone()
            if row:
                return {"status": "already_synced", "audit_id": row[0], "inserted": 0}
            account_ids = {}
            for key, item in _account_candidates(rows).items():
                cur.execute(ACCOUNT_UPSERT, (item["account"], item["platform"],
                    item["platform_account_id"], item["status"], item["last_verified"],
                    item["reason"], key, item["label"]))
                account_ids[key] = cur.fetchone()[0]
            values = []
            for record in rows:
                measured = record.get("measured_at")
                # The timestamp is part of the original immutable source identity.
                values.append((
                    account_ids[record["source_key"]], record["metric"], record["value"],
                    record["status"], record.get("reason"), measured, record["period"],
                    "github-actions-analytics-archive", measured or record["period"],
                    record["entity_type"], record["entity_id"],
                    record.get("video_id"), record.get("post_id"),
                ))
            cur.executemany(MEASUREMENT_INSERT, values)
            inserted = cur.rowcount
            # The same redacted fingerprint may occur again on retries.
            if review:
                cur.executemany("""INSERT INTO archive_review_queue(row_hash,reason,raw_record)
                    VALUES (%s,%s,%s::jsonb) ON CONFLICT(row_hash) DO NOTHING""", review)
                review_inserted = cur.rowcount
            else:
                review_inserted = 0
            details = {
                "source_run_id": str(source_run_id),
                "latest_period": latest_period, "sync_window_days": days,
                "rows_validated": len(rows), "rows_inserted": inserted,
                "records_reviewed": len(review),
                "verified_platform_account_ids_invented": 0,
            }
            cur.execute("""INSERT INTO archive_import_runs(
                source,archive_sha256,rows_seen,rows_deduplicated,rows_accepted,
                rows_review_queued,rows_rejected,dry_run,details,started_at,completed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,false,%s::jsonb,%s,%s)
                RETURNING id""", (
                    SOURCE,archive_sha,rows_seen,deduplicated,inserted,
                    review_inserted,0,json.dumps(details,sort_keys=True),
                    started,datetime.now(timezone.utc),
            ))
            audit_id = cur.fetchone()[0]
            return {"status": "synced", "audit_id": audit_id,
                    "inserted": inserted, "already_present": len(rows)-inserted,
                    "review": review_inserted, "period": latest_period}


def main():
    url = os.getenv("DASHBOARD_DATABASE_URL", "").strip()
    run_id = os.getenv("SOURCE_RUN_ID", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not url:
        print("neon_direct=blocked_missing_dashboard_database_url", flush=True)
        return 2
    try:
        validate_neon_url(url)
        session = _session()
        verify_successful_main_run(session,run_id=run_id,github_token=token)
        rows, invalid, digest = read_source_rows(session)
        days = max(1, min(30, int(os.getenv("DASHBOARD_SYNC_DAYS", "7"))))
        filtered, latest = recent_rows(rows,days=days)
        filtered.extend(invalid)
        deduped, duplicates = deduplicate_rows(filtered)
        good, review = normalize_for_neon(deduped)
        import psycopg
        with psycopg.connect(url, connect_timeout=10) as conn:
            result = ingest(conn, good, review,source_run_id=run_id,
                archive_sha=digest,latest_period=latest, rows_seen=len(rows)+len(invalid),
                deduplicated=duplicates,days=days,started=datetime.now(timezone.utc))
        print("neon_direct=" + result["status"] +
              " inserted=" + str(result["inserted"]) +
              " audit_id=" + str(result["audit_id"]),flush=True)
        return 0
    except Exception as exc:
        # Never echo psycopg connection errors (they may contain passwords).
        print("neon_direct=failed error_type=" + type(exc).__name__, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
