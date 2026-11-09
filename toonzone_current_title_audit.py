"""Read-only current ToonZone S01E04–12 title and exact Part audit.

Never updates remote captions, restores a missing video, or retries a Meta POST.
A historical ID absent from the owner's media list is UNKNOWN, not deleted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ordered_channels import toonzone_metadata
from threads_toonzone_season import ordered_catalog

ROOT = Path("toonzone-current-title-audit")
RESULT = ROOT / "result.json"


def expected_lines(source_name):
    details = toonzone_metadata(Path(source_name).stem)
    if details["season"] != 1 or not 4 <= details["episode"] <= 12:
        raise ValueError("out_of_scope_episode")
    title = details["title"].split(" — Part ", 1)[0]
    return (f"🎬 Regular Show | {title}",
            f"📺 Sezon 1 • Bölüm {details['episode']} • Part {details['part']}/4")


def audit(catalog, ledger, live_by_platform):
    if not isinstance(ledger, dict) or not isinstance(ledger.get("entries"), dict):
        raise ValueError("unverified_publisher_ledger")
    catalog_rows = [x for x in ordered_catalog(catalog)
                    if 4 <= x["episode"] <= 12]
    expected = [(e, p) for e in range(4, 13) for p in range(1, 5)]
    if [(r["episode"], r["part"]) for r in catalog_rows] != expected:
        raise ValueError("missing_ordered_part_catalog")
    indexes = {}
    for platform in ("facebook", "instagram"):
        live = live_by_platform.get(platform)
        if not isinstance(live, list):
            raise ValueError("unavailable_owned_media_list")
        index = {}
        for post in live:
            if not isinstance(post, dict):
                raise ValueError("unverified_media_row")
            post_id = str(post.get("id") or "")
            if not post_id.isdecimal() or post_id in index:
                raise ValueError("duplicate_or_invalid_live_post_id")
            index[post_id] = post
        indexes[platform] = index

    statuses = ("canonical_title_and_part", "noncanonical_live_title_or_part",
                "live_caption_unavailable", "historic_id_not_in_current_list")
    counts = {platform: {status: 0 for status in statuses}
              for platform in ("facebook", "instagram")}
    entries, seen = [], set()
    for source in catalog_rows:
        expected_title, expected_slot = expected_lines(source["name"])
        for platform in ("facebook", "instagram"):
            row = ledger["entries"].get(f"toonzone:{platform}:{source['id']}")
            if (not isinstance(row, dict) or row.get("route") != "toonzone"
                    or row.get("platform") != platform or row.get("file") != source["name"]
                    or row.get("status") != "done"
                    or not str(row.get("post_id") or "").isdecimal()):
                raise ValueError("missing_original_post_receipt_or_wrong_source")
            post_id = str(row["post_id"])
            if (platform, post_id) in seen:
                raise ValueError("reused_historical_post_id")
            seen.add((platform, post_id))
            provider_row = indexes[platform].get(post_id)
            observed = (provider_row.get("description") if platform == "facebook"
                        else provider_row.get("caption")) if provider_row else None
            if provider_row is None:
                status = "historic_id_not_in_current_list"
            elif not isinstance(observed, str) or not observed.strip():
                status = "live_caption_unavailable"
            else:
                lines = [x.strip() for x in observed.replace("\r\n", "\n").splitlines()]
                status = ("canonical_title_and_part" if len(lines) >= 2
                          and lines[0] == expected_title
                          and lines[1] == expected_slot
                          else "noncanonical_live_title_or_part")
            counts[platform][status] += 1
            entries.append({
                "platform": platform, "episode": source["episode"],
                "part": source["part"], "source_name": source["name"],
                "archived_post_id": post_id, "expected_title": expected_title,
                "expected_part_marker": expected_slot, "status": status,
            })
    correct = sum(counts[p]["canonical_title_and_part"] for p in counts)
    return {
        "status": ("all_current_titles_verified" if correct == 72
                   else "held_live_title_or_media_visibility"),
        "historical_receipts": 72,
        "verified_canonical_title_and_part": correct,
        "facebook": counts["facebook"],
        "instagram": counts["instagram"],
        "provider_title_edit_attempts": 0,
        "meta_post_attempts": 0,
        "unlisted_post_id_means_deleted": False,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }


def main():
    from public_link_runtime import FOLDERS, inventory, restore, graph_rows
    from toonzone_instagram_season import page_for_toonzone, instagram_identity

    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        page = page_for_toonzone()
        if (str(page.get("page_id") or "") != "1298191963387372"
                or str(instagram_identity(page)) != "17841477404255851"):
            raise ValueError("wrong_toonzone_account")
        catalog = inventory(FOLDERS["toonzone"])
        ledger = restore()
        live = {p: graph_rows(page, p) for p in ("facebook", "instagram")}
        result = audit(catalog, ledger, live)
    except Exception as exc:
        # Keep provider responses, token values and failure bodies out of logs.
        result = {"status": "audit_unavailable", "reason_type": type(exc).__name__,
                  "provider_title_edit_attempts": 0, "meta_post_attempts": 0}
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "entries"},
                     ensure_ascii=False), flush=True)
    return 1 if result["status"] == "audit_unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
