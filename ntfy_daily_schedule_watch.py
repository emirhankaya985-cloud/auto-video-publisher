"""Warn if yesterday's 23:59 TRT GitHub daily report never completed.

This code does not publish media, edit Drive, or alter any workflow schedule.
"""
import json
import io
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta, time, timezone

import requests

from ntfy_notifications import send_ntfy
from telegram_notifications import send_telegram, telegram_configured
from notification_dedup import mark_result, should_send


EXPECTED_REPOSITORY = "emirhankaya985-cloud/auto-video-publisher"
REPORT_ARTIFACT = "account-views-comparison"
REPORT_FILENAME = "account_views_comparison.json"
REPORT_MAX_BYTES = 4 * 1024 * 1024


def expected_window(now):
    utc_now = now.astimezone(timezone.utc)
    yesterday_utc = utc_now.date() - timedelta(days=1)
    due = datetime.combine(yesterday_utc, time(20, 59), timezone.utc)
    # The nightly GitHub schedule is 20:59 UTC. Ignore manual tests and
    # unrelated runs. A late run may still qualify only if its own report
    # artifact proves it generated the expected Istanbul report day.
    return due - timedelta(minutes=5), due + timedelta(hours=2)


def _parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def _run_has_expected_report(run, expected_day, *, get, headers):
    """Verify a scheduled run by its report-day artifact, not run time alone."""
    run_id = str(run.get("id", ""))
    if not run_id.isdecimal():
        return False
    api = f"https://api.github.com/repos/{EXPECTED_REPOSITORY}"
    artifacts_response = get(
        f"{api}/actions/runs/{run_id}/artifacts", headers=headers,
        params={"per_page": 100}, timeout=20, allow_redirects=False,
    )
    if artifacts_response.status_code != 200:
        raise requests.RequestException("report_artifact_list_unavailable")
    artifact_payload = artifacts_response.json()
    if not isinstance(artifact_payload, dict):
        raise ValueError("invalid_artifact_list")
    artifacts = artifact_payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("invalid_artifact_list")
    matches = [a for a in artifacts if isinstance(a, dict)
               and a.get("name") == REPORT_ARTIFACT and not a.get("expired")]
    if len(matches) != 1:
        return False
    archive_url = matches[0].get("archive_download_url")
    if not isinstance(archive_url, str) or not archive_url.startswith(
            "https://api.github.com/repos/"):
        raise ValueError("invalid_artifact_url")
    archive_response = get(
        archive_url, headers=headers, timeout=45, allow_redirects=True)
    if archive_response.status_code != 200:
        raise requests.RequestException("report_artifact_download_unavailable")
    archive = archive_response.content
    if len(archive) > REPORT_MAX_BYTES:
        raise ValueError("report_artifact_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            filenames = [name for name in bundle.namelist()
                         if name.rsplit("/", 1)[-1] == REPORT_FILENAME]
            if (len(filenames) != 1
                    or bundle.getinfo(filenames[0]).file_size > REPORT_MAX_BYTES):
                return False
            report = json.loads(bundle.read(filenames[0]).decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (isinstance(report, dict)
            and report.get("day") == expected_day
            and report.get("timezone") == "Europe/Istanbul")


def check_daily_run(*, now=None, get=requests.get, token=None):
    now = now or datetime.now(timezone.utc)
    token = token if token is not None else os.getenv("GITHUB_TOKEN", "")
    if not token:
        return {"status": "audit_unavailable", "reason": "github_token_missing"}
    lower, upper = expected_window(now)
    url = f"https://api.github.com/repos/{EXPECTED_REPOSITORY}/actions/workflows/daily_stats.yml/runs"
    try:
        response = get(
            url, headers={"Authorization": f"Bearer {token}",
                          "Accept": "application/vnd.github+json",
                          "X-GitHub-Api-Version": "2022-11-28"},
            params={"event": "schedule", "per_page": 100},
            timeout=20,
            allow_redirects=False,
        )
        if response.status_code != 200:
            return {"status": "audit_unavailable", "reason": "github_api_unavailable",
                    "http_status": response.status_code}
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
            return {"status": "audit_unavailable", "reason": "invalid_github_response"}
        candidates = []
        expected_day = lower.date().isoformat()
        for run in data["workflow_runs"]:
            if not isinstance(run, dict):
                return {"status": "audit_unavailable", "reason": "invalid_github_response"}
            stamp = _parse_utc(run.get("created_at"))
            if (stamp is not None and lower <= stamp <= upper and
                    run.get("event") == "schedule" and run.get("head_branch") == "main"):
                candidates.append(run)
            elif (stamp is not None and upper < stamp <= now.astimezone(timezone.utc)
                    and run.get("event") == "schedule" and run.get("head_branch") == "main"
                    and run.get("status") == "completed" and run.get("conclusion") == "success"):
                candidates.append(run)
        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        for run in candidates:
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                continue
            if _run_has_expected_report(run, expected_day, get=get, headers=headers):
                return {"status": "healthy", "matched_runs": len(candidates),
                        "verified_report_run_id": str(run["id"]),
                        "report_day": expected_day}
        return {"status": "missing_or_failed", "matched_runs": len(candidates)}
    except requests.RequestException:
        return {"status": "audit_unavailable", "reason": "github_request_failed"}
    except (TypeError, ValueError):
        return {"status": "audit_unavailable", "reason": "invalid_github_response"}


def main():
    verdict = check_daily_run()
    if verdict["status"] == "healthy":
        print(json.dumps({"state": "healthy", "alert_sent": False}), flush=True)
        return 0
    event = os.getenv("GITHUB_EVENT_NAME", "")
    attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    day = datetime.now(timezone.utc).date().isoformat()
    key = f"daily-report-watch|{day}|{verdict['status']}"
    if event and event != "schedule":
        print(json.dumps({"state": verdict["status"], "alert_sent": False,
                          "suppressed_for_event": event}), flush=True)
        return 1
    if attempt != "1":
        print(json.dumps({"state": verdict["status"], "alert_sent": False,
                          "suppressed_retry": True}), flush=True)
        return 1
    try:
        if not should_send(key):
            print(json.dumps({"state": verdict["status"], "alert_sent": False,
                              "duplicate_suppressed": True}), flush=True)
            return 1
    except Exception:
        print(json.dumps({"state": verdict["status"], "alert_sent": False,
                          "dedupe_unavailable": True}), flush=True)
        return 1
    try:
        if verdict["status"] == "missing_or_failed":
            title = "🚨 Günlük rapor otomasyonu eksik"
            message = ("Dünkü 23:59 Türkiye saati günlük raporunun başarılı "
                       "otomatik GitHub Actions çalışması bulunamadı. "
                       "İzlenme raporunun güncelliği doğrulanmadı.")
        else:
            title = "⚠️ Günlük rapor sağlık kontrolü başarısız"
            message = ("Dünkü günlük raporun GitHub Actions durumuna erişilemedi. "
                       "Bu sonuç raporun çalıştığını veya çalışmadığını kanıtlamaz.")
        ntfy_ack = False
        telegram_ack = False
        try:
            receipt = send_ntfy(
                title, message, priority=4, tags=["warning"], timeout=20,
                click=f"https://github.com/{EXPECTED_REPOSITORY}/actions/workflows/daily_stats.yml",
                require_ack=True,
            )
            ntfy_ack = receipt["server_ack"]
        except Exception as exc:
            print(json.dumps({"ntfy_error_type": type(exc).__name__}), flush=True)
        if telegram_configured():
            try:
                receipt = send_telegram(title, message)
                telegram_ack = receipt["server_ack"]
            except Exception as exc:
                print(json.dumps({"telegram_error_type": type(exc).__name__}), flush=True)
        if ntfy_ack or telegram_ack:
            try:
                mark_result(key, True)
            except Exception:
                pass
        print(json.dumps({"state": verdict["status"], "alert_server_ack": ntfy_ack,
                          "telegram_server_ack": telegram_ack,
                          "phone_delivery_verified": False}), flush=True)
        # The watchdog job stays red on a missing nightly report even when
        # the NTFY alert was accepted; ACK is not a successful daily report.
        return 1
    except Exception as exc:
        # Never expose GitHub token, ntfy topic, request URLs or error body.
        print(json.dumps({"state": verdict["status"], "alert_server_ack": False,
                          "error_type": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
