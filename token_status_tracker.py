"""Redacted daily connection/token status assembled from existing read-only checks.

The module never reads or serializes token values. Expiry and renewability stay
unknown unless an API result explicitly supplies that information.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


THREADS_SECRET_NAMES = {
    "tarladaki": "THREADS_TARLADAKI_FASULYE_ACCESS_TOKEN",
    "penguen": "PENGUEN_THREADS_ACCESS_TOKEN (fallback: THREADS_ACCESS_TOKEN)",
    "gonle": "THREADS_GONLE_DUSEN_ACCESS_TOKEN",
    "daily_laugh": "THREADS_DAILY_LAUGH_LAB_ACCESS_TOKEN",
    "film": "THREADS_FILM_MAGARASI_ACCESS_TOKEN",
    "toonzone": "THREADS_TOONZONE_ACCESS_TOKEN",
}
THREADS_ENV_NAMES = {
    "tarladaki": "TARLADAKI_THREADS_ACCESS_TOKEN",
    "penguen": "PENGUEN_THREADS_ACCESS_TOKEN",
    "gonle": "GONLE_THREADS_ACCESS_TOKEN",
    "daily_laugh": "DAILY_LAUGH_THREADS_ACCESS_TOKEN",
    "film": "FILM_THREADS_ACCESS_TOKEN",
    "toonzone": "TOONZONE_THREADS_ACCESS_TOKEN",
}
ACCOUNT_ROUTES = {
    "🌱 Tarladaki Fasulye": "tarladaki",
    "🐧 Beyinsiz Penguen": "penguen",
    "❤️ Gönle Düşen": "gonle",
    "😂 Daily Laugh Lab": "daily_laugh",
    "🎬 Film Mağarası": "film",
    "📺 ToonZone": "toonzone",
}
EXPIRY_THRESHOLDS = (30, 15, 7, 3, 1)


def expiry_warning_threshold(days_remaining):
    """Return the first configured warning window, only for a known expiry."""
    if type(days_remaining) is not int:
        return None
    if days_remaining <= 0:
        return 0
    if days_remaining >= 16:
        return 30
    if days_remaining >= 8:
        return 15
    return next(limit for limit in EXPIRY_THRESHOLDS[2:]
                if days_remaining >= limit)


def _history_successes(path):
    latest = {}
    if not path:
        return latest
    try:
        handle = Path(path).open("r", encoding="utf-8")
    except OSError:
        return latest
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (not isinstance(row, dict) or row.get("metric") != "snapshot_status"
                    or row.get("status") != "ok"):
                continue
            key = (row.get("account"), row.get("platform"))
            stamp = row.get("measured_at")
            if not isinstance(stamp, str):
                continue
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                continue
            if key not in latest or parsed > latest[key][0]:
                latest[key] = (parsed, stamp)
    return {key: value[1] for key, value in latest.items()}


def _api_error_is_action_required(error):
    value = str(error or "").casefold()
    return any(part in value for part in ("401", "403", "190", "reauthor", "token rejected", "tokenı reddedildi"))


def build_inventory(*, snapshot, errors, measured_at, history_path=None,
                    meta_expiry_metadata=None, threads_expiry_metadata=None,
                    environ=None):
    """Build sanitized per-account/platform status for the six active accounts.

    ``snapshot`` values are the existing report's read-only API results. The
    optional expiry maps must contain provider-returned timestamps; no date is
    inferred from secret age or token type.
    """
    env = os.environ if environ is None else environ
    error_by_key = {}
    for error in errors or []:
        account_platform, sep, detail = str(error).partition(": ")
        account, slash, platform = account_platform.partition(" / ")
        if sep and slash:
            error_by_key[(account.strip(), platform.strip())] = detail.strip()[:180]
    successes = _history_successes(history_path)
    now = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
    if now.tzinfo is None:
        raise ValueError("measured_at must include a timezone")
    inventory = []

    from stats_reporter import META_TARGETS
    meta_targets = []
    seen = set()
    for account, _page, platform in META_TARGETS:
        key = (account, platform)
        if key not in seen:
            seen.add(key)
            meta_targets.append(key)

    def append_row(account, route, platform, data_key, secret_name, configured,
                   expiry_metadata, refreshability, expiry_key=None):
        key = (account, data_key)
        error = error_by_key.get(key)
        result_exists = key in snapshot
        data = snapshot.get(key)
        if not configured:
            status = "NOT_CONFIGURED"
        elif not result_exists:
            status = "NOT_TESTED"
        elif data is not None:
            status = "VERIFIED_WORKING"
        elif _api_error_is_action_required(error):
            status = "ACTION_REQUIRED"
        else:
            status = "BLOCKED"

        raw_expiry = (expiry_metadata or {}).get(expiry_key or secret_name)
        expires_at = None
        days_remaining = None
        warning = None
        if isinstance(raw_expiry, str):
            try:
                expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
                if expiry.tzinfo is not None:
                    expires_at = expiry.astimezone(timezone.utc).isoformat()
                    days_remaining = int((expiry.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds() // 86400)
                    warning = expiry_warning_threshold(days_remaining)
            except ValueError:
                pass

        inventory.append({
            "account": account,
            "route": route,
            "platform": platform,
            "secret_name": secret_name,
            "credential_note": ("Page token resolved at runtime via META_ACCESS_TOKEN; no token value stored"
                                if platform != "Threads" else "Token value comes from GitHub Actions secret; never emitted"),
            "connection_status": status,
            "checked_at": measured_at,
            "last_successful_validation_at": measured_at if data is not None else successes.get(key),
            "expires_at_utc": expires_at,
            "days_remaining": days_remaining,
            "expiry_warning_days": warning,
            "renewability": refreshability,
            "last_error": error,
            "user_action_required": ("YES" if status in {"ACTION_REQUIRED", "NOT_CONFIGURED"}
                                     else "NO" if status == "VERIFIED_WORKING" else "UNKNOWN"),
            "publish_permission": "NOT_TESTED",
            "check_type": "existing_read_only_metrics_api",
        })

    for account, data_key in meta_targets:
        route = ACCOUNT_ROUTES.get(account)
        if route is None:
            continue
        display_platform = "Facebook" if data_key == "Facebook 1" else data_key
        append_row(account, route, display_platform, data_key, "META_ACCESS_TOKEN",
                   bool(env.get("META_ACCESS_TOKEN", "").strip()), meta_expiry_metadata,
                   "UNKNOWN; no refresh attempted", expiry_key=f"META_PAGE_TOKEN:{route}")
    for account, route in ACCOUNT_ROUTES.items():
        secret_name = THREADS_SECRET_NAMES[route]
        env_name = THREADS_ENV_NAMES[route]
        append_row(account, route, "Threads", "Threads", secret_name,
                   bool(env.get(env_name, "").strip()), threads_expiry_metadata,
                   "CONDITIONAL; valid token and authorized secret-write access required")
    return {
        "schema": 1,
        "measured_at": measured_at,
        "timezone": "Europe/Istanbul",
        "accounts": list(ACCOUNT_ROUTES),
        "status_scope": "connection/read-only metrics only; publishing permission is not tested",
        "expiry_policy_days": list(EXPIRY_THRESHOLDS),
        "expiry_note": "Unknown unless the provider returned an explicit expiry timestamp; no estimates.",
        "connections": inventory,
    }


def account_summary(inventory):
    """Compact Turkish summary suitable for the daily phone report."""
    rows = inventory.get("connections", []) if isinstance(inventory, dict) else []
    grouped = {account: {} for account in ACCOUNT_ROUTES}
    for row in rows:
        grouped.setdefault(row.get("account"), {})[row.get("platform")] = row
    lines = ["🔐 Bağlantı/token özeti (API okuması; yayın yetkisi ayrıca doğrulanır):"]
    for account, platforms in grouped.items():
        if not platforms:
            lines.append(f"• {account}: NOT_TESTED")
            continue
        pieces = []
        known_expiries = []
        for platform in ("Facebook", "Facebook 1", "Instagram", "Threads"):
            row = platforms.get(platform)
            if row:
                label = "Facebook" if platform == "Facebook 1" else platform
                pieces.append(f"{label}={row['connection_status']}")
                if isinstance(row.get("days_remaining"), int):
                    known_expiries.append(f"{label}:{row['days_remaining']} gün")
        expiry = ("; token bitişi: " + ", ".join(known_expiries)
                  if known_expiries else "; token expiry=UNKNOWN")
        lines.append(f"• {account}: " + "; ".join(pieces) + expiry)
    lines.append("Bitiş tarihi yalnız API açık tarih verdiğinde gösterilir; yayın yetkisi bu raporda test edilmez.")
    return lines
