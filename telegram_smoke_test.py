"""Manual Telegram-only smoke test; never publishes video or exposes secrets.

Reports allowlisted diagnostic codes only, never API URLs, tokens, chat IDs
or Telegram response bodies.
"""
import json
import re

from telegram_notifications import send_telegram


def safe_failure_code(exc):
    """Return a fixed error code, ignoring untrusted exception text."""
    if not isinstance(exc, RuntimeError):
        return "unexpected_exception"
    detail = str(exc)
    config_codes = {
        "telegram credentials missing or invalid: bot token missing": "bot_token_missing",
        "telegram credentials missing or invalid: chat id missing": "chat_id_missing",
        "telegram credentials missing or invalid: bot token format": "bot_token_format_invalid",
        "telegram credentials missing or invalid: chat id format": "chat_id_format_invalid",
    }
    if detail in config_codes:
        return config_codes[detail]
    match = re.fullmatch(r"telegram delivery not accepted HTTP ([1-5][0-9]{2})", detail)
    if match:
        status = match.group(1)
        return ("telegram_http_" + status) if status in {
            "400", "401", "403", "404", "409", "429", "500", "502", "503", "504"
        } else "telegram_http_other"
    if detail == "telegram server receipt invalid":
        return "telegram_invalid_response"
    if detail == "telegram server receipt mismatch":
        return "telegram_rejected_response"
    if detail == "telegram delivery not accepted":
        return "telegram_http_other"
    if re.fullmatch(r"telegram delivery failed(?: HTTP [1-5][0-9]{2})? \\([A-Za-z]+\\)", detail):
        return "telegram_connection_failed"
    return "telegram_error"


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
                          "error_code": safe_failure_code(exc),
                          "phone_delivery_verified": False}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
