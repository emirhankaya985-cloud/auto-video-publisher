"""Read-only, redacted Meta credential routing diagnostic.

Intended for trusted GitHub main pushes. Never POST, never print a token or
Meta's raw error body. If a saved Page-token inventory is present, check it
independently of the User token so a rejected /me/accounts cannot hide it.
"""
import json
import os
import requests


def probe_user_token(token, *, get=None):
    if not isinstance(token, str) or not token.strip():
        return {"status": "blocked", "reason": "missing_user_token"}
    get = get or requests.get
    try:
        response = get(
            "https://graph.facebook.com/v24.0/me/accounts",
            headers={"Authorization": "Bearer " + token.strip()},
            params={"fields": "id", "limit": 1}, timeout=20,
            allow_redirects=False,
        )
        body = response.json()
    except Exception:
        # Provider error text might contain signed URLs or the input token.
        return {"status": "blocked", "reason": "read_failure"}
    if not isinstance(body, dict):
        return {"status": "blocked", "reason": "invalid_graph_response"}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    if response.status_code != 200 or err:
        code = err.get("code")
        subcode = err.get("error_subcode")
        subcode = subcode if type(subcode) is int else None
        reason = (
            "expired_user_token" if code == 190 and subcode == 463 else
            "app_or_session_invalid" if code == 190 and subcode in {458, 459, 460, 467} else
            "user_token_rejected" if code == 190 else
            "permission_or_policy_denied" if response.status_code in {401, 403} else
            "graph_read_failed"
        )
        return {"status": "blocked", "reason": reason,
                "http_status": response.status_code if type(response.status_code) is int else None,
                "graph_code": code if type(code) is int else None,
                "graph_subcode": subcode}
    if not isinstance(body.get("data"), list) or not body["data"]:
        return {"status": "blocked", "reason": "no_managed_pages_returned"}
    return {"status": "read_verified", "reason": None,
            "publishing_tested": False}


def probe_page_inventory(raw, *, check=None):
    if not isinstance(raw, str) or not raw.strip():
        return {"status": "not_configured"}
    try:
        from meta_page_token_health import audit
        payload = json.loads(raw)
        result = audit(payload) if check is None else check(payload)
        rows = result.get("accounts", [])
        return {"status": result.get("status"),
                "verified_count": sum(row.get("status") == "identity_verified"
                                      for row in rows),
                "expected_accounts": 7,
                "publishing_tested": False}
    except Exception:
        return {"status": "blocked", "reason": "invalid_saved_page_configuration"}


def main():
    user = probe_user_token(os.environ.get("META_ACCESS_TOKEN", ""))
    saved = probe_page_inventory(os.environ.get("META_AUTH_JSON", ""))
    report = {"user_access": user, "saved_page_access": saved,
              "meta_writes": 0, "tokens_logged": False}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if user["status"] == "read_verified" or saved["status"] == "identity_verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
