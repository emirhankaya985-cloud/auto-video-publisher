"""GitHub secret-backed, read-only YouTube channel identity check.

Never uploads videos, edits Drive, or writes Google resources. Never logs OAuth
credentials, authorization URLs, token contents, or API response bodies.
"""
import json
import os
import sys

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession

TARGETS = {
    "channel1": ("TOKEN_CHANNEL1_JSON", "Tarladaki Fasulye", None),
    "channel2": ("TOKEN_CHANNEL2_JSON", "Beyinsiz Penguen", None),
    "daily_laugh": ("TOKEN_DAILY_LAUGH_LAB_JSON", "Daily Laugh Lab", "UCF4KwI3alXzlExviMFmmJAA"),
}
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def check_channel(target, *, environ=None, session_factory=AuthorizedSession):
    environ = os.environ if environ is None else environ
    if target not in TARGETS:
        return {"status": "invalid_target"}
    env_name, expected_title, expected_id = TARGETS[target]
    raw = environ.get(env_name, "")
    if not raw.strip():
        return {"status": "missing_github_secret", "secret_name": env_name}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"status": "invalid_authorized_user_json"}
    if not isinstance(data, dict):
        return {"status": "invalid_authorized_user_json"}
    required = ("client_id", "client_secret", "refresh_token", "token_uri")
    # Report *only fixed field names* and a recognized JSON type. Never
    # return the secret's field values, raw JSON, token or OAuth URI.
    missing = [key for key in required
               if not isinstance(data.get(key), str) or not data[key]]
    if missing:
        kind = ("oauth_client_json" if "installed" in data or "web" in data
                else "incomplete_authorized_user_json")
        return {"status": "not_an_authorized_user_token",
                "json_kind": kind, "missing_fields": missing}
    scopes = data.get("scopes")
    if isinstance(scopes, (list, tuple)) and YOUTUBE_UPLOAD_SCOPE not in scopes:
        return {"status": "youtube_upload_scope_missing"}
    try:
        credentials = Credentials.from_authorized_user_info(data)
        session = session_factory(credentials)
        response = session.get(CHANNELS_URL, params={"part": "id,snippet", "mine": "true"},
                               timeout=20, allow_redirects=False)
        if response.status_code != 200:
            code = response.status_code
            return {"status": "youtube_api_rejected",
                    "http_status": code if isinstance(code, int) else "unknown"}
        payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            return {"status": "channel_identity_unavailable"}
        channel = items[0]
        title = (channel.get("snippet") or {}).get("title")
        identifier = channel.get("id")
        if not isinstance(title, str) or not title or not isinstance(identifier, str) or not identifier:
            return {"status": "channel_identity_unavailable"}
        matched = (identifier == expected_id if expected_id else
                   title.strip().casefold() == expected_title.casefold())
        return {"status": "verified" if matched else "wrong_channel",
                "channel_title": title, "channel_id": identifier,
                "expected_label": expected_title,
                "upload_scope_in_file": YOUTUBE_UPLOAD_SCOPE in scopes if isinstance(scopes, list) else "unknown"}
    except Exception as exc:
        # Google API and OAuth errors may include secret-bearing URLs or
        # request data. Only disclose the fixed exception class name.
        return {"status": "authorization_or_connection_failed", "error_type": type(exc).__name__}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    result = check_channel(args[0] if len(args) == 1 else "")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
