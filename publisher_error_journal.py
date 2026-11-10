"""Safe structured error journal for Meta publisher GitHub Actions runs.

Capture EACH detected failure/blocked publication, even when the overall
workflow returns success. Never persist untrusted raw provider responses,
signed URLs, secrets, request headers, tokens or video contents. Workflow job
logs remain the diagnostic source for the original exception traceback.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from api_capacity_guard import safe_recovery_action

JOURNAL = Path("link-runtime/errors.jsonl")

_ALLOWED_STAGE = {
    "drive_inventory", "meta_account", "meta_history", "shared_account_history",
    "txt_caption", "toonzone_cover", "source_video", "instagram_preparation",
    "facebook_publish", "instagram_publish", "workflow_verify", "workflow_plan",
    "workflow_publish", "telegram_notification", "ntfy_notification",
    "state_restore", "previous_intent_hold", "planning_queue", "other",
    "publication_preflight", "youtube_prepare", "youtube_publish",
}
_ALLOWED_REASON = {
    "drive_unavailable", "meta_account_missing", "meta_history_unavailable",
    "txt_unavailable", "cover_missing", "source_or_cover_preparation_failed",
    "media_preparation_failed", "credentials_or_permissions", "rate_limit",
    "meta_server_or_network", "invalid_media_or_graph_request",
    "unclassified_upload_result", "workflow_step_failed",
    "notification_delivery_failed", "state_restore_failed",
    "unreconciled_previous_intent", "no_eligible_content", "other",
    "intent_validation_failed", "existing_container_reconciliation_failed",
    "missing_secret", "youtube_publication_unverified",
    "visual_duplicate_review", "source_content_changed",
    "film_part8_strict_recheck_held", "film_part8_source_is_prior_part_duplicate",
}


def safe_label(value, limit=100):
    """Keep only non-sensitive identifiers; strip arbitrary paths/URLs."""
    text = str(value or "").strip()
    if text.startswith("/") or "\\" in text or "://" in text or "=" in text:
        return "[redacted]"
    return "".join(ch for ch in text if ch.isalnum() or ch in " _.-")[:limit]


def http_failure_class(status):
    """Conservative machine-readable diagnosis; not permission to retry POST."""
    if type(status) is not int:
        return "unverified"
    if status == 400:
        return "request_or_media_validation"
    if status == 401:
        return "authentication"
    if status == 403:
        return "permission_denied"
    if status == 429:
        return "rate_limited"
    if 500 <= status <= 599:
        return "provider_unavailable"
    return "unverified"


def error_event(stage, reason, *, route="", platform="", video="",
                error=None, status="", safe_to_retry=False):
    if stage not in _ALLOWED_STAGE or reason not in _ALLOWED_REASON:
        raise ValueError("Unregistered error stage/reason")
    exc = error
    event = {
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": safe_label(os.getenv("GITHUB_RUN_ID", ""), 35),
        "stage": stage, "reason": reason,
        "route": safe_label(route, 45),
        "platform": platform if platform in ("facebook", "instagram", "threads", "youtube") else "unknown",
        "video": safe_label(video, 125),
        "outcome": "held" if status != "uncertain" else "uncertain",
        "retry_policy": ("pre_upload_only" if safe_to_retry
                         else "never_blindly_retry_meta_post"),
        "error_type": safe_label(type(exc).__name__ if exc else "", 70),
        "http_failure_class": http_failure_class(getattr(exc, "http_status", None)),
        "recovery_action": safe_recovery_action(
            "meta_publish" if stage in {"facebook_publish", "instagram_publish"}
            else "read_only_get" if stage in {"meta_history", "shared_account_history"}
            else "ffmpeg_prepare" if stage == "instagram_preparation"
            else "manual_review", previous_attempt=(status == "uncertain"))["action"],
    }
    for name, attr in (("http_status", "http_status"), ("graph_code", "code"),
                       ("graph_subcode", "subcode")):
        number = getattr(exc, attr, None)
        if type(number) is int and 0 <= number <= 99999999:
            event[name] = number
    stage_value = getattr(exc, "stage", None)
    if isinstance(stage_value, str):
        event["meta_stage"] = safe_label(stage_value, 80)
    return event


def record_error(stage, reason, *, route="", platform="", video="",
                 error=None, status="", safe_to_retry=False, path=JOURNAL):
    event = error_event(stage, reason, route=route, platform=platform, video=video,
                        error=error, status=status, safe_to_retry=safe_to_retry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event


def read_errors(path=JOURNAL, *, run_id=None):
    if not path.exists():
        return []
    output = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("Invalid structured error event")
        if run_id is None or event.get("run_id") == str(run_id):
            output.append(event)
    return output
