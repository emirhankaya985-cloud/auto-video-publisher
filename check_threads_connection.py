"""Read-only Threads token/account audit. No media, container or publish requests."""
import os
from threads_accounts import THREADS_ROUTE_PREFIXES, threads_account_config
from threads_publisher import validate_threads_identity


def main():
    route = os.getenv("THREADS_CHECK_ROUTE", "penguen").strip()
    if route not in THREADS_ROUTE_PREFIXES:
        raise RuntimeError("Threads rota seçimi allowlist dışında.")
    account = threads_account_config(route, require_enabled=False, require_media=False)
    identity = validate_threads_identity(
        token=account.token, expected_username=account.username,
    )
    if account.expected_user_id and identity["id"] != account.expected_user_id:
        raise RuntimeError("Threads tokenı beklenen kullanıcı ID'sine ait değil.")
    print(f"PASS: route={route}, username=@{identity['username']}; no upload or post.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        safe_code = f" HTTP {code}" if isinstance(code, int) else ""
        print(f"FAIL: read-only Threads check: {type(exc).__name__}{safe_code}", flush=True)
        raise SystemExit(1)
