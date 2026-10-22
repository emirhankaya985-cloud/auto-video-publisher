"""Warn if yesterday's 23:59 TRT GitHub daily report never completed.

This code does not publish media, edit Drive, or alter any workflow schedule.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, time, timezone

import requests

from ntfy_notifications import send_ntfy


EXPECTED_REPOSITORY = "emirhankaya-AFK/auto-video-publisher"


def expected_window(now):
    utc_now = now.astimezone(timezone.utc)
    yesterday_utc = utc_now.date() - timedelta(days=1)
    due = datetime.combine(yesterday_utc, time(20, 59), timezone.utc)
    # The nightly GitHub schedule is 20:59 UTC. Ignore manual tests and
    # unrelated runs. A two-hour tolerance allows ordinary queue latency,
    # but a much later success would have measured a different local day.
    return due - timedelta(minutes=5), due + timedelta(hours=2)


def _parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


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
        matching = []
        for run in data["workflow_runs"]:
            if not isinstance(run, dict):
                return {"status": "audit_unavailable", "reason": "invalid_github_response"}
            stamp = _parse_utc(run.get("created_at"))
            if (stamp is not None and lower <= stamp <= upper and
                    run.get("event") == "schedule" and run.get("head_branch") == "master"):
                matching.append(run)
        if any(run.get("status") == "completed" and run.get("conclusion") == "success"
               for run in matching):
            return {"status": "healthy", "matched_runs": len(matching)}
        return {"status": "missing_or_failed", "matched_runs": len(matching)}
    except requests.RequestException:
        return {"status": "audit_unavailable", "reason": "github_request_failed"}
    except (TypeError, ValueError):
        return {"status": "audit_unavailable", "reason": "invalid_github_response"}


def main():
    verdict = check_daily_run()
    if verdict["status"] == "healthy":
        print(json.dumps({"state": "healthy", "alert_sent": False}), flush=True)
        return 0
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
        receipt = send_ntfy(
            title, message, priority=4, tags=["warning"], timeout=20,
            click=f"https://github.com/{EXPECTED_REPOSITORY}/actions/workflows/daily_stats.yml",
            require_ack=True,
        )
        print(json.dumps({"state": verdict["status"], "alert_server_ack": receipt["server_ack"],
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
