"""Minimal Telegram Bot API notification transport with sanitized errors.

A successful API receipt does not prove the phone displayed a push notification.
"""
import os
import re
from html import escape

import requests

_BOT_TOKEN = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{20,}$")
_CHAT_ID = re.compile(r"^-?[0-9]{4,20}$")
_MAX_TEXT_CHARS = 3900


def telegram_configured():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and
                os.getenv("TELEGRAM_CHAT_ID", "").strip())


def send_telegram(title, message, *, timeout=20, session=requests, parse_mode=None):
    """One bounded POST, no redirects/retries, no credential-bearing logs."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        raise RuntimeError("telegram credentials missing or invalid: bot token missing")
    if not chat_id:
        raise RuntimeError("telegram credentials missing or invalid: chat id missing")
    if not _BOT_TOKEN.fullmatch(token):
        raise RuntimeError("telegram credentials missing or invalid: bot token format")
    if not _CHAT_ID.fullmatch(chat_id):
        raise RuntimeError("telegram credentials missing or invalid: chat id format")
    if not isinstance(title, str) or not isinstance(message, str):
        raise ValueError("telegram title and message must be strings")
    if parse_mode not in (None, "HTML"):
        raise ValueError("unsupported Telegram parse mode")
    body = ((escape(title) if parse_mode else title) + "\n\n" + message).strip()
    if not body:
        raise ValueError("telegram message is empty")
    if len(body) > _MAX_TEXT_CHARS:
        if parse_mode:
            raise ValueError("Telegram HTML report must be split before sending")
        # The phone report is already compacted; large publisher diagnostics
        # may be truncated rather than generating a multi-part retry risk.
        body = body[:_MAX_TEXT_CHARS - 30] + "\n… (rapor kısaltıldı)"
    if parse_mode and len(body.encode("utf-16-le")) // 2 > _MAX_TEXT_CHARS:
        raise ValueError("Telegram HTML report exceeds character budget")
    payload = {"chat_id": chat_id, "text": body, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        response = session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
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
