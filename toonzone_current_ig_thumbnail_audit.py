"""Read-only ToonZone live Instagram thumbnail versus original Drive PNG.

Checks only archived IDs STILL returned by the exact owned IG /media list.
Missing media IDs are unresolved, never an excuse to POST/repost.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone

from toonzone_cover_acceptance import png_identity
from threads_toonzone_season import ordered_catalog

ROOT = Path("toonzone-current-ig-thumbnails")
REPORT = ROOT / "result.json"
EXPECTED_INSTAGRAM_ID = "17841477404255851"
THUMBNAIL_DISTANCE_MAX = 0.12


def compare_thumbnail_geometry(original_png, live_thumbnail):
    """Compare read-only thumbnail with pad/crop/stretch transformations.

    Returns distances to distinguish a source mismatch from normal platform
    aspect-ratio transformations; no variant proves a video was published.
    """
    from PIL import Image, ImageOps, ImageChops, ImageStat

    with Image.open(original_png) as source, Image.open(live_thumbnail) as observed:
        source = source.convert("RGB")
        observed = observed.convert("RGB")
        options = {
            "letterbox_pad": ImageOps.pad(source, observed.size, color=(0, 0, 0)),
            "center_crop": ImageOps.fit(source, observed.size),
            "stretch": source.resize(observed.size),
        }
        reference = observed.resize((90, 160))
        measured = {}
        for name, expected in options.items():
            delta = ImageChops.difference(expected.resize((90, 160)), reference)
            measured[name] = round(sum(ImageStat.Stat(delta).rms) / (3 * 255), 6)
        return {"distances": measured,
                "best_mode": min(measured, key=measured.get),
                "best_distance": min(measured.values()),
                "original_dimensions": list(source.size),
                "live_dimensions": list(observed.size)}


def select_current(catalog, ledger, live, covers):
    """Join only exact source/ID owned-list matches, never caption guessing."""
    if not isinstance(ledger, dict) or not isinstance(ledger.get("entries"), dict):
        raise ValueError("invalid_durable_ledger")
    live_ids = {str(x.get("id") or "") for x in live if isinstance(x, dict)}
    rows = [x for x in ordered_catalog(catalog) if 4 <= x["episode"] <= 12]
    if len(rows) != 36:
        raise ValueError("missing_ordered_36_parts")
    chosen = []
    archived = 0
    for item in rows:
        old = ledger["entries"].get(f"toonzone:instagram:{item['id']}")
        if not isinstance(old, dict):
            continue
        if (old.get("route") != "toonzone" or old.get("platform") != "instagram"
                or old.get("status") != "done" or old.get("file") != item["name"]
                or not str(old.get("post_id") or "").isdecimal()):
            raise ValueError("historical_post_ledger_mismatch")
        archived += 1
        post_id = str(old["post_id"])
        if post_id not in live_ids:
            continue
        expected_cover = Path(item["name"]).stem + ".png"
        cover = covers.get(expected_cover)
        chosen.append({**item, "archived_post_id": post_id,
                       "cover_name": expected_cover,
                       "cover_id": cover.get("id") if isinstance(cover, dict) else None})
    return {"archive_count": archived, "live_id_match_count": len(chosen),
            "not_in_live_list": archived - len(chosen), "entries": chosen}


def audit(page, *, inventory, download, graph_rows, restore, thumbnail, cover_distance):
    from public_link_runtime import FOLDERS
    catalog = inventory(FOLDERS["toonzone"])
    covers = inventory(FOLDERS["covers"])
    state = restore()
    live = graph_rows(page, "instagram")
    if not isinstance(live, list):
        raise ValueError("instagram_live_list_unavailable")
    selected = select_current(catalog, state, live, covers)
    results = []
    with TemporaryDirectory(prefix="toonzone-ig-live-thumbs-") as directory:
        folder = Path(directory)
        for item in selected["entries"]:
            result = {"episode": item["episode"], "part": item["part"],
                      "source_name": item["name"], "post_id": item["archived_post_id"],
                      "status": "held", "distance": None}
            if not item["cover_id"]:
                result["reason"] = "exact_cover_missing"
            else:
                try:
                    cover = Path(download(item["cover_id"], folder / item["cover_name"]))
                    if cover != folder / item["cover_name"]:
                        raise ValueError("unexpected_cover_file_path")
                    meta = png_identity(cover)
                    observed = folder / (Path(item["name"]).stem + "-meta.jpg")
                    proof = thumbnail(page, item["archived_post_id"], observed)
                    if (str(proof.get("id") or "") != item["archived_post_id"]
                            or proof.get("media_type") != "VIDEO"
                            or not str(proof.get("permalink") or "").startswith(
                                "https://www.instagram.com/")):
                        raise ValueError("incorrect_instagram_media_identity")
                    dist = float(cover_distance(cover, observed))
                    geometric = compare_thumbnail_geometry(cover, observed)
                    best = geometric["best_distance"]
                    result.update(distance=round(dist, 6), **geometric,
                                  cover_sha256=meta["sha256"],
                                  status=("matching_original_cover"
                                          if best <= THUMBNAIL_DISTANCE_MAX
                                          else "live_thumbnail_differs_from_drive_cover"))
                except (OSError, ValueError, RuntimeError, TypeError, KeyError):
                    result["reason"] = "remote_thumbnail_or_cover_read_failed"
            results.append(result)
    passed = sum(x["status"] == "matching_original_cover" for x in results)
    distinct = sum(x["status"] == "live_thumbnail_differs_from_drive_cover" for x in results)
    uncertain = len(results) - passed - distinct
    return {
        "status": ("verified_all_currently_accessible_thumbnail_matches"
                   if passed == len(results) and len(results) > 0
                   else "held_some_current_thumbnail_mismatch_or_unavailable"),
        "historical_ig_archived": selected["archive_count"],
        "archived_post_ids_in_current_ig_media_list": selected["live_id_match_count"],
        "archived_post_ids_not_in_current_ig_media_list": selected["not_in_live_list"],
        "live_thumbnail_match_count": passed,
        "live_thumbnail_different_count": distinct,
        "live_thumbnail_unavailable_count": uncertain,
        "remote_unlisted_posts_verified": 0,
        "unlisted_ids_are_deleted": False,
        "no_meta_writes": True,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "entries": results,
    }


def main():
    from public_link_runtime import inventory, download, graph_rows, restore
    from toonzone_instagram_season import page_for_toonzone, instagram_identity
    from toonzone_instagram_first_three import thumbnail, cover_distance
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        page = page_for_toonzone()
        if str(instagram_identity(page)) != EXPECTED_INSTAGRAM_ID:
            raise ValueError("wrong_toonzone_instagram_identity")
        result = audit(page, inventory=inventory, download=download,
                       graph_rows=graph_rows, restore=restore,
                       thumbnail=thumbnail, cover_distance=cover_distance)
    except Exception as exc:
        result = {"status": "held_thumbnail_audit_unavailable",
                  "failure_class": type(exc).__name__, "no_meta_writes": True}
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k in {
        "status", "historical_ig_archived",
        "archived_post_ids_in_current_ig_media_list",
        "archived_post_ids_not_in_current_ig_media_list",
        "live_thumbnail_match_count", "live_thumbnail_different_count",
        "live_thumbnail_unavailable_count", "no_meta_writes",
    }}), flush=True)
    return 1 if result["status"] == "held_thumbnail_audit_unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
