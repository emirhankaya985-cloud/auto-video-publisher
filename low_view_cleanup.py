"""Read-only assessment of videos below the 48-hour / 10-view threshold.

This phase intentionally does not call any delete endpoint.  It emits exact
account/platform/content IDs only into a private Actions artifact so missing
metrics, identity mismatches or incomplete API reads can never be mistaken for
zero views or silently authorize a destructive action.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path


AGE = timedelta(hours=48)
MIN_VIEWS = 10
# Ordered serialized content is held until a separate safe policy is designed.
EXCLUDED_ACCOUNTS = {"🎬 Film Mağarası", "📺 ToonZone"}


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def assess(snapshot, measured_at, *, now=None, excluded_accounts=EXCLUDED_ACCOUNTS):
    """Classify a complete read-only snapshot; malformed or unknown => hold."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    measured = _parse_time(measured_at)
    if measured is None or measured > now + timedelta(minutes=5):
        raise ValueError("measurement time is missing or invalid")
    result = {"schema_version": 1, "mode": "read_only_assessment",
              "measured_at": measured.isoformat(), "deletion_enabled": False,
              "candidates": [], "held": []}
    for key, videos in sorted(snapshot.items(), key=lambda item: str(item[0])):
        if not isinstance(key, tuple) or len(key) != 2:
            result["held"].append({"reason": "invalid_account_platform_key"})
            continue
        account, platform = key
        if not isinstance(videos, dict):
            result["held"].append({"account": account, "platform": platform,
                                   "reason": "snapshot_unavailable"})
            continue
        for content_id, item in sorted(videos.items(), key=lambda x: str(x[0])):
            row = {"account": account, "platform": platform, "content_id": str(content_id)}
            if account in excluded_accounts:
                result["held"].append({**row, "reason": "ordered_series_protected"})
                continue
            if (not isinstance(content_id, str) or not content_id.strip()
                    or not isinstance(item, dict)):
                result["held"].append({**row, "reason": "invalid_content_record"})
                continue
            published = _parse_time(item.get("published_at"))
            views = item.get("views")
            if published is None:
                result["held"].append({**row, "reason": "publication_time_unverified"})
                continue
            if type(views) is not int or views < 0:
                result["held"].append({**row, "reason": "view_count_unavailable"})
                continue
            age = now - published
            if age < AGE:
                result["held"].append({**row, "views": views, "reason": "younger_than_48h"})
            elif views < MIN_VIEWS:
                result["candidates"].append({**row, "views": views,
                                             "published_at": published.isoformat(),
                                             "age_hours": round(age.total_seconds() / 3600, 2),
                                             "action": "review_only_no_delete"})
            else:
                result["held"].append({**row, "views": views, "reason": "threshold_met"})
    return result


def main():
    # Reuse the existing account-bound, read-only collectors.  No notifier or
    # publisher path is called from this entry point.
    from stats_reporter import TZ, _collect_snapshot

    measured = datetime.now(TZ)
    snapshot, _records, errors = _collect_snapshot(measured)
    report = assess(snapshot, measured.isoformat(timespec="seconds"), now=measured)
    report["collection_errors"] = errors
    report["collection_complete"] = not errors and all(value is not None
                                                        for value in snapshot.values())
    # Fail closed: if any route failed, candidates are still surfaced for
    # inspection but the workflow records that this is not a complete sweep.
    output = Path(os.environ.get("LOW_VIEW_REPORT_PATH", "low-view-cleanup-report.json"))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    summary_value = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    summary = Path(summary_value) if summary_value else None
    if summary is not None and summary.parent.exists():
        with summary.open("a", encoding="utf-8") as handle:
            handle.write("## Low-view cleanup assessment (read-only)\n\n")
            handle.write(f"Candidates: {len(report['candidates'])}; held: {len(report['held'])}; ")
            handle.write(f"complete snapshot: {report['collection_complete']}\n\n")
            handle.write("No platform content was deleted.\n")
    print(json.dumps({"mode": report["mode"], "candidates": len(report["candidates"]),
                      "held": len(report["held"]),
                      "collection_complete": report["collection_complete"]}, sort_keys=True))
    return 0 if report["collection_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
