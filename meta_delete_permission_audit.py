"""Read-only audit of Meta OAuth grants needed for content deletion."""
import json
import os
import sys

import requests

API = "https://graph.facebook.com/v24.0/me/permissions"
REQUIRED = ("instagram_basic", "instagram_manage_contents", "pages_manage_posts")


def audit(token, get=requests.get):
    if not isinstance(token, str) or not token.strip() or any(ch.isspace() for ch in token.strip()):
        return {"status": "blocked", "reason": "token_missing_or_invalid", "permissions": {}}
    try:
        response = get(API, headers={"Authorization": f"Bearer {token.strip()}"},
                       timeout=20, allow_redirects=False)
        if not response.ok:
            return {"status": "blocked", "reason": "api_rejected",
                    "http_status": response.status_code, "permissions": {}}
        body = response.json()
    except requests.RequestException as exc:
        return {"status": "blocked", "reason": "network_error",
                "error_type": type(exc).__name__, "permissions": {}}
    except (ValueError, TypeError, AttributeError) as exc:
        return {"status": "blocked", "reason": "invalid_api_response",
                "error_type": type(exc).__name__, "permissions": {}}
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return {"status": "blocked", "reason": "permissions_unavailable", "permissions": {}}
    granted = {row.get("permission") for row in rows if isinstance(row, dict)
               and row.get("status") == "granted"}
    permissions = {name: name in granted for name in REQUIRED}
    return {"status": "required_scopes_granted" if all(permissions.values()) else "scopes_missing",
            "permissions": permissions}


def main():
    result = audit(os.environ.get("META_ACCESS_TOKEN", ""))
    # Print only scope names/status, never credentials or provider payloads.
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "required_scopes_granted" else 1


if __name__ == "__main__":
    sys.exit(main())
