"""One-shot, sanitized failure notification for the daily report workflow."""
import json
import os

from ntfy_notifications import send_ntfy


def notify_failure():
    if not (os.getenv("NTFY_TOPIC_URL", "").strip() or os.getenv("NTFY_TOPIC", "").strip()):
        print(json.dumps({"state": "skipped", "reason": "ntfy_secret_missing"}), flush=True)
        return 0

    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    # Only allow the expected GitHub.com host and this known repository.
    click = None
    if (server_url == "https://github.com" and
            repository == "emirhankaya-AFK/auto-video-publisher" and run_id.isdecimal()):
        click = f"https://github.com/{repository}/actions/runs/{run_id}"
    try:
        result = send_ntfy(
            "🚨 Gün sonu raporu başarısız",
            "⚠️ Sosyal medya günlük rapor işi başarısız oldu. "
            "Bu bildirim yalnızca iş hatasını belirtir; eksik izlenmeleri sıfır saymayın. "
            "Ayrıntı için GitHub Actions kaydını inceleyin.",
            priority=4,
            tags=["warning"],
            click=click,
            timeout=20,
            require_ack=True,
        )
        print(json.dumps({
            "state": "failure_alert_server_acknowledged",
            "server_ack": result["server_ack"],
            "http_status": result["http_status"],
            "phone_delivery_verified": False,
        }, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        # Never print exception text; it may contain a private topic.
        print(json.dumps({
            "state": "failure_alert_not_delivered",
            "error_type": type(exc).__name__,
            "phone_delivery_verified": False,
        }, sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(notify_failure())
