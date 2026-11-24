#!/usr/bin/env python3
"""Safely reset one unordered account's active confirmed-publication ledger.

The workflow preserves the complete original state before this runs. Only
confirmed done rows for one allowlisted route are removed; uncertain/held/intent
rows stay in place to prevent blind retries.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RESETTABLE_ROUTES = frozenset({"tarladaki", "penguen", "gonle", "daily_laugh"})
PROTECTED_ROUTES = frozenset({"film", "film_second", "toonzone"})


def reset_state(state: dict, route: str) -> tuple[dict, dict]:
    if route in PROTECTED_ROUTES or route not in RESETTABLE_ROUTES:
        raise ValueError("route is not explicitly resettable")
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError("invalid state schema")
    entries = state.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("invalid entries ledger")
    before_siblings = {
        key: value for key, value in entries.items()
        if not (isinstance(value, dict) and value.get("route") == route)
    }
    removed = []
    preserved = {"uncertain": 0, "held": 0, "intent": 0, "done_without_post_id": 0}
    active = dict(entries)
    for key, row in entries.items():
        if not isinstance(row, dict) or row.get("route") != route:
            continue
        if row.get("status") == "done" and str(row.get("post_id") or "").strip():
            removed.append(key)
            del active[key]
        elif row.get("status") in preserved:
            preserved[row["status"]] += 1

    result = dict(state)
    result["entries"] = active
    alerts = result.get("queue_alert_days", {})
    if isinstance(alerts, dict):
        alerts = dict(alerts)
        alerts.pop(route, None)
        result["queue_alert_days"] = alerts

    after_siblings = {
        key: value for key, value in active.items()
        if not (isinstance(value, dict) and value.get("route") == route)
    }
    if after_siblings != before_siblings:
        raise RuntimeError("sibling account ledger changed during reset")
    still_done = [
        key for key, row in active.items()
        if isinstance(row, dict) and row.get("route") == route
        and row.get("status") == "done" and str(row.get("post_id") or "").strip()
    ]
    if still_done:
        raise RuntimeError("confirmed rows remain after reset")
    report = {
        "schema": 1,
        "route": route,
        "operation": "active_confirmed_ledger_reset",
        "removed_confirmed_rows": len(removed),
        "removed_keys": removed,
        "preserved_nonconfirmed_rows": preserved,
        "remaining_confirmed_rows": 0,
        "sibling_ledger_rows_preserved": len(after_siblings),
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
