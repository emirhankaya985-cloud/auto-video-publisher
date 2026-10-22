import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from googleapiclient.errors import HttpError

from cloud_omnichannel_publisher import (
    get_drive_client,
    GRAPH_API_VERSION,
    get_meta_page_info,
    get_youtube_client,
    SCOPES_YOUTUBE_CHANNEL_READ,
)
from analytics_archive import make_record, upsert_records, export_csv
from analytics_drive_store import get_or_create_archive_folder, download_history, save_history_and_csv
from ntfy_notifications import send_ntfy
from ntfy_phone_report import compact_phone_report


TZ = ZoneInfo("Europe/Istanbul")
META_TARGETS = (
    ("🌱 Tarladaki Fasulye", "Tarladaki Fasulye", "Facebook"),
    ("🌱 Tarladaki Fasulye", "Tarladaki Fasulye", "Instagram"),
    ("🐧 Beyinsiz Penguen", "Beyinsiz Penguen", "Facebook"),
    ("🐧 Beyinsiz Penguen", "Beyinsiz Penguen", "Instagram"),
    ("❤️ Gönle Düşen", "Gönle Düşen", "Facebook"),
    ("❤️ Gönle Düşen", "Gönle Düşen", "Instagram"),
    ("😂 Daily Laugh Lab", "Daily Laugh Lab", "Facebook"),
    ("😂 Daily Laugh Lab", "Daily Laugh Lab", "Instagram"),
    ("🎬 Film Mağarası + Filmmagrasi", "Film Mağarası", "Facebook 1"),
    ("🎬 Film Mağarası + Filmmagrasi", "Filmmagrasi", "Facebook 2"),
    ("🎬 Film Mağarası + Filmmagrasi", "Film Mağarası", "Instagram"),
    ("📺 ToonZone", "ToonZone", "Facebook"),
    ("📺 ToonZone", "ToonZone", "Instagram"),
)

YOUTUBE_TARGETS = (
    ("🌱 Tarladaki Fasulye", "TOKEN_CHANNEL1_JSON", "token_channel1.json", None, "YouTube"),
    ("🐧 Beyinsiz Penguen", "TOKEN_CHANNEL2_JSON", "token_channel2.json", None, "YouTube"),
    ("😂 Daily Laugh Lab", "TOKEN_DAILY_LAUGH_LAB_JSON", "token_daily_laugh_lab.json", "UCF4KwI3alXzlExviMFmmJAA", "YouTube"),
)

ACCOUNT_TARGETS = {
    "🌱 Tarladaki Fasulye": (5, "tarladaki", "DRIVE_FOLDER_ID", ("yt1", "fb", "ig")),
    "🐧 Beyinsiz Penguen": (5, "penguen", "DRIVE_FOLDER_ID", ("yt2", "fb", "ig")),
    "❤️ Gönle Düşen": (5, "gonle", "GONLE_DUSEN_DRIVE_FOLDER_ID", ("fb", "ig")),
    "😂 Daily Laugh Lab": (8, "daily_laugh", "DAILY_LAUGH_DRIVE_FOLDER_ID", ("fb", "ig", "yt_daily")),
    "🎬 Film Mağarası + Filmmagrasi": (5, "film", "FILM_DRIVE_FOLDER_ID", ("fb_film_1", "fb_film_2", "ig")),
    "📺 ToonZone": (4, "toonzone", "TOONZONE_DRIVE_FOLDER_ID", ("fb", "ig")),
}

PLATFORM_SLOT_PROPERTY = {
    "yt1": "done_yt1_slot", "yt2": "done_yt2_slot", "yt_daily": "done_yt_daily_slot",
    "fb": "done_fb_slot", "fb_film_1": "done_fb_film_1_slot",
    "fb_film_2": "done_fb_film_2_slot", "ig": "done_ig_slot",
}
PLATFORM_FAILURE_SLOT_PROPERTY = {
    "yt1": "failure_slot_yt1", "yt2": "failure_slot_yt2",
    "yt_daily": "failure_slot_yt_daily", "fb": "failure_slot_fb",
    "fb_film_1": "failure_slot_fb_film_1", "fb_film_2": "failure_slot_fb_film_2",
    "ig": "failure_slot_ig",
}

def tr_number(value):
    """Render counts with Turkish thousands separators; never use K/M."""
    return f"{int(value):,}".replace(",", ".")


def safe_error(exc):
    if isinstance(exc, HttpError):
        status = getattr(getattr(exc, "resp", None), "status", "?")
        if status == 403:
            return "HTTP 403: istatistik okuma erişimi/yetkisi reddedildi"
        return f"HTTP {status}: API isteği reddedildi"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        return f"HTTP {status}: API isteği reddedildi"
    if isinstance(exc, requests.RequestException):
        return type(exc).__name__
    message = str(exc)
    message = re.sub(r"https?://[^\s\"'<>]+", "[URL gizlendi]", message, flags=re.IGNORECASE)
    for env_name in ("META_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN", "NTFY_TOPIC_URL"):
        secret = os.getenv(env_name, "")
        if secret:
            message = message.replace(secret, "[gizli]")
    return f"{type(exc).__name__}: {message[:100]}"


def graph_get(path, token, **params):
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{path}",
        params={**params, "access_token": token},
        timeout=30,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or payload.get("error"):
        error = payload.get("error") or {}
        code = error.get("code")
        suffix = f" code={code}" if code is not None else ""
        raise RuntimeError(f"Meta API HTTP {response.status_code}{suffix}")
    return payload


def graph_pages(path, token, **params):
    """Read all cursor pages; never print next-page URLs (they contain auth)."""
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{path}",
        params={**params, "access_token": token}, timeout=30,
    )
    while True:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not response.ok or payload.get("error"):
            error = payload.get("error") or {}
            code = error.get("code")
            suffix = f" code={code}" if code is not None else ""
            raise RuntimeError(f"Meta API HTTP {response.status_code}{suffix}")
        yield from payload.get("data", [])
        next_url = (payload.get("paging") or {}).get("next")
        if not next_url:
            break
        response = requests.get(next_url, timeout=30)


def youtube_total(env_name, fallback, expected_channel_id=None):
    youtube = get_youtube_client(env_name, fallback, scopes=SCOPES_YOUTUBE_CHANNEL_READ)
    items = youtube.channels().list(part="snippet,statistics", mine=True).execute().get("items", [])
    if not items:
        raise RuntimeError("YouTube kanalı bulunamadı")
    item = items[0]
    if expected_channel_id and item.get("id") != expected_channel_id:
        raise RuntimeError("YouTube OAuth kanalı beklenen kanal ID'siyle eşleşmiyor")
    stats = item.get("statistics", {})
    return {
        "name": item.get("snippet", {}).get("title", "YouTube"),
        "views": int(stats.get("viewCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
        "followers": int(stats.get("subscriberCount", 0)),
    }


def youtube_ids_from_drive(drive, folder_id, result_key):
    files = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(appProperties)", pageSize=1000,
    ).execute().get("files", [])
    ids = []
    for item in files:
        value = (item.get("appProperties") or {}).get(result_key, "")
        if "/shorts/" in value:
            ids.append(value.split("/shorts/", 1)[1].split("?", 1)[0])
    return sorted(set(ids))


def publication_counts(drive, folder_id, result_keys, day):
    """Count only confirmed result URLs. Date filtering is unavailable in appProperties."""
    if not drive or not folder_id:
        return None
    files = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(appProperties)", pageSize=1000,
    ).execute().get("files", [])
    total = 0
    for item in files:
        props = item.get("appProperties") or {}
        total += sum(1 for key in result_keys if props.get(key, "").startswith("http"))
    return total


def youtube_video_snapshot(env_name, fallback, expected_channel_id=None):
    """Collect current per-video lifetime views for every item in the uploads playlist."""
    youtube = get_youtube_client(env_name, fallback, scopes=SCOPES_YOUTUBE_CHANNEL_READ)
    channels = youtube.channels().list(
        part="snippet,statistics,contentDetails", mine=True,
    ).execute().get("items", [])
    if len(channels) != 1:
        raise RuntimeError("YouTube OAuth hesabı için tek kanal doğrulanamadı")
    channel = channels[0]
    if expected_channel_id and channel.get("id") != expected_channel_id:
        raise RuntimeError("YouTube OAuth kanalı beklenen hesapla eşleşmiyor")
    upload_playlist = (
        channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    )
    if not upload_playlist:
        raise RuntimeError("YouTube yüklenen videolar listesi alınamadı")

    videos = {}
    page_token = None
    while True:
        page = youtube.playlistItems().list(
            part="contentDetails,snippet", playlistId=upload_playlist,
            maxResults=50, pageToken=page_token,
        ).execute()
        ids = [
            item.get("contentDetails", {}).get("videoId")
            for item in page.get("items", [])
        ]
        if any(not isinstance(video_id, str) or not video_id for video_id in ids):
            raise RuntimeError("YouTube uploads listesi eksik video kimlikleri içeriyor")
        if any(video_id in videos for video_id in ids) or len(set(ids)) != len(ids):
            raise RuntimeError("YouTube uploads listesinde yinelenen video kimlikleri var")
        published = {
            item.get("contentDetails", {}).get("videoId"):
                item.get("snippet", {}).get("publishedAt", "")
            for item in page.get("items", [])
        }
        for start in range(0, len(ids), 50):
            chunk = [video_id for video_id in ids[start:start + 50] if video_id]
            if not chunk:
                continue
            details = youtube.videos().list(
                part="statistics,snippet", id=",".join(chunk),
            ).execute().get("items", [])
            # A deleted, private, unsupported or inaccessible item can be
            # absent from videos.list even when playlistItems listed it.
            # Silently ignoring it would produce a false account total.
            response_ids = [item.get("id") for item in details]
            if len(details) != len(chunk) or set(response_ids) != set(chunk):
                raise RuntimeError("YouTube video istatistikleri eksik; toplam hesaplanmadı")
            for item in details:
                video_id = item["id"]
                views = (item.get("statistics") or {}).get("viewCount")
                if views is None:
                    raise RuntimeError("YouTube video görüntülenme alanı eksik")
                try:
                    views = int(views)
                except (ValueError, TypeError):
                    raise RuntimeError("YouTube video görüntülenme alanı geçersiz") from None
                if views < 0:
                    raise RuntimeError("YouTube video görüntülenme sayacı geçersiz")
                videos[video_id] = {
                    "views": views,
                    "published_at": (item.get("snippet") or {}).get("publishedAt") or published.get(video_id, ""),
                }
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    return videos, channel.get("snippet", {}).get("title", "YouTube")


def facebook_video_snapshot(page):
    """Collect video lifetime counters across every Page videos cursor page."""
    videos = {}
    for item in graph_pages(
        f"{page['page_id']}/videos", page["page_token"],
        fields="id,views,created_time", limit=100,
    ):
        if item.get("views") is None:
            raise RuntimeError("Facebook video views alanı API yanıtında yok")
        videos[item["id"]] = {
            "views": int(item["views"]),
            "published_at": item.get("created_time", ""),
        }
    return videos


def instagram_video_snapshot(page):
    """Collect lifetime view counters for all accessible professional video media."""
    ig_id = page.get("instagram_id")
    if not ig_id:
        raise RuntimeError("Instagram profesyonel hesabı bağlı değil")
    videos = {}
    for item in graph_pages(
        f"{ig_id}/media", page["page_token"],
        fields="id,media_type,media_product_type,timestamp", limit=100,
    ):
        if item.get("media_type") != "VIDEO":
            continue
        insight = graph_get(f"{item['id']}/insights", page["page_token"], metric="views")
        entries = insight.get("data", [])
        if not entries:
            raise RuntimeError("Instagram video views metriği erişilebilir değil")
        values = entries[0].get("values") or []
        value = entries[0].get("value")
        if value is None and values:
            value = values[0].get("value")
        if value is None:
            raise RuntimeError("Instagram video views değeri API yanıtında yok")
        videos[item["id"]] = {"views": int(value), "published_at": item.get("timestamp", "")}
    return videos


def _local_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(TZ).date().isoformat()
    except (TypeError, ValueError):
        return None


def _collect_snapshot(now, *, report_day=None):
    snapshot, records, errors = {}, [], []
    measured_at = now.astimezone(TZ).isoformat(timespec="seconds")
    # Keep actual measurement timestamp, but file a delayed scheduled run
    # under the scheduled local reporting day, not the next calendar day.
    period = (report_day or now.astimezone(TZ).date()).isoformat()

    def save_platform(account, platform, data, source_api, error=None):
        snapshot[(account, platform)] = data
        records.append(make_record(
            measured_at=measured_at, timezone="Europe/Istanbul", account=account,
            platform=platform, entity_type="account", entity_id=account,
            metric="snapshot_status", value=len(data) if data is not None else None,
            unit="videos", period=period, source_api=source_api,
            source_metric="video_view_count", status="error" if error else "ok",
        ))
        if data is None:
            errors.append(f"{account} / {platform}: {safe_error(error) if error else 'veri alınamadı'}")
            return
        records.append(make_record(
            measured_at=measured_at, timezone="Europe/Istanbul", account=account,
            platform=platform, entity_type="account", entity_id=account,
            metric="lifetime_views", value=sum(x["views"] for x in data.values()),
            unit="views", period=period, source_api=source_api,
            source_metric="sum(video views)", status="ok",
        ))
        for video_id, item in data.items():
            records.append(make_record(
                measured_at=measured_at, timezone="Europe/Istanbul", account=account,
                platform=platform, entity_type="video", entity_id=video_id,
                published_at=item.get("published_at"), metric="view_count",
                value=item["views"], unit="views", period=period,
                source_api=source_api, source_metric="views", status="ok",
            ))

    for account, page_name, platform in META_TARGETS:
        api = "meta.graph.video.views" if platform.startswith("Facebook") else "meta.graph.ig_media_insights.views"
        try:
            page = get_meta_page_info(page_name)
            data = facebook_video_snapshot(page) if platform.startswith("Facebook") else instagram_video_snapshot(page)
            save_platform(account, platform, data, api)
        except Exception as exc:
            save_platform(account, platform, None, api, exc)

    for account, env_name, fallback, expected_id, platform in YOUTUBE_TARGETS:
        api = "youtube.data.v3.videos.statistics.viewCount"
        if not os.environ.get(env_name, "").strip() and not Path(fallback).exists():
            save_platform(account, platform, None, api, RuntimeError("YouTube OAuth ayarı bulunamadı"))
            continue
        try:
            data, _channel_title = youtube_video_snapshot(env_name, fallback, expected_id)
            save_platform(account, platform, data, api)
        except Exception as exc:
            save_platform(account, platform, None, api, exc)
    return snapshot, records, errors


def _read_day_records(path, day):
    result = {}
    if not Path(path).exists():
        return result
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("period") == day:
                result[(record.get("account"), record.get("platform"), record.get("entity_type"),
                        record.get("entity_id"), record.get("metric"))] = record
    return result


def _platform_totals(snapshot, previous, account, platform, today):
    current = snapshot.get((account, platform))
    total = sum(x["views"] for x in current.values()) if current is not None else None
    previous_status = previous.get((account, platform, "account", account, "snapshot_status"))
    if current is None or not previous_status or previous_status.get("status") != "ok":
        return total, None
    old_videos = {
        entity_id: row for (owner, old_platform, entity_type, entity_id, metric), row in previous.items()
        if owner == account and old_platform == platform and entity_type == "video" and metric == "view_count"
    }
    # An API response that silently omitted previously visible videos cannot
    # support a reliable all-time sum or daily gain. Keep both unavailable.
    if set(old_videos) - set(current):
        return None, None
    # An archive may contain a succeeded account marker but not all of its
    # video records (partial write / legacy corruption). Never use incomplete
    # baselines to compute daily growth.
    expected = previous_status.get("value")
    if expected is None or str(expected) != str(len(old_videos)):
        return total, None
    delta = 0
    for video_id, item in current.items():
        old = old_videos.get(video_id)
        if old:
            if old.get("value") is None or old.get("status", "ok") != "ok":
                return total, None
            try:
                change = int(item["views"]) - int(old["value"])
            except (TypeError, ValueError):
                return total, None
            if change < 0:
                return total, None
            delta += change
        elif _local_date(item.get("published_at")) == today:
            delta += int(item["views"])
        else:
            return total, None
    return total, delta


def _daily_delta_text(total, delta, prior):
    if delta is not None:
        return f"+{tr_number(delta)}"
    if total is None or (prior and prior.get("status") != "ok"):
        return "⚠️ Veri alınamadı"
    if not prior:
        return "N/A (ilk ölçüm)"
    return "N/A (karşılaştırılamıyor)"


def publication_progress(drive, account, day):
    target, route, folder_env, keys = ACCOUNT_TARGETS[account]
    # Historical progress must not falsely demand 8 videos on old 5-slot days.
    if route == "daily_laugh" and day < "2026-10-20":
        target = 5
    folder_id = os.environ.get(folder_env, "").strip()
    if route == "film" and not folder_id:
        folder_id = "1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW"
    if route == "toonzone" and not folder_id:
        folder_id = "14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF"
    if not drive or not folder_id:
        return None
    files, page_token = [], None
    while True:
        response = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false", pageSize=1000,
            pageToken=page_token, fields="nextPageToken,files(id,mimeType,appProperties)",
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    completed = posts = failures = 0
    platforms = {key: {"success": 0, "failure": 0, "latest_slot": None, "latest_status": "N/A"}
                 for key in keys}
    for item in files:
        if item.get("mimeType") != "video/mp4":
            continue
        props = item.get("appProperties") or {}
        successes = 0
        for key in keys:
            slot = props.get(PLATFORM_SLOT_PROPERTY[key], "")
            if slot and f"-{route}" in slot:
                if slot.startswith(day):
                    successes += 1
                    platforms[key]["success"] += 1
                if (not platforms[key]["latest_slot"] or slot > platforms[key]["latest_slot"]
                        or (slot == platforms[key]["latest_slot"]
                            and platforms[key]["latest_status"] != "başarılı")):
                    platforms[key].update(latest_slot=slot, latest_status="başarılı")
            failure_slot = props.get(PLATFORM_FAILURE_SLOT_PROPERTY.get(key, ""), "")
            if failure_slot and f"-{route}" in failure_slot:
                if failure_slot.startswith(day):
                    platforms[key]["failure"] += 1
                if (not platforms[key]["latest_slot"] or failure_slot > platforms[key]["latest_slot"]
                        or (failure_slot == platforms[key]["latest_slot"]
                            and platforms[key]["latest_status"] != "başarılı")):
                    platforms[key].update(latest_slot=failure_slot, latest_status="başarısız / belirsiz")
            intent_slot = props.get({
                "yt1": "intent_yt1_slot", "yt2": "intent_yt2_slot", "yt_daily": "intent_yt_daily_slot",
                "fb": "intent_fb_slot", "fb_film_1": "intent_fb_film_1_slot",
                "fb_film_2": "intent_fb_film_2_slot", "ig": "intent_ig_slot",
            }[key], "")
            if intent_slot and f"-{route}" in intent_slot:
                if (not platforms[key]["latest_slot"] or intent_slot > platforms[key]["latest_slot"]
                        or (intent_slot == platforms[key]["latest_slot"]
                            and platforms[key]["latest_status"] != "başarılı")):
                    platforms[key].update(latest_slot=intent_slot, latest_status="sonuç belirsiz")
        posts += successes
        completed += int(successes == len(keys))
        failed = props.get("failed_route_slot", "")
        failures += int(failed.startswith(day) and f"-{route}" in failed)
    return {"target": target, "completed": completed, "posts": posts,
            "expected_posts": target * len(keys), "failures": failures, "platforms": platforms}


def resolve_report_day(now, *, event_name=None):
    """Honor the intended 23:59 TRT day when GitHub schedule starts late.

    GitHub cron runs at 20:59 UTC. If runner starts just after local midnight,
    it must not silently relabel the previous nightly report as the next day.
    Manual dispatch always reports the actual day.
    """
    event = os.getenv("GITHUB_EVENT_NAME", "") if event_name is None else event_name
    local = now.astimezone(TZ)
    if event == "schedule" and 0 <= local.hour < 6:
        return local.date() - timedelta(days=1)
    return local.date()


def build_report(now=None):
    now = now or datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    report_day = resolve_report_day(now)
    delayed = report_day != now.date()
    today = report_day.isoformat()
    yesterday = (report_day - timedelta(days=1)).isoformat()
    errors, drive, archive_folder = [], None, None
    history_read_ok = False
    with tempfile.TemporaryDirectory(prefix="daily-analytics-") as temp:
        history_path = Path(temp) / "daily_video_views.jsonl"
        csv_path = Path(temp) / "daily_video_views.csv"
        try:
            drive = get_drive_client()
            archive_folder = get_or_create_archive_folder(drive)
            download_history(drive, archive_folder, history_path)
            history_read_ok = True
        except Exception as exc:
            errors.append(f"Kalıcı geçmiş: {safe_error(exc)}")
        previous = _read_day_records(history_path, yesterday)
        snapshot, records, collection_errors = (
            _collect_snapshot(now, report_day=report_day) if delayed
            else _collect_snapshot(now)
        )
        errors.extend(collection_errors)
        archive_saved = False
        if drive and archive_folder and history_read_ok:
            try:
                upsert_records(history_path, records, preserve_success_on_failure=True)
                export_csv(history_path, csv_path)
                save_history_and_csv(drive, archive_folder, history_path, csv_path)
                archive_saved = True
            except Exception as exc:
                errors.append(f"Geçmiş Drive'a kaydedilemedi: {safe_error(exc)}")
        elif drive and archive_folder:
            errors.append("Geçmiş okunamadığı için Drive arşivi korunuyor; üzerine yazılmadı.")

        report_accounts = {}
        for account, (target, route, _folder, _keys) in ACCOUNT_TARGETS.items():
            platform_names = {p for owner, _page, p in META_TARGETS if owner == account}
            platform_names.update(p for owner, _env, _fallback, _expected, p in YOUTUBE_TARGETS if owner == account)
            platforms = {p: _platform_totals(snapshot, previous, account, p, today) for p in sorted(platform_names)}
            if delayed:
                # A post-midnight API sample can include views earned after
                # midnight. Preserve its lifetime counts, but daily gained
                # views are not a valid period-specific measurement.
                platforms = {p: (total, None) for p, (total, _delta) in platforms.items()}
            try:
                progress = publication_progress(drive, account, today)
            except Exception as exc:
                errors.append(f"{account} yayın sayacı: {safe_error(exc)}")
                progress = None
            report_accounts[account] = (target, route, platforms, progress)

        rows = [f"🌙 GÜNLÜK SOSYAL MEDYA RAPORU — {report_day:%d.%m.%Y}", ""]
        if delayed:
            rows.extend([
                f"⏰ Gecikmeli ölçüm: {now:%d.%m.%Y %H:%M} TRT.",
                "⚠️ Gece yarısından sonra toplandı: günlük izlenme farkı N/A; "
                "genel görüntülenme ölçüm anındaki değeridir.",
                "",
            ])
        all_daily, all_lifetime = [], []
        completed_total = target_total = failed_total = posts_total = 0
        for account, (target, _route, platforms, progress) in report_accounts.items():
            target_total += target
            rows.append(account.upper())
            if progress:
                completed_total += progress["completed"]
                failed_total += progress["failures"]
                posts_total += progress["posts"]
                mark = "✅" if progress["completed"] >= target else "⚠️"
                rows.append(f"🎬 Yayın: {progress['completed']}/{target} {mark}")
            else:
                rows.append("🎬 Yayın: ⚠️ Veri alınamadı")
            known_daily = [delta for _total, delta in platforms.values() if delta is not None]
            known_total = [total for total, _delta in platforms.values() if total is not None]
            daily_complete = bool(platforms) and len(known_daily) == len(platforms)
            total_complete = bool(platforms) and len(known_total) == len(platforms)
            all_daily.extend(known_daily)
            all_lifetime.extend(known_total)
            daily_prefix = "" if daily_complete else "Kısmi: "
            total_prefix = "" if total_complete else "Kısmi: "
            if known_daily:
                rows.append(f"📈 Bugün: {daily_prefix}+{tr_number(sum(known_daily))}")
            elif total_complete and platforms:
                rows.append("📈 Bugün: N/A (ilk ölçüm / karşılaştırılamıyor)")
            else:
                rows.append("📈 Bugün: ⚠️ Veri alınamadı")
            rows.append(f"👀 Genel: {total_prefix}{tr_number(sum(known_total))}" if known_total else "👀 Genel: ⚠️ Veri alınamadı")
            for platform, (total, delta) in platforms.items():
                total_text = tr_number(total) if total is not None else "⚠️ Veri alınamadı"
                prior = previous.get((account, platform, "account", account, "snapshot_status"))
                delta_text = _daily_delta_text(total, delta, prior)
                publication_status = "Yayın: ⚠️ sayaç alınamadı"
                if progress:
                    route_key = {"Facebook": "fb", "Instagram": "ig", "Facebook 1": "fb_film_1",
                                 "Facebook 2": "fb_film_2", "YouTube": "yt_daily"}.get(platform)
                    if route_key and route_key in progress["platforms"]:
                        stats = progress["platforms"][route_key]
                        publication_status = (f"Yayın ✅{stats['success']} / ❌{stats['failure']}"
                                              f" | Son: {stats['latest_status']}")
                    elif platform == "YouTube" and account == "🌱 Tarladaki Fasulye":
                        stats = progress["platforms"]["yt1"]
                        publication_status = (f"Yayın ✅{stats['success']} / ❌{stats['failure']}"
                                              f" | Son: {stats['latest_status']}")
                    elif platform == "YouTube" and account == "🐧 Beyinsiz Penguen":
                        stats = progress["platforms"]["yt2"]
                        publication_status = (f"Yayın ✅{stats['success']} / ❌{stats['failure']}"
                                              f" | Son: {stats['latest_status']}")
                    elif platform == "YouTube" and account == "😂 Daily Laugh Lab":
                        stats = progress["platforms"]["yt_daily"]
                        publication_status = (f"Yayın ✅{stats['success']} / ❌{stats['failure']}"
                                              f" | Son: {stats['latest_status']}")
                rows.append(f"{platform}: {delta_text} | Genel {total_text}")
                rows.append(f"  {publication_status}")
            rows.append("")
        rows.extend([
            "━━━━━━━━━━━━━━━━━━", "🏆 TÜM HESAPLARIN TOPLAMI",
            f"🎯 Video hedefi: {target_total}" if target_total else "🎯 Video hedefi: ⚠️ Veri alınamadı",
            f"✅ Tamamlanan: {completed_total}" if target_total else "✅ Tamamlanan: ⚠️ Veri alınamadı",
            f"❌ Eksik: {max(target_total - completed_total, 0)}" if target_total else "❌ Eksik: ⚠️ Veri alınamadı",
            f"📈 BUGÜNKÜ TOPLAM: {'Kısmi: ' if len(all_daily) < sum(len(x[2]) for x in report_accounts.values()) else ''}+{tr_number(sum(all_daily))}" if all_daily else ("📈 BUGÜNKÜ TOPLAM: N/A (ilk ölçüm / karşılaştırılamıyor)" if len(all_lifetime) == sum(len(x[2]) for x in report_accounts.values()) else "📈 BUGÜNKÜ TOPLAM: ⚠️ Veri alınamadı"),
            f"👀 GENEL TOPLAM: {'Kısmi: ' if len(all_lifetime) < sum(len(x[2]) for x in report_accounts.values()) else ''}{tr_number(sum(all_lifetime))}" if all_lifetime else "👀 GENEL TOPLAM: ⚠️ Veri alınamadı",
            f"🚨 Yayın hatası: {failed_total}" if target_total else "🚨 Yayın hatası: ⚠️ Veri alınamadı",
            f"✅ Başarılı platform gönderileri: {posts_total}" if target_total else "✅ Başarılı platform gönderileri: ⚠️ Veri alınamadı",
            "📊 Günlük fark: önceki gün sonu snapshot'ına göre; platform sayaç tanımları farklıdır.",
            f"🗄️ Geçmiş: {'Drive’a kaydedildi' if archive_saved else '⚠️ Drive arşivi kaydedilemedi'}",
        ])
        if errors:
            rows.append("\n⚠️ EKSİK VERİ / İZİN:")
            rows.extend(f"• {error}" for error in errors)
        return "\n".join(rows)


def notify(message):
    receipt = send_ntfy(
        "🌙 Günlük Sosyal Medya Raporu",
        compact_phone_report(message, ACCOUNT_TARGETS),
        timeout=20,
        require_ack=True,
    )
    # Only record server-level receipt, never claim Android push delivery.
    print(f"ntfy sunucu alındısı doğrulandı: HTTP {receipt['http_status']}; "
          "telefon teslimatı doğrulanmadı.", flush=True)


if __name__ == "__main__":
    report = build_report()
    print(report)
    notify(report)
