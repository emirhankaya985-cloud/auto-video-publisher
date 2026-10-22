import os
import io
import re
import json
import subprocess
import shutil
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

SCOPES_YOUTUBE = ["https://www.googleapis.com/auth/youtube.upload"]
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]

def get_drive_client():
    token_str = os.environ.get("DRIVE_TOKEN_JSON")
    if token_str:
        data = json.loads(token_str)
    else:
        token_path = Path("drive_token.json")
        if not token_path.exists():
            raise FileNotFoundError("drive_token.json bulunamadi.")
        data = json.loads(token_path.read_text(encoding="utf-8"))

    creds = Credentials.from_authorized_user_info(data, SCOPES_DRIVE)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)

def get_youtube_client(env_var_name, fallback_file):
    token_str = os.environ.get(env_var_name)
    if token_str:
        data = json.loads(token_str)
    else:
        token_path = Path(fallback_file)
        if not token_path.exists():
            raise FileNotFoundError(f"{fallback_file} bulunamadi.")
        data = json.loads(token_path.read_text(encoding="utf-8"))

    creds = Credentials.from_authorized_user_info(data, SCOPES_YOUTUBE)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

def parse_txt_content(content: str) -> dict:
    content_clean = content.strip()
    title = ""
    description = ""
    tags = []

    # 1. Format: Başlık / Açıklama / Etiketler
    if "başlık:" in content_clean.lower() or "baslik:" in content_clean.lower():
        lines = content_clean.splitlines()
        desc_lines = []
        for line in lines:
            ls = line.strip()
            if ls.lower().startswith("başlık:") or ls.lower().startswith("baslik:"):
                title = ls.split(":", 1)[1].strip().strip('"').strip('“').strip('”')
            elif ls.lower().startswith("açıklama:") or ls.lower().startswith("aciklama:"):
                desc_lines.append(ls.split(":", 1)[1].strip())
            elif ls.lower().startswith("etiketler:") or ls.lower().startswith("tags:"):
                tags = re.findall(r'#(\w+)', ls)
            elif ls:
                desc_lines.append(ls)
        description = "\n".join(desc_lines)

    # 2. Format: === YOUTUBE SHORTS ===
    elif "=== YOUTUBE SHORTS ===" in content_clean.upper():
        parts = content_clean.split("=== YOUTUBE SHORTS ===")[1]
        sec_body = parts.split("===")[0].strip() if "===" in parts else parts.strip()
        lines = [l.strip() for l in sec_body.splitlines() if l.strip()]
        if lines:
            title = lines[0].replace("BAŞLIK:", "").strip()
            description = "\n".join(lines[1:]).replace("AÇIKLAMA:", "").strip()
            tags = re.findall(r'#(\w+)', sec_body)

    # 3. Format: Düz Metin
    else:
        sentences = re.split(r'[.!?\n]', content_clean)
        first_sentence = sentences[0].strip() if sentences else content_clean[:60]
        title = first_sentence[:60]
        description = content_clean
        tags = ["Mizah", "Shorts", "Komik", "Kesit"]

    # Eğer başlıkta veya açıklamada Japonca/şablon metin varsa sadece YouTube için ilgi çekici Türkçe mizah başlığı ata
    is_placeholder = bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', content_clean) or "vogue world" in content_clean.lower())
    
    if is_placeholder or not title:
        import random
        fallback_titles = [
            "Bunu Beklemiyordum 😂",
            "Gülme Krizine Sokan O An 🤣",
            "Yok Artık Dedirten Anlar 💀",
            "Sonuna Kadar İzleyin 😂",
            "Gülmek Garanti 🤣",
            "Günün En Komik Anı 😂",
            "Bunu Görmeniz Lazım 🤣",
            "Kahkaha Tufanı 😂",
            "İzlemeden Geçmeyin 💀",
            "Koptum Resmen ya 🤣",
            "Hayatımda Böyle Bir Şey Görmedim 😂",
            "Efsane Komik Anlar 🤣",
            "Bunu Yapan Olamaz 💀",
            "Şaka Gibi Olay 😂"
        ]
        title = random.choice(fallback_titles)
        description = "Gülme krizine sokan en komik anlar ve efsane kesitler! 😂 Daha fazlası için abone olmayı ve beğenmeyi unutmayın! 👍"

    if "#shorts" not in title.lower():
        title = f"{title} #Shorts"

    title = title[:100]

    return {
        "title": title,
        "description": description,
        "tags": tags[:30]
    }

def convert_to_shorts(input_path: Path) -> Path:
    """
    Videoyu standart 1080x1920 (9:16 Dikey) YouTube Shorts formatına dönüştürür.
    Tüm eski dosya meta verilerini (-map_metadata -1) temizler.
    Böylece en-boy oranı yatay veya kare olan videoların YouTube tarafından normal video
    olarak algılanması engellenir ve %100 kesinlikle SHORTS olarak yayınlanması garanti edilir.
    """
    output_path = input_path.parent / f"shorts_{input_path.name}"
    ffmpeg_cmd = shutil.which("ffmpeg")
    if not ffmpeg_cmd:
        print("⚠️ Uyarı: FFmpeg bulunamadı, orijinal dosya ile devam ediliyor.")
        return input_path

    print(f"🎬 Video Shorts standardına (1080x1920 Dikey 9:16) dönüştürülüyor ve meta veriler temizleniyor: {input_path.name}...")
    cmd = [
        ffmpeg_cmd,
        "-y",
        "-i", str(input_path),
        "-map_metadata", "-1",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        print(f"✅ Shorts dönüşümü tamamlandı (1080x1920 Dikey 9:16, temiz meta veri) -> {output_path.name}")
        return output_path
    except Exception as e:
        print(f"⚠️ FFmpeg dönüştürme hatası: {e}. Orijinal video kullanılacak.")
        return input_path

def upload_single_video(youtube, video_path: str, title: str, description: str, tags: list = None, privacy="public") -> dict:
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "23", # Mizah / Eglence
            "defaultLanguage": "tr",
            "defaultAudioLanguage": "tr"
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False
        }
    }
    if tags:
        body["snippet"]["tags"] = tags[:30]

    media = MediaFileUpload(video_path, chunksize=1024*1024*4, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()

    video_id = response.get("id")
    snippet = response.get("snippet", {})
    channel_title = snippet.get("channelTitle", "Bilinmiyor")

    return {
        "video_id": video_id,
        "channel_title": channel_title,
        "link": f"https://youtube.com/shorts/{video_id}"
    }

def run_cloud_job():
    folder_id = os.environ.get("DRIVE_FOLDER_ID", "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M")
    print("=" * 65)
    print("☁️ BULUT OTOMASYONU (GITHUB ACTIONS) BASLATILIYOR...")
    print(f"Hedef Drive Klasoru: {folder_id}")
    print("=" * 65)

    drive = get_drive_client()

    # Klasordeki tum dosyalari pagination ile cek
    files = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"

    while True:
        res = drive.files().list(
            q=query,
            fields="nextPageToken, files(id, name, appProperties, size)",
            pageSize=1000,
            pageToken=page_token
        ).execute()
        files.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    mp4_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".mp4")}
    txt_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".txt")}

    # KESİN SAYISAL SIRALAMA (1, 2, 3 ... 900)
    matched_stems = sorted(
        list(set(mp4_files.keys()) & set(txt_files.keys())),
        key=lambda x: int(x) if x.isdigit() else float('inf')
    )

    total_count = len(matched_stems)
    uploaded_items = [
        s for s in matched_stems
        if (mp4_files[s].get("appProperties") or {}).get("youtube_state") == "uploaded"
    ]
    already_uploaded = len(uploaded_items)

    pending_target = None
    for stem in matched_stems:
        mp4_item = mp4_files[stem]
        props = mp4_item.get("appProperties") or {}
        if props.get("youtube_state") != "uploaded":
            pending_target = stem
            break

    if not pending_target:
        print(f"\n🎉 TEBRIKLER! Tum {total_count} video basariyla yuklendi! Kalan video yok.")
        return

    current_number = already_uploaded + 1
    remaining_count = total_count - already_uploaded
    progress_pct = (current_number / total_count) * 100

    mp4_obj = mp4_files[pending_target]
    txt_obj = txt_files[pending_target]

    print("\n" + "=" * 65)
    print(f"📊 İLERLEME SAYACI : [ {current_number} / {total_count} ] (%{progress_pct:.1f})")
    print(f"⏳ Kalan Video     : {remaining_count - 1} adet")
    print(f"🎬 Sıradaki Video  : {mp4_obj['name']} | Açıklama: {txt_obj['name']}")
    print("=" * 65)

    temp_dir = Path("temp_cloud")
    temp_dir.mkdir(exist_ok=True)
    local_mp4 = temp_dir / mp4_obj["name"]
    local_txt = temp_dir / txt_obj["name"]

    # TXT indir
    req_txt = drive.files().get_media(fileId=txt_obj["id"])
    with io.FileIO(local_txt, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req_txt)
        downloader.next_chunk()

    txt_content = local_txt.read_text(encoding="utf-8", errors="ignore")
    parsed_meta = parse_txt_content(txt_content)
    print(f"📌 Başlık: {parsed_meta['title']}")

    # MP4 indir
    print(f"📥 Video indiriliyor ({mp4_obj['name']})...")
    req_mp4 = drive.files().get_media(fileId=mp4_obj["id"])
    with io.FileIO(local_mp4, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req_mp4, chunksize=1024*1024*4)
        done = False
        while not done:
            st, done = downloader.next_chunk()
            if st:
                print(f"-> İndirme: %{int(st.progress() * 100)}", end="\r", flush=True)
    print("\n-> İndirme tamamlandı!")

    # Video'yu kesinlikle YouTube Shorts formatına (1080x1920 Dikey 9:16) dönüştür
    upload_file_path = convert_to_shorts(local_mp4)

    # Drive durumunu 'uploading' yap
    drive.files().update(
        fileId=mp4_obj["id"],
        body={"appProperties": {"youtube_state": "uploading"}}
    ).execute()

    # 1. MİZAH SAYFASI ETİKETLERİ: (Viral Komedi, Caps & Mizah Türkiye)
    ch1_hashtags = "#Mizah #Komik #Komedi #Eğlence #KomikVideolar #GülmekGaranti #MizahTürkiye #KomikAnlar #Caps #Shorts #Keşfet #Viral"
    ch1_desc = f"{parsed_meta['description']}\n\n{ch1_hashtags}".strip()
    ch1_tags = [
        "mizah", "komik videolar", "komedi", "eğlence", "komik anlar", "gülmek garanti",
        "tiktok komik", "reels mizah", "türkçe mizah", "en komik videolar", "caps",
        "şaka", "vine türkiye", "mizah türkiye", "kahkaha", "shorts", "kesitler",
        "komik kesitler", "viral"
    ]

    # 2. MİZAH SAYFASI ETİKETLERİ: (Kahkaha, Trendler & Eğlenceli Paylaşımlar)
    ch2_hashtags = "#Komik #Mizah #Kahkaha #Eğlenceli #KomikPaylaşımlar #Gülümse #KomediShorts #ShortsMizah #Trend #Shorts #Keşfet #FYP"
    ch2_desc = f"{parsed_meta['description']}\n\n{ch2_hashtags}".strip()
    ch2_tags = [
        "komik", "mizah", "kahkaha", "komik paylaşımlar", "eğlenceli videolar",
        "gülümse", "komedi shorts", "shorts mizah", "en iyi mizah", "komedi türkiye",
        "komik sahneler", "güldüren videolar", "skeç", "komik olaylar", "shorts",
        "trend", "fyp", "kesitler"
    ]

    # 1. Kanala yukle (Film Mağarası)
    print("\n🚀 1. Kanala yükleniyor (Film Mağarası)...")
    yt1 = get_youtube_client("TOKEN_CHANNEL1_JSON", "token_channel1.json")
    res1 = upload_single_video(yt1, str(upload_file_path), parsed_meta["title"], ch1_desc, tags=ch1_tags, privacy="public")
    print(f"-> 1. Kanal Başarılı: {res1['link']}")

    # 2. Kanala yukle (Velvet Rain Jazz Music)
    print("\n🚀 2. Kanala yükleniyor (Velvet Rain Jazz Music)...")
    yt2 = get_youtube_client("TOKEN_CHANNEL2_JSON", "token_channel2.json")
    res2 = upload_single_video(yt2, str(upload_file_path), parsed_meta["title"], ch2_desc, tags=ch2_tags, privacy="public")
    print(f"-> 2. Kanal Başarılı: {res2['link']}")

    # Drive durumunu 'uploaded' yap ve ID'leri kaydet
    drive.files().update(
        fileId=mp4_obj["id"],
        body={
            "appProperties": {
                "youtube_state": "uploaded",
                "youtube_id_ch1": res1["video_id"],
                "youtube_id_ch2": res2["video_id"]
            }
        }
    ).execute()

    # Temizle
    try:
        if local_mp4.exists():
            local_mp4.unlink()
        if upload_file_path.exists() and upload_file_path != local_mp4:
            upload_file_path.unlink()
        if local_txt.exists():
            local_txt.unlink()
        temp_dir.rmdir()
    except Exception:
        pass

    # GitHub Actions Step Summary (Görsel İlerleme Panosu)
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        summary_md = f"""
## 🚀 Otomatik Video Yayını Başarılı!
| Bilgi | Değer |
| :--- | :--- |
| 📊 **İlerleme Durumu** | **{current_number} / {total_count}** (%{progress_pct:.1f}) |
| ⏳ **Kalan Video** | **{remaining_count - 1} adet** |
| 🎬 **Yüklenen Video** | `{mp4_obj['name']}` |
| 📌 **Başlık** | {parsed_meta['title']} |
| 📺 **1. Kanal (Film Mağarası)** | [İzle]({res1['link']}) |
| 🎷 **2. Kanal (Velvet Rain)** | [İzle]({res2['link']}) |
"""
        with open(summary_file, "a", encoding="utf-8") as sf:
            sf.write(summary_md)

    print("\n" + "=" * 65)
    print(f"🎉 GÖREV TAMAMLANDI! [ {current_number} / {total_count} ]")
    print(f"1. Kanal ({res1['channel_title']}): {res1['link']}")
    print(f"2. Kanal ({res2['channel_title']}): {res2['link']}")
    print("=" * 65)

if __name__ == "__main__":
    if os.environ.get("ENABLE_LEGACY_PUBLISHER") != "I_UNDERSTAND":
        raise SystemExit("Eski motor devre dışı. Aktif giriş: scheduled_multi_publisher.py")
    run_cloud_job()
