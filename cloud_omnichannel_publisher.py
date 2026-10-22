import os
import io
import hashlib
import re
import json
import time
import random
import requests
import subprocess
import tempfile
from urllib.parse import urlsplit
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from ntfy_notifications import send_ntfy

SCOPES_YOUTUBE = ["https://www.googleapis.com/auth/youtube.upload"]
SCOPES_YOUTUBE_CHANNEL_READ = [
    *SCOPES_YOUTUBE,
    "https://www.googleapis.com/auth/youtube.readonly",
]
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]

TARGET_META_ACCOUNT = "Tarladaki Fasulye"
ETSY_LINK = "https://www.etsy.com/shop/MiroviaStudio?ref=dashboard-header"
NTFY_SERVER = "https://ntfy.sh"
TURKEY_TIMEZONE = ZoneInfo("Europe/Istanbul")
PUBLISH_HOURS = (9, 11, 13, 15, 17, 19, 21)
# GitHub runner gecikebilir. Aynı saat içindeki her 10 dakikalık kontrol,
# o saat için güvenli tekrar denemesidir; ilk başarılı işlem slotu kilitler.
SLOT_GRACE_MINUTES = 60
SCHEDULE_SLOT_PROPERTY = "scheduled_publish_slot"
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v24.0")
REQUIRED_INSTAGRAM_PAGES = {"Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen", "Film Mağarası", "ToonZone"}
META_PAGE_ID_BY_NAME = {
    "film mağarası": "1239298989276639",
    "film mağrası": "1239298989276639",
    "filmmagrasi": "854990964375370",
    "filmmağrası1": "854990964375370",
    "toonzone": "1298191963387372",
}


class MetaAPIError(RuntimeError):
    """Sanitized Meta failure with machine-readable retry information."""

    def __init__(self, stage, http_status, *, message, error_type=None, code=None,
                 subcode=None, user_title=None, user_message=None,
                 debug_type=None, debug_message=None, retriable=None,
                 response_headers=None, is_transient=None,
                 error_data=None, debug_info=None, upload_bytes=None,
                 uploaded_bytes=None):
        self.stage = stage
        self.http_status = http_status
        self.error_type = error_type
        self.code = code
        self.subcode = subcode
        self.retriable = retriable
        self.is_transient = is_transient
        self.upload_bytes = upload_bytes
        self.uploaded_bytes = uploaded_bytes
        self.error_data = error_data
        self.debug_info = debug_info
        details = [f"aşama={stage}", f"HTTP={http_status}"]
        if error_type:
            details.append(f"tür={_sanitize_meta_text(error_type)[:80]}")
        if code is not None:
            details.append(f"kod={code}")
        if subcode is not None:
            details.append(f"alt_kod={subcode}")
        if user_title:
            details.append(f"başlık={_sanitize_meta_text(user_title)[:120]}")
        if user_message:
            details.append(f"kullanıcı_mesajı={_sanitize_meta_text(user_message)[:200]}")
        if debug_type:
            details.append(f"işleme_türü={_sanitize_meta_text(debug_type)[:80]}")
        if debug_message:
            details.append(f"işleme_mesajı={_sanitize_meta_text(debug_message)[:200]}")
        safe_diag = {}
        for source_name, source in (("error_data", error_data), ("debug_info", debug_info)):
            if isinstance(source, dict):
                safe_diag[source_name] = {
                    key: value for key, value in source.items()
                    if key in {"message", "type", "code", "error_subcode", "fbtrace_id", "is_transient", "is_retriable", "retriable"}
                    and isinstance(value, (str, int, float, bool))
                }
        if safe_diag:
            details.append("tanı=" + _sanitize_meta_text(json.dumps(safe_diag, ensure_ascii=False, separators=(",", ":")))[:500])
        if retriable is not None:
            details.append(f"yeniden_denenebilir={bool(retriable)}")
        if is_transient is not None:
            details.append(f"geçici={bool(is_transient)}")
        if upload_bytes is not None and uploaded_bytes is not None:
            details.append(f"aktarilan_bayt={uploaded_bytes}/{upload_bytes}")
        for header in ("x-fb-trace-id", "x-fb-request-id", "x-fb-rev", "retry-after"):
            value = (response_headers or {}).get(header)
            if value:
                details.append(f"{header}={_sanitize_meta_text(value)[:120]}")
        safe_message = _sanitize_meta_text(message)
        super().__init__(f"Meta API hatası: {safe_message[:300]} ({', '.join(details)})")


def _sanitize_meta_text(value):
    """Mask credentials and signed URLs before any API error reaches logs."""
    value = str(value or "")
    value = re.sub(r"https?://[^\s\"'<>]+", "[masked-url]", value, flags=re.IGNORECASE)
    value = re.sub(r"(?i)(access_token|authorization|appsecret_proof|client_secret)(\s*[=:]\s*)[^\s,;&]+", r"\1\2[masked]", value)
    value = re.sub(r"\bEA[A-Za-z0-9_-]{20,}\b", "[masked-token]", value)
    for name, secret in sorted(os.environ.items(), key=lambda pair: len(pair[1]), reverse=True):
        if secret and any(marker in name.upper() for marker in ("TOKEN", "SECRET", "AUTH_JSON")):
            value = value.replace(secret, "[masked-secret]")
    return value.replace("\n", " ").replace("\r", " ")


def _decode_upload_error(payload):
    """Normalize direct and JSON-string nested Meta upload diagnostics."""
    error = payload.get("error") or {}
    if not isinstance(error, dict):
        error = {}
    debug = payload.get("debug_info") or error.get("debug_info") or {}
    if not isinstance(debug, dict):
        debug = {}
    message = error.get("message") or payload.get("message") or debug.get("message") or "video yüklemesi reddedildi"
    nested = None
    if isinstance(message, str) and message.lstrip().startswith("{"):
        try:
            nested = json.loads(message)
        except ValueError:
            nested = None
    if isinstance(nested, dict):
        error = nested.get("error", nested)
        if not isinstance(error, dict):
            error = {}
        debug = nested.get("debug_info") or error.get("debug_info") or debug
        if not isinstance(debug, dict):
            debug = {}
        message = error.get("message") or debug.get("message") or payload.get("message") or "video yüklemesi reddedildi"
    data = error.get("error_data") or payload.get("error_data") or {}
    if not isinstance(data, dict):
        data = {}
    debug = {**data, **debug}
    return error, debug, message


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as media:
        for block in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _graph_json(response, stage="Graph API"):
    """Return Graph JSON or raise an error that never includes credentials."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not response.ok or payload.get("error"):
        error, debug, message = _decode_upload_error(payload)
        fallback = _sanitize_meta_text(getattr(response, "text", ""))[:300]
        if not payload.get("error") and fallback:
            message = fallback
        message = message or f"HTTP {response.status_code}"
        headers = {key.lower(): value for key, value in getattr(response, "headers", {}).items()
                   if key.lower() in {"x-fb-trace-id", "x-fb-request-id", "x-fb-rev", "retry-after"}}
        trace_id = error.get("fbtrace_id") or debug.get("fbtrace_id")
        if trace_id and "x-fb-trace-id" not in headers:
            headers["x-fb-trace-id"] = trace_id
        raise MetaAPIError(
            stage,
            response.status_code,
            message=message,
            error_type=error.get("type") or debug.get("type"),
            code=error.get("code") or payload.get("code"),
            subcode=error.get("error_subcode") or payload.get("error_subcode"),
            user_title=error.get("error_user_title"),
            user_message=error.get("error_user_msg"),
            debug_type=debug.get("type"), debug_message=debug.get("message"),
            retriable=debug.get("is_retriable", debug.get("retriable")),
            is_transient=error.get("is_transient"), response_headers=headers,
            error_data=error.get("error_data"), debug_info=debug,
        )
    return payload

# --- KOMEDİ / MİZAH / DARK MİZAH ETİKET HAVUZU ---
MAX_HASHTAGS = (
    "#mizah #komedi #darkmizah #komik #caps #eğlence #kahkaha "
    "#komikvideolar #mizahtürkiye #kesfet #keşfet #keşfetteyiz "
    "#reels #shorts #fyp #viral #trend #tiktokkomik #trendler "
    "#komikkesitler #gülmekgaranti #komikpaylaşımlar #vine #mizahtr "
    "#darkhumor #karamizah #capsler #güldürü"
)

YOUTUBE_TAGS = [
    "mizah", "komedi", "dark mizah", "kara mizah", "komik videolar",
    "komik", "eğlence", "kahkaha", "gülmek garanti", "caps",
    "mizah türkiye", "shorts", "reels", "tiktok komik", "kesitler",
    "komik anlar", "viral", "trend", "keşfet", "fyp", "vine türkiye",
    "komik montaj", "güldüren videolar", "türkçe mizah", "en komik"
]


def current_publish_slot(now: datetime | None = None) -> str | None:
    """Uygun yayın penceresindeysek yerel tarih+saat slotunu döndürür.

    Her 10 dakikada bir tetiklenme güvenlidir: seçili saatin tamamı o
    saat için güvenli yeniden deneme penceresidir. İlk işlenen video slotu
    kilitler. `None`, bu çalışmanın yayın yapmaması gerektiği anlamına gelir.
    """
    if now is None:
        now = datetime.now(TURKEY_TIMEZONE)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=TURKEY_TIMEZONE)
    else:
        now = now.astimezone(TURKEY_TIMEZONE)

    if now.hour not in PUBLISH_HOURS or now.minute >= SLOT_GRACE_MINUTES:
        return None
    return now.strftime("%Y-%m-%d-%H")


def slot_already_processed(files: list[dict], slot: str) -> bool:
    """Bu slotta herhangi bir video tamamlandıysa yeni paylaşımı engeller."""
    return any(
        (item.get("appProperties") or {}).get(SCHEDULE_SLOT_PROPERTY) == slot
        for item in files
        if item.get("name", "").lower().endswith(".mp4")
    )

VIRAL_HOOKS = [
    "Bunu beklemiyordum, sonuna kadar izleyin 😂💀",
    "Gülme krizine sokan o anlar 🤣 Sizce kim haklı?",
    "Yok artık dedirten cinsten bir olay 💀 Arkadaşına gönder!",
    "Günün en komik kesiti net bu 😂 Ne düşünüyorsunuz?",
    "Sonunda patladım resmen 🤣 Kaydetmeyi unutma!",
    "Böyle bir şey yaşandı mı gerçekten ya 💀😂",
    "İzlerken kahkaha attım resmen 🤣 Yorumlara bekliyorum!",
    "Beklenmedik son 😂 Kaç kere izledim sayamadım!",
    "Günün enerjisini yükselten video 🤣 #keşfet",
    "Tam o an... Hayat durdu resmen 😂💀",
    "Bunu görmesi gereken arkadaşını yoruma etiketle 🤣",
    "Siz olsaydınız ne yapardınız? 😂 Yorumlarda buluşalım!",
    "Günün dark mizah dozu 💀 İzlemeden geçmeyin!",
    "Beyin yakan cinsten anlar 😂 Arkadaşını etiketle!",
    "Kahkaha garantili video 🤣 Takip etmeyi unutmayın!"
]

def get_drive_client():
    token_str = os.environ.get("DRIVE_TOKEN_JSON")
    if token_str:
        data = json.loads(token_str)
    else:
        token_path = Path(__file__).resolve().parent / "drive_token.json"
        data = json.loads(token_path.read_text(encoding="utf-8"))

    creds = Credentials.from_authorized_user_info(data, SCOPES_DRIVE)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)

def get_youtube_client(env_var_name, fallback_file, scopes=None):
    token_str = os.environ.get(env_var_name)
    if token_str:
        data = json.loads(token_str)
    else:
        token_path = Path(__file__).resolve().parent / fallback_file
        data = json.loads(token_path.read_text(encoding="utf-8"))

    creds = Credentials.from_authorized_user_info(data, scopes or SCOPES_YOUTUBE)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

def get_meta_auth():
    auth_str = os.environ.get("META_AUTH_JSON")
    if auth_str:
        return json.loads(auth_str)
    auth_path = Path(__file__).resolve().parent / "meta_auth.json"
    return json.loads(auth_path.read_text(encoding="utf-8"))

def get_meta_page_info(target_name=TARGET_META_ACCOUNT):
    # The saved page IDs are the allowlist. Display-name matching alone is not
    # sufficient because pages can be renamed or similarly named.
    auth = get_meta_auth()
    expected_page_id = META_PAGE_ID_BY_NAME.get(target_name.strip().casefold())
    configured = next(
        (p for p in auth.get("pages", []) if expected_page_id and str(p.get("page_id")) == expected_page_id),
        None,
    )
    if configured is None:
        configured = next(
            (p for p in auth.get("pages", []) if p.get("page_name", "").casefold() == target_name.casefold()),
            None,
        )
    if not configured or not configured.get("page_id") or not configured.get("page_token"):
        raise RuntimeError(f"META_AUTH_JSON içinde tam hesap kimliği bulunamadı: {target_name}")
    expected_page_id = str(expected_page_id or configured["page_id"])
    expected_instagram_id = str(configured.get("instagram_id") or "")
    if target_name in REQUIRED_INSTAGRAM_PAGES and not expected_instagram_id:
        raise RuntimeError(f"META_AUTH_JSON içinde onaylı Instagram kimliği eksik: {target_name}")

    user_token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if user_token:
        try:
            live_page = None
            after = None
            for _ in range(30):
                params = {
                    "fields": "id,name,access_token,instagram_business_account{id,username}",
                    "limit": 100,
                    "access_token": user_token,
                }
                if after:
                    params["after"] = after
                response = requests.get(
                    f"https://graph.facebook.com/{GRAPH_API_VERSION}/me/accounts",
                    params=params, timeout=20,
                )
                response.raise_for_status()
                body = response.json()
                live_page = next(
                    (p for p in body.get("data", [])
                     if (str(p.get("id")) == expected_page_id if META_PAGE_ID_BY_NAME.get(target_name.strip().casefold())
                         else p.get("name", "").casefold() == target_name.casefold())),
                    None,
                )
                if live_page:
                    break
                paging = body.get("paging", {})
                if not paging.get("next"):
                    break
                after = paging.get("cursors", {}).get("after")
                if not after:
                    break
            if not live_page:
                raise RuntimeError(f"Meta sayfa kimliği erişilebilir hesaplarda bulunamadı: {expected_page_id}")
            instagram = live_page.get("instagram_business_account") or {}
            if str(live_page.get("id")) != expected_page_id:
                raise RuntimeError(f"Meta sayfa kimliği onaylı hesapla eşleşmiyor: {target_name}")
            if expected_instagram_id and str(instagram.get("id") or "") != expected_instagram_id:
                raise RuntimeError(f"Instagram hesap kimliği onaylı hesapla eşleşmiyor: {target_name}")
            return {
                "page_id": live_page["id"],
                "page_name": live_page["name"],
                "page_token": live_page["access_token"],
                "instagram_id": instagram.get("id"),
                "instagram_username": instagram.get("username"),
            }
        except requests.RequestException as exc:
            print(f"Meta kullanıcı tokenı kullanılamadı; onaylı sayfa kimliği doğrudan doğrulanıyor: {type(exc).__name__}")

    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{expected_page_id}",
        params={
            "fields": "id,name,instagram_business_account{id,username}",
            "access_token": configured["page_token"],
        },
        timeout=20,
    )
    response.raise_for_status()
    live_page = response.json()
    instagram = live_page.get("instagram_business_account") or {}
    if str(live_page.get("id")) != expected_page_id or (
        not META_PAGE_ID_BY_NAME.get(target_name.strip().casefold())
        and live_page.get("name", "").casefold() != target_name.casefold()
    ):
        raise RuntimeError(f"Meta sayfa kimliği/adı onaylı hesapla eşleşmiyor: {target_name}")
    if expected_instagram_id and str(instagram.get("id") or "") != expected_instagram_id:
        raise RuntimeError(f"Instagram hesap kimliği onaylı hesapla eşleşmiyor: {target_name}")
    return {
        **configured,
        "page_name": live_page["name"],
        "instagram_id": instagram.get("id"),
        "instagram_username": instagram.get("username"),
    }

def send_ntfy_summary(selected_stem: str, results: dict, errors: dict, target_tasks: dict):
    """Yayın turu tamamlanınca telefona tek bir özet bildirimi yollar."""
    if not os.environ.get("NTFY_TOPIC_URL", "").strip() and not os.environ.get("NTFY_TOPIC", "").strip():
        print("ℹ️ ntfy bildirimi atlandı: NTFY_TOPIC_URL tanımlı değil.")
        return

    rows = [
        ("Tarladaki Fasulye", "YouTube", "yt1", target_tasks["youtube"]),
        ("Beyinsiz Penguen", "YouTube", "yt2", target_tasks["youtube"]),
        ("Tarladaki Fasulye", "Facebook", "fb", target_tasks["meta"]),
        ("Tarladaki Fasulye", "Instagram", "ig", target_tasks["meta"]),
    ]
    lines = [
        f"İçerik: {selected_stem}",
        "Hesap                  Platform    Durum",
        "------------------------------------------",
    ]
    any_error = False
    for account, platform, key, attempted in rows:
        if not attempted:
            status = "Atlandı"
        elif key in results:
            status = "✅ Başarılı"
        else:
            status = "❌ Hata"
            any_error = True
        lines.append(f"{account[:22]:<22} {platform:<11} {status}")
        if key in errors:
            lines.append(f"  ↳ {errors[key][:120]}")

    try:
        send_ntfy("⚠️ Yayın hatası" if any_error else "✅ Yayın özeti",
                  "\n".join(lines), priority=4 if any_error else 3,
                  tags=["warning"] if any_error else ["white_check_mark"])
        print("📱 ntfy yayın özeti gönderildi.")
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        safe = f"{type(exc).__name__}" + (f" HTTP {status}" if status is not None else "")
        print(f"⚠️ ntfy bildirimi gönderilemedi: {safe}")

def build_post_content(raw_text: str):
    """
    Kullanıcının kesin kuralı:
    1. İlk başta: Orijinal metin / Japonca yazı neyse birebir o.
    2. Hemen altında: Komedi / Dark Mizah etiketleri.
    3. En aşağıda: Etsy linki.
    """
    original_text = raw_text.strip()

    # YouTube için başlık: Orijinal metnin ilk satırı
    first_line = original_text.splitlines()[0].strip() if original_text else "Shorts"
    title = first_line[:95] if first_line else "Shorts"

    # Açıklama Formatı:
    # [Orijinal Metin / Japonca Yazı]
    # [Etiketler]
    # [Etsy Linki]
    parts = []
    if original_text:
        parts.append(original_text)

    parts.append(MAX_HASHTAGS)
    parts.append(ETSY_LINK)

    description = "\n\n".join(parts)
    return title, description

def convert_video_vertical(input_path: Path, output_path: Path) -> Path:
    """FFmpeg ile 1080x1920 Dikey (9:16) format ve temiz meta veri garantisi."""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-map_metadata", "-1",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_path
    except Exception as e:
        print(f"⚠️ FFmpeg dönüştürme uyarısı: {e}. Basit kopya yapılıyor...")
        cmd_copy = ["ffmpeg", "-y", "-i", str(input_path), "-map_metadata", "-1", "-c", "copy", "-movflags", "+faststart", str(output_path)]
        subprocess.run(cmd_copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_path

def upload_youtube_shorts(youtube, video_path: str, title: str, description: str, tags: list):
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "23", # Mizah / Komedi
            "defaultLanguage": "tr",
            "defaultAudioLanguage": "tr",
            "tags": tags[:30]
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=1024*1024*4, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    vid_id = response.get("id")
    return vid_id, response.get("snippet", {}).get("channelTitle", "Bilinmiyor")

def upload_facebook_reel(page, video_path: str, caption: str):
    page_id = page["page_id"]
    page_token = page["page_token"]
    file_size = os.path.getsize(video_path)
    
    init_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{page_id}/video_reels"
    init_resp = _graph_json(requests.post(init_url, data={"upload_phase": "start", "access_token": page_token}, timeout=30))
    video_id = init_resp["video_id"]
    upload_url = init_resp["upload_url"]
    
    headers = {"Authorization": f"OAuth {page_token}", "offset": "0", "file_size": str(file_size)}
    with open(video_path, "rb") as f:
        video_data = f.read()
    _graph_json(requests.post(upload_url, headers=headers, data=video_data, timeout=300))
    
    finish_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{page_id}/video_reels"
    finish_data = {
        "upload_phase": "finish", "access_token": page_token,
        "video_id": video_id, "video_state": "PUBLISHED", "description": caption
    }
    _graph_json(requests.post(finish_url, data=finish_data, timeout=30))
    return video_id

def create_instagram_cover_video(video_path: Path, cover_path: Path, output_path: Path) -> Path:
    """İlk 0,25 saniyede marka kapağını gösterir; Reels kapağı bu kareden seçilir."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path), "-loop", "1", "-i", str(cover_path),
        "-filter_complex",
        (
            "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1[cover];"
            "[0:v][cover]overlay=0:0:enable='between(t,0,0.25)'[v]"
        ),
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "copy", "-shortest", str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path


def _instagram_caption(caption: str, append_store_link: bool = True) -> str:
    """Keep platform copy intact, optionally reserving room for the shop link."""
    if not append_store_link:
        return caption[:2200].rstrip()
    suffix = f"\n\n{ETSY_LINK}"
    body = caption.replace(ETSY_LINK, "").strip()
    return body[:2200 - len(suffix)].rstrip() + suffix


def _upload_instagram_binary(upload_uri: str, page_token: str, video_path: str, file_size: int):
    """Send the resumable upload with curl; never expose credentials in argv/logs."""
    parsed = urlsplit(upload_uri)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("Geçersiz Instagram yükleme adresi") from exc
    if (parsed.scheme != "https" or parsed.hostname != "rupload.facebook.com"
            or port not in (None, 443) or parsed.username or parsed.password
            or parsed.fragment):
        raise RuntimeError("Geçersiz Instagram yükleme adresi")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", page_token):
        raise RuntimeError("Geçersiz Meta erişim anahtarı biçimi")
    actual_size = os.path.getsize(video_path)
    if file_size <= 0 or actual_size != file_size:
        raise RuntimeError("Instagram yüklemesi durduruldu: file_size ile son dosyanın boyutu eşleşmiyor")
    config = "\n".join([
        f"header = {json.dumps('Authorization: OAuth ' + page_token)}",
        'header = "offset: 0"',
        f'header = "file_size: {file_size}"',
        'header = "Content-Type: application/octet-stream"',
        f"url = {json.dumps(upload_uri)}",
        "",
    ])
    header_file = None
    try:
        with tempfile.NamedTemporaryFile(prefix="ig-upload-", suffix=".headers", delete=False) as tmp:
            header_file = tmp.name
        result = subprocess.run(
            ["curl", "--silent", "--show-error", "--request", "POST",
             "--config", "-", "--data-binary", f"@{video_path}",
             "--dump-header", header_file, "--max-time", "300",
             "--write-out", "\n%{size_upload}|%{http_code}"],
            input=config, text=True, capture_output=True, timeout=315, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Instagram ikili video yüklemesi tamamlanamadı") from exc
    finally:
        response_headers = {}
        if header_file:
            try:
                with open(header_file, encoding="utf-8", errors="replace") as stream:
                    for line in stream:
                        if ":" in line:
                            key, value = line.split(":", 1)
                            key = key.strip().lower()
                            if key in {"x-fb-trace-id", "x-fb-request-id", "x-fb-rev", "retry-after"}:
                                response_headers[key] = value.strip()
                os.unlink(header_file)
            except OSError:
                pass
    body, separator, transfer_text = result.stdout.rpartition("\n")
    transfer_match = re.fullmatch(r"(\d+(?:\.\d+)?)\|(\d{3})", transfer_text.strip()) if separator else None
    if not transfer_match or result.returncode:
        raise RuntimeError("Instagram ikili video yüklemesi başarısız oldu")
    uploaded_bytes = int(float(transfer_match.group(1)))
    status_text = transfer_match.group(2)
    try:
        payload = json.loads(body)
    except ValueError as exc:
        safe_body = _sanitize_meta_text(body)[:500]
        raise RuntimeError(
            f"Instagram ikili video aktarımı: geçersiz HTTP yanıtı (HTTP {status_text}; body={safe_body})"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Instagram video yüklemesi geçersiz yanıt döndürdü (HTTP {status_text})")
    response_headers = response_headers or {}
    if int(status_text) >= 400 or payload.get("error") or payload.get("success") is False or uploaded_bytes != file_size:
        error, debug_info, message = _decode_upload_error(payload)
        trace_id = error.get("fbtrace_id") or debug_info.get("fbtrace_id")
        if trace_id and "x-fb-trace-id" not in response_headers:
            response_headers["x-fb-trace-id"] = trace_id
        raise MetaAPIError(
            "Instagram ikili video aktarımı",
            int(status_text),
            message=message,
            error_type=error.get("type") or debug_info.get("type"),
            code=error.get("code") or payload.get("code"),
            subcode=error.get("error_subcode") or payload.get("error_subcode"),
            user_title=error.get("error_user_title"),
            user_message=error.get("error_user_msg"),
            debug_type=debug_info.get("type"),
            debug_message=debug_info.get("message"),
            retriable=debug_info.get("is_retriable", debug_info.get("retriable")),
            is_transient=error.get("is_transient"),
            response_headers=response_headers,
            error_data=error.get("error_data"), debug_info=debug_info,
            upload_bytes=file_size, uploaded_bytes=uploaded_bytes,
        )
    payload["_uploaded_bytes"] = uploaded_bytes
    payload["_http_status"] = int(status_text)
    return payload


def upload_instagram_reel(
    page, video_path: str, caption: str, append_store_link: bool = True,
    publish: bool = True, forbidden_container_ids=None,
):
    ig_user_id = page.get("instagram_id")
    if not ig_user_id:
        raise RuntimeError(f"{page.get('page_name', 'Sayfa')}: bağlı Instagram hesap kimliği bulunamadı")
    page_token = page["page_token"]
    file_size = os.path.getsize(video_path)
    
    container_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media"
    caption = _instagram_caption(caption, append_store_link=append_store_link)
    container_data = {
        "access_token": page_token, "upload_type": "resumable",
        "media_type": "REELS", "caption": caption
    }
    init_res = _graph_json(
        requests.post(container_url, data=container_data, timeout=30),
        "Instagram container oluşturma",
    )
    container_id = init_res["id"]
    if container_id in (forbidden_container_ids or set()):
        raise RuntimeError("Meta tekrarlanan container ID döndürdü; binary upload durduruldu.")
    upload_uri = init_res["uri"]
    
    started = time.monotonic()
    print(
        f"Instagram container hazır: id={container_id}; upload_bytes={file_size}; "
        f"upload_sha256={_sha256_file(video_path)}; content_type=application/octet-stream; "
        f"upload_host={urlsplit(upload_uri).hostname}; publish={'enabled' if publish else 'disabled'}.",
        flush=True,
    )
    binary_result = _upload_instagram_binary(upload_uri, page_token, video_path, file_size)
    print(
        f"Instagram binary upload kabul edildi: container={container_id}; "
        f"http={binary_result.get('_http_status')}; bytes={binary_result.get('_uploaded_bytes')}/{file_size}; "
        f"elapsed_seconds={time.monotonic() - started:.1f}.",
        flush=True,
    )
    
    status_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}"
    for poll_count in range(1, 31):
        time.sleep(5)
        status_payload = _graph_json(
            requests.get(
                status_url,
                params={
                    # A resumable IG container exposes status only here.
                    # Requesting error details (including ``error`` itself)
                    # causes Graph #100 before media_publish can run.
                    "fields": "status_code,status",
                    "access_token": page_token,
                },
                timeout=30,
            ),
            "Instagram video işleme durumu",
        )
        st = status_payload.get("status_code") or status_payload.get("status")
        if st == "FINISHED":
            print(
                f"Instagram container işlendi: container={container_id}; "
                f"status=FINISHED; polls={poll_count}; "
                f"elapsed_seconds={time.monotonic() - started:.1f}.",
                flush=True,
            )
            break
        elif st == "ERROR":
            print(
                f"Instagram container işlemesi başarısız: container={container_id}; "
                f"status=ERROR; polls={poll_count}; "
                f"elapsed_seconds={time.monotonic() - started:.1f}.",
                flush=True,
            )
            raise MetaAPIError(
                "Instagram video işleme durumu",
                400,
                message=(
                    "Instagram video işleme hatası"
                ),
                error_type=status_payload.get("status"),
                code=status_payload.get("code"),
                subcode=status_payload.get("subcode"),
            )
            
    else:
        raise RuntimeError("Instagram video işleme zaman aşımı.")

    if not publish:
        print(
            f"Instagram upload-only tamamlandı: container={container_id}; "
            "status=FINISHED; media_publish çağrılmadı.",
            flush=True,
        )
        return {"container_id": container_id, "status": "FINISHED", "published": False}

    pub_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media_publish"
    print(f"Instagram media_publish başlatılıyor: container={container_id}.", flush=True)
    pub_res = _graph_json(
        requests.post(pub_url, data={"creation_id": container_id, "access_token": page_token}, timeout=30),
        "Instagram media_publish",
    )
    media_id = pub_res["id"]
    print(f"Instagram media_publish kabul edildi: container={container_id}; media_id={media_id}.", flush=True)
    try:
        media = _graph_json(
            requests.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}",
                params={"fields": "id,permalink", "access_token": page_token},
                timeout=30,
            ),
            "Instagram gönderi permalink doğrulama",
        )
        permalink = media.get("permalink")
        if permalink:
            print(f"Instagram gerçek gönderi bağlantısı: media_id={media_id}; permalink={permalink}.", flush=True)
        else:
            print(f"Instagram gönderi bağlantısı henüz dönmedi: media_id={media_id}; permalink=unavailable.", flush=True)
    except Exception as exc:
        # media_publish already succeeded. A permalink lookup failure must not
        # turn that success into a retryable publish failure.
        details = [f"media_id={media_id}", f"error_type={type(exc).__name__}"]
        if isinstance(exc, MetaAPIError):
            details.append(f"http={exc.http_status}")
            if exc.code is not None:
                details.append(f"code={exc.code}")
            if exc.subcode is not None:
                details.append(f"subcode={exc.subcode}")
        print("Instagram gönderi bağlantısı doğrulanamadı: " + "; ".join(details) + ".", flush=True)
    return pub_res["id"]

def run_omnichannel():
    slot = current_publish_slot()
    if not slot:
        now = datetime.now(TURKEY_TIMEZONE).strftime("%Y-%m-%d %H:%M")
        print(f"⏭️ {now} Türkiye saati: yayın penceresi değil, işlem yapılmadı.")
        return

    print("=" * 65)
    print("🌍 4 KANALLI OTONOM YAYIN MOTORU (BULUT)")
    print(f"🕒 Yayın slotu: {slot} (Türkiye)")
    print("-> 1. YouTube : Tarladaki Fasulye")
    print("-> 2. YouTube : Beyinsiz Penguen")
    print("-> 3. Facebook: Tarladaki Fasulye")
    print("-> 4. Insta   : @tarladakifasulye_")
    print("=" * 65)

    drive = get_drive_client()
    meta_page = get_meta_page_info(TARGET_META_ACCOUNT)
    folder_id = os.environ.get("DRIVE_FOLDER_ID", "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M")

    # Dosyalari Listele
    files = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        res = drive.files().list(
            q=query, fields="nextPageToken, files(id, name, appProperties)",
            pageSize=1000, pageToken=page_token
        ).execute()
        files.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    mp4_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".mp4")}
    txt_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".txt")}

    if slot_already_processed(files, slot):
        print(f"⏭️ {slot} slotu zaten işlendi; tekrar paylaşım yapılmadı.")
        return

    stems = sorted(
        list(set(mp4_files.keys()) & set(txt_files.keys())),
        key=lambda s: int(s) if s.isdigit() else s
    )

    # Sıradaki hedef videoyu bul (Öncelik: Meta'ya henüz gitmemiş veya YouTube'a gitmemiş olan)
    selected_stem = None
    target_tasks = {"youtube": False, "meta": False}

    for s in stems:
        props = mp4_files[s].get("appProperties") or {}
        # Video 1..6 daha önce Meta'ya yüklendi
        meta_done = props.get("meta_state") == "uploaded" or s in ["1", "2", "3", "4", "5", "6"]
        yt_done = props.get("youtube_state") == "uploaded"

        # Eğer herhangi bir platforma henüz yüklenmediyse bu videoyu işle
        if not meta_done or not yt_done:
            selected_stem = s
            target_tasks["meta"] = not meta_done
            target_tasks["youtube"] = not yt_done
            break

    if not selected_stem:
        print("🎉 TEBRİKLER! Tüm videolar 4 platforma da eksiksiz yüklendi!")
        return

    mp4_obj = mp4_files[selected_stem]
    txt_obj = txt_files[selected_stem]

    print(f"\n🎬 İŞLENECEK VİDEO: Video {selected_stem} ({mp4_obj['name']})")
    print(f"   -> YouTube Kanallarına Yüklenecek mi? : {'EVET' if target_tasks['youtube'] else 'Zaten Yüklü'}")
    print(f"   -> Facebook & Instagram'a Yüklenecek mi?: {'EVET' if target_tasks['meta'] else 'Zaten Yüklü'}")

    temp_dir = Path("temp_omni")
    temp_dir.mkdir(exist_ok=True)
    raw_mp4 = temp_dir / f"raw_{mp4_obj['name']}"
    clean_mp4 = temp_dir / f"clean_{mp4_obj['name']}"
    instagram_mp4 = temp_dir / f"instagram_{mp4_obj['name']}"
    local_txt = temp_dir / txt_obj["name"]

    # TXT indir ve içeriği oluştur
    req_txt = drive.files().get_media(fileId=txt_obj["id"])
    with io.FileIO(local_txt, "wb") as fh:
        MediaIoBaseDownload(fh, req_txt).next_chunk()

    raw_text = local_txt.read_text(encoding="utf-8", errors="ignore")
    title, description = build_post_content(raw_text)

    print(f"\n📌 Başlık : {title}")
    print(f"📝 Açıklama ({len(description)} karakter):\n{description[:120]}...")
    print(f"🔗 Etsy Linki Eklendi: {ETSY_LINK}")

    # MP4 indir
    print(f"\n📥 Video indiriliyor ({mp4_obj['name']})...")
    req_mp4 = drive.files().get_media(fileId=mp4_obj["id"])
    with io.FileIO(raw_mp4, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req_mp4, chunksize=1024*1024*4)
        done = False
        while not done:
            st, done = downloader.next_chunk()
            if st:
                print(f"-> İndirme: %{int(st.progress() * 100)}", end="\r", flush=True)
    print("\n-> İndirme tamamlandı!")

    # FFmpeg 9:16 Dikey & Meta Temizliği
    final_video = convert_video_vertical(raw_mp4, clean_mp4)
    cover_image = Path(__file__).resolve().parent / "assets" / "instagram_tarladaki_fasulye_cover.png"
    instagram_video = create_instagram_cover_video(final_video, cover_image, instagram_mp4)

    results = {}
    errors = {}

    # 1 & 2. YOUTUBE KANALLARI (Eğer gerekliyse)
    if target_tasks["youtube"]:
        try:
            print("\n🚀 1. YouTube Kanalına Yükleniyor (Tarladaki Fasulye)...")
            yt1 = get_youtube_client("TOKEN_CHANNEL1_JSON", "token_channel1.json")
            y_id1, ch1 = upload_youtube_shorts(yt1, str(final_video), title, description, YOUTUBE_TAGS)
            results["yt1"] = f"https://youtube.com/shorts/{y_id1}"
            print(f"✅ 1. YouTube Başarılı: {results['yt1']}")
        except Exception as e:
            errors["yt1"] = str(e)
            print(f"⚠️ 1. YouTube Hatası: {e}")

        try:
            print("\n🚀 2. YouTube Kanalına Yükleniyor (Beyinsiz Penguen)...")
            yt2 = get_youtube_client("TOKEN_CHANNEL2_JSON", "token_channel2.json")
            y_id2, ch2 = upload_youtube_shorts(yt2, str(final_video), title, description, YOUTUBE_TAGS)
            results["yt2"] = f"https://youtube.com/shorts/{y_id2}"
            print(f"✅ 2. YouTube Başarılı: {results['yt2']}")
        except Exception as e:
            errors["yt2"] = str(e)
            print(f"⚠️ 2. YouTube Hatası: {e}")

    # 3. FACEBOOK REELS (Eğer gerekliyse)
    if target_tasks["meta"]:
        try:
            print("\n🚀 3. Facebook Sayfasına Reels Yükleniyor (Tarladaki Fasulye)...")
            fb_id = upload_facebook_reel(meta_page, str(final_video), description)
            results["fb"] = fb_id
            print(f"✅ Facebook Reels Başarılı! (ID: {fb_id})")
        except Exception as e:
            errors["fb"] = str(e)
            print(f"⚠️ Facebook Reels Hatası: {e}")

        # 4. INSTAGRAM REELS (Eğer gerekliyse)
        try:
            print("\n🚀 4. Instagram Hesabına Reels Yükleniyor (@tarladakifasulye_)...")
            ig_id = upload_instagram_reel(meta_page, str(instagram_video), description)
            results["ig"] = ig_id
            print(f"✅ Instagram Reels Başarılı! (ID: {ig_id})")
        except Exception as e:
            errors["ig"] = str(e)
            print(f"⚠️ Instagram Reels Hatası: {e}")

    # Drive Güncellemesi
    app_props_update = {}
    if target_tasks["youtube"] and "yt1" in results and "yt2" in results:
        app_props_update["youtube_state"] = "uploaded"
    if target_tasks["meta"] and "fb" in results and "ig" in results:
        app_props_update["meta_state"] = "uploaded"

    # Aynı saat içinde zamanlayıcı yeniden çalışsa bile yeni videoya geçmesin.
    # Bu işaret, ancak gerçekten işlenecek bir video seçildikten sonra yazılır.
    if results or errors:
        app_props_update[SCHEDULE_SLOT_PROPERTY] = slot

    if app_props_update:
        drive.files().update(
            fileId=mp4_obj["id"],
            body={"appProperties": app_props_update}
        ).execute()
        print("💾 Drive durumu başarıyla güncellendi!")

    # Temizlik
    for f in [raw_mp4, clean_mp4, instagram_mp4, local_txt]:
        if f.exists():
            f.unlink()
    try:
        temp_dir.rmdir()
    except:
        pass

    # GitHub Actions Step Summary
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        summary_md = f"""
## 🌍 4 Kanallı Otonom Video Yayını Tamamlandı!
| Kanal | Durum / Link |
| :--- | :--- |
| 🎬 **İçerik** | Video {selected_stem} (`{mp4_obj['name']}`) |
| 🛒 **Etsy Linki** | `{ETSY_LINK}` |
| 📺 **1. YouTube (Tarladaki Fasulye)** | {results.get('yt1', 'Zaten Yüklü')} |
| 🎷 **2. YouTube (Beyinsiz Penguen)** | {results.get('yt2', 'Zaten Yüklü')} |
| 📘 **3. Facebook (Tarladaki Fasulye)** | Reels ID: {results.get('fb', 'Zaten Yüklü')} |
| 📸 **4. Instagram (@tarladakifasulye_)** | Reels ID: {results.get('ig', 'Zaten Yüklü')} |
"""
        with open(summary_file, "a", encoding="utf-8") as sf:
            sf.write(summary_md)

    send_ntfy_summary(selected_stem, results, errors, target_tasks)

    print("\n" + "=" * 65)
    print("🎉 OMNICHANNEL YAYIN GÖREVİ TAMAMLANDI!")
    print("=" * 65)

if __name__ == "__main__":
    if os.environ.get("ENABLE_LEGACY_PUBLISHER") != "I_UNDERSTAND":
        raise SystemExit(
            "Eski yayın motoru doğrudan çalıştırılamaz. Aktif giriş: "
            "scheduled_multi_publisher.py"
        )
    run_omnichannel()
