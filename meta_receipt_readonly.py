"""No-write follow-up for a provider-accepted Gönle Düşen Facebook Reel.

A provider acknowledgement is not a visible post. A bounded Page /videos
list is not proof of deletion. Only a matching video GET with original owner,
exact caption, positive video length and original publication date resolves
the existing archived provider ID. Never POST, delete or reset a ledger.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = "emirhankaya985-cloud/auto-video-publisher"
ROUTE = "gonle"
SOURCE = "1P-QucF7ZWzZWXwLrFIZ0QlZ7cgUfdKu8"
SOURCE_SHA = "f4a3ed568ebc8ad5ef479857f7d91e7583527abf13f577f823ec03d16a5ca6f6"
RUN_ID = "42885778218"
FACEBOOK_ID = "1107092405268327"
INSTAGRAM_ID = "18122024707754598"
ROOT = Path("meta-receipt-readonly")


def verified_original(state):
    records = state.get("entries") if isinstance(state, dict) else None
    if not isinstance(records, dict):
        raise RuntimeError("publisher_ledger_unavailable")
    items = {}
    for platform, post_id in (("facebook", FACEBOOK_ID), ("instagram", INSTAGRAM_ID)):
        row = records.get(f"{ROUTE}:{platform}:{SOURCE}")
        if (not isinstance(row, dict)
                or row.get("route") != ROUTE or row.get("platform") != platform
                or row.get("status") != "done" or row.get("file") != "181.mp4"
                or row.get("source_sha256") != SOURCE_SHA
                or str(row.get("run_id")) != RUN_ID
                or str(row.get("post_id")) != post_id
                or not isinstance(row.get("publish_caption"), str)
                or not row["publish_caption"].strip()):
            raise RuntimeError("original_platform_receipt_changed_or_missing")
        items[platform] = row
    if items["facebook"]["publish_caption"] != items["instagram"]["publish_caption"]:
        raise RuntimeError("original_cross_platform_caption_mismatch")
    return items


def exact_facebook_video_proof(payload, *, post_id, page_id, caption):
    """Strict proof for an existing FB video ID, without accepting a caption alias."""
    if not isinstance(payload, dict):
        return False
    if (str(payload.get("id") or "") != post_id
            or not isinstance(payload.get("from"), dict)
            or str(payload["from"].get("id") or "") != page_id
            or payload.get("description") != caption):
        return False
    # Other Graph nodes can also expose id/description. Require video length.
    length = payload.get("length")
    if isinstance(length, bool) or not isinstance(length, (int, float, str)):
        return False
    try:
        if not 0 < float(length) < 10800:
            return False
    except (ValueError, TypeError):
        return False
    created = payload.get("created_time")
    try:
        timestamp = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.date().isoformat() != "2026-11-10":
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def assess(state, *, page_id, facebook_rows, instagram_rows, direct_payload=None):
    items = verified_original(state)
    if not str(page_id).isdecimal() or not isinstance(facebook_rows, list) or not isinstance(instagram_rows, list):
        raise RuntimeError("account_or_provider_history_unverified")
    fb = items["facebook"]
    ig = items["instagram"]
    exact_fb = [x for x in facebook_rows if isinstance(x, dict)
                and str(x.get("id") or "") == FACEBOOK_ID
                and x.get("description") == fb["publish_caption"]]
    exact_ig = [x for x in instagram_rows if isinstance(x, dict)
                and str(x.get("id") or "") == INSTAGRAM_ID
                and x.get("caption") == ig["publish_caption"]
                and x.get("media_type") == "VIDEO"]
    fb_proof = bool(exact_fb) or exact_facebook_video_proof(
        direct_payload, post_id=FACEBOOK_ID, page_id=page_id, caption=fb["publish_caption"])
    return {
        "schema": 1,
        "mode": "read_only_no_meta_writes",
        "source": "gonle_181_mp4_original_verified_2026_11_10",
        "facebook": {
            "post_id": FACEBOOK_ID,
            "status": "verified" if fb_proof else "held_provider_visibility_or_object_unverified",
            "proof": ("exact_page_video_history" if exact_fb else
                      "exact_provider_video_id_owner_caption_length_date" if fb_proof
                      else "not_observed_in_bounded_history_no_repost"),
        },
        "instagram": {
            "post_id": INSTAGRAM_ID,
            "status": "verified" if len(exact_ig) == 1 else "held_provider_visibility_unverified",
            "proof": "exact_owned_video_history" if len(exact_ig) == 1 else "not_observed_no_repost",
        },
        "posts_created": 0,
        "state_mutations": 0,
    }


def read_direct_video(page, post_id):
    """GET only. Failure returns no proof, not permission to republish."""
    import requests
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    from publisher_recovery import read_with_retry
    try:
        response = read_with_retry(
            requests.get,
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{post_id}",
            headers={"Authorization": "Bearer " + page["page_token"]},
            params={"fields": "id,description,from,length,created_time"},
            timeout=25, allow_redirects=False, graph_read=True,
        )
        try:
            body = response.json()
        finally:
            response.close()
        return body if response.status_code == 200 and isinstance(body, dict) and "error" not in body else None
    except (OSError, ValueError, TypeError, requests.RequestException):
        return None


def main():
    if (os.getenv("GITHUB_REPOSITORY") != REPO
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("PUBLISH_ACCOUNT_SCOPE") != ROUTE):
        raise RuntimeError("readonly_account_scope_unverified")
    from meta_auth_loader import load_meta_auth
    from public_link_runtime import restore, graph_rows, ROUTES
    state = restore()
    verified_original(state)
    pages = [p for p in load_meta_auth()["pages"] if p["page_name"] == ROUTES[ROUTE][1]]
    if len(pages) != 1 or not str(pages[0].get("page_id") or "").isdecimal():
        raise RuntimeError("gonle_identity_unverified")
    page = pages[0]
    facebook = graph_rows(page, "facebook")
    instagram = graph_rows(page, "instagram")
    raw = read_direct_video(page, FACEBOOK_ID) if not any(str(x.get("id")) == FACEBOOK_ID for x in facebook) else None
    report = assess(state, page_id=page["page_id"],
                    facebook_rows=facebook, instagram_rows=instagram, direct_payload=raw)
    unresolved = [row for row in state["entries"].values()
                  if row.get("status") in {"intent", "uncertain", "held"}]
    report["unresolved_backlog"] = {"count": len(unresolved),
                                     "by_route": dict(Counter(r.get("route", "unknown") for r in unresolved)),
                                     "all_intents_preserved": True}
    report["checked_at"] = datetime.now().astimezone().isoformat()
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"gonle_facebook": report["facebook"]["status"],
                      "gonle_instagram": report["instagram"]["status"],
                      "unresolved_count": len(unresolved),
                      "no_meta_writes": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
