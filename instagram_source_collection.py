"""Collect today's eligible Instagram Reels through Meta Business Discovery only.

This module never publishes to a social platform. It downloads only a video
media_url returned by Meta, and uploads new files to the configured Drive
folder without replacing existing files.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from instagram_source_config import collection_targets, load_config
from instagram_source_store import (connect, finish_source_scan, migrate,
                                    persist_target_asset, record_downloaded_asset,
                                    record_source_error, record_source_post,
                                    start_source_scan, sync_source_account)

TR = ZoneInfo("Europe/Istanbul")
MAX_VIDEO_BYTES = 600_000_000
MAX_PAGES_PER_SOURCE = 200
MAX_REDIRECTS = 5
CDN_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")
SOURCE_FIELDS = (
    "business_discovery.username({username})"
    "{{id,username,media.limit(100){{id,caption,media_type,media_product_type,"
    "timestamp,media_url,thumbnail_url,permalink,view_count,like_count,comments_count}}}}"
)


class SourceAPIError(RuntimeError):
    pass


class SourceCollectionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.diagnostic_code = code


def _safe_media_host(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    return (parts.scheme == "https" and not parts.username and not parts.password
            and any(host.endswith(suffix) and host != suffix.lstrip(".")
                    for suffix in CDN_SUFFIXES))


def _response_json(response) -> dict:
    if response.status_code != 200:
        raise SourceAPIError(f"meta_graph_http_{response.status_code}")
    try:
        result = response.json()
    except (ValueError, AttributeError):
        raise SourceAPIError("meta_graph_invalid_json") from None
    if not isinstance(result, dict) or isinstance(result.get("error"), dict):
        error = result.get("error", {}) if isinstance(result, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        raise SourceAPIError("meta_graph_error_" + (str(code) if isinstance(code, int) else "unknown"))
    return result


def discover_source_media(username: str, *, actor_id: str, access_token: str,
                          graph_version: str, get=None,
                          source_identity: dict | None = None) -> list[dict]:
    """Read every Business Discovery media page; errors never become empty feeds."""
    if not re.fullmatch(r"[0-9]{5,30}", str(actor_id)):
        raise ValueError("invalid_instagram_discovery_actor")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+", graph_version):
        raise ValueError("invalid_graph_api_version")
    get = get or requests.get
    root = f"https://graph.facebook.com/{graph_version}/{actor_id}"
    params = {"fields": SOURCE_FIELDS.format(username=username), "access_token": access_token}
    url = root
    seen_urls = set()
    result = []
    for _page in range(MAX_PAGES_PER_SOURCE):
        if url in seen_urls:
            raise SourceAPIError("meta_graph_paging_cycle")
        seen_urls.add(url)
        response = None
        for attempt in range(3):
            try:
                response = get(url, params=params if url == root else None,
                               timeout=(10, 30), allow_redirects=False)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                break
            except requests.RequestException:
                if attempt == 2:
                    raise SourceAPIError("meta_graph_get_failed") from None
                time.sleep(2 ** attempt)
        data = _response_json(response)
        business = data.get("business_discovery")
        media = business.get("media") if isinstance(business, dict) else None
        if source_identity is not None and isinstance(business, dict):
            source_identity.update({"instagram_user_id": business.get("id"),
                                    "username": business.get("username")})
        rows = media.get("data") if isinstance(media, dict) else None
        if not isinstance(rows, list):
            raise SourceAPIError("meta_graph_media_shape_invalid")
        result.extend(row for row in rows if isinstance(row, dict))
        paging = media.get("paging") or {}
        next_url = paging.get("next") if isinstance(paging, dict) else None
        if not next_url:
            return result
        parts = urlsplit(str(next_url))
        expected_prefix = f"/{graph_version}/"
        if (parts.scheme != "https" or parts.hostname != "graph.facebook.com"
                or not parts.path.startswith(expected_prefix)):
            raise SourceAPIError("meta_graph_untrusted_page_link")
        url, params = str(next_url), None
    raise SourceAPIError("meta_graph_page_limit_exceeded")


def todays_videos(rows: list[dict], *, today: date | None = None) -> list[dict]:
    """Keep only new video/Reels from the Istanbul calendar day; ignore photos."""
    today = today or datetime.now(TR).date()
    videos = {}
    for row in rows:
        if row.get("media_type") != "VIDEO":
            continue
        product = str(row.get("media_product_type") or "").upper()
        if product not in {"REELS", "VIDEO", "IGTV", "FEED"}:
            continue
        post_id = row.get("id")
        timestamp = row.get("timestamp")
        if not isinstance(post_id, str) or not post_id.strip() or not isinstance(timestamp, str):
            continue
        try:
            published = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if published.tzinfo is None or published.astimezone(TR).date() != today:
                continue
        except ValueError:
            continue
        videos[post_id] = {**row, "source_published_at": published.astimezone(timezone.utc).isoformat()}
    return sorted(videos.values(), key=lambda row: (row["source_published_at"], row["id"]))


def verify_source_identity(expected_username: str, identity: dict,
                           configured_user_id: str | None = None) -> str:
    account_id = identity.get("instagram_user_id")
    returned_username = identity.get("username")
    if (not isinstance(account_id, str) or not account_id.isdigit()
            or not isinstance(returned_username, str)
            or returned_username.casefold() != expected_username.casefold()
            or (configured_user_id and configured_user_id != account_id)):
        raise SourceAPIError("source_identity_mismatch")
    return account_id


def download_official_video(media_url: str, destination: str | Path, *, get=None,
                            probe_video=None) -> tuple[Path, str, int, dict]:
    """Download one API-returned URL with strict redirects, size, MP4 and ffprobe gates."""
    get = get or requests.get
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    url = media_url
    response = None
    try:
        for redirect_index in range(MAX_REDIRECTS + 1):
            if not _safe_media_host(url):
                raise ValueError("untrusted_media_url")
            response = get(url, timeout=(10, 120), allow_redirects=False, stream=True,
                           headers={"Accept": "video/mp4,application/octet-stream"})
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if redirect_index == MAX_REDIRECTS or not location:
                    raise ValueError("media_redirect_limit")
                next_url = requests.compat.urljoin(url, location)
                if not _safe_media_host(next_url):
                    raise ValueError("untrusted_media_redirect")
                url, response = next_url, None
                continue
            if response.status_code != 200:
                raise ValueError("media_download_http_error")
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if content_type and not (content_type.startswith("video/")
                                     or "octet-stream" in content_type):
                raise ValueError("media_download_not_video")
            declared = response.headers.get("Content-Length")
            expected = int(declared) if declared and declared.isdigit() else None
            if expected is not None and not 0 < expected <= MAX_VIDEO_BYTES:
                raise ValueError("media_download_size_invalid")
            size, head = 0, b""
            digest = hashlib.sha256()
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES:
                        raise ValueError("media_download_size_limit")
                    if len(head) < 16:
                        head = (head + chunk)[:16]
                    digest.update(chunk)
                    output.write(chunk)
            if not size or (expected is not None and size != expected):
                raise ValueError("media_download_incomplete")
            if len(head) < 8 or head[4:8] != b"ftyp":
                raise ValueError("media_download_not_mp4")
            probe_video = probe_video or _probe_video
            metadata = probe_video(partial)
            if not isinstance(metadata, dict) or not any(
                    stream.get("codec_type") == "video" for stream in metadata.get("streams", [])
                    if isinstance(stream, dict)):
                raise ValueError("media_download_no_video_stream")
            partial.replace(destination)
            return destination, digest.hexdigest(), size, metadata
        raise ValueError("media_redirect_limit")
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def _probe_video(path: Path) -> dict:
    from instagram_media_compat import probe
    return probe(path)


def source_stem(route: str, username: str, post_id: str, sha256: str) -> str:
    safe_user = re.sub(r"[^A-Za-z0-9_-]+", "_", username.lower())[:30]
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", post_id)[:64]
    return f"igsrc_{route}_{safe_user}_{safe_id}_{sha256[:12]}"


def _drive_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def upload_drive_file(drive, *, folder_id: str, name: str, path: Path,
                      mime_type: str, app_properties: dict) -> dict:
    """Create-only Drive upload. Ambiguous retries read back an exact immutable identity."""
    from googleapiclient.http import MediaFileUpload
    query = (f"name='{_drive_escape(name)}' and '{_drive_escape(folder_id)}' in parents "
             "and trashed=false")
    size, md5 = _local_drive_fingerprint(path)
    listed = drive.files().list(q=query, fields="files(id,name,size,md5Checksum,parents,appProperties,mimeType)",
                                pageSize=100).execute().get("files", [])
    if len(listed) > 1:
        raise SourceCollectionError("drive_name_collision")
    expected_hash = app_properties["source_sha256"]
    if listed:
        current = listed[0]
        props = current.get("appProperties") or {}
        if (current.get("name") != name or folder_id not in current.get("parents", [])
                or props.get("source_sha256") != expected_hash
                or props.get("target_route") != app_properties.get("target_route")
                or props.get("source_post_id") != app_properties.get("source_post_id")
                or str(current.get("size")) != str(size)
                or current.get("md5Checksum") != md5):
            raise SourceCollectionError("drive_existing_file_identity_mismatch")
        return current
    quota = drive_storage_status(drive)
    if (quota.get("usage_bytes") is not None and quota.get("limit_bytes") is not None
            and quota["usage_bytes"] + size > int(quota["limit_bytes"] * 0.95)):
        raise SourceCollectionError("drive_storage_quota_low")
    media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
    created = drive.files().create(
        body={"name": name, "parents": [folder_id], "appProperties": app_properties},
        media_body=media, fields="id,name,size,md5Checksum,parents,appProperties,mimeType",
    ).execute()
    if (not isinstance(created, dict) or not created.get("id")
            or created.get("name") != name
            or folder_id not in created.get("parents", [])
            or str(created.get("size")) != str(size)
            or created.get("md5Checksum") != md5):
        raise SourceCollectionError("drive_upload_readback_mismatch")
    props = created.get("appProperties") or {}
    if props.get("source_sha256") != expected_hash:
        raise SourceCollectionError("drive_upload_hash_readback_mismatch")
    return created


def _safe_upload_drive_file(drive, **kwargs) -> dict:
    try:
        return upload_drive_file(drive, **kwargs)
    except SourceCollectionError:
        raise
    except Exception:
        raise SourceCollectionError("drive_upload_or_read_failed") from None


def _local_drive_fingerprint(path: Path) -> tuple[int, str]:
    digest = hashlib.md5(usedforsecurity=False)
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, base64.b64encode(digest.digest()).decode("ascii")


def drive_storage_status(drive) -> dict:
    """Read existing Drive quota; unavailable quota is explicitly unknown."""
    try:
        quota = drive.about().get(fields="storageQuota").execute().get("storageQuota", {})
        usage = int(quota.get("usage")) if quota.get("usage") is not None else None
        limit = int(quota.get("limit")) if quota.get("limit") is not None else None
        if usage is None or limit is None or limit <= 0:
            return {"status": "unknown", "usage_bytes": usage, "limit_bytes": limit}
        ratio = usage / limit
        return {"status": "low" if ratio >= 0.95 else "ok",
                "usage_bytes": usage, "limit_bytes": limit,
                "used_percent": round(ratio * 100, 2)}
    except Exception:
        return {"status": "unknown", "usage_bytes": None, "limit_bytes": None}


def _caption_text(row: dict, username: str) -> str:
    caption = row.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        raise ValueError("source_caption_missing")
    # Keep the source owner's words; this adds only attribution, not a claim
    # about the scene or engagement metrics.
    return f"@{username}\n\n{caption.strip()}\n"


def collect(*, config_path=None, today: date | None = None, get=None,
            graph_version: str | None = None, drive_factory=None, db_connect=None,
            download_video=None) -> dict:
    config = load_config(config_path) if config_path else load_config()
    targets = collection_targets(config)
    report = {"date": (today or datetime.now(TR).date()).isoformat(),
              "timezone": "Europe/Istanbul", "targets": {}, "errors": []}
    if not targets:
        report["status"] = "disabled"
        return report
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    actor_id = os.getenv("IG_SOURCE_DISCOVERY_ACTOR_ID", "").strip()
    if not token or not actor_id:
        raise RuntimeError("instagram_source_meta_credentials_missing")
    graph_version = graph_version or os.getenv("META_GRAPH_API_VERSION", "v27.0")
    drive_factory = drive_factory or _drive_client
    db_connect = db_connect or connect
    download_video = download_video or download_official_video
    drive = drive_factory()
    storage = drive_storage_status(drive)
    report["drive_storage"] = storage
    with db_connect() as conn:
        migrate(conn)
        for route, account in targets.items():
            summary = {"sources": [], "found": 0, "downloaded": 0,
                       "duplicates_reused": 0, "drive_uploaded": 0,
                       "errors": [], "drive_status": "unknown",
                       "storage_status": storage["status"]}
            report["targets"][route] = summary
            try:
                for source in account["source_accounts"]:
                    sync_source_account(conn, route=route, source=source)
                if account.get("collection_folder_id") == account.get("target_folder_id"):
                    raise RuntimeError("drive_collection_folder_must_be_isolated")
                try:
                    _verify_folder(drive, account["collection_folder_id"],
                                   expected_parent=account["target_folder_id"])
                except SourceCollectionError:
                    raise
                except Exception:
                    raise SourceCollectionError("drive_collection_folder_verify_failed") from None
                summary["drive_status"] = "ok"
            except Exception as exc:
                code = _error_code(exc)
                summary["errors"].append(code)
                for source in account["source_accounts"]:
                    if not (source["enabled"] and source["rights_approved"]
                            and source["official_api_download_allowed"]):
                        continue
                    source_stats = {"username": source["username"], "found": 0,
                                    "downloaded": 0, "duplicates_reused": 0,
                                    "drive_uploaded": 0, "api_status": "unknown",
                                    "drive_status": "error", "neon_status": "connected",
                                    "errors": [code]}
                    summary["sources"].append(source_stats)
                    try:
                        scan_id = start_source_scan(conn, route=route, source=source)
                        finish_source_scan(conn, scan_id=scan_id, route=route,
                            username=source["username"], status="failed", api_status="unknown",
                            drive_status="error", storage_status=storage["status"],
                            drive_usage_bytes=storage.get("usage_bytes"),
                            drive_limit_bytes=storage.get("limit_bytes"), error_codes=[code])
                    except Exception:
                        source_stats["neon_status"] = "error"
                continue
            for source in account["source_accounts"]:
                if not (source["enabled"] and source["rights_approved"]
                        and source["official_api_download_allowed"]):
                    continue
                username = source["username"]
                scan_id = start_source_scan(conn, route=route, source=source)
                source_stats = {"username": username, "found": 0,
                                "downloaded": 0, "duplicates_reused": 0,
                                "drive_uploaded": 0, "api_status": "unknown",
                                "drive_status": "ok", "neon_status": "connected"}
                summary["sources"].append(source_stats)
                identity = {}
                verified_user_id = None
                scan_errors = []
                try:
                    rows = discover_source_media(username, actor_id=actor_id,
                        access_token=token, graph_version=graph_version, get=get,
                        source_identity=identity)
                    verified_user_id = verify_source_identity(
                        username, identity, source.get("instagram_user_id"))
                    source["instagram_user_id"] = verified_user_id
                    sync_source_account(conn, route=route, source=source)
                    source_stats["api_status"] = "ok"
                    eligible = todays_videos(rows, today=today)
                    source_stats["found"] = len(eligible)
                    summary["found"] += len(eligible)
                    for row in eligible:
                        try:
                            downloaded, uploaded, duplicate = _process_source_post(
                                conn, drive, route, account, username, row,
                                today=today, get=get, download_video=download_video,
                                drive_storage=storage,
                            )
                            source_stats["downloaded"] += int(downloaded)
                            source_stats["drive_uploaded"] += int(uploaded)
                            source_stats["duplicates_reused"] += int(duplicate)
                            summary["downloaded"] += int(downloaded)
                            summary["drive_uploaded"] += int(uploaded)
                            summary["duplicates_reused"] += int(duplicate)
                        except Exception as exc:
                            code = _error_code(exc)
                            scan_errors.append(code)
                            source_stats.setdefault("errors", []).append(code)
                            summary["errors"].append(code)
                            try:
                                record_source_error(conn, route=route, username=username,
                                    post_id=row["id"], error_code=code)
                            except Exception:
                                pass
                except Exception as exc:
                    code = _error_code(exc)
                    scan_errors.append(code)
                    source_stats["api_status"] = "error"
                    source_stats.setdefault("errors", []).append(code)
                    summary["errors"].append(code)
                try:
                    finish_source_scan(conn, scan_id=scan_id, route=route, username=username,
                        status="failed" if source_stats["api_status"] == "error" else "partial" if scan_errors else "completed",
                        found=source_stats["found"], downloaded=source_stats["downloaded"],
                        duplicates=source_stats["duplicates_reused"],
                        api_status=source_stats["api_status"],
                        drive_status="error" if any(code.startswith("drive_") or code.startswith("media_") for code in scan_errors) else "ok",
                        storage_status=storage["status"],
                        drive_usage_bytes=storage.get("usage_bytes"),
                        drive_limit_bytes=storage.get("limit_bytes"),
                        instagram_user_id=verified_user_id,
                        error_codes=scan_errors)
                except Exception:
                    summary["errors"].append("neon_scan_record_failed")
            summary["archive_pool_remaining"] = _count_pool(conn, route, "archive")
            summary["new_pool_remaining"] = _count_pool(conn, route, "new")
    has_errors = bool(report["errors"]) or any(
        bool(account.get("errors")) or any(bool(source.get("errors")) for source in account.get("sources", []))
        for account in report["targets"].values()
    )
    report["status"] = "completed_with_errors" if has_errors else "completed"
    return report


def _process_source_post(conn, drive, route: str, account: dict, username: str,
                         row: dict, *, today: date | None, get,
                         download_video, drive_storage: dict | None = None) -> tuple[bool, bool, bool]:
    if drive_storage and drive_storage.get("status") == "low":
        raise SourceCollectionError("drive_storage_quota_low")
    metrics = {key: row.get(key) if isinstance(row.get(key), (int, float)) else None
               for key in ("view_count", "like_count", "comments_count")}
    metrics["media_type"] = row.get("media_type")
    metrics["media_product_type"] = row.get("media_product_type")
    is_new = record_source_post(conn, route=route, source_username=username,
        source_post_id=row["id"], source_permalink=row.get("permalink"),
        source_published_at=row["source_published_at"],
        discovered_at=datetime.now(timezone.utc),
        discovered_day=(today or datetime.now(TR).date()).isoformat(),
        caption=str(row.get("caption") or ""), metrics=metrics)
    if not is_new:
        existing = _source_row(conn, username, row["id"], route)
        if not existing or existing.get("status") not in {"newly_found", "downloaded", "error"}:
            return False, False, False
        if not isinstance(row.get("media_url"), str) or not row["media_url"].strip():
            raise ValueError("source_video_url_unavailable")
    elif not isinstance(row.get("media_url"), str) or not row["media_url"].strip():
        raise ValueError("source_video_url_unavailable")
    with tempfile.TemporaryDirectory(prefix="ig-source-") as temp:
        local = Path(temp) / "source.mp4"
        path, sha, size, video_metadata = download_video(row["media_url"], local, get=get)
        _add_metrics(video_metadata, metrics)
        record_downloaded_asset(conn, route=route, username=username,
            post_id=row["id"], sha256=sha, byte_size=size, metadata=video_metadata)
        stem = source_stem(route, username, row["id"], sha)
        existing_asset = _find_target_asset(conn, route, sha)
        if existing_asset:
            _attach_duplicate_source(conn, route, username, row["id"], sha,
                                     existing_asset["drive_video_id"])
            conn.commit()
            return True, False, True
        props = {"source_username": username, "source_post_id": row["id"],
                 "source_published_at": row["source_published_at"],
                 "downloaded_at": datetime.now(timezone.utc).isoformat(),
                 "source_sha256": sha, "target_route": route,
                 "pool": "new", "publisher_status": "new_content_pool"}
        video_obj = _safe_upload_drive_file(drive, folder_id=account["collection_folder_id"],
            name=stem + ".mp4", path=path, mime_type="video/mp4", app_properties=props)
        txt_path = Path(temp) / (stem + ".txt")
        txt_path.write_text(_caption_text(row, username), encoding="utf-8")
        txt_obj = _safe_upload_drive_file(drive, folder_id=account["collection_folder_id"],
            name=stem + ".txt", path=txt_path, mime_type="text/plain",
            app_properties={**props, "asset_role": "caption"})
        cover_id = None
        thumbnail_url = row.get("thumbnail_url")
        if isinstance(thumbnail_url, str) and _safe_media_host(thumbnail_url):
            thumbnail_path = Path(temp) / (stem + ".jpg")
            try:
                _download_thumbnail(thumbnail_url, thumbnail_path, get=get)
                cover_obj = _safe_upload_drive_file(drive, folder_id=account["collection_folder_id"],
                    name=stem + ".jpg", path=thumbnail_path, mime_type="image/jpeg",
                    app_properties={**props, "asset_role": "video_cover"})
                cover_id = cover_obj["id"]
            except Exception:
                cover_id = None
        persist_target_asset(conn, route=route, username=username,
            post_id=row["id"], sha256=sha, byte_size=size,
            metadata=video_metadata, drive_video_id=video_obj["id"],
            drive_txt_id=txt_obj["id"], drive_cover_id=cover_id,
            discovered_day=(today or datetime.now(TR).date()).isoformat())
        return True, True, False


def _source_row(conn, username: str, post_id: str, route: str):
    with conn.cursor() as cur:
        cur.execute("""SELECT status,drive_video_id FROM instagram_source_posts
                       WHERE source_username=%s AND source_post_id=%s AND route=%s""",
                    (username, post_id, route))
        row = cur.fetchone()
    return {"status": row[0], "drive_video_id": row[1]} if row else None


def _find_target_asset(conn, route: str, sha: str):
    with conn.cursor() as cur:
        cur.execute("SELECT drive_video_id FROM instagram_target_assets WHERE route=%s AND sha256=%s",
                    (route, sha))
        row = cur.fetchone()
    return {"drive_video_id": row[0]} if row else None


def _attach_duplicate_source(conn, route: str, username: str, post_id: str,
                             sha: str, drive_video_id: str):
    with conn.cursor() as cur:
        cur.execute("""UPDATE instagram_source_posts SET asset_sha256=%s,
                       drive_video_id=%s,status='duplicate_reused'
                       WHERE route=%s AND source_username=%s AND source_post_id=%s""",
                    (sha, drive_video_id, route, username, post_id))
        cur.execute("""INSERT INTO instagram_source_events
                       (route,source_username,source_post_id,sha256,event)
                       VALUES (%s,%s,%s,%s,'duplicate_asset_reused')""",
                    (route, username, post_id, sha))


def _count_pool(conn, route: str, pool: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM instagram_target_assets WHERE route=%s AND pool=%s AND status='available'",
                    (route, pool))
        return int(cur.fetchone()[0])


def _add_metrics(metadata: dict, metrics: dict) -> None:
    video = next((stream for stream in metadata.get("streams", [])
                  if stream.get("codec_type") == "video"), {})
    metrics["width"] = video.get("width")
    metrics["height"] = video.get("height")
    metrics["video_bit_rate"] = video.get("bit_rate") or metadata.get("format", {}).get("bit_rate")
    metadata["width"] = metrics["width"]
    metadata["height"] = metrics["height"]
    metadata["video_bit_rate"] = metrics["video_bit_rate"]
    try:
        metrics["duration"] = float(metadata.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        metrics["duration"] = None
    metadata["duration"] = metrics["duration"]


def _download_thumbnail(url: str, destination: Path, *, get=None):
    get = get or requests.get
    response = get(url, timeout=(10, 30), allow_redirects=False, stream=True)
    try:
        if response.status_code != 200:
            raise ValueError("thumbnail_http_error")
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if not content_type.startswith("image/"):
            raise ValueError("thumbnail_not_image")
        size = 0
        with destination.open("wb") as output:
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 20_000_000:
                    raise ValueError("thumbnail_size_limit")
                output.write(chunk)
        if not size:
            raise ValueError("thumbnail_empty")
    finally:
        response.close()


def _verify_folder(drive, folder_id: str, *, expected_parent: str | None = None) -> None:
    result = drive.files().get(fileId=folder_id,
        fields="id,name,mimeType,parents,trashed").execute()
    if (result.get("id") != folder_id or result.get("mimeType") != "application/vnd.google-apps.folder"
            or result.get("trashed") is True):
        raise SourceCollectionError("drive_target_folder_identity_mismatch")
    if expected_parent and expected_parent not in result.get("parents", []):
        raise SourceCollectionError("drive_collection_folder_wrong_parent")


def _drive_client():
    from cloud_omnichannel_publisher import get_drive_client
    return get_drive_client()


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "diagnostic_code", None)
    if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,60}", code):
        return code
    name = type(exc).__name__.lower()
    if isinstance(exc, SourceAPIError):
        return str(exc)
    if isinstance(exc, SourceCollectionError):
        return exc.diagnostic_code
    return re.sub(r"[^a-z0-9_]+", "_", name)[:60] or "ingestion_failed"


def main() -> int:
    report = collect()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered, flush=True)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Instagram kaynak toplama\n\n```json\n" + rendered + "\n```\n")
    return 0 if report.get("status") != "completed_with_errors" else 2


if __name__ == "__main__":
    raise SystemExit(main())
