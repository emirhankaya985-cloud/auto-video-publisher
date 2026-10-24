"""One-shot, sanitized failure notification for the daily report workflow."""
import json
import os

from ntfy_notifications import send_ntfy
from telegram_notifications import send_telegram, telegram_configured


def notify_failure():
    if not (os.getenv("NTFY_TOPIC_URL", "").strip() or
            os.getenv("NTFY_TOPIC", "").strip() or telegram_configured()):
        print(json.dumps({"state": "skipped", "reason": "ntfy_secret_missing"}), flush=True)
        return 0

    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    # Only allow the expected GitHub.com host and this known repository.
    click = None
    if (server_url == "https://github.com" and
            repository in {"emirhankaya-AFK/auto-video-publisher",
                           "emirhankaya985-cloud/auto-video-publisher"} and run_id.isdecimal()):
        click = f"https://github.com/{repository}/actions/runs/{run_id}"
    title = "🚨 Gün sonu raporu başarısız"
    body = ("⚠️ Sosyal medya günlük rapor işi başarısız oldu. "
            "Bu bildirim yalnızca iş hatasını belirtir; eksik izlenmeleri sıfır saymayın. "
            "Ayrıntı için GitHub Actions kaydını inceleyin.")
    ntfy_ack = False
    telegram_ack = False
    http_status = None
    if os.getenv("NTFY_TOPIC_URL", "").strip() or os.getenv("NTFY_TOPIC", "").strip():
        try:
            result = send_ntfy(
                title, body, priority=4, tags=["warning"], click=click,
                timeout=20, require_ack=True,
            )
            ntfy_ack = result["server_ack"]
            http_status = result["http_status"]
        except Exception as exc:
            print(json.dumps({"ntfy_error_type": type(exc).__name__}), flush=True)
    if telegram_configured():
        try:
            telegram_ack = send_telegram(title, body)["server_ack"]
        except Exception as exc:
            print(json.dumps({"telegram_error_type": type(exc).__name__}), flush=True)
    state = ("failure_alert_server_acknowledged" if ntfy_ack else
             "failure_alert_telegram_acknowledged" if telegram_ack else
             "failure_alert_not_delivered")
    print(json.dumps({
        "state": state, "server_ack": ntfy_ack, "telegram_server_ack": telegram_ack,
        "http_status": http_status, "phone_delivery_verified": False,
    }, sort_keys=True), flush=True)
    return 0 if (ntfy_ack or telegram_ack) else 1



if __name__ == "__main__":
    raise SystemExit(notify_failure())
