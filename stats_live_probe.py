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
    meta = comparison.get("meta_collection")
    return {
        "status": "measured_partial_or_complete",
        "measurement_at": comparison.get("measured_at"),
        "account_count": len(accounts),
        "counts": counts,
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
