"""Safely clean up low-view Instagram videos after a complete inventory.

Automatic deletion is opt-in and limited to posts published after an explicit
activation timestamp. Missing metrics, identity mismatches, or partial reads
always block deletion.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path


AGE = timedelta(hours=36)
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
                result["held"].append({**row, "views": views,
                                       "reason": f"younger_than_{int(AGE.total_seconds() // 3600)}h"})
            elif views < MIN_VIEWS:
                result["candidates"].append({**row, "views": views,
                                             "published_at": published.isoformat(),
                                             "age_hours": round(age.total_seconds() / 3600, 2),
                                             "action": "review_only_no_delete"})
            else:
                result["held"].append({**row, "views": views, "reason": "threshold_met"})
    return result


def collect_instagram_snapshot(*, targets=None, get_page_info=None, snapshot_loader=None,
                               include_pages=False):
    """Read only Instagram video views for each configured Meta account.

    Facebook, Threads and YouTube are intentionally not queried for this
    Instagram-only cleanup preview. A failed Instagram account is unavailable,
    never an empty/zero-view inventory.
    """
    if targets is None or get_page_info is None or snapshot_loader is None:
        from stats_reporter import META_TARGETS, get_meta_page_info, instagram_video_snapshot
        targets = META_TARGETS if targets is None else targets
        get_page_info = get_meta_page_info if get_page_info is None else get_page_info
        snapshot_loader = instagram_video_snapshot if snapshot_loader is None else snapshot_loader
    snapshot, errors, pages = {}, [], {}
    for account, page_name, platform in targets:
        if platform != "Instagram":
            continue
        key = (account, "Instagram")
        try:
            try:
                page = get_page_info(page_name)
                if not isinstance(page, dict) or not page.get("instagram_id") or not page.get("page_token"):
                    raise RuntimeError("verified_instagram_identity_or_token_missing")
                if include_pages:
                    user_token = os.getenv("META_ACCESS_TOKEN", "").strip()
                    if not user_token:
                        raise RuntimeError("facebook_user_token_missing")
                    page = {**page, "user_access_token": user_token}
            except Exception as exc:
                snapshot[key] = None
                errors.append(f"{account} / Instagram: identity_lookup_failed ({type(exc).__name__})")
                continue
            try:
                data = snapshot_loader(page)
            except Exception as exc:
                snapshot[key] = None
                errors.append(f"{account} / Instagram: instagram_metrics_read_failed ({type(exc).__name__})")
                continue
            if not isinstance(data, dict):
                raise RuntimeError("invalid_snapshot")
            snapshot[key] = data
            pages[account] = page
        except Exception as exc:
            snapshot[key] = None
            errors.append(f"{account} / Instagram: {type(exc).__name__}")
    if include_pages:
        return snapshot, errors, pages
    return snapshot, errors


def delete_review_candidates(report, pages, delete_call, *, delete_start_at, now=None,
                             max_per_account=10):
    """Delete only new owned Instagram videos after a complete inventory.

    Videos published before the activation timestamp remain untouched. The
    caller-supplied API adapter makes this decision path testable without writes.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    start = _parse_time(delete_start_at)
    candidates = report.get("candidates", [])
    if start is None or start > now:
        return {"status": "blocked_invalid_delete_start", "deleted": [],
                "held": len(candidates), "skipped_before_start": 0, "errors": []}
    if report.get("collection_complete") is not True:
        return {"status": "blocked_incomplete_collection", "deleted": [],
                "held": len(candidates), "skipped_before_start": 0, "errors": []}

    eligible, skipped_old = [], 0
    for row in candidates:
        published = _parse_time(row.get("published_at"))
        content_id = row.get("content_id")
        if published is None or published < start:
            skipped_old += 1
            continue
        if (type(row.get("views")) is not int or row["views"] >= MIN_VIEWS
                or now - published < AGE
                or not re.fullmatch(r"[0-9]{1,30}", str(content_id or ""))):
            skipped_old += 1
            continue
        eligible.append((row, published, content_id))

    # When a per-account cap applies, always work from the oldest eligible
    # publication toward the newest. Stable tie breakers keep runs repeatable.
    eligible.sort(key=lambda item: (item[1], str(item[0].get("account", "")),
                                    str(item[2])))

    deleted, held, errors = [], 0, []
    per_account = {}
    for index, (row, published, content_id) in enumerate(eligible):
        account = row.get("account")
        page = pages.get(account)
        if (not isinstance(page, dict) or not page.get("page_token")
                or not page.get("user_access_token") or not page.get("instagram_id")):
            errors.append("verified account token unavailable")
            held += len(eligible) - index
            break
        if per_account.get(account, 0) >= max_per_account:
            held += 1
            continue
        try:
            outcome = delete_call(page, content_id)
        except Exception as exc:
            errors.append(f"delete request failed ({type(exc).__name__})")
            held += len(eligible) - index
            break
        if outcome == "threshold_reached":
            held += 1
            continue
        if outcome is not True:
            errors.append("delete result not confirmed")
            held += len(eligible) - index
            break
        deleted.append({"account": account, "content_id": content_id,
                        "views_at_scan": row["views"],
                        "published_at": published.isoformat(), "result": "deleted"})
        per_account[account] = per_account.get(account, 0) + 1
    return {"status": "success" if not errors else "halted_on_error",
            "deleted": deleted, "held": held, "skipped_before_start": skipped_old,
            "errors": errors, "delete_start_at": start.isoformat(),
            "max_per_account_per_run": max_per_account}


def _delete_instagram_media(page, media_id):
    """Recheck views and account ownership context before the Instagram DELETE."""
    import requests
    from cloud_omnichannel_publisher import GRAPH_API_VERSION

    headers = {"Authorization": f"Bearer {page['page_token']}"}
    endpoint = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}"
    response = requests.get(f"{endpoint}/insights", headers=headers,
                            params={"metric": "views"}, timeout=20,
                            allow_redirects=False)
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError("view_recheck_unavailable")
    latest = None
    for entry in entries:
        if entry.get("name") == "views":
            latest = entry.get("value")
            values = entry.get("values") or []
            if latest is None and len(values) == 1:
                latest = values[0].get("value")
            break
    if type(latest) is not int or latest < 0:
        raise RuntimeError("view_recheck_unavailable")
    if latest >= MIN_VIEWS:
        return "threshold_reached"
    delete_headers = {"Authorization": f"Bearer {page['user_access_token']}"}
    response = requests.delete(endpoint, headers=delete_headers, timeout=20,
                               allow_redirects=False)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or result.get("success") is not True:
        raise RuntimeError("delete_not_confirmed")
    return True


def main():
    # Reuse the existing account-bound, read-only Instagram collector only.
    from stats_reporter import META_TARGETS, TZ

    measured = datetime.now(TZ)
    delete_enabled = os.getenv("LOW_VIEW_DELETE_ENABLED", "false").strip().lower() == "true"
    if delete_enabled:
        snapshot, errors, pages = collect_instagram_snapshot(include_pages=True)
    else:
        snapshot, errors = collect_instagram_snapshot()
        pages = {}
    required = {(account, "Instagram") for account, _page, platform in META_TARGETS
                if platform == "Instagram"}
    report = assess(snapshot, measured.isoformat(timespec="seconds"), now=measured,
                    expected_sources=required, collection_errors=errors)
    report["platform_scope"] = "Instagram only; Facebook, Threads and YouTube are excluded."
    report["excluded_platforms"] = {
        "Facebook": "out_of_scope; its view counters are not used for this Instagram preview",
        "Threads": "out_of_scope; no Threads content can become a candidate",
        "YouTube": "out_of_scope; no YouTube content can become a candidate",
    }
    report["deletion_enabled"] = delete_enabled
    report["mode"] = "automatic_delete" if delete_enabled else "read_only_assessment"
    report["deletion"] = {"status": "disabled", "deleted": [], "held": 0,
                          "skipped_before_start": 0, "errors": []}
    if delete_enabled:
        report["deletion"] = delete_review_candidates(
            report, pages, _delete_instagram_media,
            delete_start_at=os.getenv("LOW_VIEW_DELETE_START_AT", ""), now=measured)
    for candidate in report["candidates"]:
        candidate["action"] = (
            "delete_only_if_after_activation_and_revalidated"
            if delete_enabled else "review_only_no_delete")
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
            handle.write(f"Instagram scope only. Deleted: {len(report['deletion']['deleted'])}.\n")
    print(json.dumps({"mode": report["mode"], "candidates": len(report["candidates"]),
                      "held": len(report["held"]),
                      "collection_complete": report["collection_complete"],
                      "deletion_status": report["deletion"]["status"],
                      "deleted": len(report["deletion"]["deleted"])}, sort_keys=True))
    failed = report["deletion"]["status"] in {
        "halted_on_error", "blocked_invalid_delete_start", "blocked_incomplete_collection"}
    return 0 if report["collection_complete"] and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
