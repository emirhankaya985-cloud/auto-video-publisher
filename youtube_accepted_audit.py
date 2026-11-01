"""Independently verify archived accepted YouTube uploads; never upload videos.

This runs even while Meta's User token is expired. The publisher's historical
state is read-only, and a fixed-schema receipt records what Google confirms.
"""
import json
import os
import re
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from youtube_main_bridge import ROUTES
from youtube_readonly_connection import check_channel

REPO = "emirhankaya985-cloud/auto-video-publisher"
REPORT = Path("youtube-accepted-verification.json")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def load_archived_state():
    # Use the publisher's existing authenticated GitHub artifact reader,
    # without creating or replacing any state or upload intent.
    from public_link_runtime import restore
    return restore()


def verify_accepted(entry, *, channel_check=check_channel, youtube_build=build):
    """One YouTube videos.list GET; no videos.insert or metadata writes."""
    route = entry.get("route")
    post_id = entry.get("post_id")
    if route not in ROUTES or not isinstance(post_id, str) or not VIDEO_ID.fullmatch(post_id):
        return "invalid_archived_identity"
    target, secret, expected = ROUTES[route]
    if entry.get("channel_id") != expected:
        return "channel_binding_mismatch"
    if not os.getenv(secret, "").strip():
        return "missing_youtube_secret"
    try:
        channel = channel_check(target)
        if channel.get("status") != "verified" or channel.get("channel_id") != expected:
            return "youtube_identity_unverified"
        data = json.loads(os.environ[secret])
        credentials = Credentials.from_authorized_user_info(data)
        youtube = youtube_build("youtube", "v3", credentials=credentials, cache_discovery=False)
        response = youtube.videos().list(part="snippet,status", id=post_id).execute()
        rows = response.get("items") if isinstance(response, dict) else None
        if not isinstance(rows, list) or len(rows) != 1:
            return "youtube_video_unavailable"
        row = rows[0]
        if row.get("id") != post_id or (row.get("snippet") or {}).get("channelId") != expected:
            return "youtube_video_identity_mismatch"
        status = row.get("status") or {}
        if status.get("privacyStatus") == "public" and status.get("uploadStatus") == "processed":
            return "public_processed_verified"
        return "youtube_processing_or_visibility_pending"
    except Exception:
        # Google response bodies and OAuth exception texts may contain secrets.
        return "youtube_read_or_auth_failed"


def audit(state, *, verifier=verify_accepted):
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError("invalid publisher state")
    entries = state.get("youtube_entries", {})
    if not isinstance(entries, dict):
        raise ValueError("invalid youtube entries")
    results = []
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ValueError("invalid archived entry")
        if entry.get("status") != "accepted":
            continue
        reason = verifier(entry)
        results.append({
            "route": entry.get("route") if entry.get("route") in ROUTES else "unknown",
            "video_id": entry.get("post_id") if isinstance(entry.get("post_id"), str)
                        and VIDEO_ID.fullmatch(entry["post_id"]) else None,
            "status": reason,
        })
    confirmed = sum(x["status"] == "public_processed_verified" for x in results)
    return {
        "status": "all_accepted_verified" if confirmed == len(results) else "pending_confirmation",
        "accepted_checked": len(results),
        "public_processed_verified": confirmed,
        "unverified": len(results) - confirmed,
        "posts": results,
        "uploads_attempted": 0,
        "publication_state_modified": False,
    }


def main():
    if os.getenv("GITHUB_REPOSITORY") != REPO:
        result = {"status": "wrong_repository", "uploads_attempted": 0}
        code = 1
    else:
        try:
            result = audit(load_archived_state())
            code = 0 if result["status"] == "all_accepted_verified" else 1
        except Exception:
            result = {"status": "archived_state_unavailable", "uploads_attempted": 0}
            code = 1
    REPORT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
