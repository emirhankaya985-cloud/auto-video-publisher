import io
import hashlib
import json
import os
from publication_safety import route_paused, require_route_enabled, batch_exception_allowed, platform_allowed, new_meta_route_enabled
import random
import re
import requests
import tempfile
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.http import MediaIoBaseDownload
from instagram_media_compat import (
    check_full_decode,
    create_diagnostic_clip,
    log_media_diagnostics,
    prepare_instagram_upload,
    remux_mp4_faststart,
)
from batch_api_client import BatchGate
from cover_artwork import (
    CoverScope,
    cover_config,
    download_and_validate_cover,
    match_fixed_account_cover,
    match_toonzone_cover,
    set_youtube_thumbnail,
)
from ordered_channels import CARTOON_FOLDER_ID, CHANNELS as ORDERED_CHANNELS, analyze_files, toonzone_metadata
from threads_publisher import build_threads_video_url, publish_threads_video, threads_configured
from ntfy_notifications import send_ntfy
from toonzone_schedule import due_toonzone_slots, toonzone_part_eligible

from cloud_omnichannel_publisher import (
    ETSY_LINK,
    MetaAPIError,
    YOUTUBE_TAGS,
    get_drive_client,
    get_meta_page_info,
    get_youtube_client,
    SCOPES_YOUTUBE_CHANNEL_READ,
    upload_facebook_reel,
    upload_instagram_reel,
    upload_youtube_shorts,
    create_instagram_cover_video,
)

TZ = ZoneInfo("Europe/Istanbul")
NEW_YORK_TZ = ZoneInfo("America/New_York")
SHARED_USED = "shared_mizah_used"
GONLE_USED = "gonle_used"
DAILY_LAUGH_USED = "daily_laugh_used"
GONLE_YT_USED = "gonle_youtube_used"
DAILY_LAUGH_YT_USED = "daily_laugh_youtube_used"
FILM_USED = "film_used"
# Verified 2026-10-17 Actions run 39007614428: both FB posts succeeded,
# while Instagram's binary upload explicitly failed HTTP 400 before publish.
FILM_PART3_IG_RECOVERY_CLAIM = "manual-2026-10-17-0849-film"
FILM_PART3_IG_RECOVERY_FILE_ID = "1IJloVdio5n6NY4UpxQTgIps7peZ8dv7c"
FILM_PART3_IG_RECOVERY_STEM = "Yoksul_1986_Part_3"
FILM_PART3_FB_RESULT_IDS = ("2415483262192096", "1494339649202618")
FILM_PART4_IG_RECOVERY_CLAIM = "manual-2026-10-18-0552-film"
FILM_PART4_IG_RECOVERY_FILE_ID = "11j94Mfe39BADmBXu0EUZ6RrckD7YudJT"
FILM_PART4_IG_RECOVERY_STEM = "Yoksul_1986_Part_4"
FILM_PART4_FB_RESULT_IDS = ("1737090337355286", "2095433004391736")
FILM_PART5_RECOVERY_CLAIM = "manual-2026-10-18-0609-film"
FILM_PART5_RECOVERY_FILE_ID = "1FlxhrUoqtmpNGU68C-8HNVJCcRy2KBdx"
FILM_PART5_RECOVERY_STEM = "Yoksul_1986_Part_5"
GONLE_IG_FAILED_TEST_FILE_ID = "1PmQueyQl7iD1RguTimcwBYLsXSn_M6jc"
TOONZONE_IG_FAILED_TEST_FILE_ID = "1WPrqw8SEmCyjaSLDvAe-VuP2S-AWYeuX"
TOONZONE_PART1_OLD_CLAIM = "manual-2026-10-18-2135-toonzone-toonzone-part1"
TOONZONE_PART1_FB_POST_ID = "1427675756211474"
FILM_ACTIVE_KEY = "film_active_key"
FILM_DONE_KEY = "film_done"
TOONZONE_USED = ORDERED_CHANNELS["cartoon_tr"].history_key
TOONZONE_COVER_FOLDER_ID = "1YlGz6rKfW_S2eMW82zOs09flCGtwYWMO"
LAST_SLOT = "last_route_slot"
CLAIM_SLOT = "claimed_route_slot"
CLAIMED_AT = "claimed_at"
PLATFORM_SLOT_KEYS = {
    "yt1": "done_yt1_slot",
    "yt2": "done_yt2_slot",
    "yt_gonle": "done_yt_gonle_slot",
    "yt_daily": "done_yt_daily_slot",
    "yt_film": "done_yt_film_slot",
    "fb": "done_fb_slot",
    "fb_film_1": "done_fb_film_1_slot",
    "fb_film_2": "done_fb_film_2_slot",
    "ig": "done_ig_slot",
    "threads": "done_threads_slot",
}
PLATFORM_RESULT_KEYS = {
    "yt1": "result_yt1",
    "yt2": "result_yt2",
    "yt_gonle": "result_yt_gonle",
    "yt_daily": "result_yt_daily",
    "yt_film": "result_yt_film",
    "fb": "result_fb",
    "fb_film_1": "result_fb_film_1",
    "fb_film_2": "result_fb_film_2",
    "ig": "result_ig",
    "threads": "result_threads",
}
PLATFORM_INTENT_KEYS = {
    "yt1": "intent_yt1_slot",
    "yt2": "intent_yt2_slot",
    "yt_gonle": "intent_yt_gonle_slot",
    "yt_daily": "intent_yt_daily_slot",
    "yt_film": "intent_yt_film_slot",
    "fb": "intent_fb_slot",
    "fb_film_1": "intent_fb_film_1_slot",
    "fb_film_2": "intent_fb_film_2_slot",
    "ig": "intent_ig_slot",
    "threads": "intent_threads_slot",
}
PLATFORM_FAILURE_KEYS = {
    "yt1": "failure_yt1_count",
    "yt2": "failure_yt2_count",
    "yt_gonle": "failure_yt_gonle_count",
    "yt_daily": "failure_yt_daily_count",
    "yt_film": "failure_yt_film_count",
    "fb": "failure_fb_count",
    "fb_film_1": "failure_fb_film_1_count",
    "fb_film_2": "failure_fb_film_2_count",
    "ig": "failure_ig_count",
    "threads": "failure_threads_count",
}
PLATFORM_FAILURE_SLOT_KEYS = {
    key: value.replace("failure_", "failure_slot_").replace("_count", "")
    for key, value in PLATFORM_FAILURE_KEYS.items()
}
FAILED_SLOT = "failed_route_slot"
NOTIFIED_SLOT = "notified_route_slot"
NOTIFIED_ERROR_SLOT = "notified_error_slot"
NOTIFIED_ERROR_HASH = "notified_error_hash"
MAX_PLATFORM_ATTEMPTS = 3
MAX_TRANSIENT_RETRIES = 3
DEFAULT_MAX_DUE_SLOTS = 2
MAX_DUE_SLOTS_PER_RUN = 4
DEFAULT_MIN_PLATFORM_INTERVAL_SECONDS = 60
_LAST_PLATFORM_PUBLISH_AT = {}
# Cut over at the START of a full New York calendar day; otherwise new
# historical hours would be replayed as catch-up uploads on deployment day.
DAILY_LAUGH_CUTOVER_DATE = date(2026, 10, 20)
DAILY_LAUGH_LEGACY_HOURS = (9, 12, 15, 18, 21)
DAILY_LAUGH_HOURS = (8, 10, 12, 14, 16, 18, 20, 22)


def daily_laugh_hours_for_date(day):
    """Use America/New_York calendar dates, never Istanbul/UTC day boundaries."""
    return DAILY_LAUGH_HOURS if day >= DAILY_LAUGH_CUTOVER_DATE else DAILY_LAUGH_LEGACY_HOURS

GONLE_HOURS = (9, 12, 15, 18, 21)
TARLADAKI_HOURS = (9, 12, 15, 18, 21)
PENGUEN_HOURS = (9, 12, 15, 18, 21)
FILM_HOURS = (10, 12, 14, 16, 18)
DRIVE_ROUTE_SPECS = {
    "shared": ("DRIVE_FOLDER_ID", "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M", "Ortak 2 Mizah"),
    "gonle": ("GONLE_DUSEN_DRIVE_FOLDER_ID", "1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt", "İslam olan"),
    "daily_laugh": ("DAILY_LAUGH_DRIVE_FOLDER_ID", "137--TeBht1yikZpMfV9VSEADbKuXZtLT", "İngilizce Mizahh"),
    "film": ("FILM_DRIVE_FOLDER_ID", "1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW", "Film"),
    "toonzone": ("TOONZONE_DRIVE_FOLDER_ID", CARTOON_FOLDER_ID, "cizgi film"),
}
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
YOUTUBE_COVER_ROUTES = {
    "tarladaki": ("tarladaki", "COVER_TARLADAKI_FOLDER_ID"),
    "penguen": ("penguen", "COVER_PENGUEN_FOLDER_ID"),
}


def apply_youtube_fixed_cover(drive, youtube, route, source_folder_id, video_id, temp_dir):
    """Apply a fixed cover after upload; failure must never fail the video."""
    if cover_config() is None or route not in YOUTUBE_COVER_ROUTES:
        return False
    channel_key, folder_env = YOUTUBE_COVER_ROUTES[route]
    cover_folder_id = os.environ.get(folder_env, "").strip()
    if not cover_folder_id:
        print(f"Kapak atlandı: {route} için {folder_env} eksik.", flush=True)
        return False
    try:
        files = drive.files().list(
            q=f"'{cover_folder_id}' in parents and trashed=false",
            fields="files(id,name,mimeType,parents,appProperties)",
            pageSize=100,
        ).execute().get("files", [])
        scope = CoverScope(channel_key, source_folder_id, cover_folder_id)
        cover = match_fixed_account_cover(files, scope)
        if not cover:
            print(f"Kapak atlandı: {route} sabit kapağı bulunamadı.", flush=True)
            return False
        data, dimensions = download_and_validate_cover(drive, cover)
        cover_path = safe_temp_path(Path(temp_dir), "cover", route, cover["id"], ".jpg")
        cover_path.write_bytes(data)
        set_youtube_thumbnail(youtube, video_id, str(cover_path), cover.get("mimeType", "image/jpeg"))
        print(f"YouTube kapağı uygulandı: {route} | {video_id} | {dimensions[0]}x{dimensions[1]}", flush=True)
        return True
    except Exception as exc:
        print(f"YouTube kapak uyarısı ({route}/{video_id}): {sanitize_error(exc)}", flush=True)
        return False


def is_first_daily_slot(route, slot):
    if route != "daily_laugh":
        return False
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-(\d{2})-daily_laugh", slot or "")
    if not match:
        return False
    try:
        return int(match.group(2)) == daily_laugh_hours_for_date(date.fromisoformat(match.group(1)))[0]
    except ValueError:
        return False


def notify(route, slot, stem, results, errors, *, drive=None, folder_id=None, resolved=False,
           grouped_items=None):
    if not os.environ.get("NTFY_TOPIC_URL", "").strip() and not os.environ.get("NTFY_TOPIC", "").strip():
        return False

    status = "HATA" if errors else ("DÜZELDİ" if resolved else "BAŞARILI")
    rows = [f"Hesap: {route}", f"Durum: {status}"]
    platform_labels = {
        "yt1": "YouTube", "yt2": "YouTube", "yt_gonle": "YouTube", "yt_daily": "YouTube",
        "yt_film": "YouTube", "fb": "Facebook", "fb_film_1": "Facebook 1",
        "fb_film_2": "Facebook 2", "ig": "Instagram", "threads": "Threads",
    }
    if grouped_items:
        for item in grouped_items:
            pieces = item["slot"].split("-")
            hour = pieces[3] if len(pieces) > 3 else "??"
            rows.append(f"🎬 {item['stem']} — {hour}:00")
            rows.extend(
                f"✅ {platform_labels.get(key, key)}: Yayınlandı ({item['results'][key]})"
                for key in item["results"]
            )
    else:
        rows.append(f"İçerik: {stem}")
    rows.extend(f"✅ {platform_labels.get(key, key)}: Yayınlandı ({value})" for key, value in results.items())
    rows.extend(f"❌ {platform_labels.get(key, key)}: {sanitize_error(value)}" for key, value in errors.items())
    route_accounts = {
        "tarladaki": "🌱 Tarladaki Fasulye", "penguen": "🐧 Beyinsiz Penguen",
        "gonle": "❤️ Gönle Düşen", "gonle_fb": "❤️ Gönle Düşen", "gonle_ig": "❤️ Gönle Düşen",
        "daily_laugh": "😂 Daily Laugh Lab", "film": "🎬 Film Mağarası + Filmmagrasi",
        "toonzone": "📺 ToonZone",
    }
    account = route_accounts.get(route)
    if drive is not None and account:
        try:
            from stats_reporter import publication_progress
            progress = publication_progress(drive, account, slot[:10])
            if progress:
                rows.extend([
                    f"🎬 Günlük video: {progress['completed']}/{progress['target']}",
                    f"📤 Platform yayını: {progress['posts']}/{progress['expected_posts']}",
                ])
        except Exception as exc:
            print(f"ntfy ilerleme bilgisi alınamadı: {type(exc).__name__}", flush=True)
    title = (f"✅ DÜZELDİ — {route}" if resolved else
             f"❌ YAYIN HATASI — {route}" if errors else f"✅ YAYIN BAŞARILI — {route}")
    try:
        run_url = ""
        if os.getenv("GITHUB_RUN_ID") and os.getenv("GITHUB_REPOSITORY"):
            run_url = f"\n🔗 Actions: {os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
        send_ntfy(title, "\n".join(rows) + run_url, priority=4 if errors else 3,
                  tags=["warning"] if errors else ["white_check_mark"])
        return True
    except Exception as exc:
        # Bildirim servisi yayın durumunu değiştirmemeli veya başarılı yayını
        # başarısız gösterip aynı slotun tekrar denenmesine yol açmamalı.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        safe = f"{type(exc).__name__}" + (f" HTTP {status}" if status is not None else "")
        print(f"ntfy bildirimi gönderilemedi: {safe}", flush=True)
        return False


def sanitize_error(value):
    text = str(value)
    text = re.sub(r"([?&]access_token=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"https?://[^\s\"'<>]+", "[masked-url]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEA[A-Za-z0-9_-]{20,}\b", "[masked-token]", text)
    for env_name in ("META_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN", "NTFY_TOPIC", "NTFY_TOPIC_URL", "PENGUEN_THREADS_VIDEO_URL_TEMPLATE"):
        secret = os.environ.get(env_name, "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def youtube_safe_description(description, append_store_link=True):
    """YouTube'un 5000 karakter ve yasaklı köşeli parantez kurallarına uyar."""
    cleaned = description.replace("<", "").replace(">", "")
    if not append_store_link:
        return cleaned[:5000].rstrip()
    body = cleaned.replace(ETSY_LINK, "").rstrip()
    suffix = f"\n\n{ETSY_LINK}"
    return body[: 5000 - len(suffix)].rstrip() + suffix


_PLATFORM_SECTION_NAMES = {
    "INSTAGRAM REELS": "instagram",
    "INSTAGRAM": "instagram",
    "FACEBOOK REELS": "facebook",
    "FACEBOOK": "facebook",
    "YOUTUBE SHORTS": "youtube",
    "YOUTUBE": "youtube",
    "TIKTOK": "tiktok",
}
_PLATFORM_SECTION_HEADER = re.compile(r"^\s*===\s*(.*?)\s*===\s*$", re.IGNORECASE)


def _platform_sections(raw_text):
    sections = {}
    current = None
    lines = []
    for line in raw_text.splitlines():
        match = _PLATFORM_SECTION_HEADER.match(line)
        if match:
            if current:
                sections[current] = "\n".join(lines).strip()
            current = _PLATFORM_SECTION_NAMES.get(match.group(1).strip().upper())
            lines = []
        elif current:
            lines.append(line)
    if current:
        sections[current] = "\n".join(lines).strip()
    return sections


def _clean_platform_copy(text):
    """Remove TXT export artifacts and redundant calls to action, preserving copy."""
    output = []
    seen_lines = set()
    seen_ctas = set()
    cta_patterns = {
        "comment": re.compile(r"yorum|comment", re.IGNORECASE),
        "save": re.compile(r"kaydet|save", re.IGNORECASE),
        "follow": re.compile(r"takip|follow|abone ol|subscribe", re.IGNORECASE),
        "share": re.compile(r"paylaş|share|gönder", re.IGNORECASE),
        "like": re.compile(r"beğen|like", re.IGNORECASE),
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"\d+\s*w", line, re.IGNORECASE):
            continue
        if re.fullmatch(r"🎥\s+[A-Z0-9_.-]+", line):
            continue
        normalized = re.sub(r"\s+", " ", line).casefold()
        if normalized in seen_lines:
            continue
        matched_ctas = [name for name, pattern in cta_patterns.items() if pattern.search(line)]
        if matched_ctas and any(name in seen_ctas for name in matched_ctas):
            continue
        seen_lines.add(normalized)
        seen_ctas.update(matched_ctas)
        output.append(line)
    return "\n".join(output).strip()


def _youtube_section_copy(text, fallback_title):
    title = ""
    description_lines = []
    in_description = False
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.casefold()
        if lower.startswith(("başlık:", "başlik:", "baslik:")):
            value = stripped.split(":", 1)[1].strip()
            if value:
                title = value
            continue
        if lower.startswith(("açıklama:", "açiklama:", "aciklama:")):
            value = stripped.split(":", 1)[1].strip()
            if value:
                description_lines.append(value)
            in_description = True
            continue
        if in_description:
            description_lines.append(line)
        elif not title and stripped and not re.fullmatch(r"🎥\s+[A-Z0-9_.-]+", stripped):
            title = stripped
    description = _clean_platform_copy("\n".join(description_lines))
    return (title or fallback_title)[:95], description


def content_from_txt(raw_text, stem, route):
    """Use this video's own TXT, without inserting account-wide template text."""
    source = raw_text.strip()
    first_line = next((line.strip() for line in source.splitlines() if line.strip()), "")
    generic_titles = {
        "gonle": {"gönle düşen", "gonle dusen"},
        "daily_laugh": {"daily laugh lab"},
        "tarladaki": {"tarladaki fasulye"},
        "penguen": {"beyinsiz penguen"},
    }
    base_route = route.removesuffix("_ig").removesuffix("_fb").removesuffix("_youtube")
    title = stem if first_line.casefold() in generic_titles.get(base_route, set()) else first_line
    title = (title or stem)[:95]
    # The store URL must occur once, as the final line; do not alter the TXT body.
    body = source.replace(ETSY_LINK, "").rstrip()
    description = f"{body}\n\n{ETSY_LINK}" if body else ETSY_LINK
    return title, description


def platform_content_from_txt(raw_text, stem, route):
    """Return title and platform-specific copy when TXT sections are available."""
    sections = _platform_sections(raw_text)
    if not sections:
        title, description = content_from_txt(raw_text, stem, route)
        return title, description, description, description, False

    first_header = _PLATFORM_SECTION_HEADER.search(raw_text)
    preamble = raw_text[:first_header.start()].strip() if first_header else ""
    fallback_copy = _clean_platform_copy(preamble)
    if not fallback_copy and sections.get("youtube"):
        _, fallback_copy = _youtube_section_copy(sections["youtube"], stem)
    if not fallback_copy:
        fallback_copy = _clean_platform_copy(next(iter(sections.values()), ""))
    fallback_title = next((line.strip() for line in fallback_copy.splitlines() if line.strip()), stem)
    youtube_title, youtube_description = _youtube_section_copy(
        sections.get("youtube", ""), fallback_title
    )
    facebook_caption = _clean_platform_copy(sections.get("facebook", "")) or fallback_copy
    instagram_caption = _clean_platform_copy(sections.get("instagram", "")) or fallback_copy
    if not youtube_description:
        youtube_description = fallback_copy
    return youtube_title, youtube_description, facebook_caption, instagram_caption, True


def route_for_time(now=None):
    now = now or datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    forced = os.environ.get("FORCE_ROUTE", "").strip().lower()
    if forced in {
        "gonle", "gonle_fb", "gonle_ig", "daily_laugh", "tarladaki", "penguen",
        "tarladaki_ig", "penguen_ig",
        "gonle_youtube", "daily_laugh_youtube", "film", "toonzone",
    }:
        suffix = os.environ.get("FORCE_SLOT_SUFFIX", "").strip()
        if forced == "toonzone" and not suffix:
            # A one-off forced ToonZone launch is explicitly bound to Part 1;
            # later parts remain on their normal dated slots.
            suffix = "toonzone-part1"
        if forced == "toonzone" and not re.fullmatch(r"toonzone-part[1-4]", suffix):
            raise RuntimeError("ToonZone manuel parçası 1–4 arasında açıkça seçilmelidir")
        suffix = f"-{suffix}" if suffix else ""
        return forced, f"manual-{now:%Y-%m-%d-%H%M}-{forced}{suffix}"
    routes = routes_for_time(now)
    return routes[0] if routes else (None, None)


def select_next_toonzone_part(files, slot, allow_part1_ig_recovery=False):
    """Select only the earliest unfinished episode part for this scheduled part slot."""
    match = re.search(r"toonzone-part([1-4])$", slot)
    if not match:
        raise RuntimeError("ToonZone slot içinde part numarası doğrulanmadı")
    expected_part = int(match.group(1))
    report = analyze_files(files, ORDERED_CHANNELS["cartoon_tr"])
    if report["duplicate_names"]:
        raise RuntimeError("ToonZone dosya adında MP4/TXT çakışması var; sıralı yayın durduruldu")
    for order, stem, video, _text in report["ordered"]:
        props = video.get("appProperties") or {}
        if props.get(TOONZONE_USED) == "1":
            continue
        claim = props.get(CLAIM_SLOT)
        recovering_known_part1 = (
            allow_part1_ig_recovery
            and expected_part == 1
            and video.get("id") == TOONZONE_IG_FAILED_TEST_FILE_ID
            and claim == TOONZONE_PART1_OLD_CLAIM
            and props.get(FAILED_SLOT) == TOONZONE_PART1_OLD_CLAIM
            and props.get("done_fb_slot") == TOONZONE_PART1_OLD_CLAIM
            and props.get(PLATFORM_RESULT_KEYS["fb"]) == TOONZONE_PART1_FB_POST_ID
            and not props.get("done_ig_slot")
            and not props.get(PLATFORM_RESULT_KEYS["ig"])
            and not props.get(PLATFORM_INTENT_KEYS["ig"])
            and props.get("toonzone_ig_recovery_used") != "1"
        )
        if claim and not recovering_known_part1:
            raise RuntimeError("ToonZone dosyasında önceki claim var; güvenli uzlaştırma olmadan yayın durduruldu")
        old_state = [props.get(k) for k in (
            "done_fb_slot", "done_ig_slot", "intent_fb_slot", "intent_ig_slot"
        )]
        if any(value and value != slot for value in old_state) and not (
            recovering_known_part1
            and old_state[0] == TOONZONE_PART1_OLD_CLAIM
            and old_state[1:] == [None, None, None]
        ):
            raise RuntimeError("ToonZone önceki platform sonucu belirsiz; sıradaki part durduruldu")
        if order[2] != expected_part:
            return None
        return stem, video
    return None


def routes_for_time(now=None):
    """Return only currently due slots; never turn a delayed run into a bulk backfill."""
    now = now or datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    routes = []
    if now.hour in TARLADAKI_HOURS:
        if now.minute < 30:
            routes.append(("tarladaki", f"{now:%Y-%m-%d}-{now.hour:02d}-tarladaki"))
        else:
            routes.append(("penguen", f"{now:%Y-%m-%d}-{now.hour:02d}-penguen"))
    # Gönle's :15 slots avoid contention with the two shared-humor channels.
    if now.hour in GONLE_HOURS and 15 <= now.minute < 45:
        routes.append(("gonle", f"{now:%Y-%m-%d}-{now.hour:02d}-gonle"))
    ny_now = now.astimezone(NEW_YORK_TZ)
    if ny_now.hour in daily_laugh_hours_for_date(ny_now.date()) and ny_now.minute < 30:
        routes.append(("daily_laugh", f"{ny_now:%Y-%m-%d}-{ny_now.hour:02d}-daily_laugh"))
    if os.getenv("ENABLE_FILM_ROUTES", "false").lower() == "true" and now.hour in FILM_HOURS and now.minute < 30:
        routes.append(("film", f"{now:%Y-%m-%d}-{now.hour:02d}-film"))
    if not route_paused("toonzone") and now.hour == 12 and now.minute < 40:
        part = now.minute // 10 + 1
        routes.append(("toonzone", f"{now:%Y-%m-%d}-12-toonzone-part{part}"))
    return routes


def due_slots(now=None, lookback_minutes=1440):
    """Son 24 saatte zamanı gelmiş slotları, en yenisi önce olacak şekilde üretir."""
    now = now or datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    earliest = now - timedelta(minutes=lookback_minutes)
    days = {(now - timedelta(days=1)).date(), now.date()}
    slots = []
    for day in days:
        schedule = []
        for ny_hour in daily_laugh_hours_for_date(day):
            ny_planned = datetime(day.year, day.month, day.day, ny_hour, 0, tzinfo=NEW_YORK_TZ)
            planned = ny_planned.astimezone(TZ)
            if earliest <= planned <= now:
                slot = f"{ny_planned:%Y-%m-%d}-{ny_hour:02d}-daily_laugh"
                slots.append((planned, "daily_laugh", slot))
        schedule.extend((hour, 15, "gonle") for hour in GONLE_HOURS)
        schedule.extend((hour, 0, "tarladaki") for hour in TARLADAKI_HOURS)
        schedule.extend((hour, 30, "penguen") for hour in PENGUEN_HOURS)
        if os.getenv("ENABLE_FILM_ROUTES", "false").lower() == "true":
            schedule.extend((hour, 0, "film") for hour in FILM_HOURS)
        for hour, minute, route in schedule:
            planned = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)
            if earliest <= planned <= now:
                slot = f"{planned:%Y-%m-%d}-{planned.hour:02d}-{route}"
                slots.append((planned, route, slot))
    # The live dispatcher uses due_slots(), not routes_for_time(). Include
    # ToonZone Part 1-4 here, behind the existing rights/activation gate.
    slots.extend(due_toonzone_slots(now, earliest, enabled=not route_paused("toonzone")))
    # Gecikmiş slotları zaman sırasıyla tamamla; yeni içeriği eski slotlardan
    # önce paylaşmak, yakalama sırasında kanal akışını tersine çeviriyordu.
    return sorted(slots)


def slot_is_done(files, planned, route, slot):
    """Tam slotu veya aynı pencereye düşen manuel telafiyi tamamlanmış sayar."""
    next_slot = planned + timedelta(hours=2)
    if route == "toonzone":
        # Each 10-minute slot is a different part. A manual recovery of
        # Part 1 must not silently count Part 2, 3, or 4 as completed.
        match = re.search(r"-toonzone-part([1-4])$", slot)
        if not match:
            raise RuntimeError("ToonZone slot part suffix missing")
        suffix = rf"toonzone-toonzone-part{match.group(1)}"
    else:
        suffix = rf"{re.escape(route)}(?:-.*)?"
    manual_pattern = re.compile(
        rf"manual-(\d{{4}}-\d{{2}}-\d{{2}})-(\d{{2}})(\d{{2}})-{suffix}$"
    )
    for item in files:
        properties = item.get("appProperties") or {}
        value = properties.get(LAST_SLOT, "")
        if value == slot or properties.get(FAILED_SLOT) == slot:
            return True
        match = manual_pattern.fullmatch(value)
        if match:
            manual = datetime.strptime(
                f"{match.group(1)} {match.group(2)}:{match.group(3)}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)
            if planned <= manual < next_slot:
                return True
    return False


def _normalized_name(value):
    folded = unicodedata.normalize("NFKD", " ".join(str(value or "").split()).casefold())
    return "".join(char for char in folded if not unicodedata.combining(char))


def validate_drive_routing(drive):
    """Fail closed unless every production route points to its approved folder."""
    configured = {}
    for route, (env_name, expected_id, expected_name) in DRIVE_ROUTE_SPECS.items():
        if route == "film" and os.getenv("ENABLE_FILM_ROUTES", "false").lower() != "true":
            continue
        if route == "toonzone" and route_paused("toonzone"):
            continue
        folder_id = os.environ.get(env_name, "").strip()
        if folder_id != expected_id:
            raise RuntimeError(f"{route}: {env_name} onaylı Drive klasörüyle eşleşmiyor; yayın durduruldu")
        metadata = drive.files().get(
            fileId=folder_id, fields="id,name,mimeType,trashed"
        ).execute()
        if metadata.get("id") != folder_id or metadata.get("trashed"):
            raise RuntimeError(f"{route}: onaylı Drive klasörü erişilemiyor; yayın durduruldu")
        if metadata.get("mimeType") != DRIVE_FOLDER_MIME:
            raise RuntimeError(f"{route}: Drive hedefi klasör değil; yayın durduruldu")
        if _normalized_name(metadata.get("name")) != _normalized_name(expected_name):
            raise RuntimeError(f"{route}: Drive klasör adı beklenen hesap rotasıyla eşleşmiyor; yayın durduruldu")
        configured[route] = folder_id
    if len(set(configured.values())) != len(configured):
        raise RuntimeError("Production Drive klasörleri beklenmedik biçimde aynı; yayın durduruldu")
    return configured


def validate_toonzone_starting_episode(drive):
    """Read-only preflight: verify the first episode has four exact covers."""
    folder_id = CARTOON_FOLDER_ID
    metadata = drive.files().get(fileId=folder_id, fields="id,name,mimeType,trashed").execute()
    if (metadata.get("id") != folder_id or metadata.get("mimeType") != DRIVE_FOLDER_MIME
            or metadata.get("trashed") or _normalized_name(metadata.get("name")) != "cizgi film"):
        raise RuntimeError("ToonZone Drive klasörü doğrulanmadı")
    cover_meta = drive.files().get(
        fileId=TOONZONE_COVER_FOLDER_ID, fields="id,name,mimeType,trashed,parents"
    ).execute()
    if (cover_meta.get("id") != TOONZONE_COVER_FOLDER_ID
            or cover_meta.get("mimeType") != DRIVE_FOLDER_MIME or cover_meta.get("trashed")
            or _normalized_name(cover_meta.get("name")) != "kapaklar"
            or folder_id not in cover_meta.get("parents", [])):
        raise RuntimeError("ToonZone kapak klasörü kaynak klasörün altında doğrulanmadı")
    files, _pairs = list_pairs(drive, folder_id)
    cover_files, _cover_pairs = list_pairs(drive, TOONZONE_COVER_FOLDER_ID)
    report = analyze_files(files, ORDERED_CHANNELS["cartoon_tr"])
    if report["duplicate_names"] or report["invalid_names"]:
        raise RuntimeError("ToonZone klasöründe yinelenen veya geçersiz MP4/TXT adları var")
    ordered = report["ordered"]
    first = next((row for row in ordered if row[0][2] == 1), None)
    if not first:
        raise RuntimeError("ToonZone için sıralı Part 1 bulunamadı")
    episode_key = first[0][:2]
    episode_parts = [row for row in ordered if row[0][:2] == episode_key]
    if {row[0][2] for row in episode_parts} != {1, 2, 3, 4}:
        raise RuntimeError("ToonZone ilk bölümünde Part 1–4 tam değil")
    for _order, _stem, video, _text in episode_parts:
        match_toonzone_cover(
            video, cover_files, CoverScope("cartoon_tr", folder_id, TOONZONE_COVER_FOLDER_ID)
        )
    return {"folder": metadata.get("name"), "episode": episode_key,
            "parts": len(episode_parts), "covers": len(episode_parts)}


def verify_file_in_folder(drive, video_obj, folder_id):
    metadata = drive.files().get(
        fileId=video_obj["id"], fields="id,name,parents,trashed"
    ).execute()
    if metadata.get("id") != video_obj["id"] or metadata.get("trashed"):
        raise RuntimeError("Seçilen Drive videosu erişilemiyor; yayın durduruldu")
    if folder_id not in (metadata.get("parents") or []):
        raise RuntimeError("Seçilen video hedef hesap için izin verilen Drive klasöründe değil; yayın durduruldu")


def quarantine_legacy_shared_claims(drive):
    """Stop old Tarladaki/Penguen claims found in the English-humor folder."""
    legacy_id = os.environ["DAILY_LAUGH_DRIVE_FOLDER_ID"]
    # This is a cleanup scan, not a selection path.  It must tolerate old
    # duplicate names in the forbidden folder; duplicates remain fail-closed
    # in list_pairs for every publishable source folder.
    files, token = [], None
    while True:
        page = drive.files().list(
            q=f"'{legacy_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,appProperties)", pageSize=1000,
            pageToken=token,
        ).execute()
        files.extend(page.get("files", []))
        token = page.get("nextPageToken")
        if not token:
            break
    quarantined = 0
    for item in files:
        properties = item.get("appProperties") or {}
        slot = properties.get(CLAIM_SLOT, "")
        if not re.search(r"-(?:tarladaki|penguen)(?:-|$)", slot):
            continue
        drive.files().update(
            fileId=item["id"],
            body={"appProperties": {FAILED_SLOT: slot, CLAIM_SLOT: None, CLAIMED_AT: None}},
        ).execute()
        quarantined += 1
    if quarantined:
        print(f"Eski yanlış-klasör slotları karantinaya alındı: {quarantined}", flush=True)
    return quarantined


def shared_folder_for_slot(drive, slot, folder_files=None):
    """Shared humor routes may only use their explicitly approved folder."""
    return os.environ["DRIVE_FOLDER_ID"]


def base_route_name(route):
    return route.removesuffix("_ig").removesuffix("_fb").removesuffix("_youtube")


def folder_for_route(drive, route, slot):
    base_route = base_route_name(route)
    force_platform = os.environ.get("FORCE_PLATFORM", "").strip().lower()
    if base_route == "gonle":
        return os.environ["GONLE_DUSEN_DRIVE_FOLDER_ID"]
    if base_route == "daily_laugh":
        return os.environ["DAILY_LAUGH_DRIVE_FOLDER_ID"]
    if base_route == "film":
        return os.environ["FILM_DRIVE_FOLDER_ID"]
    if base_route == "toonzone":
        return os.environ.get("TOONZONE_DRIVE_FOLDER_ID", CARTOON_FOLDER_ID)
    if base_route in ("tarladaki", "penguen"):
        return shared_folder_for_slot(drive, slot)
    raise RuntimeError(f"Bilinmeyen yayın rotası: {route}")


FILM_PART_RE = re.compile(r"^(?P<film>.+?)[ _.-]+part[ _.-]?(?P<part>\d+)$", re.IGNORECASE)


def film_part_key(name):
    """Return (film key, 1-based part) for names such as Movie_Part12.mp4."""
    stem = Path(name).stem.strip()
    # Drive commonly creates a suffixed copy as ``name (1).mp4``.  Treat it
    # as the same logical part so selection can apply the deterministic
    # preference: exact stem first, suffixed copy only as fallback.
    stem = re.sub(r"\s+\(\d+\)$", "", stem)
    match = FILM_PART_RE.match(stem)
    if not match:
        return None
    return _normalized_name(match.group("film")), int(match.group("part"))


def preferred_film_entry(entries):
    """Pick the unsuffixed Drive file, using a numbered copy only as fallback."""
    return sorted(
        entries,
        key=lambda pair: (
            bool(re.search(r"\s+\(\d+\)$", Path(pair[0]["name"]).stem)),
            Path(pair[0]["name"]).name.casefold(),
            str(pair[0].get("id", "")),
        ),
    )[0]


def select_next_film_part(drive, folder_id, slot, persist_active=True, allow_claimed_next=False):
    """Select one sequential part while keeping one film active until complete.

    State is stored on the Drive folder, so GitHub runner replacement cannot
    switch films mid-sequence. The route remains disabled unless explicitly
    enabled via ENABLE_FILM_ROUTES.
    """
    files, page_token = [], None
    while True:
        page = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,parents,md5Checksum,appProperties)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        files.extend(page.get("files", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    groups = {}
    txt_by_stem = {Path(item["name"]).stem.casefold(): item for item in files
                   if item.get("name", "").lower().endswith(".txt")}
    duplicate_parts = set()
    for item in files:
        if not item.get("name", "").lower().endswith(".mp4"):
            continue
        parsed = film_part_key(item["name"])
        if parsed:
            raw_stem = Path(item["name"]).stem
            stem = raw_stem.casefold()
            logical_stem = re.sub(r"\s+\(\d+\)$", "", raw_stem).casefold()
            txt = txt_by_stem.get(stem)
            if txt is None:
                txt = txt_by_stem.get(logical_stem)
            if txt is None:
                continue
            bucket = groups.setdefault(parsed[0], {}).setdefault(parsed[1], [])
            bucket.append((item, txt))
            if len(bucket) > 1:
                duplicate_parts.add((parsed[0], parsed[1]))
    if not groups:
        return None
    folder = drive.files().get(fileId=folder_id, fields="id,appProperties").execute()
    props = folder.get("appProperties") or {}
    active = props.get(FILM_ACTIVE_KEY)
    used = {item["id"] for item in files if any(
        (item.get("appProperties") or {}).get(key) == "1"
        for key in (FILM_USED, FILM_DONE_KEY)
    )}
    def film_order(key):
        numbers = tuple(int(value) for value in re.findall(r"\d+", key))
        return (numbers, key)

    def usable_parts(key, parts):
        return [number for number, entries in parts.items()
                if entries and preferred_film_entry(entries)[0]["id"] not in used]

    if active not in groups or not usable_parts(active, groups[active]):
        candidates = [key for key, parts in groups.items() if usable_parts(key, parts)]
        if not candidates:
            # Full Drive cycle completed: start again from the first film.
            used = set()
            candidates = list(groups)
        active = sorted(candidates, key=film_order, reverse=True)[0]
        if persist_active:
            drive.files().update(fileId=folder_id, body={"appProperties": {FILM_ACTIVE_KEY: active}}).execute()
    parts = groups[active]
    first_part = min(parts)
    if first_part != 1 and not used:
        raise RuntimeError(f"Film {active}: Part 1 bulunamadı; sıralı yayın durduruldu")
    unfinished = sorted(usable_parts(active, parts))
    if unfinished:
        next_video = preferred_film_entry(parts[unfinished[0]])[0]
        next_props = next_video.get("appProperties") or {}
        if next_props.get(CLAIM_SLOT):
            claim_summary = (
                f"file_id={next_video.get('id')}; name={next_video.get('name')}; "
                f"claim_slot={next_props.get(CLAIM_SLOT)}; "
                f"claimed_at={next_props.get(CLAIMED_AT, 'unknown')}"
            )
            if not allow_claimed_next:
                raise RuntimeError(
                    "Sıradaki Film partında açık claim var; sıra atlanmaması için yayın durduruldu "
                    f"({claim_summary})"
                )
            print(
                f"Upload-only tanısı aynı sıradaki claimed dosyayı kullanıyor; "
                f"hiçbir yayın/queue durumu değiştirilmeyecek ({claim_summary}).",
                flush=True,
            )
    if allow_claimed_next and unfinished:
        number = unfinished[0]
    else:
        available = [number for number in unfinished
                     if not (preferred_film_entry(parts[number])[0].get("appProperties") or {}).get(CLAIM_SLOT)]
        if not available:
            return None
        number = min(available)
    # Deterministic Drive-copy policy: exact logical stem wins; ``(1)`` (or
    # another numbered suffix) is only used when the exact file is absent.
    video, txt = preferred_film_entry(parts[number])
    return active, number, video, txt


def list_film_mp4s_for_test(drive, folder_id):
    """Read-only, paginated Film MP4 inventory in natural part order."""
    items = []
    token = None
    while True:
        response = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false and mimeType='video/mp4'",
            fields="nextPageToken,files(id,name,parents,mimeType,size,md5Checksum,appProperties)",
            pageSize=1000,
            pageToken=token,
        ).execute()
        items.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            break
    def natural_key(item):
        name = item.get("name", "").casefold()
        return ([int(v) for v in re.findall(r"\d+", name)], name)
    return sorted(items, key=natural_key)


def parse_film_upload_test_ids(raw_value, expected=15):
    """Parse a fixed, explicit test list; never fall back to the queue selector."""
    file_ids = [value for value in re.split(r"[\s,;]+", raw_value.strip()) if value]
    if len(file_ids) != expected or len(set(file_ids)) != expected:
        raise RuntimeError(f"FILM_IG_TEST_FILE_IDS tam olarak {expected} benzersiz Drive ID'si içermeli.")
    return file_ids


def _film_upload_only_batch(drive, folder_id, file_ids, *, start_index=0, count=2):
    """Upload explicit Film files to fresh Instagram containers, never publish or mutate Drive."""
    if len(file_ids) != 15 or len(set(file_ids)) != 15:
        raise RuntimeError("Film upload-only batch 15 benzersiz Drive ID'si gerektirir.")
    if start_index not in (0, 2) or count != (2 if start_index == 0 else 13):
        raise RuntimeError("Film test aşaması yalnızca ilk 2 veya kalan 13 dosyayı kabul eder.")
    inventory = list_film_mp4s_for_test(drive, folder_id)
    by_id = {item.get("id"): item for item in inventory}
    missing = [file_id for file_id in file_ids if file_id not in by_id]
    if missing:
        raise RuntimeError(f"Film testinde klasörde bulunmayan Drive ID var; hiçbiri yüklenmedi (adet={len(missing)}).")
    for file_id in file_ids:
        item = by_id[file_id]
        if (item.get("mimeType") != "video/mp4" or folder_id not in item.get("parents", [])
                or not item.get("name", "").lower().endswith(".mp4")):
            raise RuntimeError("Film test listesinde Film klasörüne ait olmayan MP4 var; hiçbiri yüklenmedi.")

    page = meta_page("Film Mağarası")
    seen_files, seen_containers = set(), set()
    results, failures = [], []
    selected = file_ids[start_index:start_index + count]
    # Batch tests must exercise the same compact normalization used by the
    # normal Film Instagram publishing route (upload_ig sets film_compact=True).
    compact = True
    with tempfile.TemporaryDirectory(prefix="film-ig-upload-only-") as temp_dir:
        sources, hashes = {}, {}
        # Download and fingerprint the complete fixed list before creating any container.
        for index, file_id in enumerate(file_ids):
            item = by_id[file_id]
            verify_file_in_folder(drive, item, folder_id)
            raw = Path(temp_dir) / f"source-{index:02d}.mp4"
            request = drive.files().get_media(fileId=file_id)
            with raw.open("wb") as target:
                downloader = MediaIoBaseDownload(target, request, chunksize=4 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            digest = hashlib.sha256()
            with raw.open("rb") as media:
                for block in iter(lambda: media.read(1024 * 1024), b""):
                    digest.update(block)
            digest = digest.hexdigest()
            if digest in hashes:
                raise RuntimeError("Film test listesinde aynı içerikli dosyalar var; hiçbir container oluşturulmadı.")
            hashes[digest] = file_id
            sources[file_id] = raw
        for index, file_id in enumerate(selected):
            if file_id in seen_files:
                raise RuntimeError("Film upload-only batch içinde dosya tekrarı algılandı; işlem durduruldu.")
            seen_files.add(file_id)
            item = by_id[file_id]
            stem = Path(item["name"]).stem
            raw = sources[file_id]
            try:
                log_media_diagnostics("Film upload-only kaynak", raw)
                check_full_decode(raw)
                prepared, method = prepare_instagram_upload(
                    raw, Path(temp_dir) / f"upload-{index:02d}.mp4", prefer_remux=True,
                    film_compact=compact, return_method=True,
                )
                log_media_diagnostics("Film upload-only son dosya", prepared)
                result = upload_instagram_reel(
                    page, str(prepared), stem, append_store_link=False, publish=False,
                    forbidden_container_ids=seen_containers,
                )
                container_id = result.get("container_id")
                if (not container_id or container_id in seen_containers
                        or result.get("status") != "FINISHED" or result.get("published") is not False):
                    raise RuntimeError("Upload-only container tekrarı, FINISHED dışı durum veya publish koruması ihlali.")
                seen_containers.add(container_id)
                row = {"file_id": file_id, "name": item["name"], "bytes": prepared.stat().st_size,
                       "method": method, "container_id": container_id, "status": "FINISHED"}
                results.append(row)
                print(
                    f"FILM_IG_TEST_RESULT file_id={file_id}; name={json.dumps(item['name'], ensure_ascii=False)}; bytes={row['bytes']}; "
                    f"method={method}; container={container_id}; status=FINISHED; published=false.", flush=True,
                )
            except Exception as exc:
                message = sanitize_error(exc)
                failures.append((file_id, message))
                print(f"FILM_IG_TEST_RESULT file_id={file_id}; name={json.dumps(item['name'], ensure_ascii=False)}; status=FAILED; error={message}", flush=True)
                if isinstance(exc, MetaAPIError) and (
                    exc.http_status == 429 or exc.code in {4, 17, 32, 190, 200, 613}
                    or exc.is_transient is True or exc.retriable is True
                ):
                    print("Film upload-only testi gerçek Meta kota/erişim/geçici API yanıtıyla durduruldu.", flush=True)
                    break
    print(
        f"FILM_IG_TEST_SUMMARY start={start_index}; attempted={len(results) + len(failures)}; "
        f"finished={len(results)}; failed={len(failures)}; published=0; queue_mutations=0.", flush=True,
    )
    if failures:
        raise RuntimeError(f"Film upload-only batch tamamlandı; FINISHED={len(results)}, başarısız={len(failures)}.")
    return results


def verify_film_part3_ig_only_recovery(video_obj):
    """Fail closed unless Drive confirms the exact FB-success/IG-failed history.

    This does NOT clear the old claim or republish Facebook. The one-shot
    permission is consumed before external Instagram publishing begins.
    """
    props = video_obj.get("appProperties") or {}
    required = {
        CLAIM_SLOT: FILM_PART3_IG_RECOVERY_CLAIM,
        PLATFORM_SLOT_KEYS["fb_film_1"]: FILM_PART3_IG_RECOVERY_CLAIM,
        PLATFORM_SLOT_KEYS["fb_film_2"]: FILM_PART3_IG_RECOVERY_CLAIM,
        PLATFORM_RESULT_KEYS["fb_film_1"]: FILM_PART3_FB_RESULT_IDS[0],
        PLATFORM_RESULT_KEYS["fb_film_2"]: FILM_PART3_FB_RESULT_IDS[1],
        FAILED_SLOT: FILM_PART3_IG_RECOVERY_CLAIM,
        PLATFORM_FAILURE_KEYS["ig"]: str(MAX_PLATFORM_ATTEMPTS),
    }
    if (video_obj.get("id") != FILM_PART3_IG_RECOVERY_FILE_ID
            or Path(video_obj.get("name", "")).stem != FILM_PART3_IG_RECOVERY_STEM
            or any(props.get(key) != value for key, value in required.items())
            # Verified read-only Drive audit run #39217114801 showed the legacy
            # HTTP 400 recorded failed_route_slot and failure_ig_count=3 but
            # omitted failure_slot_ig. Either absent or the exact old claim
            # is safe; a conflicting slot still blocks the recovery.
            or props.get(PLATFORM_FAILURE_SLOT_KEYS["ig"]) not in (
                None, "", FILM_PART3_IG_RECOVERY_CLAIM,
            )
            or props.get(FILM_USED) == "1"
            or props.get(FILM_DONE_KEY) == "1"
            or any(props.get(key) for key in (
                PLATFORM_SLOT_KEYS["ig"], PLATFORM_RESULT_KEYS["ig"],
                PLATFORM_INTENT_KEYS["ig"], "published_ig",
                "platform_result_ig", "platform_slot_ig",
                "film_part3_ig_recovery_used",
            ))):
        raise RuntimeError(
            "Film Part 3 IG tek seferlik kurtarma ön koşulları Drive kaydıyla eşleşmedi; yayın yapılmadı"
        )
    return True


def verify_film_part4_ig_only_recovery(video_obj):
    """Fail closed on the audited Part 4 partial success; never resend Facebook."""
    props = video_obj.get("appProperties") or {}
    required = {
        CLAIM_SLOT: FILM_PART4_IG_RECOVERY_CLAIM,
        FAILED_SLOT: FILM_PART4_IG_RECOVERY_CLAIM,
        PLATFORM_SLOT_KEYS["fb_film_1"]: FILM_PART4_IG_RECOVERY_CLAIM,
        PLATFORM_SLOT_KEYS["fb_film_2"]: FILM_PART4_IG_RECOVERY_CLAIM,
        PLATFORM_RESULT_KEYS["fb_film_1"]: FILM_PART4_FB_RESULT_IDS[0],
        PLATFORM_RESULT_KEYS["fb_film_2"]: FILM_PART4_FB_RESULT_IDS[1],
        PLATFORM_FAILURE_KEYS["ig"]: str(MAX_PLATFORM_ATTEMPTS),
    }
    if (video_obj.get("id") != FILM_PART4_IG_RECOVERY_FILE_ID
            or Path(video_obj.get("name", "")).stem != FILM_PART4_IG_RECOVERY_STEM
            or any(props.get(key) != value for key, value in required.items())
            or props.get(PLATFORM_FAILURE_SLOT_KEYS["ig"]) not in (
                None, "", FILM_PART4_IG_RECOVERY_CLAIM,
            )
            or props.get(FILM_USED) == "1"
            or props.get(FILM_DONE_KEY) == "1"
            or any(props.get(key) for key in (
                PLATFORM_SLOT_KEYS["ig"], PLATFORM_RESULT_KEYS["ig"],
                PLATFORM_INTENT_KEYS["ig"], "published_ig",
                "platform_result_ig", "platform_slot_ig",
                "film_part4_ig_recovery_used",
            ))):
        raise RuntimeError(
            "Film Part 4 IG tek seferlik kurtarma ön koşulları Drive kaydıyla eşleşmedi; yayın yapılmadı"
        )
    return True


def verify_film_part5_recovery(video_obj):
    """Fail closed on the audited unpublished Part 5; recovery targets all Meta pages."""
    props = video_obj.get("appProperties") or {}
    required = {
        CLAIM_SLOT: FILM_PART5_RECOVERY_CLAIM,
        FAILED_SLOT: FILM_PART5_RECOVERY_CLAIM,
        PLATFORM_FAILURE_KEYS["ig"]: str(MAX_PLATFORM_ATTEMPTS),
    }
    if (video_obj.get("id") != FILM_PART5_RECOVERY_FILE_ID
            or Path(video_obj.get("name", "")).stem != FILM_PART5_RECOVERY_STEM
            or any(props.get(key) != value for key, value in required.items())
            or props.get(PLATFORM_FAILURE_SLOT_KEYS["ig"]) not in (
                None, "", FILM_PART5_RECOVERY_CLAIM,
            )
            or any(props.get(PLATFORM_FAILURE_KEYS[key]) not in (None, "", "0")
                   for key in ("fb_film_1", "fb_film_2"))
            or props.get(FILM_USED) == "1"
            or props.get(FILM_DONE_KEY) == "1"
            or any(props.get(key) for platform in ("fb_film_1", "fb_film_2", "ig", "yt_film")
                   for key in (PLATFORM_SLOT_KEYS[platform], PLATFORM_RESULT_KEYS[platform],
                               PLATFORM_INTENT_KEYS[platform]))
            or any(props.get(key) for key in (
                "published_fb_film_1", "published_fb_film_2", "published_ig",
                "platform_result_fb_film_1", "platform_result_fb_film_2",
                "platform_result_ig", "film_part5_recovery_used",
            ))):
        raise RuntimeError(
            "Film Part 5 kurtarması için exact claim/file ve tüm platformlarda yayımlanmamış kayıt şartı sağlanmadı"
        )
    return True


def valid_film_part5_recovery_request(route, upload_only):
    """Part 5 recovery is an explicitly scoped manual all-Meta action, never cron."""
    return (
        route == "film"
        and not upload_only
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("FORCE_ROUTE", "").strip().lower() == "film"
        and os.environ.get("FORCE_STEM", "").strip() == FILM_PART5_RECOVERY_STEM
        and os.environ.get("FILM_CLAIM_TO_CLEAR", "").strip() == FILM_PART5_RECOVERY_CLAIM
        and not os.environ.get("FORCE_PLATFORM", "").strip()
        and not os.environ.get("BACKFILL_ROUTE", "").strip()
        and not os.environ.get("TOKEN_FILM_YOUTUBE_JSON", "").strip()
    )


def clear_exact_film_claim_for_publish(drive, folder_id, claim_value):
    """Clear one explicitly authorized stale claim, only after publish guards pass."""
    allowed_claims = {
        "manual-2026-10-17-0817-film": {"part_key": ("yoksul_1986", 1)},
        "manual-2026-10-17-0819-film": {
            "part_key": ("yoksul_1986", 2),
            "file_id": "1dhKwAI9LPpUEniIfqNuWKrY8EQuM67xZ",
        },
    }
    expected = allowed_claims.get(claim_value)
    if expected is None:
        raise RuntimeError("Film claim temizleme yalnızca yetkilendirilen exact claim için açık")
    matches, page_token = [], None
    while True:
        page = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,md5Checksum,appProperties)",
            pageSize=1000, pageToken=page_token,
        ).execute()
        matches.extend(item for item in page.get("files", [])
                       if (item.get("appProperties") or {}).get(CLAIM_SLOT) == claim_value)
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    if len(matches) != 1:
        raise RuntimeError(f"Exact Film claim doğrulanamadı; eşleşme sayısı={len(matches)}")
    item = matches[0]
    props = item.get("appProperties") or {}
    if film_part_key(item.get("name", "")) != expected["part_key"]:
        raise RuntimeError("Exact claim beklenen Yoksul partına ait değil; yayın durduruldu")
    if expected.get("file_id") and item.get("id") != expected["file_id"]:
        raise RuntimeError("Exact claim beklenen Drive dosya ID'sine ait değil; yayın durduruldu")
    if props.get(FILM_USED) == "1" or any(
        props.get(key) for key in (
            FILM_DONE_KEY, PLATFORM_RESULT_KEYS["ig"], PLATFORM_SLOT_KEYS["ig"],
            PLATFORM_INTENT_KEYS["ig"], "platform_result_ig", "platform_slot_ig", "published_ig",
        )
    ):
        raise RuntimeError("Film dosyasında mevcut yayın/işlem kaydı bulundu; claim temizlenmedi")
    drive.files().update(
        fileId=item["id"],
        body={"appProperties": {CLAIM_SLOT: None, CLAIMED_AT: None}},
    ).execute()
    print(
        f"Yetkili stale Film claim temizlendi: file_id={item['id']}; name={item['name']}; "
        f"claim={claim_value}; Drive yayın işareti yok.", flush=True,
    )
    return item["id"]


def next_due_route(drive, now=None, excluded_slots=None, allowed_routes=None, excluded_routes=None):
    """Güncel eksik slotu seçer; daha önce denenenleri bu turda atlar."""
    folder_files = {}
    excluded_slots = excluded_slots or set()
    excluded_routes = excluded_routes or set()
    for planned, route, slot in due_slots(now):
        if slot in excluded_slots:
            continue
        if route in excluded_routes:
            continue
        if allowed_routes is not None and route not in allowed_routes:
            continue
        if route_paused(route):
            continue
        folder_id = folder_for_route(drive, route, slot)
        if folder_id not in folder_files:
            folder_files[folder_id] = list_pairs(
                drive, folder_id, skip_duplicate_stems=(route == "daily_laugh")
            )[0]
        if route == "toonzone":
            # Keep Part 1-4 in verified episode order. After a prior-day
            # manual Part 1 recovery, resume at Part 2; never send a new
            # episode's Part 1 after Part 4 already posted today.
            report = analyze_files(folder_files[folder_id], ORDERED_CHANNELS["cartoon_tr"])
            if report["duplicate_names"] or report["invalid_names"]:
                raise RuntimeError("ToonZone klasöründe çakışan/geçersiz içerik; yayın durduruldu")
            if not toonzone_part_eligible(
                    slot, report["ordered"], used_key=TOONZONE_USED, last_slot_key=LAST_SLOT):
                continue
        if not slot_is_done(folder_files[folder_id], planned, route, slot):
            return route, slot
    return None, None


def list_pairs(drive, folder_id, skip_duplicate_stems=False):
    files, token = [], None
    while True:
        page = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,parents,md5Checksum,appProperties,mimeType,size)",
            pageSize=1000,
            pageToken=token,
        ).execute()
        files.extend(page.get("files", []))
        token = page.get("nextPageToken")
        if not token:
            break
    def unique_by_stem(items, kind):
        indexed = {}
        duplicates = {}
        for item in items:
            stem = Path(item["name"]).stem.casefold()
            if stem in indexed:
                duplicates.setdefault(stem, [indexed[stem]["id"]]).append(item["id"])
            else:
                indexed[stem] = item
        if duplicates and not skip_duplicate_stems:
            detail = "; ".join(f"{stem}: {ids}" for stem, ids in sorted(duplicates.items()))
            raise RuntimeError(f"Aynı gövdeli {kind} kopyaları bulundu; yayın durduruldu: {detail}")
        if duplicates:
            # Duplicate stems are ambiguous: ignore both copies without
            # blocking unrelated verified Daily Laugh candidates.
            for stem in duplicates:
                indexed.pop(stem, None)
        return indexed

    mp4 = unique_by_stem(
        [f for f in files if f["name"].lower().endswith(".mp4")], "MP4"
    )
    txt = unique_by_stem(
        [f for f in files if f["name"].lower().endswith(".txt")], "TXT"
    )
    return files, [(s, mp4[s], txt[s]) for s in mp4.keys() & txt.keys()]


def select_random_unused(drive, files, pairs, used_key, slot):
    if any(
        (f.get("appProperties") or {}).get(LAST_SLOT) == slot
        or (f.get("appProperties") or {}).get(FAILED_SLOT) == slot
        for f in files
    ):
        return None
    claimed_id = next(
        (
            f["id"]
            for f in files
            if (f.get("appProperties") or {}).get(CLAIM_SLOT) == slot
        ),
        None,
    )
    if claimed_id:
        return next((p for p in pairs if p[1]["id"] == claimed_id), None)
    # A copied Drive file can have a different ID/name while containing the
    # same MP4.  Treat the checksum of any published item as already used.
    used_md5 = {
        str(f.get("md5Checksum", "")).lower()
        for f in files
        if (f.get("appProperties") or {}).get(used_key) == "1"
        and f.get("md5Checksum")
    }
    choices = [
        p for p in pairs
        if (p[1].get("appProperties") or {}).get(used_key) != "1"
        and not (p[1].get("appProperties") or {}).get(CLAIM_SLOT)
        and str(p[1].get("md5Checksum", "")).lower() not in used_md5
    ]
    # Exhaustion is a safe stop. Never reset a used ledger entry implicitly.
    return random.choice(choices) if choices else None


def candidate_is_unused(files, pair, used_key):
    """Apply the same ledger/hash guard to forced stems as random selection."""
    video = pair[1]
    props = video.get("appProperties") or {}
    if props.get(used_key) == "1" or props.get(CLAIM_SLOT):
        return False
    used_md5 = {
        str(item.get("md5Checksum", "")).lower()
        for item in files
        if (item.get("appProperties") or {}).get(used_key) == "1" and item.get("md5Checksum")
    }
    return str(video.get("md5Checksum", "")).lower() not in used_md5


def new_youtube_candidate_unused(route, video):
    """Never recycle a confirmed or uncertain file on either new channel."""
    key, used = {"gonle_youtube": ("yt_gonle", GONLE_YT_USED),
                 "daily_laugh_youtube": ("yt_daily", DAILY_LAUGH_YT_USED)}[route]
    props = video.get("appProperties") or {}
    return not any((props.get(used) == "1", props.get(CLAIM_SLOT),
                    props.get(PLATFORM_RESULT_KEYS[key]), props.get(PLATFORM_SLOT_KEYS[key]),
                    props.get(PLATFORM_INTENT_KEYS[key])))


def safe_temp_path(temp, prefix, route, drive_id, extension):
    """Drive dosya adını yerel yola taşımadan güvenli ve çakışmasız yol üretir."""
    safe_route = re.sub(r"[^a-z0-9_-]", "_", route.lower())[:40]
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", drive_id)[:100]
    return temp / f"{prefix}_{safe_route}_{safe_id}{extension}"


def requested_platform(force_platform, platform):
    return not force_platform or force_platform == platform


def is_ambiguous_publish_error(exc):
    """Network/server failures may occur after a platform accepted a post."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, TimeoutError, ConnectionError)):
        return True
    status = (
        getattr(exc, "http_status", None)
        or
        getattr(getattr(exc, "resp", None), "status", None)
        or getattr(getattr(exc, "response", None), "status_code", None)
    )
    if status is None:
        match = re.search(r"\bHTTP\s+(\d{3})\b", str(exc), re.IGNORECASE)
        status = int(match.group(1)) if match else None
    # Meta returned an explicit error before media_publish. No visible post can
    # exist yet, so bounded retry on the next cloud tick is safe.
    if getattr(exc, "stage", None) in {
        "Instagram container oluşturma",
        "Instagram ikili video aktarımı",
        "Instagram video işleme durumu",
    }:
        return False
    # An explicit 429 response means this request was rate-limited/rejected;
    # it may be retried with pacing. Network loss, 408/425 and 5xx remain
    # ambiguous and keep the durable intent to prevent a duplicate post.
    return status in (408, 425) or (isinstance(status, int) and status >= 500)


def is_permanent_publish_error(exc):
    """Explicit client rejections are permanent for this file/slot."""
    status = getattr(exc, "http_status", None)
    if status is None:
        match = re.search(r"\bHTTP(?:=|\s+)(\d{3})\b", str(exc), re.IGNORECASE)
        status = int(match.group(1)) if match else None
    return isinstance(status, int) and 400 <= status < 500 and status not in (408, 425, 429)


def _explicit_transient_publish_error(exc):
    """Retry only an explicit transient rejection; never retry ambiguous outcomes."""
    status = getattr(exc, "http_status", None)
    if status is None:
        status = getattr(getattr(exc, "resp", None), "status", None)
    # A received HTTP 429 is an explicit rate-limit rejection, unlike a lost
    # connection or a server error that could follow an accepted publication.
    if status == 429:
        return True
    if is_ambiguous_publish_error(exc):
        return False
    return (
        getattr(exc, "is_transient", None) is True
        or getattr(exc, "retriable", None) is True
    )


def _retry_delay_seconds(exc, retry_number):
    headers = getattr(exc, "response_headers", None) or {}
    retry_after = next((value for key, value in headers.items()
                        if str(key).lower() == "retry-after"), None)
    try:
        if retry_after is not None:
            return max(0.0, min(float(retry_after), 60.0))
    except (TypeError, ValueError):
        pass
    return min(2 ** (retry_number - 1), 30)


def _publish_interval_seconds():
    try:
        value = int(os.environ.get(
            "MIN_PLATFORM_INTERVAL_SECONDS", str(DEFAULT_MIN_PLATFORM_INTERVAL_SECONDS)
        ))
    except (TypeError, ValueError):
        value = DEFAULT_MIN_PLATFORM_INTERVAL_SECONDS
    return max(0, min(value, 300))


def configured_max_due_slots(value=None):
    raw = value if value is not None else os.environ.get("MAX_DUE_SLOTS", DEFAULT_MAX_DUE_SLOTS)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = DEFAULT_MAX_DUE_SLOTS
    return max(1, min(parsed, MAX_DUE_SLOTS_PER_RUN))


def _paced_platform_call(call, account, platform):
    key = (str(account), str(platform))
    interval = _publish_interval_seconds()
    previous = _LAST_PLATFORM_PUBLISH_AT.get(key)
    if previous is not None:
        remaining = interval - (time.monotonic() - previous)
        if remaining > 0:
            time.sleep(remaining)
    _LAST_PLATFORM_PUBLISH_AT[key] = time.monotonic()
    return call()


def _call_with_transient_retries(call, account, platform):
    for attempt in range(1, MAX_TRANSIENT_RETRIES + 1):
        try:
            return _paced_platform_call(call, account, platform)
        except Exception as exc:
            if attempt >= MAX_TRANSIENT_RETRIES or not _explicit_transient_publish_error(exc):
                raise
            delay = _retry_delay_seconds(exc, attempt)
            print(
                f"Açık geçici API reddi; platform={platform}; attempt={attempt}; "
                f"bekleme_saniye={delay:g}.", flush=True,
            )
            time.sleep(delay)


def execute_platform_jobs(drive, video_obj, slot, required, jobs, properties, batch_gates=None, account="unknown"):
    """Persist intent before each external publish and result immediately after.

    An interrupted/ambiguous attempt is never automatically resent. Explicit
    platform rejections can be retried up to three times across workflow runs.
    """
    results, errors = {}, {}
    for key in required:
        state_key = PLATFORM_SLOT_KEYS[key]
        intent_key = PLATFORM_INTENT_KEYS[key]
        failure_key = PLATFORM_FAILURE_KEYS[key]
        if properties.get(state_key) == slot:
            results[key] = properties.get(PLATFORM_RESULT_KEYS[key], "önceki denemede tamamlandı")
            continue
        if properties.get(intent_key) == slot:
            errors[key] = "önceki denemenin sonucu belirsiz; mükerrer paylaşımı önlemek için otomatik tekrar durduruldu"
            drive.files().update(
                fileId=video_obj["id"],
                body={"appProperties": {FAILED_SLOT: slot, PLATFORM_FAILURE_SLOT_KEYS[key]: slot}},
            ).execute()
            properties[FAILED_SLOT] = slot
            properties[PLATFORM_FAILURE_SLOT_KEYS[key]] = slot
            continue
        try:
            failures = int(properties.get(failure_key, "0"))
        except (TypeError, ValueError):
            failures = MAX_PLATFORM_ATTEMPTS
        # A Graph field-query defect can leave a known-not-published IG
        # container with the normal retry counter exhausted.  A human may
        # explicitly request exactly one recovery attempt through the manual
        # IG-only route.  It is deliberately unavailable to schedules and it
        # cannot be repeated: a further failure increments the counter to 4.
        controlled_ig_recovery = (
            key == "ig"
            and failures == MAX_PLATFORM_ATTEMPTS
            and os.getenv("CONTROLLED_IG_RECOVERY", "").lower() == "true"
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("FORCE_ROUTE", "").strip() in {"tarladaki_ig", "penguen_ig"}
            and bool(os.getenv("FORCE_STEM", "").strip())
            and properties.get("controlled_ig_recovery_used") != "1"
        )
        toonzone_part1_ig_recovery = (
            key == "ig"
            and os.getenv("TOONZONE_RESUME_PART1_IG", "false").lower() == "true"
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("FORCE_ROUTE", "").strip() == "toonzone"
            and os.getenv("FORCE_PLATFORM", "").strip().lower() == "instagram"
            and os.getenv("FORCE_SLOT_SUFFIX", "").strip() == "toonzone-part1"
            and video_obj.get("id") == TOONZONE_IG_FAILED_TEST_FILE_ID
            and properties.get("toonzone_ig_recovery_used") == "1"
            and not properties.get(PLATFORM_SLOT_KEYS["ig"])
            and not properties.get(PLATFORM_INTENT_KEYS["ig"])
        )
        film_part3_ig_recovery = (
            key == "ig"
            and failures == MAX_PLATFORM_ATTEMPTS
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("FORCE_ROUTE", "").strip() == "film"
            and os.getenv("FORCE_PLATFORM", "").strip() == "instagram"
            and os.getenv("FORCE_STEM", "").strip() == FILM_PART3_IG_RECOVERY_STEM
            and os.getenv("FILM_CLAIM_TO_CLEAR", "").strip() == FILM_PART3_IG_RECOVERY_CLAIM
            and video_obj.get("id") == FILM_PART3_IG_RECOVERY_FILE_ID
            and properties.get("film_part3_ig_recovery_used") == "1"
            and properties.get("film_part3_ig_recovery_from") == FILM_PART3_IG_RECOVERY_CLAIM
            and not properties.get(PLATFORM_SLOT_KEYS["ig"])
            and not properties.get(PLATFORM_RESULT_KEYS["ig"])
            and not properties.get(PLATFORM_INTENT_KEYS["ig"])
        )
        film_part4_ig_recovery = (
            key == "ig"
            and failures == MAX_PLATFORM_ATTEMPTS
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("FORCE_ROUTE", "").strip() == "film"
            and os.getenv("FORCE_PLATFORM", "").strip() == "instagram"
            and os.getenv("FORCE_STEM", "").strip() == FILM_PART4_IG_RECOVERY_STEM
            and os.getenv("FILM_CLAIM_TO_CLEAR", "").strip() == FILM_PART4_IG_RECOVERY_CLAIM
            and video_obj.get("id") == FILM_PART4_IG_RECOVERY_FILE_ID
            and properties.get("film_part4_ig_recovery_used") == "1"
            and properties.get("film_part4_ig_recovery_from") == FILM_PART4_IG_RECOVERY_CLAIM
            and not properties.get(PLATFORM_SLOT_KEYS["ig"])
            and not properties.get(PLATFORM_RESULT_KEYS["ig"])
            and not properties.get(PLATFORM_INTENT_KEYS["ig"])
        )
        film_part5_recovery = (
            key == "ig"
            and failures == MAX_PLATFORM_ATTEMPTS
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("FORCE_ROUTE", "").strip().lower() == "film"
            and not os.getenv("FORCE_PLATFORM", "").strip()
            and os.getenv("FORCE_STEM", "").strip() == FILM_PART5_RECOVERY_STEM
            and os.getenv("FILM_CLAIM_TO_CLEAR", "").strip() == FILM_PART5_RECOVERY_CLAIM
            and video_obj.get("id") == FILM_PART5_RECOVERY_FILE_ID
            and properties.get("film_part5_recovery_used") == "1"
            and properties.get("film_part5_recovery_from") == FILM_PART5_RECOVERY_CLAIM
            and not properties.get(PLATFORM_SLOT_KEYS["ig"])
            and not properties.get(PLATFORM_RESULT_KEYS["ig"])
            and not properties.get(PLATFORM_INTENT_KEYS["ig"])
        )
        if (failures >= MAX_PLATFORM_ATTEMPTS and not controlled_ig_recovery
                and not toonzone_part1_ig_recovery and not film_part3_ig_recovery
                and not film_part4_ig_recovery and not film_part5_recovery):
            errors[key] = f"{MAX_PLATFORM_ATTEMPTS} açık API hatası sonrası otomatik deneme durduruldu"
            drive.files().update(
                fileId=video_obj["id"],
                body={"appProperties": {FAILED_SLOT: slot, PLATFORM_FAILURE_SLOT_KEYS[key]: slot}},
            ).execute()
            properties[FAILED_SLOT] = slot
            properties[PLATFORM_FAILURE_SLOT_KEYS[key]] = slot
            continue

        # A recovery approval is consumed before the external call.  A later
        # permanent failure therefore cannot be retried by repeatedly
        # dispatching the same workflow.
        if controlled_ig_recovery:
            drive.files().update(
                fileId=video_obj["id"], body={"appProperties": {"controlled_ig_recovery_used": "1"}}
            ).execute()
            properties["controlled_ig_recovery_used"] = "1"

        # Bu kayıt Drive'a yazılamazsa dış API çağrısı kesinlikle yapılmaz.
        drive.files().update(
            fileId=video_obj["id"], body={"appProperties": {intent_key: slot}}
        ).execute()
        properties[intent_key] = slot
        gate = (batch_gates or {}).get(key)
        if gate is not None and not gate.claim():
            errors[key] = "batch hedefi claim edilemedi; yayın çağrısı yapılmadı"
            properties.pop(intent_key, None)
            drive.files().update(fileId=video_obj["id"], body={"appProperties": {
                intent_key: None, PLATFORM_FAILURE_SLOT_KEYS[key]: slot,
            }}).execute()
            properties[PLATFORM_FAILURE_SLOT_KEYS[key]] = slot
            continue
        try:
            platform = {
                "yt1": "youtube", "yt2": "youtube", "yt_gonle": "youtube",
                "yt_daily": "youtube", "yt_film": "youtube", "fb": "facebook",
                "fb_film_1": "facebook_film_1", "fb_film_2": "facebook_film_2",
                "ig": "instagram", "threads": "threads",
            }.get(key, key)
            result = _call_with_transient_retries(jobs[key], account, platform)
        except Exception as exc:
            if gate is not None:
                gate.finish("unknown" if is_ambiguous_publish_error(exc) else "failed", error=str(exc)[:200])
            errors[key] = str(exc)
            if is_ambiguous_publish_error(exc):
                # Intent'i tut: sonraki tetik aynı gönderiyi körlemesine basmasın.
                drive.files().update(
                    fileId=video_obj["id"],
                    body={"appProperties": {FAILED_SLOT: slot, PLATFORM_FAILURE_SLOT_KEYS[key]: slot}},
                ).execute()
                properties[FAILED_SLOT] = slot
                properties[PLATFORM_FAILURE_SLOT_KEYS[key]] = slot
                continue
            if is_permanent_publish_error(exc):
                # Aynı dosyayı üç kez körlemesine denemek yerine karantinaya al.
                patch = {intent_key: None, failure_key: str(MAX_PLATFORM_ATTEMPTS),
                         FAILED_SLOT: slot, PLATFORM_FAILURE_SLOT_KEYS[key]: slot}
                drive.files().update(fileId=video_obj["id"], body={"appProperties": patch}).execute()
                properties.update({k: v for k, v in patch.items() if v is not None})
                properties.pop(intent_key, None)
                continue
            failures += 1
            patch = {intent_key: None, failure_key: str(failures), PLATFORM_FAILURE_SLOT_KEYS[key]: slot}
            if failures >= MAX_PLATFORM_ATTEMPTS:
                patch[FAILED_SLOT] = slot
            drive.files().update(fileId=video_obj["id"], body={"appProperties": patch}).execute()
            properties.update({k: v for k, v in patch.items() if v is not None})
            properties.pop(intent_key, None)
            continue

        # Tek Drive güncellemesinde tamamlanmayı ve dış API sonucunu kaydet.
        # Yanıt kaybolursa intent kalır ve tekrarlı gönderim engellenir.
        result_text = str(result)[:100]
        if gate is not None:
            gate.finish("confirmed", remote_url=result_text)
        patch = {
            state_key: slot,
            PLATFORM_RESULT_KEYS[key]: result_text,
            intent_key: None,
            failure_key: "0",
            PLATFORM_FAILURE_SLOT_KEYS[key]: None,
        }
        drive.files().update(fileId=video_obj["id"], body={"appProperties": patch}).execute()
        properties.update({k: v for k, v in patch.items() if v is not None})
        properties.pop(intent_key, None)
        results[key] = result_text
    return results, errors


def _gonle_ig_upload_only_test(drive, folder_id):
    """Re-test the previously rejected Gönle file through normal prep, never publish or mutate Drive."""
    item = drive.files().get(
        fileId=GONLE_IG_FAILED_TEST_FILE_ID,
        fields="id,name,parents,mimeType,size,md5Checksum",
    ).execute()
    if (item.get("id") != GONLE_IG_FAILED_TEST_FILE_ID
            or item.get("mimeType") != "video/mp4"
            or folder_id not in item.get("parents", [])
            or not item.get("name", "").lower().endswith(".mp4")):
        raise RuntimeError("Önceden reddedilen dosya Gönle klasöründe doğrulanmış bir MP4 değil; upload yapılmadı.")
    verify_file_in_folder(drive, item, folder_id)

    page = meta_page("Gönle Düşen")
    with tempfile.TemporaryDirectory(prefix="gonle-ig-upload-only-") as temp_dir:
        source = Path(temp_dir) / "gonle-source.mp4"
        request = drive.files().get_media(fileId=item["id"])
        with source.open("wb") as target:
            downloader = MediaIoBaseDownload(target, request, chunksize=4 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        log_media_diagnostics("Gönle upload-only kaynak", source)
        check_full_decode(source)
        prepared, method = prepare_instagram_upload(
            source, Path(temp_dir) / "gonle-upload.mp4", prefer_remux=True,
            film_compact=True, return_method=True,
        )
        log_media_diagnostics("Gönle upload-only son dosya", prepared)
        result = upload_instagram_reel(
            page, str(prepared), Path(item["name"]).stem,
            append_store_link=False, publish=False,
        )
        if (not result.get("container_id") or result.get("published") is not False
                or result.get("status") != "FINISHED"):
            raise RuntimeError("Gönle upload-only koruması veya FINISHED koşulu sağlanmadı.")
        print(
            f"Gönle upload-only doğrulandı: file={item['id']}; name={item['name']}; "
            f"method={method}; bytes={prepared.stat().st_size}; "
            f"container={result['container_id']}; status=FINISHED; media_publish=not_called; drive_write=not_called.",
            flush=True,
        )
        return result


def _toonzone_ig_upload_only_test(drive, folder_id):
    """Retry only the previously rejected ToonZone file through IG processing; never publish or mutate Drive."""
    item = drive.files().get(
        fileId=TOONZONE_IG_FAILED_TEST_FILE_ID,
        fields="id,name,parents,mimeType,size,md5Checksum",
    ).execute()
    if (item.get("id") != TOONZONE_IG_FAILED_TEST_FILE_ID
            or item.get("mimeType") != "video/mp4"
            or folder_id not in (item.get("parents") or [])
            or item.get("name") != "S01E01_The_Power_Part1.mp4"):
        raise RuntimeError("Önceden reddedilen dosya ToonZone klasöründe doğrulanmış MP4 değil; upload yapılmadı.")
    verify_file_in_folder(drive, item, folder_id)

    page = meta_page("ToonZone")
    cover_files, _ = list_pairs(drive, TOONZONE_COVER_FOLDER_ID)
    cover = match_toonzone_cover(
        item, cover_files, CoverScope("cartoon_tr", folder_id, TOONZONE_COVER_FOLDER_ID)
    )
    cover_bytes, dimensions = download_and_validate_cover(drive, cover)
    with tempfile.TemporaryDirectory(prefix="toonzone-ig-upload-only-") as temp_dir:
        root = Path(temp_dir)
        source = root / "toonzone-source.mp4"
        with source.open("wb") as target:
            downloader = MediaIoBaseDownload(
                target, drive.files().get_media(fileId=item["id"]), chunksize=4 * 1024 * 1024
            )
            done = False
            while not done:
                _, done = downloader.next_chunk()
        cover_path = root / "toonzone-cover.png"
        cover_path.write_bytes(cover_bytes)
        composite = create_instagram_cover_video(source, cover_path, root / "toonzone-cover-composite.mp4")
        prepared, method = prepare_instagram_upload(
            composite, root / "toonzone-instagram.mp4", toonzone_compact=True, return_method=True
        )
        log_media_diagnostics("ToonZone Instagram upload-only son dosya", prepared)
        result = upload_instagram_reel(
            page, str(prepared), Path(item["name"]).stem,
            append_store_link=False, publish=False,
        )
        if (not result.get("container_id") or result.get("published") is not False
                or result.get("status") != "FINISHED"):
            raise RuntimeError("ToonZone upload-only koruması veya FINISHED koşulu sağlanmadı.")
        print(
            f"ToonZone IG upload-only doğrulandı: file={item['id']}; name={item['name']}; "
            f"cover={cover['name']}; cover_dimensions={dimensions}; method={method}; "
            f"bytes={prepared.stat().st_size}; container={result['container_id']}; "
            "status=FINISHED; media_publish=not_called; drive_write=not_called.",
            flush=True,
        )
        return result


def meta_page(*names):
    errors = []
    for name in names:
        try:
            page = get_meta_page_info(name)
            check = requests.get(
                f"https://graph.facebook.com/v20.0/{page['page_id']}",
                params={"fields": "id", "access_token": page["page_token"]},
                timeout=15,
            )
            check.raise_for_status()
            if check.json().get("id") != page["page_id"]:
                raise RuntimeError(f"Meta sayfa doğrulanamadı: {name}")
            return page
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(" / ".join(errors))


def _run_impl(drive=None, selected=None, routing_validated=False, deferred_successes=None):
    upload_only = os.environ.get("FILM_IG_UPLOAD_ONLY", "false").strip().lower() == "true"
    toonzone_ig_upload_test = os.environ.get("TOONZONE_IG_UPLOAD_ONLY", "false").strip().lower() == "true"
    toonzone_part1_ig_recovery = os.environ.get("TOONZONE_RESUME_PART1_IG", "false").strip().lower() == "true"
    film_compact_test = os.environ.get("FILM_IG_COMPACT_TEST", "false").strip().lower() == "true"
    gonle_ig_upload_test = os.environ.get("GONLE_IG_CONTROLLED_TEST", "false").strip().lower() == "true"
    diagnostic_clip_seconds = os.environ.get("FILM_IG_DIAGNOSTIC_CLIP_SECONDS", "15").strip()
    diagnostic_remux = os.environ.get("FILM_IG_DIAGNOSTIC_REMUX", "false").strip().lower() == "true"
    if gonle_ig_upload_test and (
        os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("FORCE_ROUTE", "").strip().lower() != "gonle_ig"
        or os.environ.get("FORCE_PLATFORM", "").strip().lower() != "instagram"
        or upload_only or film_compact_test
        or os.environ.get("FILM_CLAIM_TO_CLEAR", "").strip()
        or os.environ.get("BACKFILL_ROUTE", "").strip()
        or os.environ.get("FILM_IG_TEST_FILE_ID", "").strip()
        or os.environ.get("FILM_IG_TEST_FILE_IDS", "").strip()
        or os.environ.get("FILM_IG_TEST_BATCH", "false").strip().lower() == "true"
    ):
        raise RuntimeError("Gönle kontrollü upload-only yalnızca manuel Gönle Instagram testinde, ek işlem olmadan çalışabilir.")
    if toonzone_ig_upload_test and (
        os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("FORCE_ROUTE", "").strip() != "toonzone"
        or os.environ.get("FORCE_PLATFORM", "").strip().lower() != "instagram"
        or upload_only or film_compact_test or gonle_ig_upload_test
        or os.environ.get("FILM_CLAIM_TO_CLEAR", "").strip()
        or os.environ.get("BACKFILL_ROUTE", "").strip()
        or os.environ.get("FILM_IG_TEST_FILE_ID", "").strip()
        or os.environ.get("FILM_IG_TEST_FILE_IDS", "").strip()
        or os.environ.get("FILM_IG_TEST_BATCH", "false").strip().lower() == "true"
    ):
        raise RuntimeError("ToonZone kontrollü upload-only yalnızca manuel ToonZone Instagram testinde, ek işlem olmadan çalışabilir.")
    if toonzone_part1_ig_recovery and (
        os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("FORCE_ROUTE", "").strip() != "toonzone"
        or os.environ.get("FORCE_SLOT_SUFFIX", "").strip() != "toonzone-part1"
        or os.environ.get("FORCE_PLATFORM", "").strip().lower() != "instagram"
        or toonzone_ig_upload_test or upload_only or film_compact_test or gonle_ig_upload_test
        or os.environ.get("BACKFILL_ROUTE", "").strip()
        or os.environ.get("FILM_CLAIM_TO_CLEAR", "").strip()
    ):
        raise RuntimeError("Part 1 claim kurtarması yalnızca manuel ToonZone/Part 1/Instagram akışında çalışabilir.")
    if upload_only and (
        os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("FORCE_ROUTE", "").strip() != "film"
        or os.environ.get("FORCE_PLATFORM", "").strip().lower() != "instagram"
    ):
        raise RuntimeError("Film Instagram upload-only modu yalnızca manuel Film/Instagram rotasında çalışabilir.")
    if upload_only and (os.environ.get("FILM_CLAIM_TO_CLEAR", "").strip()
                        or os.environ.get("BACKFILL_ROUTE", "").strip()):
        raise RuntimeError("Film upload-only testinde claim temizleme ve backfill yasak.")
    if film_compact_test and not upload_only:
        raise RuntimeError("Film compact denemesi yalnızca upload-only akışında açık.")
    if upload_only:
        try:
            diagnostic_clip_seconds = int(diagnostic_clip_seconds)
        except ValueError:
            raise RuntimeError("Film tanı klibi süresi tam sayı olmalı.") from None
        if diagnostic_clip_seconds != 0 and not 5 <= diagnostic_clip_seconds <= 60:
            raise RuntimeError("Film tanı klibi 5-60 saniye olmalı; tam dosya için 0 kullanın.")
        if diagnostic_remux and diagnostic_clip_seconds != 0:
            raise RuntimeError("Yeniden paketleme tanısı için klip süresi 0 olmalı.")
    if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("ALLOW_LOCAL_PUBLISH") != "I_UNDERSTAND":
        raise RuntimeError(
            "Yerel doğrudan yayın güvenlik nedeniyle kapalı. "
            "Üretim yayınını GitHub workflow_dispatch ile başlatın."
        )
    drive = drive or get_drive_client()
    if not routing_validated and not gonle_ig_upload_test and not toonzone_ig_upload_test:
        validate_drive_routing(drive)
        if not upload_only and not toonzone_ig_upload_test:
            quarantine_legacy_shared_claims(drive)
    if gonle_ig_upload_test:
        folder_id = folder_for_route(drive, "gonle_ig", "controlled-gonle-ig-upload-only")
        return _gonle_ig_upload_only_test(drive, folder_id)
    if toonzone_ig_upload_test:
        folder_id = folder_for_route(drive, "toonzone", "controlled-toonzone-ig-upload-only")
        return _toonzone_ig_upload_only_test(drive, folder_id)
    if selected is not None:
        route, slot = selected
    elif os.environ.get("FORCE_ROUTE", "").strip():
        route, slot = route_for_time()
    else:
        route, slot = next_due_route(drive)
    if not route:
        print("Son 24 saatte eksik yayın yok; işlem yapılmadı.")
        return

    base_route = base_route_name(route)
    force_platform = os.environ.get("FORCE_PLATFORM", "").strip().lower()
    if os.environ.get("FILM_IG_TEST_LIST_ONLY", "false").strip().lower() == "true":
        if route != "film" or force_platform != "instagram" or not upload_only:
            raise RuntimeError("Film test listeleme yalnızca upload-only Film Instagram akışında çalışabilir.")
        inventory = list_film_mp4s_for_test(drive, folder_for_route(drive, route, slot))
        for item in inventory:
            print(f"FILM_TEST_FILE id={item.get('id')} name={item.get('name')} size={item.get('size','')} md5={item.get('md5Checksum','')}", flush=True)
        print(f"FILM_TEST_FILE_COUNT={len(inventory)}", flush=True)
        return
    if not batch_exception_allowed(route):
        require_route_enabled(route)
    folder_id = folder_for_route(drive, route, slot)
    test_file_ids_raw = os.environ.get("FILM_IG_TEST_FILE_IDS", "").strip()
    test_batch_mode = os.environ.get("FILM_IG_TEST_BATCH", "false").strip().lower() == "true"
    if test_file_ids_raw and not test_batch_mode:
        raise RuntimeError("FILM_IG_TEST_FILE_IDS için açık Film batch test modu seçilmedi; normal seçiciye geçilmiyor.")
    if test_batch_mode:
        if (not upload_only or route != "film" or force_platform != "instagram"
                or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or os.environ.get("FILM_IG_TEST_FILE_ID", "").strip()
                or os.environ.get("FILM_IG_TEST_LIST_ONLY", "false").strip().lower() == "true"):
            raise RuntimeError("FILM_IG_TEST_FILE_IDS yalnızca manuel Film Instagram upload-only yolunda kullanılabilir.")
        try:
            start_index = int(os.environ.get("FILM_IG_TEST_START_INDEX", "0"))
            batch_count = int(os.environ.get("FILM_IG_TEST_BATCH_COUNT", "2"))
        except ValueError:
            raise RuntimeError("Film upload-only aşama ayarları tam sayı olmalı.") from None
        file_ids = parse_film_upload_test_ids(test_file_ids_raw)
        return _film_upload_only_batch(
            drive, folder_id, file_ids, start_index=start_index, count=batch_count,
        )
    clear_claim = os.environ.get("FILM_CLAIM_TO_CLEAR", "").strip()
    film_part3_ig_recovery = clear_claim == FILM_PART3_IG_RECOVERY_CLAIM
    film_part4_ig_recovery = clear_claim == FILM_PART4_IG_RECOVERY_CLAIM
    film_part5_recovery = clear_claim == FILM_PART5_RECOVERY_CLAIM
    if clear_claim:
        if film_part5_recovery:
            if not valid_film_part5_recovery_request(route, upload_only):
                raise RuntimeError(
                    "Part 5 kurtarması yalnızca exact manuel Film akışında, tüm Meta hedefleriyle ve YouTube secretsız çalışabilir"
                )
        elif not (route == "film" and force_platform == "instagram"
                  and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"):
            raise RuntimeError("Film claim temizleme yalnızca manuel Film Instagram akışında açık")
        elif film_part3_ig_recovery:
            if forced_stem := os.environ.get("FORCE_STEM", "").strip():
                if forced_stem != FILM_PART3_IG_RECOVERY_STEM:
                    raise RuntimeError("Film Part 3 IG kurtarması yanlış FORCE_STEM ile başlatılamaz")
            else:
                raise RuntimeError("Film Part 3 IG kurtarmasında FORCE_STEM zorunludur")
            if upload_only or os.getenv("BACKFILL_ROUTE", "").strip():
                raise RuntimeError("Film Part 3 IG kurtarmasında upload-only/backfill yasak")
        elif film_part4_ig_recovery:
            if forced_stem := os.environ.get("FORCE_STEM", "").strip():
                if forced_stem != FILM_PART4_IG_RECOVERY_STEM:
                    raise RuntimeError("Film Part 4 IG kurtarması yanlış FORCE_STEM ile başlatılamaz")
            else:
                raise RuntimeError("Film Part 4 IG kurtarmasında FORCE_STEM zorunludur")
            if upload_only or os.getenv("BACKFILL_ROUTE", "").strip():
                raise RuntimeError("Film Part 4 IG kurtarmasında upload-only/backfill yasak")
        else:
            clear_exact_film_claim_for_publish(drive, folder_id, clear_claim)
    if route == "gonle_youtube":
        used_key = GONLE_YT_USED
    elif route == "daily_laugh_youtube":
        used_key = DAILY_LAUGH_YT_USED
    elif base_route == "gonle":
        used_key = GONLE_USED
    elif base_route == "daily_laugh":
        used_key = DAILY_LAUGH_USED
    elif base_route == "film":
        used_key = FILM_USED
    elif base_route == "toonzone":
        used_key = TOONZONE_USED
    else:
        used_key = SHARED_USED

    test_file_id = os.environ.get("FILM_IG_TEST_FILE_ID", "").strip()
    if test_file_id and not (upload_only and route == "film" and force_platform == "instagram"):
        raise RuntimeError("FILM_IG_TEST_FILE_ID yalnızca Film Instagram upload-only yolunda kullanılabilir.")
    files, pairs = list_pairs(
        drive, folder_id, skip_duplicate_stems=(base_route == "daily_laugh")
    ) if base_route != "film" else ([], [])
    forced_stem = os.environ.get("FORCE_STEM", "").strip()
    if route in ("gonle_youtube", "daily_laugh_youtube"):
        eligible = [p for p in pairs if new_youtube_candidate_unused(route, p[1])]
        picked = next((p for p in eligible if p[0] == forced_stem), None) if forced_stem else (random.choice(eligible) if eligible else None)
    elif base_route == "film" and test_file_id:
        video_obj = drive.files().get(fileId=test_file_id, fields="id,name,parents,mimeType,size,md5Checksum,appProperties").execute()
        if test_file_id not in {item.get("id") for item in list_film_mp4s_for_test(drive, folder_id)}:
            raise RuntimeError("FILM_IG_TEST_FILE_ID Film klasöründe bulunan bir MP4 değil.")
        txt_obj = {"id": "", "name": ""}
        picked = (Path(video_obj["name"]).stem, video_obj, txt_obj)
    elif base_route == "film":
        film = select_next_film_part(
            drive, folder_id, slot,
            persist_active=not upload_only,
            allow_claimed_next=upload_only or film_part3_ig_recovery or film_part4_ig_recovery or film_part5_recovery,
        )
        picked = None if not film else (Path(film[2]["name"]).stem, film[2], film[3])
        # A controlled retry may pin the expected next part. Never allow the
        # manual stem to skip the persistent ordered-film selector.
        if forced_stem and (not picked or picked[0] != forced_stem):
            raise RuntimeError("FORCE_STEM sıradaki Film partıyla eşleşmedi; yayın yapılmadı")
    elif base_route == "toonzone":
        cartoon = select_next_toonzone_part(
            files, slot, allow_part1_ig_recovery=toonzone_part1_ig_recovery
        )
        picked = (cartoon[0], cartoon[1], {"id": "", "name": ""}) if cartoon else None
        if forced_stem and (not picked or picked[0] != forced_stem):
            raise RuntimeError("FORCE_STEM seçilen sıradaki ToonZone partıyla eşleşmedi; yayın yapılmadı")
    else:
        if forced_stem:
            forced = next((p for p in pairs if p[0] == forced_stem), None)
            picked = forced if forced and candidate_is_unused(files, forced, used_key) else None
        else:
            picked = select_random_unused(drive, files, pairs, used_key, slot)
        # Fan-out routes must pick a video that is also safe for their YouTube
        # target; otherwise FB/IG and YouTube would silently diverge.
        yt_route = {"gonle": "gonle_youtube", "daily_laugh": "daily_laugh_youtube"}.get(route)
        if picked and yt_route and os.getenv("ENABLE_NEW_YOUTUBE_ROUTES", "false").lower() == "true" and not new_youtube_candidate_unused(yt_route, picked[1]):
            picked = None
    if not picked:
        print(f"{slot}: daha önce işlendi veya içerik yok.")
        return

    stem, video_obj, txt_obj = picked
    if film_part3_ig_recovery:
        verify_film_part3_ig_only_recovery(video_obj)
    if film_part4_ig_recovery:
        verify_film_part4_ig_only_recovery(video_obj)
    if film_part5_recovery:
        verify_film_part5_recovery(video_obj)
    verify_file_in_folder(drive, video_obj, folder_id)
    toonzone_cover = None
    toonzone_cover_bytes = None
    toonzone_page = None
    if base_route == "toonzone":
        # Verify both Meta targets and the exact episode/part artwork before
        # claiming a Drive file or making any publish call.
        toonzone_page = meta_page("ToonZone")
        cover_files, _cover_pairs = list_pairs(drive, TOONZONE_COVER_FOLDER_ID)
        toonzone_cover = match_toonzone_cover(
            video_obj, cover_files,
            CoverScope("cartoon_tr", folder_id, TOONZONE_COVER_FOLDER_ID),
        )
        toonzone_cover_bytes, toonzone_cover_dimensions = download_and_validate_cover(
            drive, toonzone_cover
        )
        print(
            f"ToonZone ön kontrol tamam: part={slot.rsplit('part', 1)[1]}; "
            f"cover={toonzone_cover['name']}; dimensions={toonzone_cover_dimensions}.",
            flush=True,
        )
    if not upload_only:
        claim = {
            CLAIM_SLOT: slot,
            CLAIMED_AT: datetime.now(TZ).isoformat(timespec="seconds"),
        }
        if film_part3_ig_recovery:
            # One-shot approval is persisted BEFORE any remote publish call.
            # Never clear existing FB done/results, or the old IG failure count.
            claim["film_part3_ig_recovery_used"] = "1"
            claim["film_part3_ig_recovery_from"] = FILM_PART3_IG_RECOVERY_CLAIM
            print(
                "Film Part 3 IG kurtarma kaydı doğrulandı: "
                "17 Ekim Facebook 1/2 yayınları korunuyor; yalnızca Instagram denenebilir.",
                flush=True,
            )
        if film_part4_ig_recovery:
            # Persist a one-shot marker before any remote call; only the IG
            # route can proceed, preserving both already-confirmed FB results.
            claim["film_part4_ig_recovery_used"] = "1"
            claim["film_part4_ig_recovery_from"] = FILM_PART4_IG_RECOVERY_CLAIM
            print(
                "Film Part 4 IG kurtarma kaydı doğrulandı: iki Facebook yayın ID'si korunuyor; "
                "yalnızca kullanıcı tarafından manuel tetiklenen Instagram denemesi mümkün.",
                flush=True,
            )
        if film_part5_recovery:
            # This marker is committed before any network call and pins the
            # recovery to all three audited Meta targets, including both FBs.
            claim["film_part5_recovery_used"] = "1"
            claim["film_part5_recovery_from"] = FILM_PART5_RECOVERY_CLAIM
            print(
                "Film Part 5 exact recovery armed for Facebook 1, Facebook 2, and Instagram only; "
                "no YouTube target is configured.", flush=True,
            )
        if toonzone_part1_ig_recovery:
            claim["toonzone_ig_recovery_used"] = "1"
            print(
                f"ToonZone Part 1 eski claim uzlaştırıldı: Facebook post ID={TOONZONE_PART1_FB_POST_ID} doğrulandı; "
                "Instagram önceki denemesi binary upload HTTP 400 ile media_publish öncesinde durmuş. "
                "Yalnızca Instagram devam ediyor.",
                flush=True,
            )
        drive.files().update(
            fileId=video_obj["id"], body={"appProperties": claim}
        ).execute()
        video_obj.setdefault("appProperties", {}).update(claim)

    temp = Path("temp_scheduled")
    temp.mkdir(exist_ok=True)
    raw = safe_temp_path(temp, "raw", route, video_obj["id"], ".mp4")
    text_file = safe_temp_path(temp, "text", route, txt_obj["id"], ".txt")

    if txt_obj.get("name"):
        with io.FileIO(text_file, "wb") as fh:
            MediaIoBaseDownload(fh, drive.files().get_media(fileId=txt_obj["id"])).next_chunk()
    with io.FileIO(raw, "wb") as fh:
        dl = MediaIoBaseDownload(fh, drive.files().get_media(fileId=video_obj["id"]), chunksize=4 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()

    raw_text = text_file.read_text(encoding="utf-8", errors="ignore") if txt_obj.get("name") else f"{stem}\n"
    title, youtube_source, facebook_caption, instagram_caption, has_platform_sections = (
        platform_content_from_txt(raw_text, stem, route)
    )
    youtube_description = youtube_safe_description(
        youtube_source, append_store_link=not has_platform_sections
    )
    if base_route == "toonzone":
        cartoon_copy = toonzone_metadata(stem)
        title = cartoon_copy["title"]
        facebook_caption = cartoon_copy["description"]
        instagram_caption = cartoon_copy["description"]
        has_platform_sections = True
    # Kaynak video doğrudan yayınlanır; kullanıcı isteği gereği yeniden encode edilmez.
    final_video = raw
    if base_route == "toonzone":
        cover_path = safe_temp_path(temp, "toonzone-cover", route, toonzone_cover["id"], ".png")
        cover_path.write_bytes(toonzone_cover_bytes)
        final_video = create_instagram_cover_video(
            raw, cover_path, safe_temp_path(temp, "toonzone-video", route, video_obj["id"], ".mp4")
        )
        print(f"ToonZone kapak karesi videoya eklendi: {toonzone_cover['name']}.", flush=True)
    results, errors = {}, {}
    required = []
    jobs = {}
    force_platform = os.environ.get("FORCE_PLATFORM", "").strip().lower()
    page_cache = {}

    def get_page(*names):
        cache_key = tuple(names)
        if cache_key not in page_cache:
            page_cache[cache_key] = meta_page(*names)
        return page_cache[cache_key]

    if toonzone_page is not None:
        page_cache[("ToonZone",)] = toonzone_page

    def add_job(key, platform, callback):
        if requested_platform(force_platform, platform) and platform_allowed(base_route, platform):
            required.append(key)
            jobs[key] = callback

    def upload_ig(*page_names, publish=True):
        instagram_source = final_video if base_route == "toonzone" else raw
        instagram_video = prepare_instagram_upload(
            instagram_source,
            safe_temp_path(temp, "instagram", route, video_obj["id"], ".mp4"),
            prefer_remux=(base_route == "film"),
            film_compact=(base_route in ("film", "gonle")),
            toonzone_compact=(base_route == "toonzone"),
        )
        return upload_instagram_reel(
            get_page(*page_names), str(instagram_video), instagram_caption,
            append_store_link=not has_platform_sections,
            publish=publish,
        )

    if route == "gonle_fb":
        add_job("fb", "facebook", lambda: upload_facebook_reel(get_page("Gönle Düşen"), str(final_video), facebook_caption))
    elif route == "gonle_ig":
        add_job("ig", "instagram", lambda: upload_ig("Gönle Düşen"))
    elif route == "tarladaki_ig":
        add_job("ig", "instagram", lambda: upload_ig("Tarladaki Fasulye"))
    elif route == "penguen_ig":
        add_job("ig", "instagram", lambda: upload_ig("Beyinsiz Penguen"))
    elif route == "tarladaki":
        def upload_tarladaki_youtube():
            yt = get_youtube_client("TOKEN_CHANNEL1_JSON", "token_channel1.json")
            vid, _ = upload_youtube_shorts(yt, str(final_video), title, youtube_description, YOUTUBE_TAGS)
            apply_youtube_fixed_cover(drive, yt, "tarladaki", folder_id, vid, temp)
            return f"https://youtube.com/shorts/{vid}"
        add_job("yt1", "youtube", upload_tarladaki_youtube)
        add_job("fb", "facebook", lambda: upload_facebook_reel(get_page("Tarladaki Fasulye"), str(final_video), facebook_caption))
        add_job("ig", "instagram", lambda: upload_ig("Tarladaki Fasulye"))
    elif route == "penguen":
        def upload_penguen_youtube():
            yt = get_youtube_client("TOKEN_CHANNEL2_JSON", "token_channel2.json")
            vid, _ = upload_youtube_shorts(yt, str(final_video), title, youtube_description, YOUTUBE_TAGS)
            apply_youtube_fixed_cover(drive, yt, "penguen", folder_id, vid, temp)
            return f"https://youtube.com/shorts/{vid}"
        add_job("yt2", "youtube", upload_penguen_youtube)
        add_job("fb", "facebook", lambda: upload_facebook_reel(get_page("Beyinsiz Penguen"), str(final_video), facebook_caption))
        add_job("ig", "instagram", lambda: upload_ig("Beyinsiz Penguen"))
        if os.getenv("ENABLE_PENGUEN_THREADS", "false").strip().lower() == "true":
            if threads_configured():
                def upload_penguen_threads():
                    video_url = build_threads_video_url(
                        os.environ["PENGUEN_THREADS_VIDEO_URL_TEMPLATE"],
                        video_obj["id"], video_obj.get("name", ""),
                    )
                    return publish_threads_video(video_url, facebook_caption)
                add_job("threads", "threads", upload_penguen_threads)
            else:
                print(
                    "Penguen Threads atlandı: token, doğrulanmış kullanıcı adı ve herkese açık video URL şablonu gerekli.",
                    flush=True,
                )
    elif route == "daily_laugh":
        add_job("fb", "facebook", lambda: upload_facebook_reel(get_page("Daily Laugh Lab"), str(final_video), facebook_caption))
        if os.getenv("ENABLE_NEW_YOUTUBE_ROUTES", "false").lower() == "true":
            def upload_daily_youtube():
                yt = get_youtube_client("TOKEN_DAILY_LAUGH_LAB_JSON", "token_daily_laugh_lab.json", scopes=SCOPES_YOUTUBE_CHANNEL_READ)
                items = yt.channels().list(part="id", mine=True).execute().get("items", [])
                if len(items) != 1 or items[0].get("id") != "UCF4KwI3alXzlExviMFmmJAA":
                    raise RuntimeError("YouTube OAuth kanalı beklenen Daily Laugh Lab kanalına ait değil")
                vid, _ = upload_youtube_shorts(yt, str(final_video), title, youtube_description, YOUTUBE_TAGS)
                return f"https://youtube.com/shorts/{vid}"
            add_job("yt_daily", "youtube", upload_daily_youtube)
        if new_meta_route_enabled("daily_laugh_instagram"):
            add_job("ig", "instagram", lambda: upload_ig("Daily Laugh Lab"))
    elif route == "gonle":
        add_job("fb", "facebook", lambda: upload_facebook_reel(get_page("Gönle Düşen"), str(final_video), facebook_caption))
        if os.getenv("ENABLE_GONLE_INSTAGRAM_ROUTES", "false").lower() == "true":
            add_job("ig", "instagram", lambda: upload_ig("Gönle Düşen"))
        if os.getenv("ENABLE_NEW_YOUTUBE_ROUTES", "false").lower() == "true":
            def upload_gonle_youtube():
                yt = get_youtube_client("TOKEN_GONLE_DUSEN_JSON", "token_gonle_dusen.json", scopes=SCOPES_YOUTUBE_CHANNEL_READ)
                items = yt.channels().list(part="id", mine=True).execute().get("items", [])
                if len(items) != 1 or items[0].get("id") != "UCvSvo5WghuXqsjwLRmIz22g":
                    raise RuntimeError("YouTube OAuth kanalı beklenen Gönle Düşen kanalına ait değil")
                vid, _ = upload_youtube_shorts(yt, str(final_video), title, youtube_description, YOUTUBE_TAGS)
                return f"https://youtube.com/shorts/{vid}"
            add_job("yt_gonle", "youtube", upload_gonle_youtube)
    elif route == "film":
        if os.getenv("TOKEN_FILM_YOUTUBE_JSON", "").strip():
            def upload_film_youtube():
                yt = get_youtube_client("TOKEN_FILM_YOUTUBE_JSON", "token_film.json", scopes=SCOPES_YOUTUBE_CHANNEL_READ)
                vid, _ = upload_youtube_shorts(yt, str(final_video), title, youtube_description, YOUTUBE_TAGS)
                return f"https://youtube.com/shorts/{vid}"
            add_job("yt_film", "youtube", upload_film_youtube)
        else:
            print("Film YouTube atlandı: TOKEN_FILM_YOUTUBE_JSON tanımlı değil.", flush=True)
        add_job("fb_film_1", "facebook", lambda: upload_facebook_reel(get_page("Film Mağarası"), str(final_video), facebook_caption))
        add_job("fb_film_2", "facebook", lambda: upload_facebook_reel(get_page("Filmmagrasi"), str(final_video), facebook_caption))
        add_job("ig", "instagram", lambda: upload_ig("Film Mağarası"))
    elif route == "toonzone":
        add_job("fb", "facebook", lambda: upload_facebook_reel(get_page("ToonZone"), str(final_video), facebook_caption))
        add_job("ig", "instagram", lambda: upload_ig("ToonZone"))
    elif route in ("gonle_youtube", "daily_laugh_youtube"):
        is_gonle = route == "gonle_youtube"
        env_name = "TOKEN_GONLE_DUSEN_JSON" if is_gonle else "TOKEN_DAILY_LAUGH_LAB_JSON"
        fallback = "token_gonle_dusen.json" if is_gonle else "token_daily_laugh_lab.json"
        expected_channel = "UCvSvo5WghuXqsjwLRmIz22g" if is_gonle else "UCF4KwI3alXzlExviMFmmJAA"
        result_key = "yt_gonle" if is_gonle else "yt_daily"
        def upload_new_channel_youtube():
            yt = get_youtube_client(env_name, fallback, scopes=SCOPES_YOUTUBE_CHANNEL_READ)
            channel_items = yt.channels().list(part="id", mine=True).execute().get("items", [])
            if len(channel_items) != 1 or channel_items[0].get("id") != expected_channel:
                raise RuntimeError("YouTube OAuth kanalı beklenen kanal ID'siyle eşleşmiyor")
            vid, _ = upload_youtube_shorts(yt, str(final_video), title, youtube_description, YOUTUBE_TAGS)
            return f"https://youtube.com/shorts/{vid}"
        add_job(result_key, "youtube", upload_new_channel_youtube)
    else:
        add_job("fb", "facebook", lambda: upload_facebook_reel(get_page(route), str(final_video), facebook_caption))

    if not required:
        raise RuntimeError(f"Geçersiz veya bu rota için desteklenmeyen FORCE_PLATFORM: {force_platform}")

    if upload_only:
        if route != "film" or required != ["ig"]:
            raise RuntimeError("Upload-only güvenlik kilidi: yalnızca Film Instagram kabul edilir.")
        diagnostic_source = raw
        diagnostic_clip = None
        diagnostic_remuxed = None
        try:
            log_media_diagnostics("Film kaynak MP4", raw)
            check_full_decode(raw)
            print(f"Film IG kaynak tam-decode kontrolü geçti: {stem}; Drive {video_obj['id']}.", flush=True)
            if diagnostic_remux:
                diagnostic_remuxed = safe_temp_path(
                    temp, "film-ig-diagnostic-remux", route, video_obj["id"], ".mp4"
                )
                diagnostic_source = remux_mp4_faststart(raw, diagnostic_remuxed)
                print(
                    f"Film IG yeniden kodlamasız tam tanı dosyası hazır: stem={stem}; "
                    f"bytes={diagnostic_source.stat().st_size}.", flush=True,
                )
            elif diagnostic_clip_seconds:
                diagnostic_clip = safe_temp_path(
                    temp, "film-ig-diagnostic", route, video_obj["id"], ".mp4"
                )
                diagnostic_source = create_diagnostic_clip(
                    raw, diagnostic_clip, diagnostic_clip_seconds
                )
                print(
                    f"Film IG tanı klibi hazır: stem={stem}; seconds={diagnostic_clip_seconds}; "
                    f"bytes={diagnostic_source.stat().st_size}.",
                    flush=True,
                )
            prepared = prepare_instagram_upload(
                diagnostic_source,
                safe_temp_path(temp, "film-ig-upload-only", route, video_obj["id"], ".mp4"),
                prefer_remux=True,
                film_compact=film_compact_test,
            )
            result = upload_instagram_reel(
                get_page("Film Mağarası"), str(prepared), instagram_caption,
                append_store_link=not has_platform_sections, publish=False,
            )
            print(
                f"Film IG upload-only sonucu: {stem}; Drive {video_obj['id']}; "
                f"container={result['container_id']}; status={result['status']}; "
                "published=false; Drive/D1 kuyruğu değiştirilmedi.",
                flush=True,
            )
            return
        finally:
            if diagnostic_clip:
                diagnostic_clip.unlink(missing_ok=True)
            if diagnostic_remuxed:
                diagnostic_remuxed.unlink(missing_ok=True)

    properties = video_obj.setdefault("appProperties", {})
    account = {"tarladaki":"tarladaki","penguen":"penguen","gonle":"gonle","daily_laugh":"daily_laugh"}.get(base_route, base_route)
    platform_names = {"yt1":"youtube","yt2":"youtube","yt_gonle":"youtube","yt_daily":"youtube","yt_film":"youtube","fb":"facebook","fb_film_1":"facebook","fb_film_2":"facebook","ig":"instagram","threads":"threads"}
    batch_gates = {key: gate for key in required
                   for gate in [BatchGate(account, platform_names[key], video_obj["id"], folder_id)]
                   if gate.enabled}
    results, errors = execute_platform_jobs(
        drive, video_obj, slot, required, jobs, properties,
        batch_gates=batch_gates, account=account,
    )
    for key, value in results.items():
        print(f"{slot} | {stem} | Drive {video_obj['id']} | {key} başarıyla gönderildi: {value}", flush=True)
    for key, value in errors.items():
        print(f"{slot} | {stem} | {key} yayın hatası: {sanitize_error(value)}", flush=True)

    if not errors:
        drive.files().update(
            fileId=video_obj["id"],
            body={"appProperties": {
                used_key: "1",
                LAST_SLOT: slot,
                FAILED_SLOT: None,
                CLAIM_SLOT: None,
                CLAIMED_AT: None,
            }},
        ).execute()
    if errors:
        fingerprint = hashlib.sha256(json.dumps(
            sorted((key, sanitize_error(value)) for key, value in errors.items()),
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        already_notified = (
            properties.get(NOTIFIED_ERROR_SLOT) == slot
            and properties.get(NOTIFIED_ERROR_HASH) == fingerprint
        )
        if not already_notified and notify(route, slot, stem, results, errors,
                                           drive=drive, folder_id=folder_id):
            drive.files().update(
                fileId=video_obj["id"], body={"appProperties": {
                    NOTIFIED_SLOT: slot,
                    NOTIFIED_ERROR_SLOT: slot,
                    NOTIFIED_ERROR_HASH: fingerprint,
                }}
            ).execute()
            properties[NOTIFIED_SLOT] = slot
            properties[NOTIFIED_ERROR_SLOT] = slot
            properties[NOTIFIED_ERROR_HASH] = fingerprint
    else:
        had_notified_error = properties.get(NOTIFIED_ERROR_SLOT) == slot
        resolved_sent = not had_notified_error or notify(
            route, slot, stem, results, {}, drive=drive, folder_id=folder_id, resolved=True,
        )
        if had_notified_error and resolved_sent:
            drive.files().update(
                fileId=video_obj["id"], body={"appProperties": {
                    NOTIFIED_ERROR_SLOT: None, NOTIFIED_ERROR_HASH: None,
                }}
            ).execute()
            properties[NOTIFIED_ERROR_SLOT] = None
            properties[NOTIFIED_ERROR_HASH] = None
        if deferred_successes is not None:
            deferred_successes.append({
                "route": route, "slot": slot, "stem": stem,
                "results": dict(results), "file_id": video_obj["id"],
                "already_notified": properties.get(NOTIFIED_SLOT) == slot,
            })
        elif properties.get(NOTIFIED_SLOT) != slot and notify(
            route, slot, stem, results, errors, drive=drive, folder_id=folder_id,
        ):
            drive.files().update(
                fileId=video_obj["id"], body={"appProperties": {NOTIFIED_SLOT: slot}}
            ).execute()
            properties[NOTIFIED_SLOT] = slot
    if errors:
        failure = RuntimeError(sanitize_error(" / ".join(f"{key}: {value}" for key, value in errors.items())))
        # The route-level notification was sent or deliberately deduplicated above.
        failure._ntfy_notification_handled = True
        raise failure


def _is_upload_only_test():
    return any(os.environ.get(name, "false").strip().lower() == "true" for name in (
        "FILM_IG_UPLOAD_ONLY", "TOONZONE_IG_UPLOAD_ONLY", "FILM_IG_COMPACT_TEST",
        "GONLE_IG_CONTROLLED_TEST", "FILM_IG_TEST_BATCH",
    ))


def run(drive=None, selected=None, routing_validated=False, deferred_successes=None):
    """Run one slot and notify on pre-platform/pipeline failures too."""
    try:
        return _run_impl(
            drive=drive, selected=selected, routing_validated=routing_validated,
            deferred_successes=deferred_successes,
        )
    except Exception as exc:
        if not getattr(exc, "_ntfy_notification_handled", False) and not _is_upload_only_test():
            route, slot = selected or route_for_time()
            route = route or os.environ.get("FORCE_ROUTE", "sistem") or "sistem"
            slot = slot or f"manual-{datetime.now(TZ):%Y-%m-%d-%H%M}-{route}"
            notify(route, slot, "Yayın ön kontrolü / işlem aşaması", {},
                   {"işlem": sanitize_error(exc)}, drive=drive)
            try:
                exc._ntfy_notification_handled = True
            except Exception:
                pass
        raise


def run_due(max_slots=DEFAULT_MAX_DUE_SLOTS, allowed_routes=None, quarantine_shared_claims=True):
    """Bir bulut çalışmasında birikmiş slotları sırayla tamamlar."""
    drive = get_drive_client()
    validate_drive_routing(drive)
    if quarantine_shared_claims:
        quarantine_legacy_shared_claims(drive)
    attempted = set()
    handled_routes = set()
    failures = []
    deferred_successes = []
    max_slots = configured_max_due_slots(max_slots)
    # A blocked Film/ToonZone claim must not consume a healthy account's
    # publication allowance. Try each route at most once, while still
    # permitting at most max_slots successful route executions per run.
    route_attempt_cap = len(allowed_routes) if allowed_routes is not None else 6
    successful_routes = 0
    for _ in range(route_attempt_cap):
        if successful_routes >= max_slots:
            break
        selected = next_due_route(
            drive, excluded_slots=attempted, allowed_routes=allowed_routes,
            excluded_routes=handled_routes,
        )
        if selected == (None, None):
            break
        route, slot = selected
        attempted.add(slot)
        # One slot per route in a single invocation prevents a long backlog
        # for one account from consuming the whole bounded batch.
        handled_routes.add(route)
        try:
            run(drive=drive, selected=selected, routing_validated=True,
                deferred_successes=deferred_successes)
            successful_routes += 1
        except Exception as exc:
            failures.append(f"{slot}: {sanitize_error(exc)}")
            print(f"{slot}: yayın hatası: {sanitize_error(exc)}", flush=True)
    grouped = {}
    for item in deferred_successes:
        if not item["already_notified"]:
            grouped.setdefault(item["route"], []).append(item)
    for route, items in grouped.items():
        if notify(route, items[-1]["slot"], "", {}, {}, drive=drive,
                  grouped_items=items):
            for item in items:
                drive.files().update(
                    fileId=item["file_id"],
                    body={"appProperties": {NOTIFIED_SLOT: item["slot"]}},
                ).execute()
    print(f"Bu turda denenen slot: {len(attempted)}; hata: {len(failures)}", flush=True)
    if failures:
        raise RuntimeError("Tamamlanamayan yayınlar: " + " / ".join(failures))


def audit_routing_only():
    """Read-only production routing check; never selects or publishes media."""
    drive = get_drive_client()
    validate_drive_routing(drive)
    for page_name in (
        "Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen", "Daily Laugh Lab",
        "Film Mağarası", "Filmmagrasi", "ToonZone",
    ):
        meta_page(page_name)
        print(f"Hesap yönlendirmesi doğrulandı: {page_name}", flush=True)
    toonzone_assets = validate_toonzone_starting_episode(drive)
    print(f"ToonZone içerik/kapak ön kontrolü: {toonzone_assets}", flush=True)
    print("Drive yönlendirmeleri doğrulandı: Ortak Mizah, İslam, İngilizce Mizah", flush=True)


if __name__ == "__main__":
    if os.environ.get("ROUTING_AUDIT_ONLY", "").strip().lower() == "true":
        audit_routing_only()
    elif os.environ.get("FORCE_ROUTE", "").strip():
        run()
    elif (
        os.environ.get("TP_NORMAL_AUTOMATION_ONLY", "false").lower() == "true"
        or os.environ.get("DG_NORMAL_AUTOMATION_ONLY", "false").lower() == "true"
    ):
        # Current-slot mode keeps all normal routes out of the 24-hour
        # backfill path. Each channel remains independently gated.
        allowed = set()
        if os.environ.get("TP_NORMAL_AUTOMATION_ONLY", "false").lower() == "true":
            allowed.update({"tarladaki", "penguen"})
        if os.environ.get("DG_NORMAL_AUTOMATION_ONLY", "false").lower() == "true":
            allowed.update({"daily_laugh", "gonle"})
        if os.environ.get("ENABLE_FILM_ROUTES", "false").lower() == "true":
            allowed.add("film")
        if os.environ.get("ENABLE_TOONZONE_ROUTES", "false").lower() == "true":
            allowed.add("toonzone")
        # Recover slots missed by delayed/dropped schedule events. The due-slot
        # ledger is idempotent and bounded to the previous 24 hours; keep the
        # recovery restricted to normal automation routes and do not run the
        # legacy claim-quarantine write during this catch-up path.
        run_due(
            max_slots=configured_max_due_slots(),
            allowed_routes=allowed,
            quarantine_shared_claims=False,
        )
    else:
        run_due(max_slots=configured_max_due_slots())
