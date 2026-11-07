"""GET-only owner YouTube OAuth/channel preflight across four configured channels.

This never inserts, modifies, deletes, or retries videos. No raw Google error
bodies, tokens, URLs, or OAuth credentials are ever written to the artifact.
"""
import json
from pathlib import Path

from youtube_readonly_connection import TARGETS, check_channel

REPORT = Path("youtube-authorization-readonly.json")
SAFE_STATUSES = {
    "verified", "missing_github_secret", "invalid_authorized_user_json",
    "not_an_authorized_user_token", "youtube_upload_scope_missing",
    "youtube_api_rejected", "channel_identity_unavailable", "wrong_channel",
    "authorization_or_connection_failed", "invalid_target",
}


def probe_all(*, checker=check_channel):
    checked = []
    for route, (_, _title, expected_id) in TARGETS.items():
        try:
            evidence = checker(route)
            if not isinstance(evidence, dict):
                raise ValueError("invalid_channel_response")
            status = evidence.get("status")
            if status not in SAFE_STATUSES:
                raise ValueError("unexpected_channel_status")
            verified = status == "verified" and evidence.get("channel_id") == expected_id
            item = {"route": route,
                    "status": "verified" if verified else (
                        "channel_identity_mismatch" if status == "verified" else status),
                    "expected_channel_id_matched": verified}
            code = evidence.get("http_status")
            if type(code) is int and 400 <= code <= 599:
                item["http_status"] = code
            scope = evidence.get("upload_scope_in_file")
            if scope is True or scope is False:
                item["upload_scope_in_file"] = scope
            else:
                item["upload_scope_in_file"] = "N/A"
        except Exception:
            item = {"route": route, "status": "authorization_or_connection_failed",
                    "expected_channel_id_matched": False,
                    "upload_scope_in_file": "N/A"}
        checked.append(item)
    return {"status": "all_four_verified" if all(r["expected_channel_id_matched"]
             for r in checked) else "auth_or_identity_incomplete",
            "accounts_checked": len(checked), "accounts": checked,
            "youtube_upload_requests": 0, "provider_writes": 0,
            "cannot_prove_insert_permission_without_a_real_upload": True}


def main():
    report = probe_all()
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "all_four_verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
