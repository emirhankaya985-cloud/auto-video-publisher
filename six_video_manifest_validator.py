"""Offline validation for a six-source-video intake manifest.

This module only reads and validates manifest data. It never contacts providers,
queues posts, or changes publication state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


EXPECTED_VIDEO_COUNT = 6
ALLOWED_ACCOUNTS = {
    "tarladaki", "gonle", "penguen", "daily_laugh", "film", "toonzone",
}
ALLOWED_PLATFORMS = {"facebook", "instagram", "youtube", "threads", "x"}


def validate_manifest(manifest):
    """Check that targets describe exactly six distinct source videos.

    Multiple platform rows may refer to one source video; they count once.
    A source ID with conflicting filenames and duplicate account/platform routes
    fail closed. The returned report excludes source IDs and other user data.
    """
    if not isinstance(manifest, dict):
        return _report("invalid", ["manifest_must_be_object"], 0, 0)
    targets = manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        return _report("invalid", ["targets_missing_or_invalid"], 0, 0)

    errors = []
    source_names = {}
    routes = set()
    valid_rows = 0
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            errors.append("target_record_invalid")
            continue
        account = target.get("account")
        platform = target.get("platform")
        source_id = target.get("drive_file_id")
        filename = target.get("video")
        if not isinstance(account, str) or account not in ALLOWED_ACCOUNTS:
            errors.append("account_invalid")
            continue
        if not isinstance(platform, str) or platform.casefold() not in ALLOWED_PLATFORMS:
            errors.append("platform_invalid")
            continue
        if not isinstance(source_id, str) or not source_id.strip():
            errors.append("source_id_missing")
            continue
        if not isinstance(filename, str) or not filename.strip():
            errors.append("video_filename_missing")
            continue

        source_id = source_id.strip()
        filename = filename.strip()
        prior_name = source_names.setdefault(source_id, filename)
        if prior_name != filename:
            errors.append("source_id_filename_conflict")
        route = (source_id, account, platform.casefold())
        if route in routes:
            errors.append("duplicate_account_platform_route")
        routes.add(route)
        valid_rows += 1

    unique_sources = len(source_names)
    if unique_sources < EXPECTED_VIDEO_COUNT:
        errors.append("source_video_count_below_six")
    elif unique_sources > EXPECTED_VIDEO_COUNT:
        errors.append("source_video_count_exceeds_six")
    if valid_rows != len(targets):
        errors.append("one_or_more_targets_invalid")

    # Stable, de-duplicated reasons keep CI and logs useful without echoing IDs.
    errors = list(dict.fromkeys(errors))
    status = "valid" if not errors else (
        "incomplete" if errors == ["source_video_count_below_six"] else "invalid"
    )
    return _report(status, errors, unique_sources, len(targets))


def _report(status, errors, unique_sources, target_rows):
    return {
        "status": status,
        "expected_source_videos": EXPECTED_VIDEO_COUNT,
        "unique_source_videos": unique_sources,
        "missing_source_videos": max(0, EXPECTED_VIDEO_COUNT - unique_sources),
        "target_rows": target_rows,
        "errors": errors,
        "publishing_performed": False,
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print(json.dumps({"status": "invalid", "reason": "usage: python six_video_manifest_validator.py MANIFEST.json"}))
        return 2
    try:
        manifest = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(json.dumps({"status": "invalid", "reason": "manifest_unreadable_or_invalid_json"}))
        return 2
    result = validate_manifest(manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
