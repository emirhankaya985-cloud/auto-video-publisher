#!/usr/bin/env python3
"""Safely reset one unordered account's active confirmed-publication ledger.

The workflow preserves the complete original state before this runs. Only
confirmed done rows for one allowlisted route are removed from its Meta and
YouTube active ledgers; uncertain/held/intent rows stay to prevent blind retries.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RESETTABLE_ROUTES = frozenset({"tarladaki", "penguen", "gonle", "daily_laugh"})
PROTECTED_ROUTES = frozenset({"film", "film_second", "toonzone"})


def _remove_confirmed(rows: dict, route: str, preserved: dict) -> tuple[dict, int]:
    active = dict(rows)
    removed = 0
    for key, row in rows.items():
        if not isinstance(row, dict) or row.get("route") != route:
            continue
        if row.get("status") == "done" and str(row.get("post_id") or "").strip():
            del active[key]
            removed += 1
        elif row.get("status") in preserved:
            preserved[row["status"]] += 1
    return active, removed


def reset_state(state: dict, route: str) -> tuple[dict, dict]:
    if route in PROTECTED_ROUTES or route not in RESETTABLE_ROUTES:
        raise ValueError("route is not explicitly resettable")
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError("invalid state schema")
    entries = state.get("entries")
    youtube_entries = state.get("youtube_entries", {})
    if not isinstance(entries, dict) or not isinstance(youtube_entries, dict):
        raise ValueError("invalid publication ledger")

    before_meta_siblings = {
        key: value for key, value in entries.items()
        if not (isinstance(value, dict) and value.get("route") == route)
    }
    before_youtube_siblings = {
        key: value for key, value in youtube_entries.items()
        if not (isinstance(value, dict) and value.get("route") == route)
    }
    preserved_meta = {"uncertain": 0, "held": 0, "intent": 0, "done_without_post_id": 0}
    preserved_youtube = {"uncertain": 0, "held": 0, "intent": 0, "done_without_post_id": 0}
    active_meta, removed_meta = _remove_confirmed(entries, route, preserved_meta)
    active_youtube, removed_youtube = _remove_confirmed(
        youtube_entries, route, preserved_youtube
    )

    result = dict(state)
    result["entries"] = active_meta
    result["youtube_entries"] = active_youtube
    alerts = result.get("queue_alert_days", {})
    if isinstance(alerts, dict):
        alerts = dict(alerts)
        alerts.pop(route, None)
        result["queue_alert_days"] = alerts

    after_meta_siblings = {
        key: value for key, value in active_meta.items()
        if not (isinstance(value, dict) and value.get("route") == route)
    }
    after_youtube_siblings = {
        key: value for key, value in active_youtube.items()
        if not (isinstance(value, dict) and value.get("route") == route)
    }
    if after_meta_siblings != before_meta_siblings:
        raise RuntimeError("sibling Meta account ledger changed during reset")
    if after_youtube_siblings != before_youtube_siblings:
        raise RuntimeError("sibling YouTube account ledger changed during reset")

    def confirmed(rows):
        return sum(
            1 for row in rows.values()
            if isinstance(row, dict) and row.get("route") == route
            and row.get("status") == "done" and str(row.get("post_id") or "").strip()
        )

    if confirmed(active_meta) or confirmed(active_youtube):
        raise RuntimeError("confirmed rows remain after reset")
    report = {
        "schema": 1,
        "route": route,
        "operation": "active_confirmed_ledger_reset",
        "removed_confirmed_rows": removed_meta + removed_youtube,
        "removed_confirmed_meta_rows": removed_meta,
        "removed_confirmed_youtube_rows": removed_youtube,
        "preserved_nonconfirmed_meta_rows": preserved_meta,
        "preserved_nonconfirmed_youtube_rows": preserved_youtube,
        "remaining_confirmed_meta_rows": 0,
        "remaining_confirmed_youtube_rows": 0,
        "sibling_meta_ledger_rows_preserved": len(after_meta_siblings),
        "sibling_youtube_ledger_rows_preserved": len(after_youtube_siblings),
        "protected_routes": sorted(PROTECTED_ROUTES),
        "platform_posts_deleted": False,
    }
    return result, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    state = json.loads(args.input.read_text(encoding="utf-8"))
    result, report = reset_state(state, args.route)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
