"""Minimal Telegram Bot API notification transport with sanitized errors.

A successful API receipt does not prove the phone displayed a push notification.
"""
import os
import re

import requests

_BOT_TOKEN = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{20,}$")
_CHAT_ID = re.compile(r"^-?[0-9]{4,20}$")
_MAX_TEXT_CHARS = 3900


def telegram_configured():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and
                os.getenv("TELEGRAM_CHAT_ID", "").strip())


def send_telegram(title, message, *, timeout=20, session=requests):
    """One plain-text POST, no redirects/retries, no credential-bearing logs."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not _BOT_TOKEN.fullmatch(token) or not _CHAT_ID.fullmatch(chat_id):
        raise RuntimeError("telegram credentials missing or invalid")
    if not isinstance(title, str) or not isinstance(message, str):
        raise ValueError("telegram title and message must be strings")
    body = (title + "\n\n" + message).strip()
    if not body:
        raise ValueError("telegram message is empty")
    if len(body) > _MAX_TEXT_CHARS:
        # The phone report is already compacted; large publisher diagnostics
        # may be truncated rather than generating a multi-part retry risk.
        body = body[:_MAX_TEXT_CHARS - 30] + "\n… (rapor kısaltıldı)"
    try:
        response = session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": body,
                  "disable_web_page_preview": True},
            timeout=timeout, allow_redirects=False,
        )
        code = response.status_code
        if code != 200:
            raise RuntimeError(
                f"telegram delivery not accepted HTTP {code}"
                if isinstance(code, int) else "telegram delivery not accepted"
            )
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise RuntimeError("telegram server receipt invalid") from None
        if (not isinstance(payload, dict) or payload.get("ok") is not True or
                not isinstance(payload.get("result"), dict) or
                type(payload["result"].get("message_id")) is not int):
            raise RuntimeError("telegram server receipt mismatch")
        return {"http_status": code, "server_ack": True}
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f" HTTP {status}" if isinstance(status, int) else ""
        raise RuntimeError(
            f"telegram delivery failed{suffix} ({type(exc).__name__})"
        ) from None
