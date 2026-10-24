"""Manual Telegram-only smoke test; never publishes video or exposes secrets."""
import json
from telegram_notifications import send_telegram


def main():
    try:
        result = send_telegram(
            "🧪 Telegram bağlantı testi",
            "✅ 985 video otomasyonu test bildirimi. Video yayınlanmadı.",
        )
        print(json.dumps({"status": "telegram_server_acknowledged",
                          "server_ack": result["server_ack"],
                          "phone_delivery_verified": False}), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "telegram_test_failed",
                          "error_type": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
