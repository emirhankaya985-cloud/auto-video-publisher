"""One-shot ntfy health smoke. Sends a test message and prints no private topics."""
import json
import os
from datetime import datetime, timezone

from ntfy_notifications import send_ntfy


def main():
    run = os.getenv("GITHUB_RUN_ID", "unknown")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not (os.getenv("NTFY_TOPIC_URL", "").strip() or os.getenv("NTFY_TOPIC", "").strip()):
        print(json.dumps({"status": "blocked", "reason": "ntfy_secret_missing"}), flush=True)
        return 1
    try:
        accepted = send_ntfy(
            "🧪 NTFY bağlantı doğrulaması",
            f"✅ GitHub Actions test bildirimi. Run: {run}. UTC: {stamp}. "
            "Bu bir testtir, sosyal medya paylaşımı yapılmadı.",
            priority=3, timeout=20, require_ack=True,
        )
        print(json.dumps({
            "status": "ntfy_server_acknowledged",
            "http_status": accepted["http_status"],
            "server_ack": accepted["server_ack"],
            "phone_delivery_verified": False,
            "run_id": run,
        }, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        # No exception bodies, secret topic, server response or request URLs.
        print(json.dumps({
            "status": "failed", "error_type": type(exc).__name__,
            "phone_delivery_verified": False,
            "run_id": run,
        }, sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
