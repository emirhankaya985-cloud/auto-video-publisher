"""Film Part 17 cross-checks archived source against live IG captions, GET-only.

A caption match does NOT prove video bytes or original upload provenance.
A missing historical caption does NOT prove no publication. No rescue unlock.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from expired_ig_container_recovery import (
    FILM17_SOURCE_ID, FILM17_FILENAME, FILM17_CAPTION_HASH,
    FILM17_SOURCE_SHA256, FILM17_CONTAINER_ID, FILM17_ORIGIN_RUN,
)
from toonzone_direct_media_verifier import caption_digest, read_json
from public_link_runtime import graph_rows, timestamp

FILM_PAGE_ID = "1239298989276639"
FILM_IG_ID = "17841477990224124"
FB_PART17_ID = "1435010394958762"
OUTPUT = Path("film17-readonly/result.json")


def archive_binding(state):
    rows = state.get("entries") if isinstance(state, dict) else None
    if not isinstance(rows, dict):
        raise ValueError("invalid_film_state")
    row = rows.get(f"film:instagram:{FILM17_SOURCE_ID}")
    if not isinstance(row, dict):
        raise ValueError("film17_source_ledger_missing")
    failure = row.get("failure", {})
    if (row.get("route") != "film" or row.get("platform") != "instagram"
            or row.get("file") != FILM17_FILENAME
            or row.get("source_sha256") != FILM17_SOURCE_SHA256
            or row.get("caption_hash") != FILM17_CAPTION_HASH
            or caption_digest(row.get("publish_caption")) != FILM17_CAPTION_HASH
            or row.get("run_id") != FILM17_ORIGIN_RUN
            or row.get("status") != "uncertain" or row.get("post_id")
            or not isinstance(failure, dict)
            or failure.get("container_id") != FILM17_CONTAINER_ID
            or failure.get("http_status") != 400
            or failure.get("safe_to_repost") is not False):
        raise ValueError("film17_immutable_proof_mismatch")
    return row


def reconcile(state, page, *, get=None, rows=None):
    """No state changes or publish release, even if no match is found."""
    from requests import get as default_get
    get = get or default_get
    archive_binding(state)
    if (not isinstance(page, dict)
            or str(page.get("page_id")) != FILM_PAGE_ID
            or str(page.get("instagram_id")) != FILM_IG_ID
            or not page.get("page_token")):
        raise ValueError("film17_owner_not_pinned")
    container, err = read_json(
        get, "https://graph.facebook.com/v24.0/" + FILM17_CONTAINER_ID,
        page["page_token"], "status_code,status")
    container_status = container.get("status_code") if container else "unavailable"
    if container_status not in {"EXPIRED", "PUBLISHED", "FINISHED", "ERROR", "IN_PROGRESS", "unavailable"}:
        container_status = "unrecognized"
    if rows is None:
        rows = graph_rows(page, "instagram")
    if not isinstance(rows, list):
        raise ValueError("film17_history_unavailable")
    matches = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("media_type") != "VIDEO" or not str(item.get("id") or "").isdecimal():
            continue
        if caption_digest(item.get("caption")) != FILM17_CAPTION_HASH:
            continue
        try:
            created = timestamp(item)
        except (ValueError, RuntimeError, TypeError):
            continue
        if created.date().isoformat() < "2026-11-12":
            continue
        matches.append(item)
    # Direct per-media GET confirms owner of a unique caption candidate,
    # but cannot match original uploaded video bytes. Never promote the state.
    candidate_id = matches[0]["id"] if len(matches) == 1 else None
    owner_verified = False
    direct_failure = None
    if candidate_id:
        media, error = read_json(
            get, "https://graph.facebook.com/v24.0/" + str(candidate_id),
            page["page_token"], "id,username,caption,timestamp,media_type")
        if error:
            direct_failure = error.get("reason")
        elif (str(media.get("id")) == str(candidate_id)
                and str(media.get("username") or "").casefold() ==
                str(page.get("instagram_username") or "").casefold()
                and bool(page.get("instagram_username"))
                and media.get("media_type") == "VIDEO"
                and caption_digest(media.get("caption")) == FILM17_CAPTION_HASH):
            owner_verified = True
        else:
            direct_failure = "media_binding_mismatch"
    return {
        "schema": 1,
        "status": ("uncertain_single_matching_live_caption" if owner_verified
                   else "uncertain_multiple_caption_matches" if len(matches) > 1
                   else "uncertain_direct_media_unverified" if candidate_id
                   else "uncertain_no_matching_live_caption"),
        "source_name": FILM17_FILENAME, "source_id": FILM17_SOURCE_ID,
        "facebook_post_id_original": FB_PART17_ID,
        "instagram_post_id_archived": None,
        "instagram_candidate_post_id": str(candidate_id) if owner_verified else None,
        "live_caption_candidates": len(matches),
        "live_unique_media_owner_verified": owner_verified,
        "direct_read_failure": direct_failure,
        "old_container_status": container_status,
        "container_read_error": (err or {}).get("reason"),
        "original_source_binary_verified_by_meta": False,
        "reupload_authorized": False,
        "recovery_switch_enabled": False,
        "provider_writes": 0,
        "state_mutations": 0,
    }


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        if (os.getenv("GITHUB_REPOSITORY") != "emirhankaya985-cloud/auto-video-publisher"
                or os.getenv("GITHUB_REF") != "refs/heads/main"
                or os.getenv("PUBLISH_ACCOUNT_SCOPE") != "film"):
            raise ValueError("trusted_readonly_scope_required")
        from meta_auth_loader import load_meta_auth
        from meta_page_token_health import check_page
        from public_link_runtime import restore
        pages = load_meta_auth()["pages"]
        chosen = [p for p in pages if str(p.get("page_id")) == FILM_PAGE_ID
                  and str(p.get("instagram_id")) == FILM_IG_ID
                  and check_page(p).get("status") == "identity_verified"]
        if len(chosen) != 1:
            raise ValueError("film17_ig_identity_unverified")
        report = reconcile(restore(), chosen[0])
    except Exception as exc:
        report = {"schema": 1, "status": "blocked", "reason": type(exc).__name__,
                  "provider_writes": 0, "state_mutations": 0,
                  "reupload_authorized": False}
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report.get("status", "").startswith("uncertain_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
