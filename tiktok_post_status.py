"""Read-only-purpose TikTok Content Posting API reconciliation and metadata gates.

This module NEVER initializes a new post, uploads video, or grants OAuth scopes.
The official status/fetch endpoint is POST for a read operation. Call only for
an already archived publish_id, under an explicitly enabled probe. Never treat
PUBLISH_COMPLETE alone as evidence of a publicly visible post ID.
"""
from __future__ import annotations

import os
import re

import requests

STATUS_FETCH_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
STATUSES = frozenset({"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX",
                      "PUBLISH_COMPLETE", "FAILED"})
PRIVACY_LEVELS = frozenset({"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS",
                            "FOLLOWER_OF_CREATOR", "SELF_ONLY"})
# Publish ids are opaque, e.g. v_pub_file~v2-1.123456789. Do not accept URLs.
PUBLISH_ID = re.compile(r"[A-Za-z0-9_.~-]{1,64}\Z", re.ASCII)
SAFE_FAILURES = frozenset({"file_format_check_failed", "duration_check_failed",
    "frame_rate_check_failed", "picture_size_check_failed", "internal",
    "video_pull_failed", "photo_pull_failed", "publish_cancelled", "auth_removed",
    "spam_risk_too_many_posts", "spam_risk_user_banned_from_posting",
    "spam_risk_text", "spam_risk"})


def validate_draft(*, title, privacy_level, creator_info, duration_sec):
    """Check draft against fresh creator info; this NEVER authorizes a publish.

    The platform requires a user-chosen privacy setting (no default), an
    editable caption and an explicit user consent/preview outside this module.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("tiktok_caption_required")
    if len(title.encode("utf-16-le")) // 2 > 2200:
        raise ValueError("tiktok_caption_exceeds_2200_utf16_units")
    if not isinstance(creator_info, dict):
        raise ValueError("tiktok_creator_info_required")
    options = creator_info.get("privacy_options")
    if (not isinstance(options, list) or not options
            or any(x not in PRIVACY_LEVELS for x in options)):
        raise ValueError("tiktok_privacy_options_unverified")
    if privacy_level not in options:
        raise ValueError("tiktok_privacy_selection_required")
    allowed_duration = creator_info.get("max_video_post_duration_sec")
    if (type(duration_sec) not in (int, float) or duration_sec <= 0
            or type(allowed_duration) is not int or allowed_duration <= 0):
        raise ValueError("tiktok_duration_unverified")
    if duration_sec > allowed_duration:
        raise ValueError("tiktok_duration_exceeds_creator_limit")
    return {"metadata_valid": True, "publishes": 0,
            "requires_editable_preview_and_explicit_user_consent": True}


def fetch_status(publish_id, *, session=requests, environ=None):
    """Read the status of an existing ID. No uploads, no provider error echo."""
    env = os.environ if environ is None else environ
    if str(env.get("TIKTOK_STATUS_PROBE_ENABLED", "")).strip().lower() != "true":
        raise RuntimeError("tiktok_status_probe_not_enabled")
    if not isinstance(publish_id, str) or not PUBLISH_ID.fullmatch(publish_id):
        raise ValueError("tiktok_publish_id_invalid")
    token = str(env.get("TIKTOK_ACCESS_TOKEN", "")).strip()
    if not token or any(ch.isspace() for ch in token):
        raise RuntimeError("tiktok_credential_missing_or_invalid")
    try:
        response = session.post(
            STATUS_FETCH_URL,
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json; charset=UTF-8"},
            json={"publish_id": publish_id}, timeout=20, allow_redirects=False)
        if response.status_code != 200:
            # Never copy a response body, credentials, or a signed URL into logs.
            raise RuntimeError("tiktok_status_api_rejected")
        body = response.json()
    except requests.RequestException:
        raise RuntimeError("tiktok_status_network_failed") from None
    except (TypeError, ValueError):
        raise RuntimeError("tiktok_status_response_invalid") from None
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        raise RuntimeError("tiktok_status_response_invalid")
    if body["error"].get("code") != "ok":
        raise RuntimeError("tiktok_status_api_rejected")
    data = body.get("data")
    if not isinstance(data, dict) or data.get("status") not in STATUSES:
        raise RuntimeError("tiktok_status_response_invalid")
    ids = data.get("publicaly_available_post_id", [])  # Official API's spelling.
    if not isinstance(ids, list):
        raise RuntimeError("tiktok_status_response_invalid")
    normalized = []
    for post_id in ids:
        if (type(post_id) not in (str, int) or isinstance(post_id, bool)
                or not str(post_id).isascii() or not str(post_id).isdecimal()
                or not 1 <= len(str(post_id)) <= 20 or int(post_id) <= 0):
            raise RuntimeError("tiktok_status_response_invalid")
        if str(post_id) not in normalized:
            normalized.append(str(post_id))
    status = data["status"]
    if status != "PUBLISH_COMPLETE" and normalized:
        raise RuntimeError("tiktok_status_response_invalid")
    failure = data.get("fail_reason")
    return {
        "publish_id": publish_id, "status": status,
        "public_post_ids": normalized,
        "public_post_id_verified": status == "PUBLISH_COMPLETE" and bool(normalized),
        "failure_reason": failure if status == "FAILED" and failure in SAFE_FAILURES else (
            "unclassified_failure" if status == "FAILED" else None),
        "provider_writes": 0,
    }
