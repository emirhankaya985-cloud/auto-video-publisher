"""Read-only Telegram Bot API verification; never send a message or log credentials."""
import json
import os
import sys

import requests

from telegram_notifications import _BOT_TOKEN, _CHAT_ID


def diagnose(*, token=None, chat_id=None, get=requests.get):
    token = (token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = (chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chat_id:
        return {"status": "blocked", "code": "telegram_secrets_missing"}
    if not _BOT_TOKEN.fullmatch(token):
        return {"status": "blocked", "code": "telegram_bot_token_format"}
    if not _CHAT_ID.fullmatch(chat_id):
        return {"status": "blocked", "code": "telegram_chat_id_format"}
    for method in ("getMe", "getChat"):
        try:
            res = get(
                f"https://api.telegram.org/bot{token}/{method}",
                params={"chat_id": chat_id} if method == "getChat" else {},
                timeout=20, allow_redirects=False,
            )
        except requests.RequestException:
            return {"status": "unknown", "code": "telegram_transport_unavailable"}
        if res.status_code != 200:
            code = res.status_code
            code = code if isinstance(code, int) and 400 <= code <= 599 else "other"
            return {"status": "blocked", "code": f"telegram_{method.lower()}_http_{code}"}
        try:
            payload = res.json()
        except (ValueError, TypeError):
            return {"status": "unknown", "code": "telegram_response_invalid"}
        if not isinstance(payload, dict) or payload.get("ok") is not True or not isinstance(payload.get("result"), dict):
            return {"status": "unknown", "code": f"telegram_{method.lower()}_receipt_invalid"}
    return {"status": "healthy", "code": "bot_and_chat_readable", "message_sent": False}


def main():
    result = diagnose()
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
