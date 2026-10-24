"""Read-only daily health check for the 985 Meta-only publisher.

A green CI run is NOT evidence of a published video. This watchdog only checks
whether scheduled publishing jobs actually completed successfully. It cannot
claim individual posts or their view counts.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from ntfy_notifications import send_ntfy

EXPECTED_REPO = "emirhankaya985-cloud/auto-video-publisher"
WORKFLOW = "public_link_schedule.yml"


def parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def check_publisher(*, now=None, token=None, get=requests.get):
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    token = token if token is not None else os.getenv("GITHUB_TOKEN", "")
    if not token:
        return {"status": "unknown", "reason": "github_token_missing"}
    try:
        response = get(
            f"https://api.github.com/repos/{EXPECTED_REPO}/actions/workflows/{WORKFLOW}/runs",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            params={"event": "schedule", "branch": "main", "per_page": 100},
            timeout=20, allow_redirects=False,
        )
        if response.status_code != 200:
            return {"status": "unknown", "reason": "github_api_unavailable",
                    "http_status": response.status_code}
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
            return {"status": "unknown", "reason": "invalid_github_response"}
        recent = []
        for run in payload["workflow_runs"]:
            if not isinstance(run, dict):
                return {"status": "unknown", "reason": "invalid_github_response"}
            stamp = parse_utc(run.get("created_at"))
            if (stamp and now - timedelta(hours=3) <= stamp <= now
                    and run.get("event") == "schedule"
                    and run.get("head_branch") == "main"
                    and run.get("path") == f".github/workflows/{WORKFLOW}"):
                recent.append((stamp, run))
        recent.sort(key=lambda row: row[0], reverse=True)
        if not recent:
            return {"status": "unhealthy", "reason": "no_recent_scheduled_runs", "recent_runs": 0}
        completed = [r for _, r in recent if r.get("status") == "completed"]
        if len(completed) >= 2 and all(r.get("conclusion") == "failure" for r in completed[:2]):
            return {"status": "unhealthy", "reason": "consecutive_failures",
                    "recent_runs": len(recent)}
        if not any(r.get("status") == "completed" and r.get("conclusion") == "success"
                   for _, r in recent):
            return {"status": "unhealthy", "reason": "no_recent_success",
                    "recent_runs": len(recent)}
        return {"status": "healthy", "recent_runs": len(recent)}
    except requests.RequestException:
        return {"status": "unknown", "reason": "github_request_failed"}
    except (TypeError, ValueError):
        return {"status": "unknown", "reason": "invalid_github_response"}


def main():
    verdict = check_publisher()
    print(json.dumps(verdict, sort_keys=True), flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write(f"### Meta-only publisher health\n\n"
                         f"- Result: {verdict['status']}\n"
                         f"- Reason: {verdict.get('reason', 'n/a')}\n"
                         f"- This is an Actions health check, not proof of individual published posts.\n")
    if verdict["status"] == "healthy":
        return 0
    if os.getenv("NTFY_TOPIC", "").strip() or os.getenv("NTFY_TOPIC_URL", "").strip():
        try:
            send_ntfy(
                "🚨 985 Meta video yayıncısı kontrolü",
                "985 hesabındaki otomatik Meta yayınlarının son 3 saatte "
                "başarıyla tamamlandığı doğrulanamadı. "
                f"Durum: {verdict['status']}; neden: {verdict.get('reason', 'unknown')}. "
                "Bu bir otomasyon arızası uyarısıdır, paylaşım sonucu değildir.",
                priority=4, tags=["warning"], timeout=20, require_ack=True,
                click=f"https://github.com/{EXPECTED_REPO}/actions/workflows/{WORKFLOW}",
            )
            print('{"alert": "ntfy_server_ack", "phone_delivery_verified": false}', flush=True)
        except Exception as exc:
            # A private ntfy topic or request URL must never appear in logs.
            print(json.dumps({"alert": "failed", "error_type": type(exc).__name__}), flush=True)
    else:
        print('{"alert": "ntfy_not_configured"}', flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
