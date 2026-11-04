"""Bounded read-only preview for the Daily Laugh Lab accounts.

The public receipt holds counts and fingerprints of exact ID sets, never
individual content IDs, titles, URLs, captions or OAuth data.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from meta_auth_loader import load_meta_auth
from publisher_recovery import read_with_retry
from threads_accounts import threads_account_config
from youtube_readonly_connection import TARGETS

REPO = "emirhankaya985-cloud/auto-video-publisher"
PAGE_NAME = "Daily Laugh Lab"
THREADS_USERNAME = "dail.ylaughlab"
META_BASE = "https://graph.facebook.com/v24.0"
THREADS_BASE = "https://graph.threads.com/v1.0"
YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
YOUTUBE_DELETE_SCOPES = {f"https://www.googleapis.com/auth/{scope}" for scope in
                         ("youtube", "youtube.force-ssl", "youtubepartner")}


class PreviewError(RuntimeError):
    def __init__(self, reason, *, status=None):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def read_json(get, url, *, headers=None, graph=False, **params):
    response = read_with_retry(get, url, params=params, headers=headers,
                               allow_redirects=False, timeout=20, graph_read=graph)
    if response.status_code != 200:
        raise PreviewError("api_read_rejected", status=response.status_code)
    data = response.json()
    if not isinstance(data, dict) or "error" in data:
        raise PreviewError("invalid_api_response")
    return data


def list_all(fetch, *, graph):
    """Read fixed-endpoint pages, never follow server-supplied next URLs."""
    rows, cursors = [], set()
    cursor = None
    for _ in range(100):
        params = {("after" if graph else "pageToken"): cursor} if cursor else {}
        body = fetch(**params)
        batch = body.get("data" if graph else "items")
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise PreviewError("invalid_inventory_rows")
        rows.extend(batch)
        if graph:
            paging = body.get("paging", {})
            if not isinstance(paging, dict):
                raise PreviewError("invalid_pagination")
            if not paging.get("next"):
                return rows
            cursor = (paging.get("cursors") or {}).get("after")
        else:
            cursor = body.get("nextPageToken")
            if cursor is None:
                return rows
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise PreviewError("inventory_pagination_incomplete")
        cursors.add(cursor)
    raise PreviewError("inventory_page_limit")


def id_summary(ids, valid):
    if not all(isinstance(value, str) and valid(value) for value in ids):
        raise PreviewError("invalid_content_id")
    unique_ids = sorted(set(ids))
    return {"count": len(unique_ids), "ids_sha256": hashlib.sha256(
        json.dumps(unique_ids, separators=(",", ":")).encode()).hexdigest()}


def graph_reader(base, token):
    if not token or any(character.isspace() for character in token):
        raise PreviewError("missing_or_invalid_credential")

    def get(path, **params):
        return read_json(requests.get, f"{base}/{path}", graph=True,
                         headers={"Authorization": f"Bearer {token}"}, **params)
    return get


def graph_edge(get, path, fields):
    return list_all(lambda **params: get(path, fields=fields, limit=100, **params), graph=True)


def read_permissions():
    get = graph_reader(META_BASE, os.environ.get("META_ACCESS_TOKEN", "").strip())
    rows = graph_edge(get, "me/permissions", "permission,status")
    granted = {row.get("permission") for row in rows if row.get("status") == "granted"}
    return {scope: scope in granted for scope in
            ("pages_manage_posts", "instagram_basic", "instagram_manage_contents")}


def daily_page():
    pages = [row for row in load_meta_auth()["pages"] if row.get("page_name") == PAGE_NAME]
    if len(pages) != 1:
        raise PreviewError("daily_laugh_page_identity_unverified")
    page = pages[0]
    get = graph_reader(META_BASE, page["page_token"])
    identity = get("me", fields="id,name")
    if identity.get("name") != PAGE_NAME or str(identity.get("id")) != page["page_id"]:
        raise PreviewError("daily_laugh_page_identity_unverified")
    return page, get


def facebook(page, get):
    account = page["page_id"]
    def owned_edge(edge, valid_id):
        rows = graph_edge(get, f"{account}/{edge}", "id,from{id}")
        if any(str((row.get("from") or {}).get("id")) != account for row in rows):
            raise PreviewError("facebook_content_owner_unverified")
        return id_summary([row.get("id") for row in rows], valid_id)

    posts = checked(lambda: owned_edge("published_posts", lambda value: bool(
        re.fullmatch(r"[0-9]+(?:_[0-9]+)?", value))))
    # A Page video can also be represented in published_posts. Keep counts separate.
    videos = checked(lambda: owned_edge("videos", str.isdecimal))
    complete = all(row["status"] == "visible_edges_exhausted" for row in (posts, videos))
    return {"account_id": account, "page_name": PAGE_NAME,
            "status": "visible_edges_exhausted" if complete else "incomplete",
            "published_posts": posts, "page_videos": videos,
            "edge_counts_may_overlap": True}


def instagram(page, get):
    account = str(page.get("instagram_id") or "")
    username = page.get("instagram_username")
    if not account.isdecimal() or not username:
        raise PreviewError("instagram_account_unlinked")
    identity = get(account, fields="id,username")
    if str(identity.get("id")) != account or identity.get("username") != username:
        raise PreviewError("instagram_identity_unverified")
    rows = graph_edge(get, f"{account}/media", "id")
    return {"account_id": account, "username": username, "profile_media": id_summary(
        [row.get("id") for row in rows], str.isdecimal), "stories_included": False}


def threads():
    account = threads_account_config("daily_laugh", require_enabled=False, require_media=False)
    if account.username.casefold() != THREADS_USERNAME:
        raise PreviewError("threads_configured_identity_mismatch")
    get = graph_reader(THREADS_BASE, account.token)
    identity = get("me", fields="id,username")
    identifier = str(identity.get("id") or "")
    if (not identifier.isdecimal() or str(identity.get("username")).casefold() != THREADS_USERNAME
            or account.expected_user_id and identifier != account.expected_user_id):
        raise PreviewError("threads_identity_unverified")
    rows = graph_edge(get, "me/threads", "id")
    return {"account_id": identifier, "username": THREADS_USERNAME,
            "profile_posts": id_summary([row.get("id") for row in rows], str.isdecimal),
            "replies_included": False, "threads_delete_grant_verified": None}


def youtube():
    variable, _, expected_id = TARGETS["daily_laugh"]
    raw = os.environ.get(variable, "").strip()
    if not raw:
        raise PreviewError("missing_or_invalid_credential")
    info = json.loads(raw)
    credentials = Credentials.from_authorized_user_info(info)
    session = AuthorizedSession(credentials)

    def get(path, **params):
        return read_json(session.get, f"{YOUTUBE_BASE}/{path}", **params)

    channels = get("channels", part="id,contentDetails", mine="true").get("items")
    if not isinstance(channels, list) or len(channels) != 1 or channels[0].get("id") != expected_id:
        raise PreviewError("youtube_channel_identity_unverified")
    uploads = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    rows = list_all(lambda **params: get("playlistItems", part="contentDetails",
                    playlistId=uploads, maxResults=50, **params), graph=False)
    ids = [(row.get("contentDetails") or {}).get("videoId") for row in rows]
    summary = id_summary(ids, VIDEO_ID.fullmatch)
    ids = sorted(set(ids))
    privacy = Counter()
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        items = get("videos", part="snippet,status", id=",".join(batch)).get("items")
        if not isinstance(items, list) or sorted(row.get("id", "") for row in items) != batch:
            raise PreviewError("youtube_video_details_incomplete")
        for row in items:
            if (row.get("snippet") or {}).get("channelId") != expected_id:
                raise PreviewError("youtube_video_owner_unverified")
            visibility = (row.get("status") or {}).get("privacyStatus")
            if visibility not in {"public", "unlisted", "private"}:
                raise PreviewError("youtube_visibility_unverified")
            privacy[visibility] += 1
    configured = info.get("scopes")
    scopes = set(configured.split()) if isinstance(configured, str) else set(configured or ())
    return {"account_id": expected_id, "uploads": summary,
            "visibility": {name: privacy[name] for name in ("public", "unlisted", "private")},
            "delete_scope_declared": bool(scopes & YOUTUBE_DELETE_SCOPES) if configured else None}


def checked(fetch):
    try:
        return {"status": "visible_edges_exhausted", **fetch()}
    except PreviewError as exc:
        return {"status": "incomplete", "reason": exc.reason, "http_status": exc.status}
    except Exception as exc:
        return {"status": "incomplete", "error_type": type(exc).__name__}


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPO or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Preview requires the production repository main branch.")
    try:
        page, get = daily_page()
    except Exception as exc:
        error = {"status": "incomplete", "reason": "daily_laugh_page_identity_unverified",
                 "error_type": type(exc).__name__}
        meta = {"facebook": error, "instagram": error}
    else:
        meta = {"facebook": checked(lambda: facebook(page, get)),
                "instagram": checked(lambda: instagram(page, get))}
    result = {"account": PAGE_NAME, "run_id": os.environ.get("GITHUB_RUN_ID"),
              "checked_at": datetime.now(timezone.utc).isoformat(), "deletions_attempted": 0,
              "platforms": {**meta, "youtube": checked(youtube), "threads": checked(threads)},
              "meta_user_permissions": checked(read_permissions)}
    result["all_visible_edges_exhausted"] = all(
        row["status"] == "visible_edges_exhausted" for row in result["platforms"].values())
    summary = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    Path("daily-laugh-deletion-preview.json").write_text(summary + "\n", encoding="utf-8")
    print(summary, flush=True)
    return 0 if result["all_visible_edges_exhausted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
