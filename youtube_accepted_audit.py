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
SOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
MAX_UPLOAD_PAGES = 100


def load_archived_state():
    # Use the publisher's existing authenticated GitHub artifact reader,
    # without creating or replacing any state or upload intent.
    from public_link_runtime import restore
    return restore()


def verify_accepted(entry, *, channel_check=check_channel, youtube_build=build):
    """One YouTube videos.list GET; no videos.insert or metadata writes."""
    route = entry.get("route")
    post_id = entry.get("post_id")
    # A positively bound pre-upload source hold is not a missing Google ID.
    # Never contact Google or release the hold merely to classify it.
    source = entry.get("source_id")
    if (route in ROUTES and entry.get("status") == "held" and post_id is None
            and entry.get("verification_status") == "source_local_preparation_failed"
            and entry.get("external_post_attempted") is False
            and isinstance(source, str) and SOURCE_ID.fullmatch(source)
            and entry.get("channel_id") == ROUTES[route][2]):
        return "youtube_source_local_preparation_held"
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
        if status.get("uploadStatus") in {"failed", "rejected", "deleted"}:
            return "youtube_upload_" + status["uploadStatus"]
        if status.get("privacyStatus") == "public" and status.get("uploadStatus") == "processed":
            return "public_processed_verified"
        return "youtube_processing_or_visibility_pending"
    except Exception:
        # Google response bodies and OAuth exception texts may contain secrets.
        return "youtube_read_or_auth_failed"


def verify_uncertain(key, entry, *, channel_check=check_channel, youtube_build=build):
    """Find exact source-marker evidence using GETs; never release an intent.

    Absence, incomplete history and duplicate markers all remain unresolved.
    A unique match is evidence for later reconciliation, not a retry permit.
    """
    result = {"video_id": None, "status": "invalid_uncertain_source_binding",
              "requires_reconciliation": True}
    route, source_id = entry.get("route"), entry.get("source_id")
    if (not isinstance(route, str) or route not in ROUTES
            or not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id)
            or key != f"{route}:{source_id}" or entry.get("status") != "uncertain"
            or entry.get("post_id") is not None):
        return result
    target, secret, expected = ROUTES[route]
    if entry.get("channel_id") != expected:
        return dict(result, status="channel_binding_mismatch")
    if not os.getenv(secret, "").strip():
        return dict(result, status="missing_youtube_secret")
    marker = "[avp-source:" + key + "]"
    try:
        channel = channel_check(target)
        if channel.get("status") != "verified" or channel.get("channel_id") != expected:
            return dict(result, status="youtube_identity_unverified")
        credentials = Credentials.from_authorized_user_info(json.loads(os.environ[secret]))
        youtube = youtube_build("youtube", "v3", credentials=credentials, cache_discovery=False)
        payload = youtube.channels().list(part="contentDetails", mine=True).execute()
        rows = payload.get("items") if isinstance(payload, dict) else None
        if (not isinstance(rows, list) or len(rows) != 1
                or not isinstance(rows[0], dict) or rows[0].get("id") != expected):
            return dict(result, status="youtube_identity_unverified")
        playlist = rows[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not isinstance(playlist, str) or not playlist.strip():
            return dict(result, status="youtube_upload_history_invalid")
        token, seen, matches = None, set(), set()
        for _ in range(MAX_UPLOAD_PAGES):
            args = {"part": "snippet", "playlistId": playlist, "maxResults": 50}
            if token:
                args["pageToken"] = token
            payload = youtube.playlistItems().list(**args).execute()
            rows = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                return dict(result, status="youtube_upload_history_invalid")
            for row in rows:
                snippet = row.get("snippet") if isinstance(row, dict) else None
                if not isinstance(snippet, dict):
                    return dict(result, status="youtube_upload_history_invalid")
                description = snippet.get("description", "")
                if not isinstance(description, str):
                    return dict(result, status="youtube_upload_history_invalid")
                if marker not in description.splitlines():
                    continue
                post_id = snippet.get("resourceId", {}).get("videoId")
                if not isinstance(post_id, str) or not VIDEO_ID.fullmatch(post_id):
                    return dict(result, status="youtube_upload_history_invalid")
                matches.add(post_id)
            if len(matches) > 1:
                return dict(result, status="uncertain_marker_ambiguous")
            token = payload.get("nextPageToken")
            if token is None or token == "":
                break
            if not isinstance(token, str) or token in seen:
                return dict(result, status="youtube_upload_history_incomplete")
            seen.add(token)
        else:
            return dict(result, status="youtube_upload_history_incomplete")
        if not matches:
            return dict(result, status="uncertain_marker_not_found")
        post_id = next(iter(matches))
        payload = youtube.videos().list(part="snippet,status", id=post_id).execute()
        rows = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return dict(result, status="youtube_video_unavailable")
        row, snippet = rows[0], rows[0].get("snippet")
        if (row.get("id") != post_id or not isinstance(snippet, dict)
                or snippet.get("channelId") != expected
                or not isinstance(snippet.get("description"), str)
                or marker not in snippet["description"].splitlines()):
            return dict(result, status="youtube_source_identity_mismatch")
        result["video_id"] = post_id
        status = row.get("status") or {}
        if status.get("uploadStatus") in {"failed", "rejected", "deleted"}:
            return dict(result, status="youtube_upload_" + status["uploadStatus"])
        if status.get("privacyStatus") == "public" and status.get("uploadStatus") == "processed":
            return dict(result, status="uncertain_marker_public_processed_verified")
        return dict(result, status="uncertain_marker_processing_or_visibility_pending")
    except Exception:
        return dict(result, status="youtube_read_or_auth_failed")


def audit(state, *, verifier=verify_accepted, uncertain_verifier=verify_uncertain):
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError("invalid publisher state")
    entries = state.get("youtube_entries", {})
    if not isinstance(entries, dict):
        raise ValueError("invalid youtube entries")
    results = []
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ValueError("invalid archived entry")
        if entry.get("status") == "uncertain":
            result = uncertain_verifier(key, entry)
            source_id = entry.get("source_id")
            route = entry.get("route")
            valid_source = isinstance(source_id, str) and SOURCE_ID.fullmatch(source_id)
            bound_key = (isinstance(route, str) and route in ROUTES and valid_source
                         and key == f"{route}:{source_id}")
            results.append({
                **result,
                "route": route if isinstance(route, str) and route in ROUTES else "unknown",
                "ledger_key": key if bound_key else None,
                "source_id": source_id if valid_source else None,
            })
            continue
        if entry.get("status") not in {"accepted", "held"}:
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
        "accepted_checked": sum(row.get("status") == "accepted" for row in entries.values()),
        "held_checked": sum(row.get("status") == "held" for row in entries.values()),
        "uncertain_checked": sum(row.get("status") == "uncertain" for row in entries.values()),
        "uncertain_marker_public_processed_verified": sum(
            x["status"] == "uncertain_marker_public_processed_verified" for x in results),
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
