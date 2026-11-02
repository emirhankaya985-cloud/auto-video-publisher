"""Read-only serial catch-up preview. NEVER uploads, clears state or grants repost rights.

The production publication ledger remains authoritative. A requested restart at
S01E01 is treated as a cursor, not permission to duplicate old posts. The
rejoin episode must come from a separately confirmed production snapshot.
"""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
import re

_EPISODE_RE = re.compile(r"^S(?P<s>\d+)E(?P<e>\d+)_.+_Part_?(?P<p>[1-4])(?: \(\d+\))?\.mp4$", re.I)
_PLATFORMS = ("facebook", "instagram")
_PART_MINUTES = (0, 10, 20, 30)


def _episode(item):
    name = str(item.get("name", ""))
    match = _EPISODE_RE.fullmatch(name)
    if not match:
        raise ValueError("Unordered ToonZone source; no catch-up.")
    return (int(match["s"]), int(match["e"])), int(match["p"])


def plan_toonzone_catchup(
    sources, entries, *, start_day, rejoin_episode, first_episode=(1, 1),
    days=7, platforms=_PLATFORMS
):
    """Preview one/two episodes per day, with strict platform/part idempotency.

    `rejoin_episode` is the already documented normal-series cursor: the
    episode at which acceleration ends. It cannot be guessed from inventory
    size. No publishing/API calls or state changes occur here.
    """
    if not isinstance(start_day, date) or days < 1 or days > 60:
        raise ValueError("A real local day and bounded preview horizon are required")
    if (not isinstance(rejoin_episode, tuple) or len(rejoin_episode) != 2
            or not all(type(n) is int and n >= 1 for n in rejoin_episode)):
        raise ValueError("Verified normal-flow rejoin episode required")
    if (not isinstance(first_episode, tuple) or len(first_episode) != 2
            or not all(type(n) is int and n >= 1 for n in first_episode)):
        raise ValueError("Invalid starting episode")
    if rejoin_episode < first_episode:
        raise ValueError("Rejoin cursor cannot precede starting episode")
    if tuple(platforms) != _PLATFORMS:
        raise ValueError("Both Facebook and Instagram evidence required")
    if not isinstance(entries, dict):
        raise ValueError("Ledger unavailable")

    catalog = {}
    for item in sources:
        episode, part = _episode(item)
        identifier = str(item.get("id") or "")
        if not identifier:
            raise ValueError("Drive source ID is required")
        key = catalog.setdefault(episode, {})
        if part in key:
            raise ValueError("Ambiguous duplicate ToonZone episode part")
        key[part] = dict(item)

    result = {"mode": "read_only_preview", "status": "preview", "posts": [],
              "skipped_verified": [], "held": None, "rejoin_episode": rejoin_episode,
              "normal_parts_per_day": 4, "catchup_parts_per_day": 8,
              "publishing_enabled": False}
    episodes = [ep for ep in sorted(catalog) if ep >= first_episode]
    cursor = 0
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        planned_today = 0
        while cursor < len(episodes):
            ep = episodes[cursor]
            rows = catalog[ep]
            if set(rows) != {1, 2, 3, 4}:
                result["status"] = "held"
                result["held"] = {"episode": ep, "reason": "missing_or_invalid_part"}
                return result
            source_statuses = []
            for part in range(1, 5):
                clip = rows[part]
                for platform in platforms:
                    record = entries.get(f"toonzone:{platform}:{clip['id']}")
                    if record is None:
                        source_statuses.append("fresh")
                    elif (isinstance(record, dict) and record.get("status") == "done"
                          and str(record.get("post_id") or "").strip()
                          and record.get("file") == clip["name"]):
                        source_statuses.append("done")
                    else:
                        source_statuses.append("unresolved")
            if all(status == "done" for status in source_statuses):
                result["skipped_verified"].append(ep)
                cursor += 1
                continue
            if any(status != "fresh" for status in source_statuses):
                result["status"] = "held"
                result["held"] = {"episode": ep, "reason": "partial_or_uncertain_existing_publication"}
                return result
            daily_capacity = 2 if ep < rejoin_episode else 1
            if planned_today >= daily_capacity:
                break
            hour = 12 if planned_today == 0 else 18
            for part, minute in enumerate(_PART_MINUTES, 1):
                clip = rows[part]
                result["posts"].append({
                    "day": day.isoformat(), "time_trt": f"{hour:02d}:{minute:02d}",
                    "episode": ep, "part": part, "source_id": clip["id"],
                    "platforms": list(platforms),
                })
            planned_today += 1
            cursor += 1
            if ep >= rejoin_episode:
                break
    result["preview_episodes"] = len({(row["day"], tuple(row["episode"])) for row in result["posts"]})
    result["preview_parts"] = len(result["posts"])
    result["potential_platform_posts"] = 2 * len(result["posts"])
    return result


def film_restart_guard(entries):
    """Do not mistake 'start at Part 1' for permission to republish old clips."""
    if not isinstance(entries, dict):
        return "held_unknown_history"
    for row in entries.values():
        if isinstance(row, dict) and row.get("route") in {"film", "film_second"}:
            if row.get("status") in {"done", "intent", "uncertain", "held"}:
                return "requires_source_and_post_id_reconciliation"
    return "read_only_first_part_inventory_audit_required"
