"""Meta tokenını kontrol eder; kimlik bilgilerini yalnızca ortamdan okur."""

import os
import sys
import json
from datetime import datetime, timezone

import requests


def _epoch_iso(value):
    if value in (None, ""):
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp == 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def safe_debug_report(data):
    """Whitelist token-debug fields; never return token or app-secret material."""
    return {
        "is_valid": bool(data.get("is_valid")),
        "app_id": data.get("app_id"),
        "token_type": data.get("type"),
        "expires_at": data.get("expires_at"),
        "expires_at_utc": _epoch_iso(data.get("expires_at")),
        "data_access_expires_at": data.get("data_access_expires_at"),
        "data_access_expires_at_utc": _epoch_iso(data.get("data_access_expires_at")),
        "permissions": sorted(set(data.get("scopes") or [])),
    }


def main():
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    app_id = os.environ.get("META_APP_ID", "").strip()
    app_secret = os.environ.get("META_APP_SECRET", "").strip()
    if not all((token, app_id, app_secret)):
        raise SystemExit("META_ACCESS_TOKEN, META_APP_ID ve META_APP_SECRET gerekli.")

    try:
        response = requests.get(
            "https://graph.facebook.com/v24.0/debug_token",
            params={"input_token": token, "access_token": f"{app_id}|{app_secret}"},
            timeout=20,
        )
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}))
        sys.exit(1)
    try:
        payload = response.json()
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__, "http_status": response.status_code}))
        sys.exit(1)
    if not response.ok or payload.get("error"):
        print(json.dumps({"http_status": response.status_code, "token_debug_succeeded": False}))
        sys.exit(1)
    report = safe_debug_report(payload.get("data") or {})
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not report["is_valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
