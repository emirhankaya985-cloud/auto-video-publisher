"""Read-only all-route Meta post-ID to Google Drive inventory comparison.

Never writes provider data or publisher state. IDs missing from a bounded
provider feed are UNVERIFIED, not proof of deletions.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("all-accounts-id-drive-readonly.json")
ROUTES = {
    "tarladaki": ("humor", "Tarladaki Fasulye", ("facebook", "instagram")),
    "penguen": ("humor", "Beyinsiz Penguen", ("facebook", "instagram")),
    "gonle": ("gonle", "Gönle Düşen", ("facebook", "instagram")),
    "daily_laugh": ("daily_laugh", "Daily Laugh Lab", ("facebook", "instagram")),
    "film": ("film", "Film Mağarası", ("facebook", "instagram")),
    "film_second": ("film", "Filmmagrasi", ("facebook",)),
    "toonzone": ("toonzone", "ToonZone", ("facebook", "instagram")),
}


def analyze(state, catalogs, feeds):
    """Compare exact source ID, route, platform and remote video ID.

    A None feed means unavailable. No count of missing IDs authorizes reposting.
    """
    if state.get("schema") != 1 or not isinstance(state.get("entries"), dict):
        raise ValueError("invalid_publication_state")
    ledger = state["entries"]
    for key, row in ledger.items():
        if not isinstance(row, dict) or not isinstance(key, str):
            raise ValueError("invalid_ledger_entry")

    reports, manifest = [], []
    for route, (folder, name, platforms) in ROUTES.items():
        catalog = catalogs.get(folder)
        videos = None if catalog is None else {
            str(item["id"]): filename for filename, item in catalog.items()
            if filename.lower().endswith(".mp4") and isinstance(item, dict)
            and isinstance(item.get("id"), str)
        }
        for platform in platforms:
            feed = feeds.get((route, platform))
            if feed is not None and not isinstance(feed, set):
                raise ValueError("invalid_remote_feed")
            groups = defaultdict(list)
            for key, row in ledger.items():
                if row.get("route") == route and row.get("platform") == platform:
                    prefix = route + ":" + platform + ":"
                    if not key.startswith(prefix) or not key[len(prefix):]:
                        raise ValueError("ledger_source_identity_inconsistent")
                    groups[key[len(prefix):]].append(row)

            # Do not grant a single provider ID to multiple source videos.
            ids_by_source = defaultdict(set)
            for source, entries in groups.items():
                for row in entries:
                    if row.get("status") == "done" and str(row.get("post_id") or "").isdecimal():
                        ids_by_source[str(row["post_id"])].add(source)
            collisions = {pid for pid, sources in ids_by_source.items() if len(sources) > 1}
            receipt_ids = set(ids_by_source) - collisions
            verified_ids = receipt_ids & feed if feed is not None else set()
            not_seen_ids = receipt_ids - verified_ids if feed is not None else set()
            statuses = Counter()
            sources = set(videos or {}) | set(groups)
            for source in sorted(sources):
                entry_set = groups.get(source, [])
                done = [r for r in entry_set
                        if r.get("status") == "done"
                        and str(r.get("post_id") or "").isdecimal()]
                numeric_ids = sorted({str(r["post_id"]) for r in done})
                live_ids = [pid for pid in numeric_ids if pid in verified_ids]
                unresolved = sorted({str(r.get("status")) for r in entry_set
                                     if r.get("status") in
                                     {"held", "uncertain", "intent", "ready"}})
                if any(pid in collisions for pid in numeric_ids):
                    status = "ledger_id_collision_needs_review"
                elif live_ids:
                    status = "live_id_verified_in_correct_account_feed"
                elif numeric_ids:
                    status = ("past_receipt_not_in_feed" if feed is not None
                              else "past_receipt_remote_unavailable")
                elif unresolved:
                    status = "held_or_unverified"
                elif entry_set:
                    status = "other_ledger_state"
                else:
                    status = "drive_video_no_route_receipt"
                statuses[status] += 1
                manifest.append({
                    "route": route, "account": name, "platform": platform,
                    "file": ((videos or {}).get(source)
                             or str(entry_set[-1].get("file") or "")),
                    "drive_file_id": source,
                    "present_in_current_drive_inventory":
                        None if videos is None else source in videos,
                    "published_post_ids_from_ledger": numeric_ids,
                    "currently_observed_matching_post_ids": live_ids,
                    "unresolved_statuses": unresolved,
                    "classification": status,
                })
            reports.append({
                "route": route, "account": name, "platform": platform,
                "drive_inventory": "available" if videos is not None else "unavailable",
                "remote_feed": "available" if feed is not None else "unavailable",
                "drive_mp4_in_shared_folder": len(videos) if videos is not None else None,
                "remote_video_ids_observed": len(feed) if feed is not None else None,
                "unique_historical_post_ids": len(receipt_ids),
                "historical_id_collisions": len(collisions),
                "historical_ids_seen_live": len(verified_ids),
                "historical_ids_not_seen_in_bounded_feed":
                    len(not_seen_ids) if feed is not None else None,
                "unmatched_remote_ids":
                    len(feed - receipt_ids) if feed is not None else None,
                "drive_files_with_no_route_receipt":
                    statuses["drive_video_no_route_receipt"] if videos is not None else None,
                "drive_files_held_or_unverified":
                    statuses["held_or_unverified"] if videos is not None else None,
                "source_classifications": dict(statuses),
            })
    return {
        "schema": 1, "mode": "read_only", "provider_post_requests": 0,
        "provider_write_requests": 0, "ledger_writes": 0,
        "snapshot_scope": "Meta FB and IG only; bounded feed is not a deletion oracle",
        "accounts": reports, "videos": manifest,
    }


def main():
    if (os.getenv("GITHUB_REPOSITORY") !=
            "emirhankaya985-cloud/auto-video-publisher"
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1"):
        raise RuntimeError("untrusted_audit_context")
    from publication_github_progress import restore_publication_state
    from public_link_runtime import FOLDERS, graph_rows, inventory
    from meta_auth_loader import load_meta_auth
    state = restore_publication_state()
    pages = {p["page_name"]: p for p in load_meta_auth()["pages"]}
    catalogs, feeds, failures = {}, {}, []
    for folder in sorted({row[0] for row in ROUTES.values()}):
        try:
            catalogs[folder] = inventory(FOLDERS[folder])
        except Exception as exc:
            catalogs[folder] = None
            failures.append({"source": folder, "failure_class": type(exc).__name__})
    for route, (_, name, platforms) in ROUTES.items():
        page = pages.get(name)
        for platform in platforms:
            try:
                if not page or (platform == "instagram"
                                and not page.get("instagram_id")):
                    raise ValueError("platform_identity_missing")
                feed_rows = graph_rows(page, platform)
                ids = {str(row["id"]) for row in feed_rows}
                if any(not ident.isdecimal() for ident in ids):
                    raise ValueError("invalid_remote_id")
                feeds[(route, platform)] = ids
            except Exception as exc:
                feeds[(route, platform)] = None
                failures.append({"route": route, "platform": platform,
                                 "failure_class": type(exc).__name__})
    report = analyze(state, catalogs, feeds)
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["source_run_id"] = os.getenv("GITHUB_RUN_ID", "")
    report["read_failures"] = failures
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "mode": "read_only", "account_platforms": len(report["accounts"]),
        "source_files": len(report["videos"]), "read_failures": len(failures),
        "provider_write_requests": 0, "ledger_writes": 0,
        "account_summary": [{k: row[k] for k in
                             ("route", "platform", "unique_historical_post_ids",
                              "historical_ids_seen_live", "drive_mp4_in_shared_folder",
                              "drive_files_with_no_route_receipt")}
                            for row in report["accounts"]]},
        ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("all_accounts_id_drive_readonly_failed: " + type(exc).__name__)
        raise SystemExit(1)
