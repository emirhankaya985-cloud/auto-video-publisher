"""Owner-authorized isolated ToonZone S01E04 republishing.

Keep old historic Meta IDs intact. This new immutable campaign is independent
and at most one part is released per run, with a durable pre-POST intent.
"""
from __future__ import annotations
import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import publisher_alert_history as history

REPO = "emirhankaya985-cloud/auto-video-publisher"
WORKFLOW = ".github/workflows/toonzone_relaunch.yml"
NAMES = ("toonzone-relaunch-intent", "toonzone-relaunch-result")
ROOT = Path("toonzone-relaunch-runtime")
LEDGER = ROOT / "alert-history.json"
PLAN = ROOT / "plan.json"
CAMPAIGN = "toonzone-owner-relaunch-2026-11-10-s01e04"
FIRST_EPISODE = 4
LAST_EPISODE = 12
EPISODES = range(FIRST_EPISODE, LAST_EPISODE + 1)
PARTS = (1, 2, 3, 4)
PLATFORMS = ("facebook", "instagram")
EXPECTED_IG = "17841477404255851"
APPROVAL = Path("docs/toonzone-relaunch-approved-2026-11-10.md")
MARKER = "ToonZone re-publication approved: existing old posts will be removed later by owner."


# This precise prior intent is immutable: Meta accepted 14,427,127 upload
# bytes, but the binary endpoint returned HTTP400 while the container was
# still processing. No media_publish was attempted in run 42873941861.
RECOVERY_RUN = "42873941861"
RECOVERY_FILE = "S01E06_Meat_Your_Maker_Part2.mp4"
RECOVERY_SOURCE = "1iSkWsT2kUzUGxM8g-GuvdxzY_0Bgezjq"
RECOVERY_COVER = "1ZoabUuyA9NvlpjkFT3YZYf_G54r8rD9-"
RECOVERY_SOURCE_SHA = "9958e4231115fe95235ec7f2d343144e39d9382ed54a96b921908652607dddc0"
RECOVERY_COVER_SHA = "cdda18fbf9b94998d34c8e303b41d28b384cc97c816854eef5bca83da956e538"
RECOVERY_CONTAINER = "17912149164580142"
RECOVERY_FB_ID = "1483886187013259"


def known_ig_incident(item, record):
    """Only the archived S1E6P2 source, cover, and exact original attempt."""
    return bool(record and item.get("episode") == 6 and item.get("part") == 2
                and item.get("id") == RECOVERY_SOURCE and item.get("name") == RECOVERY_FILE
                and record.get("platform") == "instagram"
                and record.get("source_id") == RECOVERY_SOURCE
                and record.get("file") == RECOVERY_FILE
                and record.get("intent_run_id") == RECOVERY_RUN
                and record.get("cover_id") == RECOVERY_COVER
                and record.get("source_sha256") == RECOVERY_SOURCE_SHA
                and record.get("cover_sha256") == RECOVERY_COVER_SHA)


def verified_incident_media(rows, caption):
    """Recover an exact unique IG media ID only from the original attempt window."""
    from datetime import datetime, timezone
    from public_link_runtime import timestamp
    matched = matches(rows, caption)
    if len(matched) > 1:
        raise RuntimeError("relaunch_ambiguous_original_caption")
    if matched:
        posted = timestamp(matched[0]).astimezone(timezone.utc)
        earliest = datetime.fromisoformat("2026-11-10T18:22:12+00:00")
        if not (earliest <= posted <= history.now_utc()):
            raise RuntimeError("relaunch_media_outside_original_attempt")
        if not str(matched[0].get("id") or "").isdecimal():
            raise RuntimeError("relaunch_remote_identity_invalid")
    return matched


def pinned_container_status(page):
    """Read status only; never resend binary or create another container."""
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    from publisher_recovery import read_with_retry
    import requests
    response = read_with_retry(
        requests.get, f"https://graph.facebook.com/{GRAPH_API_VERSION}/{RECOVERY_CONTAINER}",
        headers={"Authorization": "Bearer " + page["page_token"]},
        params={"fields": "status_code,status"}, timeout=30, graph_read=True)
    try:
        data = response.json()
    except (ValueError, TypeError):
        raise RuntimeError("relaunch_container_response_unverified") from None
    if (response.status_code != 200 or not isinstance(data, dict)
            or data.get("error") or str(data.get("id", RECOVERY_CONTAINER)) != RECOVERY_CONTAINER):
        raise RuntimeError("relaunch_container_identity_or_read_failed")
    status = data.get("status_code")
    if status not in {"IN_PROGRESS", "FINISHED", "PUBLISHED", "ERROR", "EXPIRED"}:
        raise RuntimeError("relaunch_container_status_unverified")
    return status


def finish_existing_container(page, item, data, ledger, run_id):
    """At most one publish call to the original FINISHED container, never a new upload."""
    from cloud_omnichannel_publisher import resume_instagram_container
    from public_link_runtime import graph_rows
    fb = ledger["records"].get(record_key(item, "facebook"))
    ig = ledger["records"].get(record_key(item, "instagram"))
    if (not known_ig_incident(item, ig) or not fb
            or fb.get("status") != "verified" or str(fb.get("post_id")) != RECOVERY_FB_ID
            or ig.get("status") != "resume_reserved"
            or ig.get("resume_run_id") != run_id
            or ig.get("resume_container_id") != RECOVERY_CONTAINER
            or data.get("platforms") != ["instagram"]):
        raise RuntimeError("relaunch_original_recovery_binding_unverified")
    facebook_matches = matches(graph_rows(page, "facebook"), fb["caption"])
    if len(facebook_matches) != 1 or str(facebook_matches[0].get("id")) != RECOVERY_FB_ID:
        raise RuntimeError("relaunch_facebook_part2_unverified")
    existing = verified_incident_media(graph_rows(page, "instagram"), ig["caption"])
    if existing:
        ig.update(status="verified", post_id=str(existing[0]["id"]),
                  last_seen=history.now_utc().isoformat(),
                  reconciled_without_new_post=True)
        history.save(LEDGER, history.validate(ledger))
        print("RELAUNCH_IG_RECOVERED_EXISTING_POST_NO_NEW_POST", flush=True)
        return
    if pinned_container_status(page) != "FINISHED":
        # No media_publish occurred; leave exact old attempt awaiting a future tick.
        ig.update(status="attempted", last_seen=history.now_utc().isoformat())
        ig.pop("resume_run_id", None)
        ig.pop("resume_container_id", None)
        history.save(LEDGER, history.validate(ledger))
        print("RELAUNCH_IG_EXISTING_CONTAINER_NOT_READY_NO_POST", flush=True)
        return

    started = False
    def reserve_publish_once():
        nonlocal started
        ig.update(status="resume_publish_attempted",
                  resume_publish_run_id=run_id,
                  last_seen=history.now_utc().isoformat())
        history.save(LEDGER, history.validate(ledger))
        started = True
    try:
        post_id = resume_instagram_container(page, RECOVERY_CONTAINER, reserve_publish_once)
        if post_id is None:
            ig.update(status="attempted", last_seen=history.now_utc().isoformat())
            ig.pop("resume_run_id", None)
            ig.pop("resume_container_id", None)
            history.save(LEDGER, history.validate(ledger))
            return
        if not str(post_id).isdecimal() or not started:
            raise RuntimeError("relaunch_resume_ack_invalid")
        ig.update(status="accepted_unverified", post_id=str(post_id),
                  last_seen=history.now_utc().isoformat())
        history.save(LEDGER, history.validate(ledger))
        if verify_post(page, "instagram", str(post_id), ig["caption"]):
            ig.update(status="verified", last_seen=history.now_utc().isoformat())
            history.save(LEDGER, history.validate(ledger))
            print(f"RELAUNCH_IG_RESUME_VERIFIED media_id={post_id}", flush=True)
        else:
            print(f"RELAUNCH_IG_RESUME_ACCEPTED_NOT_YET_VISIBLE media_id={post_id}", flush=True)
    except Exception as exc:
        ig.update(error_type=type(exc).__name__, last_seen=history.now_utc().isoformat())
        history.save(LEDGER, history.validate(ledger))
        raise RuntimeError("relaunch_ig_resume_ambiguous_no_retry") from None


def allowed_context(env=None):
    env = os.environ if env is None else env
    return (env.get("GITHUB_REPOSITORY") == REPO
            and env.get("GITHUB_REF") == "refs/heads/main"
            and env.get("GITHUB_RUN_ATTEMPT") == "1"
            and env.get("TOONZONE_RELAUNCH_APPROVED") == "true")


def require_approval():
    if not allowed_context() or not APPROVAL.is_file() or MARKER not in APPROVAL.read_text(encoding="utf-8"):
        raise RuntimeError("relaunch_owner_authorization_missing")


def caption(item):
    from toonzone_instagram_first_three import text_for
    if item.get("episode") not in EPISODES or item.get("part") not in PARTS:
        raise ValueError("wrong_relaunch_source")
    return text_for(item) + f"\n\n📺 ToonZone yeniden başlangıç · S01E{item['episode']:02d} Part{item['part']} · 10.11.2026"


def record_key(item, platform):
    return history.identity(CAMPAIGN, "toonzone", platform, item["id"])


def ordered_episode(catalog):
    selected = [r for r in catalog if r["episode"] in EPISODES]
    expected = [(episode, part, True) for episode in EPISODES for part in PARTS]
    if [(r["episode"], r["part"], r["name"].endswith(f"Part{r['part']}.mp4")) for r in selected] != expected:
        raise RuntimeError("s01e04_exact_order_missing_or_ambiguous")
    if len({r["id"] for r in selected}) != len(EPISODES) * len(PARTS):
        raise RuntimeError("duplicate_relaunch_source_ids")
    return selected


def matches(rows, exact_caption):
    return [row for row in rows if (row.get("description") or row.get("caption")) == exact_caption]


def state_for(record, matched):
    """Never mistake an absent remote ID for a deletion certificate."""
    status = record.get("status")
    post_id = str(record.get("post_id") or "")
    verified_id = post_id and len([m for m in matched if str(m.get("id")) == post_id]) == 1
    if status in {"verified", "accepted_unverified"}:
        return "verified" if verified_id else "held_remote_id_unverified"
    return "held_previous_attempt_or_reservation"


def validate_remote(rows, exact_caption, previous):
    candidates = matches(rows, exact_caption)
    if len(candidates) > 1:
        raise RuntimeError("relaunch_caption_multiple_provider_posts")
    if candidates and previous is None:
        raise RuntimeError("relaunch_post_found_without_archived_intent")
    if candidates and str(candidates[0].get("id")) != str((previous or {}).get("post_id")):
        raise RuntimeError("relaunch_provider_id_mismatch")
    return candidates


def create_plan(run_id):
    require_approval()
    from public_link_runtime import FOLDERS, inventory, graph_rows, download, download_verified_publication_video
    from toonzone_instagram_season import page_for_toonzone, instagram_identity
    from threads_toonzone_season import ordered_catalog
    from toonzone_instagram_first_three import digest
    from toonzone_cover_acceptance import png_identity
    page = page_for_toonzone()
    if instagram_identity(page) != EXPECTED_IG:
        raise RuntimeError("toonzone_instagram_identity_changed")
    catalog = ordered_episode(ordered_catalog(inventory(FOLDERS["toonzone"])))
    covers = inventory(FOLDERS["covers"])
    ledger = history.validate(history.restore(names=NAMES, workflow_path=WORKFLOW))
    remote = {platform: graph_rows(page, platform) for platform in PLATFORMS}
    for item in catalog:
        text = caption(item)
        statuses = {}
        for platform in PLATFORMS:
            key = record_key(item, platform)
            previous = ledger["records"].get(key)
            if platform == "instagram" and known_ig_incident(item, previous):
                # Existing exact caption and in-window media proves publication;
                # a missing post never proves safe reupload.
                matched = verified_incident_media(remote[platform], text)
                if matched and previous.get("status") in {"attempted", "resume_publish_attempted", "resume_reserved"}:
                    previous.update(post_id=str(matched[0]["id"]), status="verified",
                                    last_seen=history.now_utc().isoformat(),
                                    reconciled_without_new_post=True)
            else:
                matched = validate_remote(remote[platform], text, previous)
            if previous:
                if (previous.get("source_id") != item["id"] or previous.get("file") != item["name"]
                        or previous.get("platform") != platform or previous.get("caption") != text):
                    raise RuntimeError("relaunch_archived_identity_changed")
                statuses[platform] = state_for(previous, matched)
                if statuses[platform] == "verified" and previous.get("status") == "accepted_unverified":
                    previous.update(status="verified", last_seen=history.now_utc().isoformat())
            else:
                statuses[platform] = "new"
        if all(value == "verified" for value in statuses.values()):
            continue
        if any(value.startswith("held") for value in statuses.values()):
            fb = ledger["records"].get(record_key(item, "facebook"))
            ig = ledger["records"].get(record_key(item, "instagram"))
            if (known_ig_incident(item, ig) and fb
                    and statuses.get("facebook") == "verified"
                    and fb.get("post_id") == RECOVERY_FB_ID
                    and statuses.get("instagram") == "held_previous_attempt_or_reservation"
                    and ig.get("status") == "attempted" and not ig.get("post_id")):
                status = pinned_container_status(page)
                if status == "FINISHED":
                    ig.update(status="resume_reserved", resume_run_id=run_id,
                              resume_container_id=RECOVERY_CONTAINER,
                              last_seen=history.now_utc().isoformat())
                    history.save(LEDGER, history.validate(ledger))
                    data = dict(run_id=run_id, item=item, mode="resume_container",
                                platforms=["instagram"])
                    history.save(PLAN, data)
                    print("RELAUNCH_IG_EXISTING_CONTAINER_RESUME_RESERVED", flush=True)
                    return data
                if status == "IN_PROGRESS":
                    history.save(LEDGER, history.validate(ledger))
                    history.save(PLAN, {"run_id": run_id, "item": None, "platforms": []})
                    print("RELAUNCH_IG_EXISTING_CONTAINER_PROCESSING_NO_POST", flush=True)
                    return None
                print(f"RELAUNCH_IG_CONTAINER_TERMINAL_HOLD status={status}", flush=True)
            history.save(LEDGER, ledger)
            raise RuntimeError(f"relaunch_part{item['part']}_requires_previous_intent_reconciliation")
        # Reserve at most one ordered part, on both independently verified accounts.
        cover_name = Path(item["name"]).stem + ".png"
        cover_file = covers.get(cover_name)
        if not cover_file:
            raise RuntimeError("relaunch_exact_original_png_missing")
        ROOT.mkdir(exist_ok=True)
        cover = download(cover_file["id"], ROOT / "original.png")
        png_identity(cover)
        with tempfile.TemporaryDirectory() as directory:
            source = download_verified_publication_video(item["id"], Path(directory) / "source.mp4")
            source_sha = digest(source)
        cover_sha = digest(cover)
        for platform in PLATFORMS:
            if statuses[platform] == "new":
                ledger["records"][record_key(item, platform)] = dict(
                    status="reserved", route="toonzone", platform=platform,
                    source_id=item["id"], file=item["name"],
                    caption=text, cover_id=cover_file["id"],
                    source_sha256=source_sha, cover_sha256=cover_sha,
                    intent_run_id=run_id, last_seen=history.now_utc().isoformat(),
                    note="owner_consented_to_republish_before_deleting_old_posts")
        history.save(LEDGER, history.validate(ledger))
        data = dict(run_id=run_id, item=item, text=text, cover_id=cover_file["id"],
                    source_sha256=source_sha, cover_sha256=cover_sha,
                    platforms=[p for p in PLATFORMS if statuses[p] == "new"])
        history.save(PLAN, data)
        print("RELAUNCH_RESERVED " + json.dumps({"episode": item["episode"], "part": item["part"],
              "platforms": data["platforms"], "external_posts": 0}), flush=True)
        return data
    history.save(LEDGER, history.validate(ledger))
    history.save(PLAN, {"run_id": run_id, "item": None, "platforms": []})
    print("RELAUNCH_SEASON1_E04_E12_ALREADY_VERIFIED", flush=True)
    return None


def verify_post(page, platform, post_id, exact_caption):
    from public_link_runtime import graph_rows
    for attempt in range(3):
        rows = graph_rows(page, platform)
        found = [x for x in rows if str(x.get("id")) == str(post_id)
                 and (x.get("description") or x.get("caption")) == exact_caption]
        if len(found) == 1:
            return True
        if attempt < 2:
            time.sleep(5)
    return False


def publish(run_id):
    require_approval()
    if os.getenv("RELAUNCH_INTENT_ARCHIVED") != "true":
        raise RuntimeError("relaunch_intent_not_archived")
    from public_link_runtime import download, download_verified_publication_video, graph_rows
    from toonzone_instagram_season import page_for_toonzone, instagram_identity
    from toonzone_instagram_first_three import digest
    from cloud_omnichannel_publisher import upload_facebook_reel, upload_instagram_reel, create_instagram_cover_video
    from instagram_media_compat import prepare_instagram_upload
    from toonzone_cover_acceptance import png_identity, verify_prepared_instagram_first_frame
    data = history.read(PLAN)
    ledger = history.validate(history.read(LEDGER))
    if data.get("run_id") != run_id:
        raise RuntimeError("relaunch_run_id_changed")
    item = data.get("item")
    if item is None:
        return
    if item.get("episode") not in EPISODES or item.get("part") not in PARTS:
        raise RuntimeError("relaunch_episode_mismatch")
    page = page_for_toonzone()
    if instagram_identity(page) != EXPECTED_IG:
        raise RuntimeError("relaunch_instagram_identity_changed")
    platforms = data["platforms"]
    if not isinstance(platforms, list) or not platforms or not set(platforms).issubset(PLATFORMS):
        raise RuntimeError("relaunch_platforms_invalid")
    if data.get("mode") == "resume_container":
        finish_existing_container(page, item, data, ledger, run_id)
        return
    with tempfile.TemporaryDirectory(prefix="toonzone-relaunch-") as directory:
        temp = Path(directory)
        source = download_verified_publication_video(item["id"], temp / "source.mp4")
        cover = download(data["cover_id"], temp / "original.png")
        png_identity(cover)
        if digest(source) != data["source_sha256"] or digest(cover) != data["cover_sha256"]:
            raise RuntimeError("relaunch_source_or_original_cover_changed")
        covered = create_instagram_cover_video(source, cover, temp / "covered.mp4", preserve_full_cover=True)
        prepared = None
        if "instagram" in platforms:
            prepared = prepare_instagram_upload(covered, temp / "instagram.mp4", toonzone_compact=True)
            verify_prepared_instagram_first_frame(cover, prepared)
        for platform in platforms:
            key = record_key(item, platform)
            record = ledger["records"][key]
            if (record["status"] != "reserved" or record["intent_run_id"] != run_id
                    or record["source_sha256"] != data["source_sha256"]
                    or record["cover_sha256"] != data["cover_sha256"]
                    or record["caption"] != data["text"]):
                raise RuntimeError("relaunch_intent_binding_changed")
            if matches(graph_rows(page, platform), data["text"]):
                raise RuntimeError("relaunch_remote_post_detected_before_write")
            record.update(status="attempted", last_seen=history.now_utc().isoformat())
            history.save(LEDGER, ledger)
            print(f"RELAUNCH_ATTEMPT platform={platform} episode={item['episode']} part={item['part']}", flush=True)
            try:
                post_id = (upload_facebook_reel(page, str(covered), data["text"])
                           if platform == "facebook" else
                           upload_instagram_reel(page, str(prepared), data["text"],
                                                 append_store_link=False, thumb_offset=0))
                post_id = str(post_id)
                if not post_id.isdecimal():
                    raise RuntimeError("relaunch_post_id_not_numeric")
                record.update(status="accepted_unverified", post_id=post_id,
                              last_seen=history.now_utc().isoformat())
                history.save(LEDGER, ledger)
                if verify_post(page, platform, post_id, data["text"]):
                    record.update(status="verified", last_seen=history.now_utc().isoformat())
                    history.save(LEDGER, ledger)
                    print(f"RELAUNCH_VERIFIED platform={platform} episode={item['episode']} part={item['part']} post_id={post_id}", flush=True)
                else:
                    print(f"RELAUNCH_ACCEPTED_NOT_YET_VISIBLE platform={platform} episode={item['episode']} part={item['part']} post_id={post_id}", flush=True)
            except Exception as exc:
                record.update(error_type=type(exc).__name__, last_seen=history.now_utc().isoformat())
                history.save(LEDGER, ledger)
                raise RuntimeError("relaunch_post_ambiguous_no_retry") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "publish"))
    args = parser.parse_args()
    run_id = os.environ["GITHUB_RUN_ID"]
    if not run_id.isdecimal():
        raise RuntimeError("unverified_run_id")
    create_plan(run_id) if args.mode == "plan" else publish(run_id)


if __name__ == "__main__":
    main()
