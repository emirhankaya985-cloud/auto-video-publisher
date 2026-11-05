"""Opt-in, nonpublishing TikTok Content Posting API readiness check.

Never uploads or posts video. Access credentials must remain in GitHub Secrets.
Creator-info query uses the official read-only-purpose POST endpoint only after
an explicit probe opt-in. Publishing requires a separate audited integration.
"""
import argparse
import json
import os

import requests

CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"


def readiness(*, environ=None):
    env = os.environ if environ is None else environ
    token = bool(str(env.get("TIKTOK_ACCESS_TOKEN", "")).strip())
    open_id = bool(str(env.get("TIKTOK_OPEN_ID", "")).strip())
    approved = str(env.get("TIKTOK_APP_AUDITED", "")).strip().lower() == "true"
    enabled = str(env.get("TIKTOK_PUBLISH_ENABLED", "")).strip().lower() == "true"
    return {
        "platform": "tiktok", "mode": "preflight_only", "publishes": 0,
        "token_configured": token, "open_id_configured": open_id,
        "app_audited_declared": approved, "publishing_requested": enabled,
        "authorization_live_verified": False,
        "blocked": not (token and open_id and approved and enabled),
        "note": "A configured token or flag does not prove video.publish approval, creator settings or domain verification.",
    }


def probe_creator_info(*, session=requests, environ=None):
    """One bounded official creator-info query; never a publish/video/init call."""
    env = os.environ if environ is None else environ
    if str(env.get("TIKTOK_PREFLIGHT_PROBE_ENABLED", "")).lower() != "true":
        raise RuntimeError("tiktok_probe_not_enabled")
    token = str(env.get("TIKTOK_ACCESS_TOKEN", "")).strip()
    if not token or any(c.isspace() for c in token):
        raise RuntimeError("tiktok_credential_missing_or_invalid")
    try:
        response = session.post(
            CREATOR_INFO_URL,
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json; charset=UTF-8"},
            json={}, timeout=20, allow_redirects=False,
        )
        if response.status_code != 200:
            raise RuntimeError("tiktok_creator_info_rejected")
        body = response.json()
        if not isinstance(body, dict) or (body.get("error") or {}).get("code") != "ok":
            raise RuntimeError("tiktok_creator_info_rejected")
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("privacy_level_options"), list):
            raise RuntimeError("tiktok_creator_info_invalid")
        levels = data["privacy_level_options"]
        allow = {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
        if not levels or any(not isinstance(x, str) or x not in allow for x in levels):
            raise RuntimeError("tiktok_creator_info_invalid")
        max_duration = data.get("max_video_post_duration_sec")
        return {"creator_info_verified": True,
                "privacy_options": levels,
                "max_video_post_duration_sec": max_duration if type(max_duration) is int and max_duration > 0 else None,
                "publishes": 0}
    except (requests.RequestException, ValueError, TypeError):
        raise RuntimeError("tiktok_creator_info_unavailable") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-creator", action="store_true")
    args = parser.parse_args()
    result = readiness()
    if args.probe_creator:
        result.update(probe_creator_info())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
