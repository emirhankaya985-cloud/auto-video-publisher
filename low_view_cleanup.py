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


def assess(snapshot, measured_at, *, now=None, excluded_accounts=EXCLUDED_ACCOUNTS,
           expected_sources=None, collection_errors=()):
    """Classify a complete read-only snapshot; malformed or unknown => hold."""
    collection_errors = list(collection_errors)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    measured = _parse_time(measured_at)
    if measured is None or measured > now + timedelta(minutes=5):
        raise ValueError("measurement time is missing or invalid")
    expected_sources = set(expected_sources or ())
    actual_sources = set(snapshot)
    missing_sources = expected_sources - actual_sources
    invalid_sources = {key for key, value in snapshot.items() if value is None}
    complete = not collection_errors and not missing_sources and not invalid_sources
    result = {"schema_version": 2, "mode": "read_only_assessment",
              "measured_at": measured.isoformat(), "deletion_enabled": False,
              "collection_complete": complete,
              "missing_sources": [list(key) for key in sorted(missing_sources, key=str)],
              "unavailable_sources": [list(key) for key in sorted(invalid_sources, key=str)],
              "collection_errors": list(collection_errors),
              "candidates": [], "held": []}
    # Validate each account and metric without exposing provider error details.
    malformed_sources = set()
    for key, videos in snapshot.items():
        if not isinstance(key, tuple) or len(key) != 2 or not isinstance(videos, dict):
            malformed_sources.add(key)
            continue
        for content_id, item in videos.items():
            if (not isinstance(content_id, str) or not content_id.strip()
                    or not isinstance(item, dict)
                    or _parse_time(item.get("published_at")) is None
                    or type(item.get("views")) is not int or item.get("views") < 0):
                malformed_sources.add(key)
                break
    for account, platform in sorted(malformed_sources, key=str):
        result["collection_errors"].append(
            f"{account} / {platform}: invalid or incomplete measurement")
    if malformed_sources:
        result["collection_complete"] = False
    # A partial read can never produce review candidates. Hold every measured
    # row so a missing account/platform cannot turn into an actionable report.
    if not complete:
        for key, videos in sorted(snapshot.items(), key=lambda item: str(item[0])):
            account, platform = key if isinstance(key, tuple) and len(key) == 2 else (None, None)
            if isinstance(videos, dict):
                for content_id in videos:
                    result["held"].append({"account": account, "platform": platform,
                                           "content_id": str(content_id),
                                           "reason": "collection_incomplete"})
        for key in missing_sources | invalid_sources:
            account, platform = key if isinstance(key, tuple) and len(key) == 2 else (None, None)
            result["held"].append({"account": account, "platform": platform,
                                   "reason": "platform_collection_unavailable"})
        for key in malformed_sources:
            account, platform = key if isinstance(key, tuple) and len(key) == 2 else (None, None)
            result["held"].append({"account": account, "platform": platform,
                                   "reason": "platform_measurement_invalid"})
        return result
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


def collect_instagram_snapshot(*, targets=None, get_page_info=None, snapshot_loader=None):
    """Collect only configured Instagram snapshots; any failure remains unavailable."""
    if targets is None or get_page_info is None or snapshot_loader is None:
        from stats_reporter import META_TARGETS, get_meta_page_info, instagram_video_snapshot
        targets = META_TARGETS if targets is None else targets
        get_page_info = get_meta_page_info if get_page_info is None else get_page_info
        snapshot_loader = instagram_video_snapshot if snapshot_loader is None else snapshot_loader
    snapshot, errors = {}, []
    for account, page_name, platform in targets:
        if platform != "Instagram":
            continue
        key = (account, "Instagram")
        page = None
        try:
            page = get_page_info(page_name)
            data = snapshot_loader(page)
            if not isinstance(data, dict):
                raise RuntimeError("invalid_snapshot")
            snapshot[key] = data
        except Exception as exc:
            snapshot[key] = None
            stage = "identity_lookup_failed" if page is None else "instagram_metrics_read_failed"
            errors.append(f"{account} / Instagram: {stage} ({type(exc).__name__})")
    return snapshot, errors


def main():
    # Reuse only account-bound Instagram reads. No publisher path is invoked.
    from stats_reporter import META_TARGETS, TZ

    measured = datetime.now(TZ)
    snapshot, errors = collect_instagram_snapshot()
    required = {(account, "Instagram") for account, _page, platform in META_TARGETS
                if platform == "Instagram"}
    report = assess(snapshot, measured.isoformat(timespec="seconds"), now=measured,
                    expected_sources=required, collection_errors=errors)
    report["platform_scope"] = "Instagram only; Facebook, Threads and YouTube are excluded."
    report["excluded_platforms"] = {
        "Facebook": "out_of_scope", "Threads": "out_of_scope", "YouTube": "out_of_scope",
    }
    # Incomplete sweeps contain held records only and always fail the job.
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
            handle.write("Instagram scope only. No platform content was deleted.\n")
    print(json.dumps({"mode": report["mode"], "candidates": len(report["candidates"]),
                      "held": len(report["held"]),
                      "collection_complete": report["collection_complete"]}, sort_keys=True))
    return 0 if report["collection_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
