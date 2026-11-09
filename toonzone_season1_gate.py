"""Season 1 S01E04–S01E12 must be verified before any ToonZone S02 publish.

This is a pure, read-only gate. An archived "done" or green GitHub run
never substitutes for a provider ID currently visible in that Page's history.
An absent ID is UNKNOWN (not proof of deletion); never repost it blindly.
"""
from pathlib import Path
from ordered_channels import parse_order

EPISODES = range(4, 13)
PARTS = range(1, 5)
PLATFORMS = ("facebook", "instagram")


def scope_order(filename):
    value = parse_order(Path(str(filename)).stem, "cartoon")
    return value[:3] if value else None


def season1_receipts(videos, covers, state, histories):
    """Compute 36x2 exact source+cover+ledger+remote readiness, no writes."""
    if not isinstance(videos, list) or not isinstance(covers, dict):
        raise ValueError("Invalid ToonZone catalogs")
    entries = state.get("entries") if isinstance(state, dict) else None
    if not isinstance(entries, dict):
        raise ValueError("Invalid publisher state")
    live_ids = {}
    for platform in PLATFORMS:
        rows = histories.get(platform) if isinstance(histories, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Meta history unavailable")
        live_ids[platform] = {str(row.get("id")) for row in rows
                              if isinstance(row, dict) and str(row.get("id") or "").isdecimal()}

    catalog = {}
    duplicate_slots = []
    for row in videos:
        if not isinstance(row, dict):
            raise ValueError("Invalid ToonZone video")
        order = scope_order(row.get("name"))
        if not order or order[0] != 1 or order[1] not in EPISODES or order[2] not in PARTS:
            continue
        slot = (order[1], order[2])
        if slot in catalog:
            duplicate_slots.append(f"S01E{slot[0]:02d} Part{slot[1]}")
        else:
            catalog[slot] = row

    results = []
    for episode in EPISODES:
        for part in PARTS:
            item = catalog.get((episode, part))
            slot = f"S01E{episode:02d} Part{part}"
            cover_name = Path(item["name"]).stem + ".png" if item else None
            cover = covers.get(cover_name) if cover_name else None
            base = {
                "slot": slot, "source_present": bool(item and str(item.get("id") or "").strip()),
                "original_cover_present": bool(isinstance(cover, dict) and str(cover.get("id") or "").strip()),
                "source_name": item.get("name") if item else None,
                "original_png_name": cover_name,
            }
            for platform in PLATFORMS:
                row = entries.get(f"toonzone:{platform}:{item['id']}", {}) if item else {}
                valid_ledger = (isinstance(row, dict) and row.get("route") == "toonzone"
                                and row.get("platform") == platform and row.get("file") == item["name"]
                                and row.get("status") == "done"
                                and str(row.get("post_id") or "").isdecimal())
                remote_seen = bool(valid_ledger and str(row["post_id"]) in live_ids[platform])
                reason = ("missing_source" if not base["source_present"] else
                          "missing_original_cover" if not base["original_cover_present"] else
                          "no_exact_done_receipt" if not valid_ledger else
                          "archived_id_not_in_live_history" if not remote_seen else None)
                results.append({**base, "platform": platform,
                                "archived_post_id": str(row.get("post_id")) if valid_ledger else None,
                                "exact_archived_receipt": bool(valid_ledger),
                                "live_id_present": remote_seen,
                                "status": "verified_in_history" if reason is None else "held",
                                "reason": reason})
    verified = sum(r["status"] == "verified_in_history" for r in results)
    # Even with 72 matching IDs, duplicate source slots invalidate readiness.
    return {
        "schema": 1, "season": 1, "episodes": [4, 12],
        "required_source_parts": 36, "required_platform_receipts": 72,
        "verified_platform_receipts": verified,
        "missing_or_unverified_platform_receipts": 72 - verified,
        "duplicate_source_slots": duplicate_slots,
        "all_verified": verified == 72 and not duplicate_slots,
        "uncertain_remote_id_does_not_authorize_repost": True,
        "rows": results,
    }


def season2_release_allowed(receipts, *, owner_release=False):
    """Requires both full season-one proof and a separate explicit owner gate."""
    return bool(owner_release is True and isinstance(receipts, dict)
                and receipts.get("all_verified") is True)
