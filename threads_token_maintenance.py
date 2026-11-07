"""Safe Threads long-lived token rotation; secret write only after ID verification.

Requires a separately authorized GitHub secret-write credential. Never emits
tokens or raw provider bodies. Expired/revoked token: reauthorize, do not bypass.
"""
import os
import subprocess
import requests

from threads_accounts import THREADS_ROUTE_PREFIXES, threads_account_config
from threads_publisher import validate_threads_identity

REPO = "emirhankaya985-cloud/auto-video-publisher"
SECRET_NAMES = {
    "tarladaki": "THREADS_TARLADAKI_FASULYE_ACCESS_TOKEN",
    "penguen": "PENGUEN_THREADS_ACCESS_TOKEN",
    "gonle": "THREADS_GONLE_DUSEN_ACCESS_TOKEN",
    "daily_laugh": "THREADS_DAILY_LAUGH_LAB_ACCESS_TOKEN",
    "film": "THREADS_FILM_MAGARASI_ACCESS_TOKEN",
    "toonzone": "THREADS_TOONZONE_ACCESS_TOKEN",
}
REFRESH_URL = "https://graph.threads.net/refresh_access_token"


def classify_current_token_error(error):
    """Never confuse transient GET failures with revoked login credentials."""
    status = getattr(getattr(error, "response", None), "status_code", None)
    if type(status) is int and status in (400, 401):
        return "threads_token_reauthorization_required"
    if (type(error) is RuntimeError
            and str(error) == "Threads token beklenen Beyinsiz Penguen hesabıyla eşleşmedi."):
        return "threads_profile_identity_mismatch"
    return "threads_identity_unverified_no_automatic_rotation"


def rotate(route, *, session=requests, persist):
    """Exchange only a VALID token; verify both identities before secret commit.

    persist(secret_name, token) is trusted storage. No implicit env/file writes.
    """
    if route not in THREADS_ROUTE_PREFIXES or not callable(persist):
        raise ValueError("invalid_refresh_destination")
    account = threads_account_config(route, require_enabled=False, require_media=False)
    try:
        original = validate_threads_identity(token=account.token,
            expected_username=account.username, session=session)
    except Exception as exc:
        raise RuntimeError(classify_current_token_error(exc)) from None
    if account.expected_user_id and account.expected_user_id != str(original["id"]):
        raise RuntimeError("threads_existing_identity_mismatch")
    try:
        response = session.get(REFRESH_URL,
            params={"grant_type": "th_refresh_token"},
            headers={"Authorization": "Bearer " + account.token},
            timeout=20, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("refresh_rejected")
        payload = response.json()
    except Exception:
        raise RuntimeError("threads_refresh_rejected_reauthorization_may_be_required") from None
    renewed = payload.get("access_token") if isinstance(payload, dict) else None
    expiry = payload.get("expires_in") if isinstance(payload, dict) else None
    if (not isinstance(renewed, str) or not renewed or any(c.isspace() for c in renewed)
            or type(expiry) is not int or not 0 < expiry <= 5184000):
        raise RuntimeError("threads_refresh_response_invalid")
    try:
        refreshed = validate_threads_identity(token=renewed,
            expected_username=account.username, session=session)
    except Exception:
        raise RuntimeError("threads_refreshed_identity_unverified") from None
    if str(refreshed["id"]) != str(original["id"]):
        raise RuntimeError("threads_refresh_identity_changed")
    # Only persist verified credentials. Storage failures surface as generic
    # errors; callers must not log the exception body.
    try:
        persist(SECRET_NAMES[route], renewed)
    except Exception:
        raise RuntimeError("threads_secure_secret_persistence_failed") from None
    return {"route": route, "status": "refreshed_and_stored",
            "identity_verified": True, "days_valid": expiry // 86400}


def github_secret_store(secret_name, token):
    """Encrypted repository-secret update using official gh CLI stdin protocol."""
    pat = os.environ.get("THREADS_SECRET_ROTATION_PAT", "").strip()
    if (not pat or secret_name not in SECRET_NAMES.values()
            or os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
        raise RuntimeError("threads_secret_write_not_authorized")
    # Never put raw token in command line, step output, files or error text.
    process = subprocess.run(["gh", "secret", "set", secret_name, "--repo", REPO],
        input=token, text=True, capture_output=True, timeout=45,
        env={"GH_TOKEN": pat, "PATH": os.environ.get("PATH", ""),
             "HOME": os.environ.get("HOME", "")}, check=False)
    if process.returncode:
        raise RuntimeError("threads_secret_write_failed")


def main():
    if (os.environ.get("GITHUB_REPOSITORY") != REPO
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
        raise RuntimeError("untrusted_rotation_context")
    if not os.getenv("THREADS_SECRET_ROTATION_PAT"):
        print("Threads rotation blocked: secret-write authority unavailable; no token changes.")
        return 0
    failures = []
    for route in SECRET_NAMES:
        try:
            result = rotate(route, persist=github_secret_store)
            print("Threads rotation verified and stored: " + result["route"])
        except Exception:
            failures.append(route)
            print("Threads rotation held for account: " + route + " (no token printed)")
    if failures:
        raise RuntimeError("threads_rotation_incomplete_routes_" + "_".join(failures))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Threads rotation incomplete; invalid credentials require reauthorization.")
        raise SystemExit(1)
