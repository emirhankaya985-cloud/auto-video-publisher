"""Owner-requested ToonZone S01E04-S01E08 (20 parts) with strict preflight.

Never repeats an uncertain Meta POST, never resets prior state, and never
assumes a historical post proves the same original source. A read-only audit
must pass before any separately gated production release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import publisher_alert_history as history
from threads_toonzone_season import ordered_catalog
from toonzone_instagram_season import page_for_toonzone, instagram_identity
from toonzone_instagram_first_three import text_for, digest, cover_distance, thumbnail

WORKFLOW = ".github/workflows/toonzone_episodes_4_8.yml"
NAMES = ("toonzone-4-8-intent", "toonzone-4-8-result")
ROOT = Path("toonzone-4-8-runtime")
HISTORY = ROOT / "alert-history.json"
PLAN = ROOT / "plan.json"
REPORT = ROOT / "audit.json"
CAMPAIGN = "toonzone-instagram-s01e04-s01e08-20261106"
ACCOUNT_ID = "17841477404255851"
EXPECTED = [(episode, part) for episode in range(4, 9) for part in range(1, 5)]
PUBLISHED_SLOT = re.compile(r"\bS01E(?P<episode>\d{2})\b.*?\bPart\s*(?P<part>[1-4])\b", re.I | re.S)
EXACT_PART = re.compile(r"Sezon\s*1\s*[•·]\s*Bölüm\s*(?P<episode>\d+)\s*[•·]\s*Part\s*(?P<part>[1-4])\s*/4", re.I)


def selected(catalog):
    items = [row for row in catalog if 4 <= row["episode"] <= 8]
    if [(r["episode"], r["part"]) for r in items] != EXPECTED:
        raise RuntimeError("target_catalog_missing_or_out_of_order")
    if len({r["id"] for r in items}) != 20:
        raise RuntimeError("reused_source_drive_identity")
    return items


def published_slot(caption):
    if not isinstance(caption, str):
        return None
    for match in (EXACT_PART.search(caption), PUBLISHED_SLOT.search(caption)):
        if match:
            slot = int(match["episode"]), int(match["part"])
            return slot if slot in EXPECTED else None
    return None


def conflicts(live, existing):
    """Fail closed on any target slot already on Instagram, even old campaigns."""
    live_ids = {}
    found = {}
    for row in live:
        pid = str(row.get("id") or "")
        if not pid.isdecimal():
            raise RuntimeError("live_instagram_media_identity_unverified")
        if pid in live_ids:
            raise RuntimeError("duplicate_live_instagram_media")
        live_ids[pid] = row
        slot = published_slot(row.get("caption"))
        if slot:
            found.setdefault(slot, []).append(pid)
    verified = set()
    for row in existing.values():
        if not isinstance(row, dict):
            raise RuntimeError("invalid_campaign_history")
        if row.get("status") != "verified" or not str(row.get("post_id", "")).isdecimal():
            raise RuntimeError("previous_campaign_attempt_unresolved")
        pid = str(row["post_id"])
        live_row = live_ids.get(pid)
        if not live_row:
            raise RuntimeError("previous_verified_post_missing_from_live")
        slot = published_slot(live_row.get("caption"))
        if slot is None or row.get("caption") != live_row.get("caption"):
            raise RuntimeError("previous_verified_caption_changed")
        verified.add(slot)
    # Do not resume around old/unrelated media, even if it has the same title.
    if any(len(ids) != 1 or slot not in verified for slot, ids in found.items()):
        raise RuntimeError("target_part_already_live_unreconciled")
    return verified


def preflight_sources(items):
    """Read and validate every pending source before reserving any provider write.

    Keep only hashes, not twenty potentially large MP4s. Publication downloads
    must match these bytes, so a replaced Drive file cannot silently pass.
    """
    from public_link_runtime import download_verified_publication_video
    result = []
    with tempfile.TemporaryDirectory(prefix="toonzone-source-preflight-") as directory:
        for item in items:
            path = download_verified_publication_video(item["id"], Path(directory) / "source.mp4")
            result.append(dict(item, source_sha256=digest(path)))
            path.unlink()
    return result


def verify_reserved_source(source, item, record):
    expected = record.get("source_sha256")
    if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
            or item.get("source_sha256") != expected or digest(source) != expected):
        raise RuntimeError("source_changed_since_preflight")


def audit(run_id, *, reserve=False):
    from public_link_runtime import FOLDERS, inventory, graph_rows, download, probe
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    if user_id != ACCOUNT_ID:
        raise RuntimeError("toonzone_instagram_identity_changed")
    items = selected(ordered_catalog(inventory(FOLDERS["toonzone"])))
    covers = inventory(FOLDERS["covers"])
    archive = history.restore(names=NAMES, workflow_path=WORKFLOW)
    live = graph_rows(page, "instagram")
    if not isinstance(live, list):
        raise RuntimeError("instagram_live_history_unavailable")
    already = conflicts(live, archive["records"])
    records = archive["records"]
    prepared = []
    (ROOT / "covers").mkdir(parents=True, exist_ok=True)
    for row in items:
        key = history.identity(CAMPAIGN, "toonzone", "instagram", row["id"])
        if (row["episode"], row["part"]) in already:
            recorded = records.get(key)
            if not recorded or recorded.get("source_id") != row["id"] or recorded.get("file") != row["name"]:
                raise RuntimeError("previous_source_identity_changed")
            continue
        name = Path(row["name"]).stem + ".png"
        cover = covers.get(name)
        if not cover:
            raise RuntimeError("exact_drive_cover_missing")
        path = download(cover["id"], ROOT / "covers" / name)
        if not any(x.get("codec_type") == "video" and x.get("width", 0) > 0
                   for x in probe(path).get("streams", [])):
            raise RuntimeError("exact_cover_unreadable")
        caption = text_for(row)
        prepared.append(dict(row, key=key, text=caption, cover_id=cover["id"],
                             cover_path=str(path), cover_sha256=digest(path)))
    prepared = preflight_sources(prepared)
    report = {"run_id": run_id, "target_episodes": [4, 5, 6, 7, 8],
              "expected_parts": 20, "previously_verified": len(already),
              "prepared_parts": len(prepared), "exact_covers_verified": len(prepared),
              "source_files_verified": len(prepared),
              "instagram_identity_verified": True, "live_history_read": True,
              "publication_authorized": reserve,
              "posts_created": 0}
    ROOT.mkdir(exist_ok=True)
    history.save(REPORT, report)
    if not reserve:
        print(json.dumps(report), flush=True)
        return report
    if os.getenv("TOONZONE_RIGHTS_APPROVED") != "true":
        raise RuntimeError("toonzone_rights_approval_not_verified")
    if os.getenv("TOONZONE_RELEASE_4_8") != "true":
        raise RuntimeError("toonzone_episode_release_not_authorized")
    if not prepared:
        print(json.dumps({**report, "status": "already_verified", "posts_created": 0}), flush=True)
        history.save(PLAN, {"run_id": run_id, "user_id": user_id, "plans": []})
        history.save(HISTORY, history.validate(archive))
        return report
    # Complete-source/caption/cover preflight before reserving even one POST.
    for item in prepared:
        records[item["key"]] = {"status": "reserved", "intent_run_id": run_id,
            "user_id": user_id, "platform": "instagram", "route": "toonzone",
            "source_id": item["id"], "file": item["name"], "cover_id": item["cover_id"],
            "source_sha256": item["source_sha256"],
            "cover_sha256": item["cover_sha256"], "caption": item["text"],
            "last_seen": history.now_utc().isoformat()}
    history.save(HISTORY, history.validate(archive))
    history.save(PLAN, {"run_id": run_id, "user_id": user_id, "plans": prepared})
    print(json.dumps({**report, "status": "reserved_no_provider_writes"}), flush=True)
    return report


def publish(run_id):
    if os.getenv("TOONZONE_INTENT_ARCHIVED") != "true":
        raise RuntimeError("toonzone_intent_not_archived")
    if os.getenv("TOONZONE_RIGHTS_APPROVED") != "true" or os.getenv("TOONZONE_RELEASE_4_8") != "true":
        raise RuntimeError("toonzone_release_gate_closed")
    from public_link_runtime import download_verified_publication_video
    from cloud_omnichannel_publisher import create_instagram_cover_video, upload_instagram_reel
    from instagram_media_compat import prepare_instagram_upload
    from publisher_recovery import classify_meta_failure
    data = history.read(PLAN)
    archive = history.validate(history.read(HISTORY))
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    if user_id != ACCOUNT_ID or data.get("run_id") != run_id or data.get("user_id") != user_id:
        raise RuntimeError("toonzone_release_identity_mismatch")
    plans = data.get("plans")
    if not isinstance(plans, list) or len(plans) > 20:
        raise RuntimeError("invalid_release_plan")
    for item in plans:
        record = archive["records"][item["key"]]
        if (record["status"] != "reserved" or record["intent_run_id"] != run_id
                or record["user_id"] != user_id or record["source_id"] != item["id"]
                or record["caption"] != item["text"] or digest(item["cover_path"]) != record["cover_sha256"]):
            raise RuntimeError("reservation_changed")
        try:
            with tempfile.TemporaryDirectory(prefix="toonzone-4-8-") as d:
                d = Path(d)
                source = download_verified_publication_video(item["id"], d / "source.mp4")
                verify_reserved_source(source, item, record)
                covered = create_instagram_cover_video(source, Path(item["cover_path"]), d / "covered.mp4",
                                                       preserve_full_cover=True)
                video = prepare_instagram_upload(covered, d / "upload.mp4", toonzone_compact=True)
                frame = d / "first.jpg"
                subprocess.run(["ffmpeg", "-y", "-i", str(video), "-frames:v", "1", str(frame)],
                               capture_output=True, check=True, timeout=60)
                distance = cover_distance(Path(item["cover_path"]), frame)
                if distance > 0.12:
                    raise RuntimeError("first_frame_cover_mismatch")
                record.update(status="attempted", upload_sha256=digest(video), prepared_cover_distance=distance)
                history.save(HISTORY, archive)
                post_id = str(upload_instagram_reel(page, str(video), item["text"],
                                                   append_store_link=False, thumb_offset=0))
                if not post_id.isdecimal():
                    raise RuntimeError("instagram_post_id_missing")
                record["post_id"] = post_id
                history.save(HISTORY, archive)
                output = ROOT / (Path(item["name"]).stem + ".jpg")
                evidence = thumbnail(page, post_id, output)
                image_distance = cover_distance(frame, output, reference_is_frame=True)
                if (evidence.get("caption") != item["text"] or evidence.get("media_type") != "VIDEO"
                    or not str(evidence.get("permalink") or "").startswith("https://www.instagram.com/")
                    or image_distance > 0.12):
                    raise RuntimeError("live_cover_or_caption_not_verified")
                record.update(status="verified", permalink=evidence["permalink"],
                              instagram_cover_distance=image_distance)
                history.save(HISTORY, archive)
                print(f"TOONZONE_PART_VERIFIED episode={item['episode']} part={item['part']} id={post_id}", flush=True)
        except Exception as exc:
            record.update(diagnostic=classify_meta_failure(exc), failure_type=type(exc).__name__)
            history.save(HISTORY, archive)
            print(json.dumps({"stopped_episode": item["episode"], "part": item["part"],
                              "error_type": type(exc).__name__, "retry_allowed": False}), flush=True)
            raise RuntimeError("stopped_before_next_part_no_blind_retry") from None
    completed = [x for x in archive["records"].values() if x.get("status") == "verified"]
    result = {"completed_posts": len(completed), "expected": 20,
              "status": "verified" if len(completed) == 20 else "partial"}
    history.save(ROOT / "result.json", result)
    print(json.dumps(result), flush=True)
    if len(completed) == 20:
        from telegram_notifications import send_telegram
        try:
            send_telegram("✅ ToonZone 4–8 tamamlandı",
                          "Instagram: Sezon 1, 4–8. bölümler; 20/20 Part, doğrulanmış post ID ve kapak. "
                          f"Kanıt: https://github.com/{history.REPO}/actions/runs/{run_id}")
        except Exception:
            print('{"telegram_ack":false}', flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["audit", "reserve", "publish"])
    mode = p.parse_args().command
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if not run_id.isdecimal():
        raise SystemExit("invalid_run_id")
    if mode == "publish":
        publish(run_id)
    else:
        audit(run_id, reserve=(mode == "reserve"))
