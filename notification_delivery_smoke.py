"""One-run live Telegram + ntfy ACK smoke with no publisher or fake incident.

Only the exact explicitly approved main commit may execute provider POSTs.
This sends one clearly labelled TEST message per configured destination.
No phone-delivery claim. Second same-key attempt is checked in memory/local
dedup only; persistent inter-run dedup still depends on Neon configuration.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from notification_dedup import should_send, mark_result
from telegram_notifications import telegram_configured, send_telegram
from ntfy_notifications import send_ntfy

ID = "task2-notify-safe-smoke-2026-11-14"
OUTPUT = Path("notification-smoke/receipt.json")
COMMIT_MARKER = "ops: safe-once-notification-ack-2026-11-14"


def trusted_run(env):
    return (env.get("GITHUB_REPOSITORY") == "emirhankaya985-cloud/auto-video-publisher"
            and env.get("GITHUB_REF") == "refs/heads/main"
            and env.get("GITHUB_EVENT_NAME") == "push"
            and env.get("GITHUB_RUN_ATTEMPT") == "1"
            and env.get("NOTIFICATION_SMOKE_COMMIT_TITLE") == COMMIT_MARKER
            and str(env.get("GITHUB_RUN_ID", "")).isdecimal())


def deliver_once(name, sender, *, configured=True):
    """One ACK per transport, then prove a duplicate key is suppressed locally."""
    if not configured:
        return {"status": "missing_configuration", "server_ack": False}
    key = ID + "|" + name
    if not should_send(key):
        return {"status": "duplicate_suppressed", "server_ack": False}
    result = {"status": "delivery_failed", "server_ack": False}
    try:
        receipt = sender()
        if not isinstance(receipt, dict) or receipt.get("server_ack") is not True:
            raise RuntimeError("provider_ack_missing")
        code = receipt.get("http_status")
        if type(code) is not int or code < 200 or code >= 300:
            raise RuntimeError("provider_ack_http_invalid")
        result = {"status": "server_ack", "server_ack": True, "http_status": code,
                  "message_id": receipt.get("message_id") if name == "telegram" else None}
    except Exception as exc:
        # Never expose provider response body, token, URL or topic.
        result["error_class"] = type(exc).__name__
    mark_result(key, result["server_ack"], None if result["server_ack"] else "probe_delivery_failed")
    if result["server_ack"]:
        result["second_same_key_blocked"] = not should_send(key)
    return result


def smoke(*, env=None, telegram_sender=None, ntfy_sender=None, strict=True):
    environ = os.environ if env is None else env
    if strict and not trusted_run(environ):
        return {"status": "blocked_untrusted_invocation", "provider_writes": 0}
    title = "[TEST] 985 hata bildirimi teslimat kontrolü"
    body = ("Bu bir TEST uyarısıdır. Gerçek yayın hatası yoktur; "
            "Meta, YouTube ve TikTok için yeni video veya test gönderisi oluşturulmadı. "
            "Aynı hata anahtarı ikinci kez gönderilmez.")
    tg_sender = telegram_sender or (lambda: send_telegram(title, body))
    nf_sender = ntfy_sender or (lambda: send_ntfy(
        title, body, priority=3, tags=["test"], timeout=20, require_ack=True))
    telegram = deliver_once(
        "telegram", tg_sender,
        configured=telegram_configured() if telegram_sender is None
        else True)
    ntfy = deliver_once(
        "ntfy", nf_sender,
        configured=bool(environ.get("NTFY_TOPIC_URL", "").strip() or environ.get("NTFY_TOPIC", "").strip())
        if ntfy_sender is None else True)
    passed = (telegram["status"] == "server_ack" and ntfy["status"] == "server_ack"
              and telegram.get("second_same_key_blocked") is True
              and ntfy.get("second_same_key_blocked") is True)
    return {"status": "both_server_ack" if passed else "incomplete",
            "telegram": telegram, "ntfy": ntfy, "phone_delivery_verified": False,
            "publisher_post_requests": 0, "real_incidents_created": 0}


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    report = smoke()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report.get("status") == "both_server_ack" else 1


if __name__ == "__main__":
    raise SystemExit(main())
