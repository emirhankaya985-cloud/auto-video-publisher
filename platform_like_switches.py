"""Explicit per-platform like switches for the read-only engagement audit.

A switch never authorizes a like. Unsupported or prohibited write paths fail
closed even when a value is changed to true.
"""
import json
import os
from pathlib import Path

FLAGS = {
    "x": "X_AUTO_LIKE_ENABLED",
    "youtube": "YOUTUBE_AUTO_LIKE_ENABLED",
    "instagram": "INSTAGRAM_AUTO_LIKE_ENABLED",
}
REASONS = {
    "x": "x_automation_rules_prohibit_automated_likes",
    "youtube": "coordinated_automated_engagement_not_supported",
    "instagram": "instagram_official_api_has_no_media_like_write",
}


def status(environ=None):
    environ = os.environ if environ is None else environ
    platforms = {}
    for platform, key in FLAGS.items():
        raw = environ.get(key, "false")
        platforms[platform] = {
            "flag": key,
            "configured_value": raw,
            "enabled": False,
            "mode": "manual_review_only",
            "reason": REASONS[platform] if raw == "true" else "disabled_by_configuration",
        }
    return {"schema_version": 1, "like_writes_performed": 0, "platforms": platforms}


def write_status(path, environ=None):
    result = status(environ)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    write_status("cross-engagement/platform-like-status.json")
