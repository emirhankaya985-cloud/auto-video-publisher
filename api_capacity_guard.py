"""Redacted, GET-only Meta usage and auth safety checks.

Opaque Meta user tokens have no locally inspectable expiration timestamp.
A proven Graph OAuth 190/463 identifies expiry; otherwise do NOT invent one.
"""
import json


def capacity_from_headers(headers):
    rows = {}
    for label, key in (("app", "X-App-Usage"), ("page", "X-Page-Usage")):
        try:
            raw = headers.get(key, "")
            parsed = json.loads(raw) if isinstance(raw, str) and len(raw) <= 8192 else {}
            if not isinstance(parsed, dict):
                continue
            values = [n for field, n in parsed.items()
                      if field in {"call_count", "total_time", "total_cputime"}
                      and type(n) in {int, float} and 0 <= n <= 100]
            if values:
                rows[label] = max(values)
        except (ValueError, TypeError):
            continue
    if not rows:
        return {"status": "unavailable", "usage_percent": None}
    maximum = max(rows.values())
    return {"status": "hold" if maximum >= 95 else
            "warning" if maximum >= 80 else "within_observed_header",
            "usage_percent": maximum}


def classify_auth_response(http_status, code, subcode):
    """Return a non-secret warning, never claim token lifetime is known."""
    if code == 190 and subcode == 463:
        return {"status": "blocked", "reason": "token_expired", "safe_to_publish": False}
    if code == 190 or http_status in {401, 403} or code in {10, 200}:
        return {"status": "blocked", "reason": "token_or_permission_error",
                "safe_to_publish": False}
    if code in {4, 17, 32, 613} or http_status == 429:
        return {"status": "blocked", "reason": "rate_limit",
                "safe_to_publish": False}
    return {"status": "unknown", "reason": "no_expiry_evidence",
            "safe_to_publish": None}


def safe_recovery_action(stage, *, status=None, previous_attempt=False):
    """Narrow recovery table; never auto-repeat a potentially completed write."""
    if stage in {"drive_download", "ffmpeg_prepare", "read_only_get"} and not previous_attempt:
        return {"action": "bounded_read_or_local_retry", "may_repost": False}
    if stage in {"meta_publish", "instagram_media_publish", "youtube_insert",
                 "telegram_send", "meta_upload"} or previous_attempt:
        return {"action": "hold_and_reconcile", "may_repost": False}
    if status in {401, 403, 429, 500, 502, 503, 504}:
        return {"action": "hold_and_alert", "may_repost": False}
    return {"action": "manual_review", "may_repost": False}
