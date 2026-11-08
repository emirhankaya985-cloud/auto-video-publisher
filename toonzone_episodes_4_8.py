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


def season_inventory_coverage(catalog, covers):
    """Account for all 36 owner-requested source/cover names without provider writes.

    A matching Drive filename is readiness evidence, NOT proof that the
    bytes are genuine, readable, or currently authorized for publication.
    """
    target = [item for item in catalog if 4 <= item["episode"] <= 12]
    expected = [(episode, part) for episode in range(4, 13) for part in range(1, 5)]
    if [(item["episode"], item["part"]) for item in target] != expected:
        raise RuntimeError("requested_season_catalog_incomplete")
    if len({item["id"] for item in target}) != 36:
        raise RuntimeError("requested_season_source_identity_collision")
    missing = [Path(item["name"]).stem + ".png" for item in target
               if Path(item["name"]).stem + ".png" not in covers]
    return {"requested_4_12_parts": 36,
            "source_names_found_4_12": len(target),
            "cover_names_found_4_12": 36 - len(missing),
            "missing_cover_names_4_12": missing,
            "cover_bytes_verified_4_12": False}


def facebook_caption_candidates(rows):
    """Read-only candidates only; never equate captions with source/post proof."""
    slots = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("description") or row.get("caption") or "")
        episode = re.search(r"\bS01E(\d{2})\b", text, re.I)
        part = re.search(r"\bPart\s*([1-4])\b", text, re.I)
        if episode and part and 4 <= int(episode[1]) <= 12:
            slots.add((int(episode[1]), int(part[1])))
    return {"facebook_live_list_read": True,
            "facebook_caption_candidate_count_4_12": len(slots),
            "facebook_caption_candidate_slots_4_12":
                [f"S01E{episode:02d} Part{part}" for episode, part in sorted(slots)],
            "facebook_source_identity_verified": False}


class MainPublisherLiveMissing(RuntimeError):
    """Provider GET cannot confirm main-ledger posts; never publish them again."""

    def __init__(self, records):
        super().__init__("main_publisher_post_missing_from_live")
        self.records = records


def main_publisher_posts(items, live, state):
    """Verify old regular-publisher IDs by exact account, Drive ID and live GET.

    This separate 4-8 campaign must not re-post clips already confirmed by the
    normal Meta publisher. Older ledger rows need not have a source digest:
    only skip their exact source IDs, never infer a fresh publishing approval.
    Missing/corrupt archives and unmatched provider IDs fail closed.
    """
    if not isinstance(state, dict) or state.get("schema") != 1 or not isinstance(state.get("entries"), dict):
        raise RuntimeError("main_publisher_ledger_unavailable")
    live_by_id = {}
    for row in live:
        if not isinstance(row, dict) or not str(row.get("id") or "").isdecimal():
            raise RuntimeError("main_publisher_live_identity_invalid")
        pid = str(row["id"])
        if pid in live_by_id:
            raise RuntimeError("main_publisher_duplicate_live_identity")
        live_by_id[pid] = row
    result = {}
    used_ids = set()
    missing_live = []
    for item in items:
        key = f"toonzone:instagram:{item['id']}"
        entry = state["entries"].get(key)
        if entry is None:
            continue
        if (not isinstance(entry, dict) or entry.get("route") != "toonzone"
                or entry.get("platform") != "instagram"
                or entry.get("file") != item["name"]):
            raise RuntimeError("main_publisher_source_identity_conflict")
        pid = str(entry.get("post_id") or "")
        if entry.get("status") != "done" or not pid.isdecimal():
            raise RuntimeError("main_publisher_prior_intent_unresolved")
        if pid not in live_by_id:
            missing_live.append({"episode": item["episode"], "part": item["part"],
                                 "file": item["name"], "source_id": item["id"],
                                 "archived_post_id": pid})
            continue
        slot = item["episode"], item["part"]
        caption_slot = published_slot(live_by_id[pid].get("caption"))
        if caption_slot is not None and caption_slot != slot:
            raise RuntimeError("main_publisher_live_caption_slot_mismatch")
        if pid in used_ids or slot in result:
            raise RuntimeError("main_publisher_duplicate_post_or_slot")
        result[slot] = pid
        used_ids.add(pid)
    if missing_live:
        # Fail closed even when some other IDs are found: never partially
        # reserve an old season against incomplete remote history.
        raise MainPublisherLiveMissing(missing_live)
    return result




def individual_get_positive_control(live, page, *, get=None):
    """Test the exact per-ID Graph query against a confirmed listed IG video.

    If the positive control also fails, old ID failures do not diagnose
    deletion. Compare the full query with the same safe query minus owner
    to distinguish an unsupported field from a token/read-scope failure.
    No publication endpoints are used. Never emit provider error messages.
    """
    import requests
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    from publisher_recovery import read_with_retry

    get = get or requests.get
    if not isinstance(live, list) or not live:
        return {"status": "no_listed_media_for_control"}
    known = str(live[0].get("id") or "")
    if not known.isdecimal():
        return {"status": "invalid_listed_media_identity"}
    if not isinstance(page, dict) or not page.get("page_token"):
        return {"status": "page_token_missing"}
    outcome = {"listed_media_id": known, "status": "tested"}
    variants = (
        ("with_owner", "id,caption,media_type,permalink,timestamp,owner"),
        ("basic", "id,caption,media_type,permalink,timestamp"),
    )
    for label, fields in variants:
        response = None
        detail = {"status": "unavailable"}
        try:
            response = read_with_retry(
                get, f"https://graph.facebook.com/{GRAPH_API_VERSION}/{known}",
                headers={"Authorization": "Bearer " + page["page_token"]},
                params={"fields": fields}, timeout=25,
                allow_redirects=False, graph_read=True,
            )
            http = getattr(response, "status_code", None)
            detail["http_status"] = http if type(http) is int else None
            try:
                body = response.json()
            except (ValueError, TypeError, AttributeError):
                body = None
            if isinstance(body, dict):
                error = body.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                if type(code) is int:
                    detail["graph_error_code"] = code
                if http == 200 and str(body.get("id") or "") == known:
                    detail["status"] = "exact_id_readable"
                    owner = body.get("owner")
                    owner_id = str(owner.get("id") or "") if isinstance(owner, dict) else str(owner or "")
                    if owner_id.isdecimal():
                        detail["returned_owner_id"] = owner_id
                elif http == 200:
                    detail["status"] = "returned_identity_mismatch"
                else:
                    detail["status"] = "read_rejected"
            else:
                detail["status"] = "invalid_provider_response"
        except (OSError, RuntimeError, ValueError, TypeError):
            detail["status"] = "read_exception"
        finally:
            if response is not None:
                closer = getattr(response, "close", None)
                if callable(closer):
                    closer()
        outcome[label] = detail
    return outcome



def direct_probe_missing_main_posts(records, page, account_id, state, *, get=None):
    """Read-only per-ID Graph reconciliation for list-missing ToonZone posts.

    An unavailable media list, an HTTP 400, or a 404 never proves deletion or
    authorizes reposting. A VERIFIED outcome requires the exact archived ID,
    same IG owner, VIDEO type, timestamp, permalink and saved caption hash.
    Return only sanitized diagnostics; never include access tokens/API bodies.
    """
    import requests
    from datetime import datetime
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    from public_link_runtime import caption_key
    from publisher_recovery import read_with_retry

    get = get or requests.get
    if not isinstance(account_id, str) or not account_id.isdecimal():
        raise RuntimeError("toonzone_expected_ig_account_invalid")
    if not isinstance(page, dict) or not str(page.get("page_id") or "").isdecimal():
        raise RuntimeError("toonzone_page_identity_invalid")
    if not isinstance(page.get("page_token"), str) or not page["page_token"]:
        raise RuntimeError("toonzone_page_credential_unavailable")
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise RuntimeError("toonzone_main_ledger_invalid")
    evidence = []
    for row in records:
        key = f"toonzone:instagram:{row['source_id']}"
        old = state["entries"].get(key)
        if (not isinstance(old, dict) or old.get("status") != "done"
                or old.get("route") != "toonzone" or old.get("platform") != "instagram"
                or old.get("file") != row["file"]
                or str(old.get("post_id") or "") != row["archived_post_id"]):
            raise RuntimeError("toonzone_main_record_changed_during_probe")
        post_id = str(row["archived_post_id"])
        if not post_id.isdecimal():
            raise RuntimeError("toonzone_media_id_not_numeric")
        result = {
            "episode": row["episode"], "part": row["part"],
            "file": row["file"], "source_id": row["source_id"],
            "archived_post_id": post_id,
            "expected_instagram_account_id": account_id,
            "status": "ambiguous", "reason": "not_yet_probed",
            "method": "individual_graph_get",
        }
        response = None
        try:
            response = read_with_retry(
                get, f"https://graph.facebook.com/{GRAPH_API_VERSION}/{post_id}",
                headers={"Authorization": "Bearer " + page["page_token"]},
                params={"fields": "id,caption,media_type,permalink,timestamp,owner"},
                timeout=25, allow_redirects=False, graph_read=True,
            )
            status_code = getattr(response, "status_code", None)
            result["http_status"] = status_code if type(status_code) is int else None
            try:
                body = response.json()
            except (ValueError, TypeError, AttributeError):
                body = None
            if not isinstance(body, dict):
                result["reason"] = "invalid_provider_response"
            elif status_code != 200 or "error" in body:
                error = body.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                result["graph_error_code"] = code if type(code) is int else None
                if status_code in (401, 403) or code in (190, 10, 200):
                    result.update(status="access_blocked",
                                  reason="meta_permission_or_token_blocked")
                elif status_code == 404:
                    # A 404 is NOT proof of deletion: Graph also hides objects
                    # when a token cannot access them.
                    result.update(status="not_found",
                                  reason="id_not_found_or_inaccessible_not_deletion_proof")
                else:
                    result["reason"] = "meta_get_failed_or_ambiguous"
            elif str(body.get("id") or "") != post_id:
                result["reason"] = "returned_id_mismatch"
            else:
                owner = body.get("owner")
                owner_id = str(owner.get("id") or "") if isinstance(owner, dict) else str(owner or "")
                if owner_id.isdecimal():
                    result["returned_owner_id"] = owner_id
                media_type = body.get("media_type")
                result["media_type"] = media_type if isinstance(media_type, str) else None
                permalink = body.get("permalink")
                if isinstance(permalink, str) and permalink.startswith("https://www.instagram.com/"):
                    result["permalink"] = permalink
                stamp = body.get("timestamp")
                if isinstance(stamp, str):
                    try:
                        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                        if dt.tzinfo is not None:
                            result["timestamp"] = stamp
                    except ValueError:
                        pass
                caption = body.get("caption")
                saved_hash = old.get("caption_hash")
                if owner_id != account_id:
                    result["reason"] = ("wrong_instagram_account"
                                        if owner_id.isdecimal() else "owner_id_unavailable")
                elif media_type != "VIDEO":
                    result["reason"] = "not_video_or_media_type_unavailable"
                elif "timestamp" not in result or "permalink" not in result:
                    result["reason"] = "media_metadata_incomplete"
                elif (not isinstance(caption, str)
                      or not isinstance(saved_hash, str)
                      or caption_key(caption) != saved_hash):
                    result["reason"] = "archived_caption_hash_not_confirmed"
                else:
                    result.update(status="verified", reason="exact_id_account_video_caption")
        except (OSError, RuntimeError, ValueError, TypeError):
            result["reason"] = "individual_graph_get_unavailable"
        finally:
            if response is not None:
                closer = getattr(response, "close", None)
                if callable(closer):
                    closer()
        evidence.append(result)
    return evidence




def probe_ig_without_owner(individual, page, account_id, state, *, get=None):
    """Second independent read of code-100 IG IDs with username, not owner.

    Graph may reject a media node's owner field independently of the media
    itself. Only the SAME media ID, canonical account username, VIDEO, matching
    saved caption hash, valid timestamp and permalink can confirm a post.
    A successful bare GET without username is evidence, not account proof.
    No provider writes, no token or error-message logging.
    """
    import requests
    from datetime import datetime
    from public_link_runtime import caption_key
    from publisher_recovery import read_with_retry
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    from toonzone_instagram_season import graph_get

    rows = [row for row in individual if row.get("status") == "ambiguous"
            and row.get("graph_error_code") == 100]
    if not rows:
        return individual
    try:
        account = graph_get(page, account_id, "id,username")
        expected = str(account.get("username") or "").casefold().lstrip("@")
        if str(account.get("id") or "") != account_id or not expected:
            raise ValueError("missing canonical profile")
    except (OSError, RuntimeError, ValueError, TypeError):
        for row in rows:
            row["basic_read_status"] = "canonical_profile_unavailable"
        return individual

    get = get or requests.get
    for row in rows:
        old = state["entries"].get(f"toonzone:instagram:{row['source_id']}")
        if (not isinstance(old, dict) or old.get("status") != "done"
                or str(old.get("post_id") or "") != row["archived_post_id"]):
            raise RuntimeError("toonzone_archive_changed_before_basic_probe")
        post_id = row["archived_post_id"]
        row["basic_read_status"] = "unverified"
        for label, fields in (
            ("with_username", "id,caption,media_type,permalink,timestamp,username"),
            ("basic", "id,caption,media_type,permalink,timestamp"),
        ):
            response = None
            try:
                response = read_with_retry(
                    get, f"https://graph.facebook.com/{GRAPH_API_VERSION}/{post_id}",
                    headers={"Authorization": "Bearer " + page["page_token"]},
                    params={"fields": fields}, timeout=25, allow_redirects=False,
                    graph_read=True,
                )
                status = getattr(response, "status_code", None)
                body = response.json()
                row["basic_read_http_status"] = status if type(status) is int else None
                if not isinstance(body, dict):
                    row["basic_read_status"] = "invalid_provider_response"
                    break
                if status != 200 or "error" in body:
                    error = body.get("error")
                    code = error.get("code") if isinstance(error, dict) else None
                    subcode = error.get("error_subcode") if isinstance(error, dict) else None
                    row["basic_read_graph_code"] = code if type(code) is int else None
                    row["basic_read_graph_subcode"] = subcode if type(subcode) is int else None
                    if label == "with_username" and code == 100:
                        continue  # A field-level code 100 warrants only a no-owner read.
                    row["basic_read_status"] = "provider_rejected"
                    break
                if str(body.get("id") or "") != post_id:
                    row["basic_read_status"] = "id_mismatch"
                    break
                caption = body.get("caption")
                stamp = body.get("timestamp")
                permalink = body.get("permalink")
                try:
                    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    valid_date = dt.tzinfo is not None
                except (TypeError, AttributeError, ValueError):
                    valid_date = False
                if (body.get("media_type") != "VIDEO" or not valid_date
                        or not isinstance(permalink, str)
                        or not permalink.startswith("https://www.instagram.com/")
                        or not isinstance(caption, str)
                        or published_slot(caption) != (row["episode"], row["part"])
                        or not isinstance(old.get("caption_hash"), str)
                        or caption_key(caption) != old["caption_hash"]):
                    row["basic_read_status"] = "media_or_saved_source_mismatch"
                    break
                if label == "basic":
                    row["basic_read_status"] = "readable_but_owner_unconfirmed"
                    break
                returned_username = str(body.get("username") or "").casefold().lstrip("@")
                if not returned_username or returned_username != expected:
                    row["basic_read_status"] = "username_mismatch_or_missing"
                    break
                row["status"] = "verified"
                row["reason"] = "exact_id_canonical_username_video_caption"
                row["basic_read_status"] = "verified"
                # Internal in-memory value, stripped before writing the redacted audit.
                row["_verified_caption"] = caption
                break
            except (OSError, RuntimeError, ValueError, TypeError):
                row["basic_read_status"] = "read_exception"
                break
            finally:
                if response is not None:
                    closer = getattr(response, "close", None)
                    if callable(closer):
                        closer()
    return individual


def conflicts(live, existing, main_posts=None):
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
    main_posts = main_posts or {}
    verified = set(main_posts)
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
    if any(len(ids) != 1 or slot not in verified
           or (slot in main_posts and main_posts[slot] != ids[0])
           for slot, ids in found.items()):
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


def release_authorized(reserve, *, environ=None):
    """Only claim approval after BOTH owner-controlled gates are verified."""
    env = os.environ if environ is None else environ
    return bool(reserve and env.get("TOONZONE_RIGHTS_APPROVED") == "true"
                and env.get("TOONZONE_RELEASE_4_8") == "true")



def historical_publish_receipts(records, main_state, *, registry_path=None):
    """Archive-vs-original-Graph-receipt check, never a CURRENT live-media proof.

    The file is grounded in the twenty original publisher job logs that
    recorded both Meta media_publish acceptance and a real Reel permalink.
    A registry match cannot bypass any read-only GET, reserve or publish gate.
    """
    registry_path = registry_path or (
        Path(__file__).resolve().parent / "docs"
        / "toonzone-4-8-original-instagram-publish-receipts.json"
    )
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("historical_publish_receipts_unavailable") from None
    if (not isinstance(data, dict) or data.get("schema") != 1
            or data.get("platform") != "instagram" or data.get("account") != "ToonZone"
            or not isinstance(data.get("records"), list)
            or len(data["records"]) != 20):
        raise RuntimeError("historical_publish_receipts_invalid")
    by_slot = {}
    used_ids = set()
    for row in data["records"]:
        if not isinstance(row, dict):
            raise RuntimeError("historical_publish_receipts_invalid")
        slot = row.get("episode"), row.get("part")
        if (slot not in EXPECTED or slot in by_slot
                or not str(row.get("post_id") or "").isdecimal()
                or not str(row.get("source_run_id") or "").isdecimal()
                or str(row["post_id"]) in used_ids
                or not re.fullmatch(
                    r"https://www\.instagram\.com/reel/[A-Za-z0-9_-]+/",
                    str(row.get("permalink") or ""),
                )
                or not isinstance(row.get("source_file"), str)
                or not row["source_file"].startswith(f"S01E{slot[0]:02d}_")
                or not row["source_file"].endswith(f"_Part{slot[1]}.mp4")):
            raise RuntimeError("historical_publish_receipts_invalid")
        by_slot[slot] = row
        used_ids.add(str(row["post_id"]))
    if len(by_slot) != len(EXPECTED):
        raise RuntimeError("historical_publish_receipts_incomplete")
    if not isinstance(main_state, dict) or not isinstance(main_state.get("entries"), dict):
        raise RuntimeError("historical_main_ledger_unavailable")
    matched = 0
    for missing in records:
        slot = missing.get("episode"), missing.get("part")
        row = by_slot.get(slot)
        ledger = main_state["entries"].get(
            f"toonzone:instagram:{missing.get('source_id')}"
        )
        if (row is not None and isinstance(ledger, dict)
                and row["source_file"] == missing.get("file")
                and str(row["post_id"]) == str(missing.get("archived_post_id"))
                and ledger.get("file") == row["source_file"]
                and str(ledger.get("post_id")) == str(row["post_id"])
                and str(ledger.get("run_id")) == str(row["source_run_id"])
                and ledger.get("route") == "toonzone"
                and ledger.get("platform") == "instagram"
                and ledger.get("status") == "done"):
            matched += 1
    return {
        "historical_publish_receipts_matching_ledger": matched,
        "historical_publish_receipts_checked": len(records),
        "historical_publish_reel_urls_available": matched,
        "current_live_verified_by_historical_receipts": 0,
        "historical_only": True,
        "receipt_registry": str(Path(registry_path).name),
    }


def audit(run_id, *, reserve=False):
    from public_link_runtime import FOLDERS, inventory, graph_rows, download, probe, restore as restore_main
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    if user_id != ACCOUNT_ID:
        raise RuntimeError("toonzone_instagram_identity_changed")
    catalog = ordered_catalog(inventory(FOLDERS["toonzone"]))
    items = selected(catalog)
    covers = inventory(FOLDERS["covers"])
    inventory_coverage = season_inventory_coverage(catalog, covers)
    archive = history.restore(names=NAMES, workflow_path=WORKFLOW)
    live = graph_rows(page, "instagram")
    if not isinstance(live, list):
        raise RuntimeError("instagram_live_history_unavailable")
    main_state = restore_main()
    try:
        main_posts = main_publisher_posts(items, live, main_state)
    except MainPublisherLiveMissing as exc:
        # A missing ID in the list is not a deletion finding. Individually GET
        # every missing ID against this exact, previously validated IG account.
        # The archive is read-only and no publication is permitted here.
        control = individual_get_positive_control(live, page)
        individual = direct_probe_missing_main_posts(exc.records, page, user_id, main_state)
        individual = probe_ig_without_owner(individual, page, user_id, main_state)
        counts = {status: sum(x["status"] == status for x in individual)
                  for status in ("verified", "not_found", "access_blocked", "ambiguous")}
        verified_fallback = [row for row in individual
                             if row.get("status") == "verified"
                             and isinstance(row.get("_verified_caption"), str)]
        redacted = [{k: v for k, v in row.items() if not k.startswith("_")}
                    for row in individual]
        # Never turn an unknown old post into another provider POST. Resume
        # only if EVERY previously missing ID has a canonical-profile proof.
        fully_reconciled = len(verified_fallback) == len(exc.records)
        if fully_reconciled:
            synthetic = [{"id": row["archived_post_id"],
                          "caption": row["_verified_caption"]}
                         for row in verified_fallback]
            main_posts = main_publisher_posts(items, live + synthetic, main_state)
        else:
            try:
                facebook_coverage = facebook_caption_candidates(graph_rows(page, "facebook"))
            except Exception:
                facebook_coverage = {"facebook_live_list_read": False,
                                     "facebook_read_status": "unavailable"}
            original_proof = historical_publish_receipts(exc.records, main_state)
            ROOT.mkdir(parents=True, exist_ok=True)
            history.save(REPORT, {
                **inventory_coverage, **facebook_coverage, **original_proof,
                "run_id": run_id, "status": "held_live_history_mismatch",
                "expected_parts": 20,
                "expected_instagram_account_id": user_id,
                "meta_page_id": str(page["page_id"]),
                "archived_ids_absent_from_list": exc.records,
                "individual_post_checks": redacted,
                "individual_get_positive_control": control,
                "individual_status_counts": counts,
                "basic_read_verified": len(verified_fallback),
                "provider_list_observed": len(live),
                "publication_authorized": False, "posts_created": 0,
                "safe_to_reserve": False,
                "unverified_archive_count": len(exc.records) - len(verified_fallback),
                "reason": "provider_list_does_not_confirm_archived_ids",
                "next_action": "remote_history_identity_reconciliation_required",
            })
            if reserve:
                raise
            report = history.read(REPORT)
            print(json.dumps({
                "status": report["status"],
                "safe_to_reserve": False,
                "publication_authorized": False,
                "unverified_archive_count": report["unverified_archive_count"],
                "historical_publish_receipts_matching_ledger":
                    report["historical_publish_receipts_matching_ledger"],
                "posts_created": 0,
            }), flush=True)
            return report
    already = conflicts(live, archive["records"], main_posts)
    records = archive["records"]
    prepared = []
    (ROOT / "covers").mkdir(parents=True, exist_ok=True)
    for row in items:
        key = history.identity(CAMPAIGN, "toonzone", "instagram", row["id"])
        if (row["episode"], row["part"]) in already:
            recorded = records.get(key)
            # An existing main-publisher post is verified by source ID and
            # provider GET, even when this separate campaign has no history.
            # Never invent an entry in the campaign journal.
            if recorded is not None and (
                    recorded.get("source_id") != row["id"]
                    or recorded.get("file") != row["name"]):
                raise RuntimeError("previous_source_identity_changed")
            if (row["episode"], row["part"]) not in main_posts and recorded is None:
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
    report = {**inventory_coverage,
              "run_id": run_id, "target_episodes": [4, 5, 6, 7, 8],
              "expected_parts": 20, "previously_verified": len(already),
              "regular_publisher_live_id_matches": len(main_posts),
              "prepared_parts": len(prepared), "exact_covers_verified": len(prepared),
              "source_files_verified": len(prepared),
              "instagram_identity_verified": True, "live_history_read": True,
              "publication_authorized": release_authorized(reserve),
              "safe_to_reserve": True,
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
