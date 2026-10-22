"""Read-only live preflight and evidence-based publication reconciliation.

No publisher, claim, Drive update or media upload is called by this module.
Only whitelisted fields and error codes are printed; never exception strings.
"""
import json
import os
import sys
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from publication_safety import route_paused
from scheduled_multi_publisher import new_youtube_candidate_unused, verify_file_in_folder

REPO = Path(__file__).resolve().parent
NEW_CHANNELS = (
    ("daily_laugh_youtube", "TOKEN_DAILY_LAUGH_LAB_JSON", "UCF4KwI3alXzlExviMFmmJAA", "DAILY_LAUGH_DRIVE_FOLDER_ID", "137--TeBht1yikZpMfV9VSEADbKuXZtLT", "1xIecwryEZ5yHt_ccdkHJFBxP6z7BeJ1e", "916.mp4"),
    ("gonle_youtube", "TOKEN_GONLE_DUSEN_JSON", "UCvSvo5WghuXqsjwLRmIz22g", "GONLE_DUSEN_DRIVE_FOLDER_ID", "1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt", "1lLSnbJblWAoFSXNsEchbp3gz2izzdbU9", "141.mp4"),
)


def safe_error(exc):
    result = {"error_type": type(exc).__name__, "http_status": getattr(getattr(exc, "resp", None), "status", None)}
    try:
        body = json.loads(exc.content)
        result["reason"] = body.get("error", {}).get("errors", [{}])[0].get("reason")
    except (AttributeError, ValueError, TypeError, IndexError):
        pass
    if isinstance(exc, AuditError):
        result.update(exc.details)
    return result


class AuditError(RuntimeError):
    def __init__(self, audit_code, **details):
        self.details = {"audit_error": audit_code, **details}


def google_client(env_name, service):
    raw = os.environ.get(env_name)
    if not raw:
        raise AuditError("missing_credential", variable=env_name)
    creds = Credentials.from_authorized_user_info(json.loads(raw))
    if not creds.valid:
        creds.refresh(Request())
    return build(service, "v3", credentials=creds, cache_discovery=False), set(creds.scopes or [])


def youtube_history(youtube):
    channels = youtube.channels().list(part="id,snippet,contentDetails", mine=True).execute().get("items", [])
    if len(channels) != 1:
        raise AuditError("channel_identity_ambiguous")
    channel = channels[0]
    playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        response = youtube.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50, pageToken=page).execute()
        ids.extend(item["contentDetails"]["videoId"] for item in response.get("items", []))
        page = response.get("nextPageToken")
        if not page:
            break
    return channel, ids


def new_youtube_preflight():
    drive, _ = google_client("DRIVE_TOKEN_JSON", "drive")
    rows = []
    for route, secret, expected_channel, folder_env, folder_id, file_id, filename in NEW_CHANNELS:
        row = {"route": route, "file_id": file_id, "filename": filename, "folder_id": folder_id, "publishing_enabled": False}
        try:
            if not route_paused(route):
                raise AuditError("route_must_remain_disabled")
            if os.environ.get(folder_env) != folder_id:
                raise AuditError("folder_configuration_mismatch")
            yt, scopes = google_client(secret, "youtube")
            required = {"https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"}
            if not required.issubset(scopes):
                raise AuditError("missing_youtube_scope")
            channel, uploads = youtube_history(yt)
            if channel["id"] != expected_channel:
                raise AuditError("channel_identity_mismatch")
            row.update(channel_id=channel["id"], channel_verified=True, uploads_checked=len(uploads))
            video = drive.files().get(fileId=file_id, fields="id,name,parents,trashed,appProperties,videoMediaMetadata").execute()
            verify_file_in_folder(drive, video, folder_id)
            if video["name"] != filename:
                raise AuditError("candidate_name_changed")
            row["parent_verified"] = True
            if not new_youtube_candidate_unused(route, video):
                raise AuditError("candidate_has_prior_or_uncertain_publication")
            # Empty authenticated uploads history is stronger than public videoCount=0.
            # Non-empty history requires source evidence, so fail closed here.
            if uploads:
                raise AuditError("nonempty_channel_history_requires_reconciliation")
            txt = drive.files().list(q=f"'{folder_id}' in parents and name='{Path(filename).stem}.txt' and trashed=false", fields="files(id,parents)").execute().get("files", [])
            if len(txt) != 1 or folder_id not in txt[0].get("parents", []):
                raise AuditError("txt_missing_or_ambiguous")
            metadata = video.get("videoMediaMetadata", {})
            row.update(txt_id=txt[0]["id"], video_metadata=metadata, content_approval="user_review_not_automated", history_clear=True, dry_run="passed")
        except Exception as exc:
            row.update(dry_run="blocked", **safe_error(exc))
        rows.append(row)
    return rows


def candidate_inventory():
    """Read-only, bounded candidate list for an explicitly scoped source folder."""
    drive, _ = google_client("DRIVE_TOKEN_JSON", "drive")
    routes = (
        ("daily_laugh", "DAILY_LAUGH_DRIVE_FOLDER_ID", "137--TeBht1yikZpMfV9VSEADbKuXZtLT"),
        ("gonle", "GONLE_DUSEN_DRIVE_FOLDER_ID", "1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt"),
    )
    result = []
    for route, env_name, expected_folder in routes:
        folder_id = os.environ.get(env_name, "")
        if folder_id != expected_folder:
            raise AuditError("folder_configuration_mismatch", route=route)
        page, files = None, []
        while len(files) < 100:
            response = drive.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken,files(id,name,parents,md5Checksum,size,videoMediaMetadata,appProperties)",
                pageSize=100,
                pageToken=page,
            ).execute()
            files.extend(response.get("files", []))
            page = response.get("nextPageToken")
            if not page:
                break
        rows = []
        for item in files:
            if not str(item.get("name", "")).lower().endswith(".mp4"):
                continue
            verify_file_in_folder(drive, item, folder_id)
            props = item.get("appProperties") or {}
            prior = any(key.startswith(("done_", "result_", "intent_", "claimed_")) or key.endswith("_used") for key in props)
            rows.append({
                "file_id": item["id"], "name": item["name"], "md5": item.get("md5Checksum"),
                "size": item.get("size"), "duration_ms": (item.get("videoMediaMetadata") or {}).get("durationMillis"),
                "parent_verified": True, "drive_ledger_clear": not prior,
            })
        result.append({"route": route, "folder_id": folder_id, "candidates": sorted(rows, key=lambda row: row["name"])[:25]})
    return result


def graph_get(path, token, *, diagnostic=None, **params):
    url = f"https://graph.facebook.com/v22.0/{path}"
    headers = {"Authorization": f"Bearer {token}"}
    if diagnostic is None:
        response = requests.get(url, headers=headers, params=params, timeout=30)
    else:
        diagnostic["phase"] = "request_preparation"
        _emit_meta_diagnostic(diagnostic)
        session = requests.Session()
        request = requests.Request("GET", url, headers=headers, params=params)
        prepared = session.prepare_request(request)
        diagnostic["phase"] = "http_call"
        diagnostic["http_status"] = None
        _emit_meta_diagnostic(diagnostic)
        response = session.send(prepared, timeout=30)
        diagnostic["http_status"] = response.status_code
        diagnostic["phase"] = "response_json_parse"
        _emit_meta_diagnostic(diagnostic)
    body = response.json()
    if not response.ok or body.get("error"):
        err = body.get("error", {})
        raise AuditError("meta_api_rejected", http_status=response.status_code, code=err.get("code"), subcode=err.get("error_subcode"), type=err.get("type"))
    return body


def graph_list(path, token, fields, *, diagnostic=None):
    items, after = [], None
    for _ in range(30):
        body = graph_get(
            path, token, fields=fields, limit=100,
            diagnostic=diagnostic,
            **({"after": after} if after else {}),
        )
        items.extend(body.get("data", []))
        paging = body.get("paging", {})
        if not paging.get("next"):
            return items
        after = paging.get("cursors", {}).get("after")
        if not after:
            break
    raise AuditError("history_pagination_incomplete")


def _emit_meta_diagnostic(diagnostic):
    """Emit only stage, status, and boolean token-format flags."""
    safe = {
        "phase": diagnostic.get("phase"),
        "http_status": diagnostic.get("http_status"),
        "token_format": diagnostic.get("token_format", {}),
    }
    print("META_DIAGNOSTIC " + json.dumps(safe, sort_keys=True))


def batch_history_audit():
    manifest = json.loads((REPO / "manifests/batch-20261016-user-approved.json").read_text(encoding="utf-8"))
    drive, _ = google_client("DRIVE_TOKEN_JSON", "drive")
    auth = json.loads(os.environ.get("META_AUTH_JSON") or "{}")
    names = {"tarladaki": "Tarladaki Fasulye", "penguen": "Beyinsiz Penguen", "gonle": "Gönle Düşen", "daily_laugh": "Daily Laugh Lab"}
    youtube_env = {"tarladaki": "TOKEN_CHANNEL1_JSON", "penguen": "TOKEN_CHANNEL2_JSON"}
    drive_cache, history_cache, rows = {}, {}, []
    live_pages = {}
    if os.environ.get("META_ACCESS_TOKEN"):
        try:
            live_pages = {str(p["id"]): p for p in graph_list("me/accounts", os.environ["META_ACCESS_TOKEN"], "id,name,access_token,instagram_business_account{id}")}
        except Exception:
            pass  # Saved page tokens still undergo direct identity verification below.
    for target in manifest["targets"]:
        if target.get("status") == "blocked-http-400":
            continue
        account, platform, fid = target["account"], target["platform"], target["drive_file_id"]
        row = {"account": account, "platform": platform, "drive_file_id": fid, "folder_id": target["drive_folder_id"], "result": "unproven_do_not_retry"}
        try:
            if fid not in drive_cache:
                drive_cache[fid] = drive.files().get(fileId=fid, fields="id,name,parents,trashed,appProperties").execute()
            video = drive_cache[fid]
            verify_file_in_folder(drive, video, target["drive_folder_id"])
            row["parent_verified"] = True
            props = video.get("appProperties") or {}
            cache_key = (account, platform)
            if cache_key not in history_cache:
                if platform == "youtube":
                    yt, _ = google_client(youtube_env[account], "youtube")
                    channel, ids = youtube_history(yt)
                    records = []
                    for offset in range(0, len(ids), 50):
                        records.extend(yt.videos().list(part="snippet,fileDetails,status", id=",".join(ids[offset:offset+50])).execute().get("items", []))
                    history_cache[cache_key] = (channel["id"], records)
                else:
                    configs = [p for p in auth.get("pages", []) if p.get("page_name") == names[account]]
                    if len(configs) != 1:
                        raise AuditError("configured_meta_identity_missing")
                    configured = configs[0]
                    page_id = str(configured["page_id"])
                    live = live_pages.get(page_id, {})
                    token = live.get("access_token") or configured.get("page_token")
                    identity = graph_get(page_id, token, fields="id,name,instagram_business_account{id}")
                    if identity.get("id") != page_id or identity.get("name") != names[account]:
                        raise AuditError("meta_identity_mismatch")
                    if platform == "instagram":
                        ig_id = str(configured.get("instagram_id") or "")
                        if not ig_id or str(identity.get("instagram_business_account", {}).get("id")) != ig_id:
                            raise AuditError("instagram_identity_mismatch")
                        records = graph_list(f"{ig_id}/media", token, "id,permalink,timestamp")
                        history_cache[cache_key] = (ig_id, records)
                    else:
                        records = graph_list(f"{page_id}/videos", token, "id,permalink_url,created_time")
                        history_cache[cache_key] = (page_id, records)
            identity, records = history_cache[cache_key]
            row.update(platform_account_id=identity, posts_checked=len(records), history_complete=True)
            key = {"youtube": "result_yt1" if account == "tarladaki" else "result_yt2", "facebook": "result_fb", "instagram": "result_ig"}[platform]
            saved = str(props.get(key) or "")
            matches = []
            for record in records:
                rid = str(record["id"])
                source_match = platform == "youtube" and fid in record.get("fileDetails", {}).get("fileName", "")
                if (saved and (saved == rid or saved.rstrip("/").split("/")[-1].split("?")[0] == rid)) or source_match:
                    url = record.get("permalink") or record.get("permalink_url") or f"https://www.youtube.com/watch?v={rid}"
                    matches.append({"id": rid, "url": url, "evidence": "original_filename_contains_drive_id" if source_match else "drive_result_matches_platform_record"})
            if matches:
                row.update(result="already_published_do_not_retry", matches=matches)
            elif not records:
                row["result"] = "no_current_platform_posts_historical_deletions_unverifiable"
            row["has_drive_result"] = bool(saved)
        except Exception as exc:
            row.update(**safe_error(exc))
        rows.append(row)
    return {"batch_id": manifest["batch_id"], "manifest_publishing_enabled": manifest["publishing_enabled"], "targets": rows}


if __name__ == "__main__":
    try:
        mode = sys.argv[1]
        report = new_youtube_preflight() if mode == "new-youtube" else candidate_inventory() if mode == "candidates" else batch_history_audit() if mode == "batch-history" else None
        if report is None:
            raise AuditError("unsupported_mode")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if mode == "new-youtube" and any(row["dry_run"] != "passed" for row in report):
            raise SystemExit(1)
    except Exception as exc:
        print(json.dumps(safe_error(exc)))
        raise SystemExit(1)
