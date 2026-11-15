"""Owner-local YouTube credential preflight: reuse only a live exact-ID token.

Reads the local authorized-user token in process memory; calls channels.list
GET through the existing conservative verifier. Never writes or prints tokens.
Existing GitHub secrets are not fetched, guessed, or modified by this module.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

from youtube_authorize_channel import ROOT, TOKEN_PATHS
from youtube_readonly_connection import TARGETS, check_channel

MAX_TOKEN_BYTES = 65536
RENEW_REASONS = frozenset({
    "local_token_missing", "not_an_authorized_user_token",
    "invalid_authorized_user_json", "youtube_upload_scope_missing",
    "authorization_or_connection_failed", "youtube_api_rejected",
    "channel_identity_unavailable", "wrong_channel",
})


def inspect_local(target, *, base_dir=ROOT, checker=check_channel):
    if target not in TOKEN_PATHS or target not in TARGETS:
        return {"status": "invalid_target", "renewal_needed": False}
    candidate = Path(base_dir) / TOKEN_PATHS[target]
    if candidate.is_symlink():
        return {"status": "unsafe_local_symlink", "renewal_needed": False}
    if not candidate.is_file():
        return {"status": "local_token_missing", "renewal_needed": True}
    try:
        if candidate.stat().st_size > MAX_TOKEN_BYTES or candidate.stat().st_size == 0:
            return {"status": "invalid_authorized_user_json", "renewal_needed": True}
        raw = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {"status": "local_token_unreadable", "renewal_needed": False}
    if len(raw.encode("utf-8")) > MAX_TOKEN_BYTES:
        return {"status": "invalid_authorized_user_json", "renewal_needed": True}
    env_name, _label, expected_id = TARGETS[target]
    try:
        result = checker(target, environ={env_name: raw})
    except Exception:
        result = {"status": "authorization_or_connection_failed"}
    if (isinstance(result, dict) and result.get("status") == "verified"
            and result.get("channel_id") == expected_id
            and result.get("upload_scope_in_file") is not False):
        return {"status": "verified_local_exact_channel",
                "renewal_needed": False, "channel_id": expected_id}
    status = result.get("status") if isinstance(result, dict) else None
    if status == "verified":
        status = "wrong_channel"
    if status not in RENEW_REASONS:
        status = "authorization_or_connection_failed"
    # Wrong-channel is not a reason to silently overwrite: the owner must
    # explicitly choose the correct Google account in the browser.
    return {"status": status, "renewal_needed": True, "expected_channel_id": expected_id}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(json.dumps({"status": "invalid_target", "renewal_needed": False}))
        return 2
    result = inspect_local(args[0])
    # Only statuses from the allowlist; no raw JSON or Google errors.
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "verified_local_exact_channel" else 1


if __name__ == "__main__":
    raise SystemExit(main())
