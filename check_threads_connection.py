"""Read-only Threads token/account audit for one or all six routes.

No media, container or publish requests. Logs never show access tokens.
"""
import os

from threads_accounts import THREADS_ROUTE_PREFIXES, threads_account_config
from threads_publisher import validate_threads_identity


def safe_provider_failure(exc):
    """Return only bounded official error codes, never token or Graph text."""
    result = {"type": type(exc).__name__,
              "reason": "connection_or_identity_unverified"}
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if type(status) is int and 400 <= status <= 599:
        result["http_status"] = status
    if status in (400, 401, 403) and response is not None:
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            if type(code) is int and 1 <= code <= 9999:
                result["graph_code"] = code
        except Exception:
            pass
    if result.get("http_status") == 401 and result.get("graph_code") == 190:
        result["reason"] = "threads_token_reauthorization_required"
    elif result.get("http_status") in (401, 403):
        result["reason"] = "threads_authorization_denied"
    return result


def verify_route(route):
    """Fail closed if the selected token does not belong to its configured identity."""
    account = threads_account_config(route, require_enabled=False, require_media=False)
    identity = validate_threads_identity(
        token=account.token, expected_username=account.username,
    )
    if account.expected_user_id and identity["id"] != account.expected_user_id:
        raise RuntimeError("Threads tokenı beklenen kullanıcı ID'sine ait değil.")
    return identity


def main():
    selected = os.getenv("THREADS_CHECK_ROUTE", "all").strip()
    if selected != "all" and selected not in THREADS_ROUTE_PREFIXES:
        raise RuntimeError("Threads rota seçimi allowlist dışında.")

    routes = tuple(THREADS_ROUTE_PREFIXES) if selected == "all" else (selected,)
    failures = []
    for route in routes:
        try:
            identity = verify_route(route)
        except Exception as exc:
            if selected != "all":
                raise
            # Account-specific failures must not prevent other GET-only checks.
            evidence = safe_provider_failure(exc)
            safe_status = "; ".join(f"{key}={value}" for key, value in evidence.items())
            print(f"FAIL: route={route}; {safe_status}; no post.", flush=True)
            failures.append(route)
        else:
            print(f"PASS: route={route}, username=@{identity['username']}; no upload or post.", flush=True)

    if failures:
        raise RuntimeError("Threads read-only verification failed for routes: " + ", ".join(failures))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        safe_status = f" HTTP {status}" if isinstance(status, int) else ""
        print(f"FAIL: read-only Threads check: {type(exc).__name__}{safe_status}", flush=True)
        raise SystemExit(1)
