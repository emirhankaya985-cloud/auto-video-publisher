"""Durable, read-only serial publication cursor derived from confirmed Meta IDs.

Saved inside link-runtime/state.json (the existing GitHub Actions artifact).
Never use this cache as permission to POST: the entries and remote history remain
authoritative. Daily Laugh Lab and other unordered feeds are intentionally absent.
"""
from __future__ import annotations

import re
from pathlib import Path

CARTOON = re.compile(r"^S(\d+)E(\d+)_.+?_Part_?(\d+)(?: \(\d+\))?$", re.I)
FILM = re.compile(r"^(.+?)_Part_?(\d+)(?: \(\d+\))?$", re.I)
SERIAL_ROUTES = {"toonzone", "film", "film_second"}
PLATFORMS = {"facebook", "instagram"}


def derive_serial_cursor(state):
    """Report last verified part and first unverified observed part per destination.

    Only status=done with an actual post_id is verified. Never infer publication
    from a caption, filename, planned intent, or an old cursor snapshot.
    """
    entries = state.get("entries", {})
    if not isinstance(entries, dict):
        raise ValueError("Invalid publication ledger")
    groups = {}
    for key, row in entries.items():
        if not isinstance(row, dict):
            continue
        route, platform = row.get("route"), row.get("platform")
        if route not in SERIAL_ROUTES or platform not in PLATFORMS:
            continue
        name = row.get("file")
        if not isinstance(name, str):
            continue
        stem = Path(name).stem
        match = (CARTOON if route == "toonzone" else FILM).fullmatch(stem)
        if not match:
            continue
        if route == "toonzone":
            season, episode, part = map(int, match.groups())
            if not 1 <= part <= 4:
                continue
            series = f"S{season:02d}E{episode:02d}"
        else:
            series = re.sub(r"_+", " ", match.group(1)).strip().casefold()
            part = int(match.group(2))
        if not series or part < 1:
            continue
        scope = f"{route}:{platform}:{series}"
        group = groups.setdefault(scope, {})
        record = group.setdefault(part, {"confirmed": [], "unverified": []})
        post_id = str(row.get("post_id") or "").strip()
        item = {"file": name, "source_key": key}
        if row.get("status") == "done" and post_id:
            record["confirmed"].append({**item, "post_id": post_id})
        else:
            record["unverified"].append(item)

    cursor = {}
    for scope, parts in sorted(groups.items()):
        confirmed = sorted(n for n, item in parts.items() if item["confirmed"])
        first_missing = next((n for n in range(1, max(parts) + 1)
                              if n not in confirmed), None)
        last_part = confirmed[-1] if confirmed else None
        latest = parts[last_part]["confirmed"][0] if last_part is not None else None
        cursor[scope] = {
            "last_verified_part": last_part,
            "last_verified_post_id": latest["post_id"] if latest else None,
            "last_verified_source": latest["file"] if latest else None,
            "first_unverified_part": first_missing,
            "held_parts": sorted(n for n, item in parts.items()
                                 if item["unverified"] and not item["confirmed"]),
            "confirmed_parts": confirmed,
            "conflicting_parts": sorted(n for n, item in parts.items()
                                        if len({x["post_id"] for x in item["confirmed"]}) > 1),
        }
    return cursor
