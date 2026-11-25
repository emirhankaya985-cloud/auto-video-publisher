"""Read-only, source-bound diagnosis of ToonZone S01E06 Part2 (no Meta POST)."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from publisher_alert_history import now_utc, stamp, validate, restore
from toonzone_relaunch import CAMPAIGN, WORKFLOW, NAMES, record_key, EXPECTED_IG

ROOT = Path("toonzone-ig-p2-diagnostic")
TARGET_FILE = "S01E06_Meat_Your_Maker_Part2.mp4"
TARGET_SOURCE = "1iSkWsT2kUzUGxM8g-GuvdxzY_0Bgezjq"
TARGET_RUN = "42873941861"
TARGET_CONTAINER = "17912149164580142"
TARGET_FACEBOOK_ID = "1483886187013259"
ATTEMPT_BEGIN = stamp("2026-11-10T18:22:12Z")
VALID_STATES = {"IN_PROGRESS", "FINISHED", "PUBLISHED", "ERROR", "EXPIRED"}


def inspect(ledger, page, rows_for, container_get, *, now=None):
    """Accept only exact source, campaign intent and provider-owned visible posts.

    A missing post is *not* evidence of non-publication. No write API is used.
    """
    now = now or now_utc()
    validate(ledger)
    if page.get("page_id") != "1298191963387372" or str(page.get("instagram_id")) != EXPECTED_IG:
        raise RuntimeError("toonzone_identity_unverified")
    records = []
    for platform in ("facebook", "instagram"):
        rec = next((r for r in ledger["records"].values()
                    if r.get("platform") == platform and r.get("file") == TARGET_FILE
                    and r.get("source_id") == TARGET_SOURCE
                    and r.get("intent_run_id") == TARGET_RUN), None)
        if not rec or rec.get("route") != "toonzone" or not isinstance(rec.get("caption"), str):
            raise RuntimeError("exact_original_intent_not_found")
        # Reject accidental collisions with old unrelated campaign entries.
        from publisher_alert_history import identity
        if identity(CAMPAIGN, "toonzone", platform, TARGET_SOURCE) not in ledger["records"]:
            raise RuntimeError("campaign_identity_unverified")
        records.append(rec)
    if records[0].get("post_id") != TARGET_FACEBOOK_ID:
        raise RuntimeError("facebook_ack_mismatch")
    facebook, instagram = records
    if instagram.get("post_id") and instagram.get("status") != "verified":
        # An independent accepted ID must have its actual platform match too.
        pass
    result = {"schema": 1, "scope": "toonzone_s01e06p2",
              "posts_created": 0, "uploads_started": 0,
              "source_and_intents_verified": True,
              "facebook": {}, "instagram": {}}
    for platform, rec in (("facebook", facebook), ("instagram", instagram)):
        media = rows_for(page, platform)
        exact = [m for m in media if (m.get("description") or m.get("caption")) == rec["caption"]]
        if len(exact) > 1:
            raise RuntimeError("ambiguous_duplicate_exact_caption")
        if exact:
            published = stamp(exact[0].get("created_time") or exact[0].get("timestamp"))
            if not ATTEMPT_BEGIN - timedelta(minutes=3) <= published <= now + timedelta(minutes=3):
                raise RuntimeError("matching_media_outside_original_attempt_window")
        provider_id = str(exact[0].get("id")) if exact else None
        if provider_id and not provider_id.isdecimal():
            raise RuntimeError("invalid_remote_id")
        if rec.get("post_id") and provider_id and str(rec["post_id"]) != provider_id:
            raise RuntimeError("archived_provider_id_mismatch")
        result[platform] = {"ledger_status": rec.get("status"),
                            "remote_exact_caption_matches": len(exact),
                            "provider_post_id_verified": provider_id,
                            "archived_id_matches": (bool(provider_id) and provider_id == str(rec.get("post_id")))
                                                   if rec.get("post_id") else None,
                            "remote_absence_does_not_authorize_reupload": True}
    response = container_get(page, TARGET_CONTAINER)
    if not isinstance(response, dict) or response.get("id", TARGET_CONTAINER) != TARGET_CONTAINER:
        raise RuntimeError("container_reply_unverified")
    state = response.get("status_code")
    if state not in VALID_STATES:
        raise RuntimeError("container_state_unverified")
    result["container"] = {"id": TARGET_CONTAINER, "status": state,
                           "media_publish_verified": bool(result["instagram"]["provider_post_id_verified"]),
                           "existing_container_ready_for_guarded_resumption": (
                               state == "FINISHED"
                               and result["instagram"]["remote_exact_caption_matches"] == 0
                               and instagram.get("status") == "attempted"
                               and not instagram.get("post_id"))}
    return result


def main():
    from public_link_runtime import graph_rows
    from toonzone_instagram_season import page_for_toonzone, instagram_identity
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    from publisher_recovery import read_with_retry
    import requests

    page = page_for_toonzone()
    if instagram_identity(page) != EXPECTED_IG:
        raise RuntimeError("toonzone_instagram_identity_changed")
    def container_get(page, container):
        response = read_with_retry(
            requests.get, f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container}",
            headers={"Authorization": "Bearer " + page["page_token"]},
            params={"fields": "status_code,status"},
            timeout=30, graph_read=True)
        try:
            data = response.json()
        except (ValueError, TypeError):
            raise RuntimeError("container_json_unavailable") from None
        if response.status_code != 200 or not isinstance(data, dict) or data.get("error"):
            error = data.get("error") if isinstance(data, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise RuntimeError(f"container_read_rejected_graph_code_{code if isinstance(code, int) else 'unknown'}")
        return data

    ledger = restore(names=NAMES, workflow_path=WORKFLOW)
    report = inspect(ledger, page, graph_rows, container_get)
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
