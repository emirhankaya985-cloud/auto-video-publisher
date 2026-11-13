"""One-time production read-only statistics probe; never sends any Telegram/ntfy messages."""
import json
from pathlib import Path
import stats_reporter

OUTPUT = Path("stats-readonly-health/summary.json")


def summarize(report):
    comparison = getattr(report, "comparison", None)
    if not isinstance(comparison, dict):
        raise RuntimeError("invalid_comparison")
    accounts = comparison.get("accounts")
    if not isinstance(accounts, list):
        raise RuntimeError("invalid_account_list")
    rows = [p for a in accounts if isinstance(a, dict)
            for p in a.get("platforms", []) if isinstance(p, dict)]
    counts = {
        "platforms_reported": len(rows),
        "view_totals_measured": sum(type(p.get("total")) is int and p["total"] >= 0 for p in rows),
        "daily_changes_measured": sum(type((p.get("daily") or {}).get("delta")) is int for p in rows),
        "weekly_changes_measured": sum(type((p.get("weekly") or {}).get("delta")) is int for p in rows),
        "threads_platforms_reported": sum(p.get("platform") == "Threads" for p in rows),
        "threads_view_totals_measured": sum(p.get("platform") == "Threads" and type(p.get("total")) is int for p in rows),
        "youtube_platforms_reported": sum(p.get("platform") == "YouTube" for p in rows),
    }
    # Never export untrusted provider error text or access credentials.
    # Show only the project-owned account/platform labels for missing counters.
    known_accounts = set(stats_reporter.ACCOUNT_TARGETS)
    known_platforms = {"Facebook", "Facebook 1", "Facebook 2", "Instagram", "Threads", "YouTube"}
    missing_counters = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        canonical = account.get("account")
        canonical = canonical if canonical in known_accounts else "N/A"
        for platform in account.get("platforms", []):
            if not isinstance(platform, dict):
                continue
            kind = platform.get("platform")
            if kind not in known_platforms:
                kind = "N/A"
            count = platform.get("total")
            if type(count) is not int or count < 0:
                missing_counters.append({
                    "account": canonical, "platform": kind, "reason": "view_counter_unavailable"
                })
    if len(missing_counters) > 64:
        raise RuntimeError("invalid_metric_coverage")
    # Owner-listed accounts absent from the configured collector must never
    # silently disappear from a green metrics probe.
    expected_accounts = tuple(stats_reporter.ACCOUNT_TARGETS) + ("OddFrames",)
    measured_names = {item.get("account") for item in accounts
                      if isinstance(item, dict) and isinstance(item.get("account"), str)}
    owner_coverage = {
        "expected_accounts": len(expected_accounts),
        "configured_accounts": len(stats_reporter.ACCOUNT_TARGETS),
        "measured_accounts": len(set(expected_accounts) & measured_names),
        "unconfigured_accounts": [name for name in expected_accounts
                                  if name not in stats_reporter.ACCOUNT_TARGETS],
        "unmeasured_accounts": [name for name in expected_accounts if name not in measured_names],
    }
    # The live statistics probe is NOT a publication ledger: never turn
    # missing accounts, unsupported platforms, or unseen post counts into 0.
    owner_accounts = []
    for name in expected_accounts:
        configured = name in stats_reporter.ACCOUNT_TARGETS
        row = next((a for a in accounts
                    if isinstance(a, dict) and a.get("account") == name), None)
        observed = {p.get("platform"): p for p in (row or {}).get("platforms", [])
                    if isinstance(p, dict) and isinstance(p.get("platform"), str)}
        platform_coverage = {}
        for platform in ("Facebook", "Instagram", "Threads", "YouTube"):
            parts = [p for kind, p in observed.items()
                     if kind == platform or (platform == "Facebook" and kind in ("Facebook 1", "Facebook 2"))]
            measured = [p for p in parts if type(p.get("total")) is int and p.get("total") >= 0]
            platform_coverage[platform] = {
                "view_metric": ("measured" if measured else "N/A"),
                "reported_channels": len(parts),
            }
        owner_accounts.append({
            "account": name,
            "configured": configured,
            "view_coverage": platform_coverage,
            "planned_daily_target": stats_reporter.ACCOUNT_TARGETS[name][0] if configured else None,
            "today_verified_post_count": "N/A",
            "publisher_ledger_required": True,
        })
    # Export only validated numeric counters and owner-defined labels so the
    # owner can read the live result. Never copy provider errors or credentials.
    measured_metrics = []
    account_totals = []
    for account in accounts:
        if not isinstance(account, dict) or account.get("account") not in known_accounts:
            continue
        name = account["account"]
        total = account.get("total")
        if type(total) is int and total >= 0:
            account_totals.append({
                "account": name, "views": total,
                "daily_change": (account.get("daily") or {}).get("delta")
                    if type((account.get("daily") or {}).get("delta")) is int else None,
                "weekly_change": (account.get("weekly") or {}).get("delta")
                    if type((account.get("weekly") or {}).get("delta")) is int else None,
            })
        for part in account.get("platforms", []):
            if not isinstance(part, dict) or part.get("platform") not in known_platforms:
                continue
            value = part.get("total")
            if type(value) is not int or value < 0:
                continue
            daily = part.get("daily") or {}
            weekly = part.get("weekly") or {}
            measured_metrics.append({
                "account": name, "platform": part["platform"], "views": value,
                "daily_change": daily.get("delta") if type(daily.get("delta")) is int else None,
                "weekly_change": weekly.get("delta") if type(weekly.get("delta")) is int else None,
            })
    follower_metrics = []
    for row in comparison.get("followers", []):
        if not isinstance(row, dict) or row.get("account") not in known_accounts:
            continue
        if row.get("platform") not in known_platforms:
            continue
        value = row.get("followers")
        if type(value) is not int or value < 0:
            continue
        change = row.get("daily_change")
        follower_metrics.append({
            "account": row["account"], "platform": row["platform"],
            "followers": value, "daily_change": change if type(change) is int else None,
        })
    meta = comparison.get("meta_collection")
    return {
        "status": "measured_partial_or_complete",
        "measurement_at": comparison.get("measured_at"),
        "account_count": len(accounts),
        "owner_account_coverage": owner_coverage,
        "owner_account_platform_health": owner_accounts,
        "counts": counts,
        "account_totals": account_totals,
        "platform_metrics": measured_metrics,
        "follower_metrics": follower_metrics,
        "missing_view_counters": missing_counters,
        "meta_collection": meta if isinstance(meta, dict) else {"status": "unverified"},
        "collection_errors_count": len(comparison.get("collection_errors", []))
            if isinstance(comparison.get("collection_errors"), list) else None,
        "telegram_messages_sent": 0, "ntfy_messages_sent": 0, "publisher_writes": 0,
        "threads_engagement_coverage": {
            metric: {"expected_accounts": counts["threads_platforms_reported"],
                     "measured_accounts": len({row.get("account") for row in comparison.get("threads_engagement", [])
                         if isinstance(row, dict) and row.get("platform") == "Threads"
                         and row.get("metric") == metric and row.get("status") == "ok"
                         and type(row.get("value")) is int and row["value"] >= 0})}
            for metric in stats_reporter.THREADS_ENGAGEMENT_METRICS
        },
        "source": "stats_reporter.build_report; no notify invocation",
    }


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    try:
        data = summarize(stats_reporter.build_report())
        OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(data, ensure_ascii=False), flush=True)
        if data["counts"]["view_totals_measured"] == 0:
            raise RuntimeError("no_live_platform_views")
        if data["counts"]["threads_view_totals_measured"] == 0:
            print("THREADS_COVERAGE_UNAVAILABLE (not counted as zero)", flush=True)
        return 0
    except Exception as exc:
        # Never echo a provider error response which might contain credentials.
        data = {"status": "probe_failed", "safe_error_type": type(exc).__name__,
                "telegram_messages_sent": 0, "ntfy_messages_sent": 0, "publisher_writes": 0}
        OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(data), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
