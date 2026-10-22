"""Safe, idempotent export of existing analytics and run evidence to Sheets.

This module never publishes content and never writes to Drive.  Google Sheets
updates are disabled unless both explicit configuration and ``--write`` exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from analytics_archive import SCHEMA as ARCHIVE_SCHEMA
from cloud_omnichannel_publisher import get_drive_client


TZ = ZoneInfo("Europe/Istanbul")
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
ARCHIVE_NAME = "daily_video_views.jsonl"
DEFAULT_ARCHIVE_FOLDER_ID = "1oX3LwQyxofYYxUirJSSv9E2SI3mOJ2uo"
SCHEMA_VERSION = "1.2"
REPO = os.environ.get("GITHUB_REPOSITORY", "emirhankaya-AFK/auto-video-publisher")

# First column is a deterministic key. Updates target fixed row numbers, so a
# retry after a lost HTTP response cannot append a duplicate row.
HEADERS = {
    "PANEL": ("kayıt_anahtarı", "hesap", "platform", "durum", "son_ölçüm_tarihi",
              "ömür_boyu_görüntülenme", "günlük_görüntülenme", "7_günlük_değişim",
              "30_günlük_değişim", "takipçi", "günlük_yayın", "toplam_doğrulanmış_yayın", "hata_sayısı", "veri_durumu", "veri_kaynağı"),
    "HESAPLAR": ("kayıt_anahtarı", "marka", "platform", "hesap_adı", "profil_adresi",
                 "hesap_id", "aktiflik", "son_doğrulama_durumu", "veri_kaynağı"),
    "YAYINLAR": ("kayıt_anahtarı", "marka", "platform", "video_dosya_adı", "drive_dosya_id",
                 "platform_gönderi_id", "gönderi_url", "planlanan_slot", "gerçek_yayın_zamanı",
                 "yayın_türü", "yayın_durumu", "actions_run_url", "kanıt_kaynağı"),
    "GÜNLÜK METRİKLER": ("kayıt_anahtarı", "ölçüm_zamanı", "tarih", "hesap", "platform",
                         "varlık_türü", "varlık_id", "metrik", "değer", "birim", "dönem",
                         "kaynak_api", "kaynak_metrik", "veri_durumu"),
    "HESAP TOPLAMLARI": ("kayıt_anahtarı", "tarih", "hesap", "platform", "ömür_boyu_görüntülenme",
                         "günlük_görüntülenme", "önceki_güne_göre_değişim", "7_günlük_artış", "30_günlük_artış",
                         "takipçi", "günlük_takipçi_değişimi", "toplam_doğrulanmış_yayın",
                         "günlük_doğrulanmış_yayın", "veri_durumu", "veri_kaynağı"),
    "İŞLEM LOGLARI": ("kayıt_anahtarı", "run_id", "workflow", "tetikleyici", "başlangıç_utc",
                      "bitiş_utc", "durum", "sonuç", "run_url", "kanıt_türü"),
    "HATALAR": ("kayıt_anahtarı", "ilk_görülme", "son_görülme", "hesap", "platform", "aşama",
                "hata_türü", "hata_kodu", "tekrar_sayısı", "çözülme_durumu", "kanıt_url", "güvenli_özet"),
    "KAYNAK SAĞLIĞI": ("kayıt_anahtarı", "tarih", "kaynak", "hesap", "platform", "erişim_durumu",
                       "izin_durumu", "token_bitiş_zamanı", "son_başarılı_veri", "hata_sayısı", "kanıt"),
    "GEÇMİŞ KANIT": ("kayıt_anahtarı", "tarih", "hesap", "platform", "kanıt_türü", "varlık_id",
                    "değer_veya_durum", "kaynak", "kanıt_url", "veri_durumu"),
    "KURULUM": ("kayıt_anahtarı", "şema_sürümü", "ayar", "değer", "durum", "açıklama"),
}

# Values reflect current master stats_reporter routing. Threads is represented
# for the six requested brands, but its collector is not in master (PR #46 is
# intentionally not imported or modified here).
ACCOUNT_PLATFORMS = (
    ("Tarladaki Fasulye", "Facebook", "Tarladaki Fasulye", "@tarladakifasulye_", "active", "stats_reporter / Meta"),
    ("Tarladaki Fasulye", "Instagram", "Tarladaki Fasulye", "@tarladakifasulye_", "active", "stats_reporter / Meta"),
    ("Tarladaki Fasulye", "YouTube", "TOKEN_CHANNEL1_JSON", "N/A", "active", "stats_reporter / YouTube"),
    ("Tarladaki Fasulye", "Threads", "tarladakifasulye_", "@tarladakifasulye_", "not_collected", "Threads metrik kaynağı master'da yok (PR #46 ayrı)"),
    ("Beyinsiz Penguen", "Facebook", "Beyinsiz Penguen", "@beyinsizpenguen", "active", "stats_reporter / Meta"),
    ("Beyinsiz Penguen", "Instagram", "Beyinsiz Penguen", "@beyinsizpenguen", "active", "stats_reporter / Meta"),
    ("Beyinsiz Penguen", "YouTube", "TOKEN_CHANNEL2_JSON", "N/A", "active", "stats_reporter / YouTube"),
    ("Beyinsiz Penguen", "Threads", "beyinsizpenguen", "@beyinsizpenguen", "not_collected", "Threads metrik kaynağı master'da yok (PR #46 ayrı)"),
    ("Gönle Düşen", "Facebook", "Gönle Düşen", "N/A", "active", "stats_reporter / Meta"),
    ("Gönle Düşen", "Instagram", "Gönle Düşen", "N/A", "active", "stats_reporter / Meta"),
    ("Gönle Düşen", "Threads", "gonl_edusen", "@gonl_edusen", "not_collected", "Threads metrik kaynağı master'da yok (PR #46 ayrı)"),
    ("Daily Laugh Lab", "Facebook", "Daily Laugh Lab", "N/A", "active", "stats_reporter / Meta"),
    ("Daily Laugh Lab", "Instagram", "Daily Laugh Lab", "N/A", "active", "stats_reporter / Meta"),
    ("Daily Laugh Lab", "YouTube", "TOKEN_DAILY_LAUGH_LAB_JSON", "N/A", "active", "stats_reporter / YouTube"),
    ("Daily Laugh Lab", "Threads", "daily.laughlab", "@daily.laughlab", "not_collected", "Threads metrik kaynağı master'da yok (PR #46 ayrı)"),
    ("Film Mağarası", "Facebook", "Film Mağarası", "N/A", "active", "stats_reporter / Meta; Facebook sayfa 1"),
    ("Film Mağarası", "Instagram", "Film Mağarası", "N/A", "active", "stats_reporter / Meta"),
    ("Film Mağarası", "Threads", "film_magrasi", "@film_magrasi", "not_collected", "Threads metrik kaynağı master'da yok (PR #46 ayrı)"),
    ("Filmmagrasi", "Facebook", "Filmmagrasi", "N/A", "active", "stats_reporter / Meta; Facebook sayfa 2"),
    ("ToonZone", "Facebook", "ToonZone", "N/A", "active", "stats_reporter / Meta"),
    ("ToonZone", "Instagram", "ToonZone", "N/A", "active", "stats_reporter / Meta"),
    ("ToonZone", "Threads", "toonzone.tr", "@toonzone.tr", "not_collected", "Threads metrik kaynağı master'da yok (PR #46 ayrı)"),
)

# Verified account identifiers are included only where explicitly supplied.
# Do not infer IDs from handles or mix the separate Facebook page identities.
ACCOUNT_IDS = {
    ("Film Mağarası", "Threads"): "28752898447698066",
}

DRIVE_TARGETS = (
    ("Tarladaki Fasulye", "DRIVE_FOLDER_ID", ("yt1", "fb", "ig")),
    ("Beyinsiz Penguen", "DRIVE_FOLDER_ID", ("yt2", "fb", "ig")),
    ("Gönle Düşen", "GONLE_DUSEN_DRIVE_FOLDER_ID", ("fb", "ig")),
    ("Daily Laugh Lab", "DAILY_LAUGH_DRIVE_FOLDER_ID", ("fb", "ig", "yt_daily")),
    ("Film Mağarası", "FILM_DRIVE_FOLDER_ID", ("fb_film_1", "fb_film_2", "ig")),
    ("ToonZone", "TOONZONE_DRIVE_FOLDER_ID", ("fb", "ig")),
)
RESULTS = {
    "yt1": ("YouTube", "done_yt1_slot", "result_yt1", "failure_slot_yt1"),
    "yt2": ("YouTube", "done_yt2_slot", "result_yt2", "failure_slot_yt2"),
    "yt_daily": ("YouTube", "done_yt_daily_slot", "result_yt_daily", "failure_slot_yt_daily"),
    "fb": ("Facebook", "done_fb_slot", "result_fb", "failure_slot_fb"),
    "fb_film_1": ("Facebook 1", "done_fb_film_1_slot", "result_fb_film_1", "failure_slot_fb_film_1"),
    "fb_film_2": ("Facebook 2", "done_fb_film_2_slot", "result_fb_film_2", "failure_slot_fb_film_2"),
    "ig": ("Instagram", "done_ig_slot", "result_ig", "failure_slot_ig"),
}


def _key(*parts: Any) -> str:
    raw = "\x1f".join("" if value is None else str(value) for value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cell(value: Any) -> Any:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _local_day(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(TZ).date().isoformat()
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def safe_public_url(value: Any) -> str:
    """Keep a public permalink only; never persist query/fragment credentials."""
    if not isinstance(value, str) or not value.startswith("https://"):
        return "N/A"
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if parts.username or parts.password:
            return "N/A"
        if not any(host == domain or host.endswith("." + domain) for domain in (
            "facebook.com", "fb.watch", "instagram.com", "youtube.com", "youtu.be", "threads.net",
        )):
            return "N/A"
        if (host == "youtube.com" or host.endswith(".youtube.com")) and parts.path == "/watch":
            video_id = parse_qs(parts.query).get("v", [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return f"https://www.youtube.com/watch?v={video_id}"
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return "N/A"


def _slot_date(slot: str | None) -> str | None:
    if not slot:
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(slot))
    return match.group(1) if match else None


def _publication_type(slot: str | None) -> str:
    text = str(slot or "")
    if text.startswith("manual-") or "-manual-" in text:
        return "manüel"
    if text.startswith("backfill-") or "-backfill-" in text:
        return "telafi/backfill"
    if _slot_date(text):
        return "cron/slot"
    return "N/A (slot türü bilinmiyor)"


def _canonical_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy display labels while preserving platform separation."""
    row = dict(record)
    account = str(row.get("account") or "")
    platform = str(row.get("platform") or "")
    aliases = {
        "🌱 Tarladaki Fasulye": "Tarladaki Fasulye",
        "🐧 Beyinsiz Penguen": "Beyinsiz Penguen",
        "❤️ Gönle Düşen": "Gönle Düşen",
        "😂 Daily Laugh Lab": "Daily Laugh Lab",
        "📺 ToonZone": "ToonZone",
    }
    if account == "🎬 Film Mağarası + Filmmagrasi":
        if platform in {"Facebook 2", "Facebook page 2"}:
            row["account"], row["platform"] = "Filmmagrasi", "Facebook"
        else:
            row["account"] = "Film Mağarası"
            if platform in {"Facebook 1", "Facebook page 1"}:
                row["platform"] = "Facebook"
    else:
        row["account"] = aliases.get(account, account)
    return row


def _archive_rows(records: Iterable[dict[str, Any]]) -> list[list[Any]]:
    rows: dict[str, list[Any]] = {}
    for record in records:
        metric = str(record.get("metric") or "unknown")
        row_key = _key("archive", record.get("period"), record.get("account"), record.get("platform"),
                       record.get("entity_type"), record.get("entity_id"), metric)
        rows[row_key] = [row_key, record.get("measured_at"), record.get("period"), record.get("account"),
                         record.get("platform"), record.get("entity_type"), record.get("entity_id"),
                         metric, record.get("value"), record.get("unit"), record.get("period"),
                         record.get("source_api"), record.get("source_metric"), record.get("status", "unavailable")]
    return list(rows.values())


def _daily_metric_rows(records: list[dict[str, Any]]) -> tuple[list[list[Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    """Return raw snapshot rows plus conservative per-video daily deltas."""
    rows = {row[0]: row for row in _archive_rows(records)}
    by_video: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    snapshots: dict[tuple[str, str, str], dict[str, Any]] = {}
    video_ids_by_day: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for rec in records:
        account, platform = str(rec.get("account") or "N/A"), str(rec.get("platform") or "N/A")
        period = str(rec.get("period") or "")
        if rec.get("metric") == "snapshot_status" and rec.get("entity_type") == "account":
            snapshots[(account, platform, period)] = rec
        if rec.get("metric") == "view_count" and rec.get("entity_type") == "video" and period:
            video_id = str(rec.get("entity_id") or "N/A")
            by_video[(account, platform, video_id)][period] = rec
            video_ids_by_day[(account, platform, period)].add(video_id)

    by_platform: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"total": None, "daily": {}, "weekly": None, "monthly": None, "followers": None})
    dates = sorted({str(rec.get("period")) for rec in records if rec.get("period")})
    latest_day = dates[-1] if dates else None
    previous_day = (datetime.fromisoformat(latest_day).date() - timedelta(days=1)).isoformat() if latest_day else None
    week_day = (datetime.fromisoformat(latest_day).date() - timedelta(days=7)).isoformat() if latest_day else None
    month_day = (datetime.fromisoformat(latest_day).date() - timedelta(days=30)).isoformat() if latest_day else None

    for rec in records:
        account, platform = str(rec.get("account") or "N/A"), str(rec.get("platform") or "N/A")
        metric, entity_type = rec.get("metric"), rec.get("entity_type")
        summary = by_platform[(account, platform)]
        if metric == "lifetime_views" and entity_type == "account" and rec.get("period") == latest_day:
            summary["total"] = _int_value(rec.get("value")) if rec.get("status") == "ok" else None
        if metric in {"followers", "follower_count", "followers_count", "subscribers"} and rec.get("period") == latest_day:
            summary["followers"] = _int_value(rec.get("value")) if rec.get("status") == "ok" else None

    # Per-video deltas require an exact prior calendar-day observation. New
    # videos can contribute only when the archive records publication date on
    # that date; resets/negative deltas remain unavailable, never zero/loss.
    delta_by_day: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(dict)
    for (account, platform, video_id), daily in by_video.items():
        periods = sorted(daily)
        for day in periods:
            rec = daily[day]
            current = _int_value(rec.get("value")) if rec.get("status") == "ok" else None
            prior_date = (datetime.fromisoformat(day).date() - timedelta(days=1)).isoformat()
            prior_rec = daily.get(prior_date)
            previous = _int_value(prior_rec.get("value")) if prior_rec and prior_rec.get("status") == "ok" else None
            value: int | None = None
            status = "unavailable"
            if current is not None and previous is not None and current >= previous:
                value, status = current - previous, "ok"
            elif current is not None and not prior_rec and _local_day(rec.get("published_at")) == day:
                value, status = current, "ok"
            day_key = _key("daily", day, account, platform, "video", video_id, "daily_views")
            rows[day_key] = [day_key, rec.get("measured_at"), day, account, platform, "video", video_id,
                             "daily_views", value if value is not None else "N/A", "views", day,
                             rec.get("source_api"), "derived from consecutive lifetime view snapshots", status]
            delta_by_day[(account, platform, day)][video_id] = {"value": value, "status": status}

    # Aggregate only when every known video on that date has a valid delta and
    # the source snapshot itself succeeded. Partial sums are not mislabeled.
    for account, platform, day in video_ids_by_day:
        videos = video_ids_by_day[(account, platform, day)]
        values = [delta_by_day.get((account, platform, day), {}).get(video, {}) for video in videos]
        snapshot = snapshots.get((account, platform, day), {})
        expected_count = _int_value(snapshot.get("value"))
        snap_ok = snapshot.get("status") == "ok" and expected_count == len(videos)
        known = bool(values) and all(v.get("status") == "ok" and v.get("value") is not None for v in values)
        prior_day = (datetime.fromisoformat(day).date() - timedelta(days=1)).isoformat()
        prior_videos = video_ids_by_day.get((account, platform, prior_day), set())
        # Missing formerly measured videos make the account delta incomplete,
        # even if today's API returned a superficially successful snapshot.
        # A newly published video can join the inventory, but an existing one
        # disappearing cannot silently be treated as zero daily views.
        inventory_complete = prior_videos.issubset(videos)
        total = sum(v["value"] for v in values) if known and snap_ok and inventory_complete else None
        delta_key = _key("daily", day, account, platform, "account", account, "daily_views")
        sample = next((items[day] for (a, p, _), items in by_video.items() if a == account and p == platform and day in items), {})
        rows[delta_key] = [delta_key, sample.get("measured_at"), day, account, platform, "account", account,
                           "daily_views", total if total is not None else "N/A", "views", day,
                           sample.get("source_api"), "derived from complete video snapshot deltas",
                           "ok" if total is not None else "unavailable"]
        by_platform[(account, platform)]["daily"][day] = total
        if day == latest_day and not inventory_complete:
            # A current account total summing only surviving videos is not
            # a trustworthy all-time total when we know a prior video vanished.
            by_platform[(account, platform)]["total"] = None

    # Windowed growth requires exact calendar-day baselines and complete
    # snapshots. Missing or reset data stays N/A; never interpolate.
    if latest_day:
        for key, summary in by_platform.items():
            account, platform = key
            for window, baseline_day in (("weekly", week_day), ("monthly", month_day)):
                current_ids = {video for (a, p, video), date_map in by_video.items()
                               if a == account and p == platform and latest_day in date_map}
                baseline_ids = {video for (a, p, video), date_map in by_video.items()
                                if a == account and p == platform and baseline_day in date_map} if baseline_day else set()
                latest_snapshot = snapshots.get((account, platform, latest_day), {})
                baseline_snapshot = snapshots.get((account, platform, baseline_day), {}) if baseline_day else {}
                latest_complete = (latest_snapshot.get("status") == "ok" and
                                   _int_value(latest_snapshot.get("value")) == len(current_ids) and bool(current_ids))
                baseline_complete = (baseline_snapshot.get("status") == "ok" and
                                     _int_value(baseline_snapshot.get("value")) == len(baseline_ids))
                deltas = []
                # Do not report an apparent 7/30-day gain if older inventory
                # disappeared from the latest API snapshot. Its contribution
                # is unknown, so summing surviving videos would undercount.
                valid = bool(baseline_day and latest_complete and baseline_complete
                             and baseline_ids.issubset(current_ids))
                if valid:
                    for video in current_ids:
                        date_map = by_video[(account, platform, video)]
                        latest = date_map.get(latest_day, {})
                        baseline = date_map.get(baseline_day, {})
                        current_value = _int_value(latest.get("value")) if latest.get("status") == "ok" else None
                        baseline_value = _int_value(baseline.get("value")) if baseline.get("status") == "ok" else None
                        if baseline:
                            if current_value is None or baseline_value is None or current_value < baseline_value:
                                valid = False
                                break
                            deltas.append(current_value - baseline_value)
                        elif (current_value is not None and
                              (published_day := _local_day(latest.get("published_at"))) and
                              baseline_day < published_day <= latest_day):
                            deltas.append(current_value)
                        else:
                            valid = False
                            break
                summary[window] = sum(deltas) if valid and len(deltas) == len(current_ids) else None
    return list(rows.values()), by_platform


def _account_rows() -> list[list[Any]]:
    result = []
    for brand, platform, name, profile, active, source in ACCOUNT_PLATFORMS:
        key = _key("account", brand, platform)
        state = ("Collector kodda tanımlı; canlı bağlantı bu aktarımda doğrulanmıyor"
                 if active == "active" else "Collector master'da yok; metrik N/A")
        account_id = ACCOUNT_IDS.get((brand, platform), "N/A (ID kaynakta yok)")
        result.append([key, brand, platform, name, profile, account_id,
                       "kodda tanımlı" if active == "active" else "izleniyor / veri yok", state, source])
    return result


def _drive_publications(drive, today: str) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]], dict[tuple[str, str], dict[str, int | None]]]:
    publications: dict[str, list[Any]] = {}
    errors: dict[str, list[Any]] = {}
    evidence: dict[str, list[Any]] = {}
    counts: dict[tuple[str, str], dict[str, int | None]] = defaultdict(lambda: {"daily": None, "total": None, "errors": None})
    if drive is None:
        return [], [], [], counts
    for brand, env_name, keys in DRIVE_TARGETS:
        route = {"Tarladaki Fasulye": "tarladaki", "Beyinsiz Penguen": "penguen",
                 "Gönle Düşen": "gonle", "Daily Laugh Lab": "daily_laugh",
                 "Film Mağarası": "film", "ToonZone": "toonzone"}[brand]
        folder_id = os.environ.get(env_name, "").strip()
        if not folder_id and brand == "Film Mağarası":
            folder_id = "1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW"
        if not folder_id and brand == "ToonZone":
            folder_id = "14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF"
        if not folder_id:
            continue
        for key in keys:
            platform = RESULTS[key][0]
            result_brand = "Filmmagrasi" if key == "fb_film_2" else brand
            if key in {"fb_film_1", "fb_film_2"}:
                platform = "Facebook"
            counts[(result_brand, platform)] = {"daily": 0, "total": 0, "errors": 0}
        token = None
        while True:
            response = drive.files().list(
                q=f"'{folder_id}' in parents and trashed=false", pageSize=1000, pageToken=token,
                fields="nextPageToken,files(id,name,mimeType,appProperties)",
                includeItemsFromAllDrives=True, supportsAllDrives=True,
            ).execute()
            for item in response.get("files", []):
                if item.get("mimeType") not in {"video/mp4", "application/vnd.google-apps.shortcut"}:
                    continue
                props = item.get("appProperties") or {}
                for key in keys:
                    descriptor = RESULTS.get(key)
                    if not descriptor:
                        continue
                    platform, done_prop, result_prop, fail_prop = descriptor
                    result_brand = ("Filmmagrasi" if key == "fb_film_2" else
                                    "Film Mağarası" if brand == "Film Mağarası" else brand)
                    slot = props.get(done_prop)
                    failure = props.get(fail_prop)
                    result_value = props.get(result_prop)
                    latest_success = slot if slot and result_value else None
                    latest_failure = failure if failure else None
                    if latest_success and latest_failure:
                        status = "başarısız/belirsiz" if latest_failure >= latest_success else "başarılı"
                    elif latest_success:
                        status = "başarılı"
                    elif latest_failure:
                        status = "başarısız/belirsiz"
                    else:
                        status = None
                    if not status:
                        continue
                    event_slot = (latest_failure if status == "başarısız/belirsiz" else latest_success) or "N/A"
                    if event_slot != "N/A" and f"-{route}" not in event_slot:
                        continue
                    if key in {"fb_film_1", "fb_film_2"}:
                        platform = "Facebook"
                    event_key = _key("publication", item.get("id"), key, event_slot)
                    result_text = str(result_value or "")
                    if status != "başarılı":
                        result_text = ""
                    url = safe_public_url(result_text)
                    post_ref = "N/A"
                    if url != "N/A":
                        safe_parts = urlsplit(url)
                        if safe_parts.path == "/watch":
                            post_ref = parse_qs(safe_parts.query).get("v", ["N/A"])[0]
                        else:
                            post_ref = safe_parts.path.rstrip("/").split("/")[-1] or "N/A"
                    elif re.fullmatch(r"(?:\d{4,32}|[A-Za-z0-9_-]{11})", result_text):
                        post_ref = result_text
                    row = [event_key, result_brand, platform, item.get("name"), item.get("id"), post_ref, url,
                           event_slot, "N/A (platform zamanı saklanmıyor)",
                           _publication_type(event_slot), status,
                           "N/A (Drive metadata ile run eşleşmesi yok)", "Google Drive appProperties"]
                    publications[event_key] = row
                    day = _slot_date(event_slot)
                    counts[(result_brand, platform)]["total"] += int(status == "başarılı")
                    counts[(result_brand, platform)]["daily"] += int(status == "başarılı" and day == today)
                    if status != "başarılı":
                        counts[(result_brand, platform)]["errors"] += 1
                        error_key = _key("drive-error", item.get("id"), key, event_slot)
                        errors[error_key] = [error_key, day or "N/A", day or "N/A", result_brand, platform,
                                             "yayın denemesi / Drive sonucu", "Drive failure appProperty",
                                             "N/A (ayrıntı GitHub run logunda olabilir)", 1, "açık / uzlaştırma gerekli",
                                             "N/A", "Drive kaydı başarısız veya sonucu belirsiz gösteriyor; ham hata alınmadı"]
                    evidence_key = _key("drive-evidence", item.get("id"), key, event_slot)
                    evidence[evidence_key] = [evidence_key, day or "N/A", result_brand, platform,
                                              "Drive yayın sonucu", item.get("id"), status,
                                              "Google Drive appProperties", url, "doğrulanmış" if status == "başarılı" else "hata/belirsiz"]
            token = response.get("nextPageToken")
            if not token:
                break
    return list(publications.values()), list(errors.values()), list(evidence.values()), counts


def _requests_get_with_retry(url: str, *, params: dict[str, Any], headers: dict[str, str],
                             timeout: int, sleep=time.sleep, attempts: int = 4):
    """Retry only idempotent GitHub GETs on throttling/transient server errors."""
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                return response
            try:
                retry_after = float(response.headers.get("Retry-After", "0"))
            except (TypeError, ValueError):
                retry_after = 0
            delay = min(30.0, max(retry_after, 2 ** attempt))
        except (requests.Timeout, requests.ConnectionError):
            if attempt + 1 >= attempts:
                raise
            delay = min(30.0, 2 ** attempt)
        sleep(delay)
    raise RuntimeError("unreachable retry state")


def _github_runs(token: str | None, now: datetime) -> tuple[list[dict[str, Any]], str]:
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", REPO):
        return [], "not_configured"
    since = (now.astimezone(timezone.utc) - timedelta(days=30)).date().isoformat()
    try:
        runs, page, total = [], 1, None
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        while page <= 100:
            response = _requests_get_with_retry(
                f"https://api.github.com/repos/{REPO}/actions/runs",
                params={"per_page": 100, "page": page, "created": f">={since}"},
                headers=headers, timeout=20,
            )
            status = response.status_code
            response.raise_for_status()
            payload = response.json()
            page_runs = payload.get("workflow_runs", [])
            total = payload.get("total_count", total)
            if not page_runs:
                break
            runs.extend(page_runs)
            if total is not None and len(runs) >= total:
                break
            page += 1
        return runs, "truncated_10000" if total is not None and total > len(runs) else "ok"
    except Exception:
        status = getattr(locals().get("response"), "status_code", None)
        return [], f"error_http_{status}" if status else "error_transport_or_parse"


def _run_rows(runs: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    log_rows, error_rows, evidence_rows = {}, {}, {}
    for run in runs:
        run_id = str(run.get("id") or "N/A")
        workflow = run.get("name") or "N/A"
        url = run.get("html_url") or "N/A"
        status, conclusion = run.get("status") or "N/A", run.get("conclusion") or "N/A"
        created, updated = run.get("created_at") or "N/A", run.get("updated_at") or "N/A"
        key = _key("workflow-run", run_id)
        log_rows[key] = [key, run_id, workflow, run.get("event") or "N/A", created, updated,
                         status, conclusion, url, "GitHub Actions run metadata; raw logs hariç"]
        if conclusion not in {"success", "N/A", None}:
            err_key = _key("workflow-error", run_id)
            error_rows[err_key] = [err_key, created, updated, "N/A", "N/A", "GitHub Actions workflow",
                                   "workflow conclusion", conclusion, 1, "açık", url,
                                   "Workflow başarısız; ham log bu sisteme aktarılmadı"]
        evidence_rows[key] = [key, _local_day(created) or "N/A", "N/A", "N/A", "GitHub Actions run",
                              run_id, f"{workflow}: {status}/{conclusion}", "GitHub Actions API", url,
                              "doğrulanmış run metadata"]
    return list(log_rows.values()), list(error_rows.values()), list(evidence_rows.values())


def _health_rows(today: str, github_status: str, sheet_configured: bool,
                 drive_status: str, records: list[dict[str, Any]] | None = None) -> list[list[Any]]:
    rows = []
    sources = [
        ("Drive analytics arşivi", drive_status, "DRIVE_TOKEN_JSON", "Sadece mevcut JSONL okundu; Drive yazması yok"),
        ("Google Sheets", "credential + ID yapılandırıldı; yazma sonucu bu satırdan bağımsız" if sheet_configured else "kapalı / yapılandırma eksik", "Sheets scope", "Canlı yazım yalnızca explicit --write ile"),
        ("GitHub Actions API", github_status, "actions:read", "Yalnızca run metadata; ham log yok"),
        ("Meta / Facebook / Instagram", "ölçülmedi", "N/A", "Bu aktarım token veya izin denetimi yapmaz"),
        ("YouTube", "ölçülmedi", "N/A", "Bu aktarım OAuth/izin denetimi yapmaz"),
        ("Threads", "master'da veri kaynağı yok", "N/A", "PR #46 değişikliklerine dokunulmadı"),
    ]
    for name, access, permission, note in sources:
        key = _key("health", today, name)
        rows.append([key, today, name, "Tüm hesaplar", "N/A", access, permission, "N/A",
                     today if access == "ok" else "N/A", "N/A", note])
    latest_snapshot: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records or []:
        if record.get("metric") != "snapshot_status" or record.get("entity_type") != "account":
            continue
        normalized = _canonical_record(record)
        key = (str(normalized.get("account") or "N/A"), str(normalized.get("platform") or "N/A"))
        if key not in latest_snapshot or str(record.get("period") or "") > str(latest_snapshot[key].get("period") or ""):
            latest_snapshot[key] = record
    for (account, platform), record in latest_snapshot.items():
        normalized = _canonical_record(record)
        status = "son snapshot başarılı" if record.get("status") == "ok" else "son snapshot hata verdi"
        failure_count = sum(1 for item in records or []
                            if _canonical_record(item).get("account") == account
                            and _canonical_record(item).get("platform") == platform
                            and item.get("metric") == "snapshot_status" and item.get("status") == "error")
        source = record.get("source_api") or "N/A"
        key = _key("health-metric", today, account, platform, source)
        rows.append([key, today, source, account, platform, status,
                     "N/A (token/izin denetimi yapılmadı)", "N/A",
                     record.get("measured_at") if record.get("status") == "ok" else "N/A",
                     failure_count, "Mevcut JSONL snapshot durumundan; canlı bağlantı denetimi değildir"])
    return rows


def build_tables(records: list[dict[str, Any]], runs: list[dict[str, Any]], drive=None,
                 now: datetime | None = None, drive_status: str = "not_checked",
                 github_status: str = "not_checked", sheet_configured: bool = False) -> dict[str, list[list[Any]]]:
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    today = now.date().isoformat()
    records = [_canonical_record(record) for record in records]
    metric_rows, summaries = _daily_metric_rows(records)
    publications, drive_errors, drive_evidence, publication_counts = _drive_publications(drive, today)
    run_logs, run_errors, run_evidence = _run_rows(runs)
    archive_errors = []
    for record in records:
        if record.get("status") != "error":
            continue
        normalized = _canonical_record(record)
        error_key = _key("archive-error", record.get("period"), normalized.get("account"),
                         normalized.get("platform"), record.get("metric"))
        archive_errors.append([error_key, record.get("measured_at"), record.get("measured_at"),
                               normalized.get("account"), normalized.get("platform"),
                               "istatistik toplama", record.get("source_api") or "API collection",
                               "N/A (hata kodu arşivlenmemiş)", 1, "gözlem gerekli", "N/A",
                               "JSONL kaydı error; hassas hata mesajı saklanmadı"])
    errors = {row[0]: row for row in drive_errors + run_errors + archive_errors}
    evidence = {row[0]: row for row in drive_evidence + run_evidence}
    for record in records:
        key = _key("archive-evidence", record.get("period"), record.get("account"), record.get("platform"),
                   record.get("entity_type"), record.get("entity_id"), record.get("metric"))
        normalized = _canonical_record(record)
        evidence[key] = [key, record.get("period") or "N/A", normalized.get("account"),
                         normalized.get("platform"), record.get("metric") or "N/A",
                         record.get("entity_id") or "N/A", _cell(record.get("value")),
                         record.get("source_api") or "N/A", "N/A", record.get("status") or "unavailable"]

    latest_date = max((str(r.get("period")) for r in records if r.get("period")), default="N/A")
    total_rows, panel_rows = [], []
    pairs = {(str(r.get("account") or "N/A"), str(r.get("platform") or "N/A")) for r in records}
    pairs.update((brand, platform) for brand, platform, *_ in ACCOUNT_PLATFORMS)
    for brand, platform in sorted(pairs):
        summary = summaries.get((brand, platform), {})
        total = summary.get("total")
        daily = summary.get("daily", {}).get(latest_date) if latest_date != "N/A" else None
        prior_day = (datetime.fromisoformat(latest_date).date() - timedelta(days=1)).isoformat() if latest_date != "N/A" else None
        prior = summary.get("daily", {}).get(prior_day) if prior_day else None
        daily_delta = daily if daily is not None else None
        week = summary.get("weekly")
        month = summary.get("monthly")
        counts = publication_counts.get((brand, platform), {"daily": None, "total": None, "errors": None})
        metric_state = "ok" if total is not None else "N/A"
        key = _key("totals", latest_date, brand, platform)
        total_rows.append([key, latest_date, brand, platform, _cell(total), _cell(daily),
                           _cell(daily - prior if daily is not None and prior is not None else None),
                           _cell(week), _cell(month), _cell(summary.get("followers")), "N/A", _cell(counts["total"]),
                           _cell(counts["daily"]), metric_state,
                           "daily_video_views.jsonl + Google Drive appProperties"])
        panel_rows.append([key, brand, platform, "kodda tanımlı; canlı erişim doğrulanmadı" if any(b == brand and p == platform and a == "active" for b, p, *_rest, a, _src in ACCOUNT_PLATFORMS) else "izleniyor / collector yok",
                           latest_date, _cell(total), _cell(daily), _cell(week), _cell(month), _cell(summary.get("followers")),
                           _cell(counts["daily"]), _cell(counts["total"]), _cell(counts["errors"]), metric_state,
                           "daily_video_views.jsonl + Google Drive appProperties"])

    setup_rows = []
    setup = [
        ("schema_version", SCHEMA_VERSION, "hazır", "Google Sheets şema sürümü"),
        ("timezone", "Europe/Istanbul", "hazır", "Bütün tarih alanları TRT/Europe-Istanbul"),
        ("spreadsheet_id", "configured" if os.environ.get("ANALYTICS_SHEET_ID", "").strip() else "missing", "gerekli", "ANALYTICS_SHEET_ID repository variable; değer loglanmaz"),
        ("sheets_credentials", "configured" if os.environ.get("ANALYTICS_SHEETS_CREDENTIALS_JSON", "").strip() else "missing", "gerekli", "ANALYTICS_SHEETS_CREDENTIALS_JSON secret; Sheets-only scope"),
        ("drive_archive", drive_status, "ok" if drive_status == "ok" else "kontrol edilmeli", "Mevcut JSONL/CSV korunur; bu modül salt-okunur"),
        ("live_writes", "enabled only with --write + both credentials", "kapalı varsayılan", "Sheet ID veya credential yoksa API yazma çağrısı yapılmaz"),
        ("data_quality", "N/A for unavailable metrics", "korunuyor", "Eksik değer 0'a çevrilmez; tahmin üretilmez"),
        ("Threads", "PR #46 ayrı; mevcut branch'te collector yok", "N/A", "PR #46 dosyaları bu branch'te değiştirilmedi"),
    ]
    for name, value, status, note in setup:
        key = _key("setup", name)
        setup_rows.append([key, SCHEMA_VERSION, name, value, status, note])

    health = _health_rows(today, github_status,
                          bool(os.environ.get("ANALYTICS_SHEET_ID", "").strip()
                               and os.environ.get("ANALYTICS_SHEETS_CREDENTIALS_JSON", "").strip()), drive_status, records)
    return {
        "PANEL": panel_rows,
        "HESAPLAR": _account_rows(),
        "YAYINLAR": publications,
        "GÜNLÜK METRİKLER": metric_rows,
        "HESAP TOPLAMLARI": total_rows,
        "İŞLEM LOGLARI": run_logs,
        "HATALAR": list(errors.values()),
        "KAYNAK SAĞLIĞI": health,
        "GEÇMİŞ KANIT": list(evidence.values()),
        "KURULUM": setup_rows,
    }


def load_archive_records(drive, folder_id: str | None = None) -> tuple[list[dict[str, Any]], str]:
    """Download existing JSONL from Drive to a temp file, without Drive writes."""
    folder_id = (folder_id or os.environ.get("ANALYTICS_DRIVE_FOLDER_ID", "").strip()
                 or DEFAULT_ARCHIVE_FOLDER_ID)
    if not folder_id:
        return [], "folder_not_configured"
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", folder_id):
        return [], "folder_id_invalid"
    def list_history(parent_id: str) -> list[dict[str, Any]]:
        query = f"'{parent_id}' in parents and name='{ARCHIVE_NAME}' and trashed=false"
        response = drive.files().list(q=query, pageSize=100, fields="files(id,name,modifiedTime)",
                                      includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        return response.get("files", [])

    files = list_history(folder_id)
    if not files:
        # The existing reporter historically created this named archive
        # folder. Search it read-only as a compatibility fallback.
        response = drive.files().list(
            q="name='Auto Video Publisher Analytics' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            pageSize=100, fields="files(id,name,modifiedTime)", includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        for folder in response.get("files", []):
            files = list_history(folder["id"])
            if files:
                break
    if not files:
        return [], "archive_file_not_found"
    item = max(files, key=lambda row: row.get("modifiedTime", ""))
    import io
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, drive.files().get_media(fileId=item["id"]), chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    records = []
    for line in buffer.getvalue().decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        # Accept older JSONL records with missing optional fields; do not
        # mutate or re-upload the Drive archive.
        for field in ARCHIVE_SCHEMA:
            row.setdefault(field, None)
        records.append(row)
    return records, "ok"


def collect_github_runs(now: datetime | None = None) -> tuple[list[dict[str, Any]], str]:
    now = now or datetime.now(timezone.utc)
    return _github_runs(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"), now)


def _sheets_client(raw_credentials: str):
    info = json.loads(raw_credentials)
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError("Sheets credential must be a service-account JSON object")
    credentials = ServiceAccountCredentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _execute_with_retry(request, sleep=time.sleep, attempts: int = 4):
    for attempt in range(attempts):
        try:
            return request.execute(num_retries=0)
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
            retry_after = getattr(exc, "resp", {}).get("retry-after") if getattr(exc, "resp", None) else None
            try:
                retry_delay = float(retry_after or 0)
            except (TypeError, ValueError):
                retry_delay = 0
            delay = min(30.0, max(retry_delay, 2 ** attempt))
        except (requests.Timeout, requests.ConnectionError, TimeoutError, OSError):
            if attempt + 1 >= attempts:
                raise
            delay = min(30.0, 2 ** attempt)
        sleep(delay)
    raise RuntimeError("unreachable retry state")


def _quote_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _ensure_tabs(sheets, spreadsheet_id: str) -> dict[str, int]:
    meta = _execute_with_retry(sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)",
    ))
    known = {item["properties"]["title"]: item["properties"]["sheetId"] for item in meta.get("sheets", [])}
    missing = [title for title in HEADERS if title not in known]
    if missing:
        _execute_with_retry(sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}} for title in missing]},
        ))
        meta = _execute_with_retry(sheets.spreadsheets().get(
            spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)",
        ))
        known = {item["properties"]["title"]: item["properties"]["sheetId"] for item in meta.get("sheets", [])}
    return known


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _preflight_existing_tab_headers(sheets, spreadsheet_id: str) -> None:
    """Check every existing owned tab before any Sheets mutation.

    A mismatch in a later tab must not leave earlier tabs partially updated.
    Missing tabs are created only after this read-only preflight succeeds.
    Each tab is rechecked by _sync_tab at write time.
    """
    metadata = _execute_with_retry(sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties(title)",
    ))
    titles = {row.get("properties", {}).get("title")
              for row in metadata.get("sheets", [])}
    for title, header in HEADERS.items():
        if title not in titles:
            continue
        response = _execute_with_retry(sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_tab(title)}!A1:{_column_name(len(header))}1",
        ))
        existing = response.get("values", [])
        if existing and tuple(existing[0][:len(header)]) != tuple(header):
            raise RuntimeError(f"sheet header mismatch: {title}")
        if existing:
            # Read only the key column rather than downloading all cells twice.
            # Detect corruption in a later tab before earlier tabs are updated.
            key_rows = _execute_with_retry(sheets.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=f"{_quote_tab(title)}!A2:A",
            )).get("values", [])
            seen = set()
            for key_row in key_rows:
                if not key_row or not key_row[0]:
                    continue
                record_key = str(key_row[0])
                if record_key in seen:
                    raise RuntimeError(f"duplicate existing sheet record key: {title}")
                seen.add(record_key)


def _sync_tab(sheets, spreadsheet_id: str, title: str, header: tuple[str, ...], rows: list[list[Any]]) -> tuple[int, int]:
    quoted = _quote_tab(title)
    response = _execute_with_retry(sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"{quoted}!A:{_column_name(len(header))}",
        # Sheets defaults to locale-formatted strings: numeric 1234 can be
        # returned as "1.234" and trigger writes on every identical sync.
        # Compare typed raw values, matching our RAW write requests.
        valueRenderOption="UNFORMATTED_VALUE",
    ))
    existing = response.get("values", [])
    if not existing:
        _execute_with_retry(sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=f"{quoted}!A1",
            valueInputOption="RAW", body={"values": [list(header)]},
        ))
        existing = [list(header)]
    elif tuple(existing[0][:len(header)]) != tuple(header):
        raise RuntimeError(f"sheet header mismatch: {title}")
    key_to_row: dict[str, int] = {}
    for index, values in enumerate(existing[1:], start=2):
        if values and values[0]:
            key = str(values[0])
            if key in key_to_row:
                raise RuntimeError(f"duplicate existing sheet record key: {title}")
            key_to_row[key] = index

    updates, new_rows = [], []
    incoming: dict[str, list[Any]] = {}
    for row in rows:
        normalized = [_cell(value) for value in row]
        if len(normalized) != len(header):
            raise ValueError(f"invalid row width for {title}")
        incoming[str(normalized[0])] = normalized
    for key, normalized in incoming.items():
        row_number = key_to_row.get(key)
        if row_number:
            old_row = existing[row_number - 1] if row_number - 1 < len(existing) else []
            old_normalized = [value if value != "" else "N/A" for value in old_row[:len(header)]]
            old_normalized += ["N/A"] * max(0, len(header) - len(old_normalized))
            if old_normalized != normalized:
                updates.append({"range": f"{quoted}!A{row_number}", "values": [normalized]})
        else:
            new_rows.append(normalized)

    # Direct, deterministic range updates are safe to retry even when the
    # server accepted the previous request but the response was lost.
    for start in range(0, len(updates), 500):
        _execute_with_retry(sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": updates[start:start + 500]},
        ))
    if new_rows:
        first = max(2, len(existing) + 1)
        for offset in range(0, len(new_rows), 500):
            chunk = new_rows[offset:offset + 500]
            row_start = first + offset
            row_end = row_start + len(chunk) - 1
            _execute_with_retry(sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id, range=f"{quoted}!A{row_start}:{_column_name(len(header))}{row_end}",
                valueInputOption="RAW", body={"values": chunk},
            ))
    return len(updates), len(new_rows)


def sync_tables(sheets, spreadsheet_id: str, tables: dict[str, list[list[Any]]]) -> dict[str, tuple[int, int]]:
    _preflight_existing_tab_headers(sheets, spreadsheet_id)
    _ensure_tabs(sheets, spreadsheet_id)
    return {title: _sync_tab(sheets, spreadsheet_id, title, HEADERS[title], tables.get(title, []))
            for title in HEADERS}


def run_sync(*, write: bool = False, now: datetime | None = None,
             drive=None, sheets=None, github_runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    now = now or datetime.now(TZ)
    archive_status, github_status, drive_status = "not_checked", "not_checked", "not_checked"
    records: list[dict[str, Any]] = []
    if drive is None:
        try:
            drive = get_drive_client()
            drive_status = "ok"
        except Exception:
            drive, drive_status, archive_status = None, "error", "drive_unavailable"
    if drive is not None:
        try:
            records, archive_status = load_archive_records(drive)
            drive_status = "ok" if archive_status == "ok" else archive_status
        except Exception:
            archive_status, drive_status = "error", "error"
    if github_runs is None:
        github_runs, github_status = collect_github_runs(now.astimezone(timezone.utc))
    else:
        github_status = "ok"
    configured = bool(os.environ.get("ANALYTICS_SHEET_ID", "").strip()
                      and os.environ.get("ANALYTICS_SHEETS_CREDENTIALS_JSON", "").strip())
    tables = build_tables(records, github_runs or [], drive=drive, now=now,
                          drive_status=drive_status, github_status=github_status,
                          sheet_configured=configured)
    counts = {name: len(rows) for name, rows in tables.items()}
    if not write:
        return {"mode": "dry-run", "row_counts": counts, "archive_status": archive_status,
                "github_status": github_status, "writes": 0}
    spreadsheet_id = os.environ.get("ANALYTICS_SHEET_ID", "").strip()
    credential_json = os.environ.get("ANALYTICS_SHEETS_CREDENTIALS_JSON", "").strip()
    if not spreadsheet_id or not credential_json:
        return {"mode": "disabled", "row_counts": counts, "archive_status": archive_status,
                "github_status": github_status, "writes": 0,
                "reason": "spreadsheet id or Sheets-only credential missing"}
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", spreadsheet_id):
        return {"mode": "disabled", "row_counts": counts, "archive_status": archive_status,
                "github_status": github_status, "writes": 0,
                "reason": "spreadsheet id format invalid"}
    # A transient Drive/GitHub failure must never overwrite existing Sheet
    # summaries with placeholders and make a partially collected report look
    # authoritative. Dry-run remains available for troubleshooting.
    if archive_status != "ok" or github_status != "ok" or not records:
        return {"mode": "source_unavailable", "row_counts": counts,
                "archive_status": archive_status, "github_status": github_status,
                "writes": 0, "reason": "source collection incomplete"}
    if sheets is None:
        try:
            sheets = _sheets_client(credential_json)
        except Exception as exc:
            raise SafeSyncError("sheets_auth", exc) from None
    try:
        results = sync_tables(sheets, spreadsheet_id, tables)
    except Exception as exc:
        raise SafeSyncError("sheets_sync", exc) from None
    # Never return or log spreadsheet ID, credential contents, or API bodies.
    return {"mode": "write", "row_counts": counts,
            "updated_rows": sum(item[0] for item in results.values()),
            "inserted_rows": sum(item[1] for item in results.values()),
            "archive_status": archive_status, "github_status": github_status, "writes": sum(sum(item) for item in results.values())}


class SafeSyncError(RuntimeError):
    """Carries safe diagnostics only; never interpolates API bodies."""
    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.error_type = type(original).__name__
        self.http_status = getattr(getattr(original, "resp", None), "status", None)
        super().__init__("analytics sync failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="never write to Google Sheets")
    mode.add_argument("--write", action="store_true", help="sync only when both Sheet ID and credential exist")
    args = parser.parse_args(argv)
    try:
        result = run_sync(write=args.write)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        # Surface incomplete automatic sync as a failed Actions job, not a
        # misleading green run. Dry-run and explicitly unconfigured syncs
        # retain their existing behavior.
        return 1 if result["mode"] == "source_unavailable" else 0
    except SafeSyncError as exc:
        print(json.dumps({"mode": "error", "stage": exc.stage, "error_type": exc.error_type,
                          "http_status": exc.http_status}, ensure_ascii=False, sort_keys=True), flush=True)
        return 1
    except Exception as exc:
        # Avoid traceback/exception message: API exceptions may contain a body.
        print(json.dumps({"mode": "error", "stage": "collection_or_transform",
                          "error_type": type(exc).__name__}, sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
