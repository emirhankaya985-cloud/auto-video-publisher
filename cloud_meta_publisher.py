import os
import io
import re
import json
import time
import requests
import subprocess
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]
TARGET_ACCOUNT = "Tarladaki Fasulye"

def get_drive_client():
    token_str = os.environ.get("DRIVE_TOKEN_JSON")
    if token_str:
        data = json.loads(token_str)
    else:
        token_path = Path(__file__).resolve().parent / "drive_token.json"
        if not token_path.exists():
            raise FileNotFoundError("drive_token.json bulunamadi.")
        data = json.loads(token_path.read_text(encoding="utf-8"))

    creds = Credentials.from_authorized_user_info(data, SCOPES_DRIVE)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)

def get_meta_auth():
    auth_str = os.environ.get("META_AUTH_JSON")
    if auth_str:
        return json.loads(auth_str)
    auth_path = Path(__file__).resolve().parent / "meta_auth.json"
    if not auth_path.exists():
        raise FileNotFoundError("meta_auth.json bulunamadi.")
    return json.loads(auth_path.read_text(encoding="utf-8"))

def get_meta_page_info(target_name=TARGET_ACCOUNT):
    auth = get_meta_auth()
    pages = auth.get("pages", [])
    for p in pages:
        if target_name.lower() in p.get("page_name", "").lower():
            return p
    for p in pages:
        if p.get("instagram_id"):
            return p
    if pages:
        return pages[0]
    raise ValueError("Meta yetkili sayfa bulunamadı!")

def upload_facebook_reel(page, video_path: str, caption: str):
    page_id = page["page_id"]
    page_token = page["page_token"]
    file_size = os.path.getsize(video_path)
    
    print(f"\n[Facebook Reels] Başlatılıyor: {os.path.basename(video_path)} ({file_size / (1024*1024):.2f} MB)")
    init_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
    init_resp = requests.post(init_url, data={
        "upload_phase": "start",
        "access_token": page_token
    }).json()
    
    if "video_id" not in init_resp or "upload_url" not in init_resp:
        raise RuntimeError(f"FB Reels başlatma hatası: {init_resp}")
        
    video_id = init_resp["video_id"]
    upload_url = init_resp["upload_url"]
    
    headers = {
        "Authorization": f"OAuth {page_token}",
        "offset": "0",
        "file_size": str(file_size)
    }
    with open(video_path, "rb") as f:
        video_data = f.read()
        
    upload_resp = requests.post(upload_url, headers=headers, data=video_data)
    if upload_resp.status_code not in (200, 201):
        raise RuntimeError(f"FB Video yükleme hatası: {upload_resp.text}")
        
    finish_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
    finish_data = {
        "upload_phase": "finish",
        "access_token": page_token,
        "video_id": video_id,
        "video_state": "PUBLISHED",
        "description": caption
    }
    finish_resp = requests.post(finish_url, data=finish_data).json()
    if not finish_resp.get("success"):
        raise RuntimeError(f"FB Reels yayınlama hatası: {finish_resp}")
        
    print(f"🎉 [Facebook Reels] Başarıyla Yüklendi! (Video ID: {video_id})")
    return video_id

def upload_instagram_reel(page, video_path: str, caption: str):
    ig_user_id = page.get("instagram_id")
    page_token = page["page_token"]
    if not ig_user_id:
        raise RuntimeError("Instagram hesabı bağlı değil!")
        
    file_size = os.path.getsize(video_path)
    print(f"\n[Instagram Reels] Başlatılıyor: {os.path.basename(video_path)} ({file_size / (1024*1024):.2f} MB)")
    
    container_url = f"https://graph.facebook.com/v20.0/{ig_user_id}/media"
    container_data = {
        "access_token": page_token,
        "upload_type": "resumable",
        "media_type": "REELS",
        "caption": caption
    }
    init_res = requests.post(container_url, data=container_data).json()
    if "id" not in init_res or "uri" not in init_res:
        raise RuntimeError(f"Instagram Container başlatma hatası: {init_res}")
        
    container_id = init_res["id"]
    upload_uri = init_res["uri"]
    
    headers = {
        "Authorization": f"OAuth {page_token}",
        "offset": "0",
        "file_size": str(file_size)
    }
    with open(video_path, "rb") as f:
        video_data = f.read()
        
    upload_resp = requests.post(upload_uri, headers=headers, data=video_data)
    if upload_resp.status_code not in (200, 201):
        raise RuntimeError(f"Instagram Video yükleme hatası: {upload_resp.text}")
        
    status_url = f"https://graph.facebook.com/v20.0/{container_id}?fields=status_code&access_token={page_token}"
    for _ in range(30):
        time.sleep(5)
        st_res = requests.get(status_url).json()
        status_code = st_res.get("status_code")
        print(f"  -> Instagram İşleme Durumu: {status_code}")
        if status_code == "FINISHED":
            break
        elif status_code == "ERROR":
            raise RuntimeError(f"Instagram video işleme hatası: {st_res}")
            
    pub_url = f"https://graph.facebook.com/v20.0/{ig_user_id}/media_publish"
    pub_res = requests.post(pub_url, data={
        "creation_id": container_id,
        "access_token": page_token
    }).json()
    
    if "id" not in pub_res:
        raise RuntimeError(f"Instagram yayınlama hatası: {pub_res}")
        
    print(f"🎉 [Instagram Reels] Başarıyla Yüklendi! (Reels ID: {pub_res['id']})")
    return pub_res["id"]

def run_cloud_meta():
    print("=" * 65)
    print("☁️ BULUT META OTONOM YAYINCI (Facebook & Instagram Reels)")
    print(f"Hedef Hesap: {TARGET_ACCOUNT}")
    print("=" * 65)

    drive = get_drive_client()
    meta_page = get_meta_page_info(TARGET_ACCOUNT)
    
    folder_id = os.environ.get("DRIVE_FOLDER_ID", "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M")
    
    query = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken, files(id, name, mimeType, size, appProperties)"
    all_files = []
    page_token = None
    
    while True:
        resp = drive.files().list(q=query, fields=fields, pageToken=page_token, pageSize=1000).execute()
        all_files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    mp4_files = {}
    txt_files = {}
    for f in all_files:
        name_lower = f["name"].lower()
        if name_lower.endswith(".mp4"):
            stem = f["name"][:-4]
            mp4_files[stem] = f
        elif name_lower.endswith(".txt"):
            stem = f["name"][:-4]
            txt_files[stem] = f

    matching_stems = sorted(
        list(set(mp4_files.keys()) & set(txt_files.keys())),
        key=lambda s: int(s) if s.isdigit() else s
    )
    
    total_count = len(matching_stems)
    
    # Sıradaki yüklenmemiş videoyu bul
    selected_stem = None
    already_uploaded = 0
    for stem in matching_stems:
        mp4_obj = mp4_files[stem]
        app_props = mp4_obj.get("appProperties") or {}
        # Video 1 ve 2 daha önce yüklendiği için bunları da kontrol et
        if app_props.get("meta_state") == "uploaded" or stem in ["1", "2"]:
            already_uploaded += 1
            continue
        if selected_stem is None:
            selected_stem = stem

    if selected_stem is None:
        print("🎉 TEBRİKLER! Drive'daki tüm videolar Meta'ya yüklendi!")
        return

    mp4_obj = mp4_files[selected_stem]
    txt_obj = txt_files[selected_stem]
    
    current_number = already_uploaded + 1
    remaining_count = total_count - already_uploaded
    progress_pct = (already_uploaded / total_count) * 100

    print(f"\n📊 İLERLEME SAYACI : [ {current_number} / {total_count} ] (%{progress_pct:.1f})")
    print(f"⏳ Kalan Video     : {remaining_count - 1} adet")
    print(f"🎬 Sıradaki İçerik : Video {selected_stem} ({mp4_obj['name']})")

    temp_dir = Path("temp_cloud_meta")
    temp_dir.mkdir(exist_ok=True)
    raw_mp4 = temp_dir / f"raw_{mp4_obj['name']}"
    clean_mp4 = temp_dir / f"clean_{mp4_obj['name']}"
    local_txt = temp_dir / txt_obj["name"]

    # TXT indir
    req_txt = drive.files().get_media(fileId=txt_obj["id"])
    with io.FileIO(local_txt, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req_txt)
        downloader.next_chunk()

    raw_caption = local_txt.read_text(encoding="utf-8", errors="ignore").strip()
    
    is_placeholder = bool(
        re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', raw_caption) 
        or "vogue world" in raw_caption.lower()
        or not raw_caption
    )
    
    if is_placeholder:
        import random
        VIRAL_HOOKS = [
            "Bunu beklemiyordum, sonuna kadar izleyin 😂💀",
            "Gülme krizine sokan o anlar 🤣 Sizce haklı mı?",
            "Yok artık dedirten cinsten bir olay 💀 Arkadaşına gönder!",
            "Günün en komik kesiti net bu 😂 Ne düşünüyorsunuz?",
            "Sonunda patladım resmen 🤣 Kaydetmeyi unutma!",
            "Böyle bir şey yaşandı mı gerçekten ya 💀😂",
            "İzlerken kahkaha attım resmen 🤣 Yorumlara bekliyorum!",
            "Beklenmedik son 😂 Kaç kere izledim sayamadım!",
            "Günün enerjisini yükselten video 🤣 #keşfet",
            "Tam o an... Hayat durdu resmen 😂💀",
            "Bunu görmesi gereken arkadaşını yoruma etiketle 🤣",
            "Siz olsaydınız ne yapardınız? 😂 Yorumlarda buluşalım!"
        ]
        HASHTAGS = "\n.\n.\n#mizah #komedi #komik #reels #keşfet #fyp #trend #eğlence #kahkaha #kesfet #viral #mizahtürkiye"
        caption = f"{random.choice(VIRAL_HOOKS)}{HASHTAGS}"
    else:
        caption = raw_caption
        if "#" not in caption:
            caption += "\n\n#mizah #reels #viral #kesfet #trend"

    print(f"📝 Açıklama Metni Hazırlandı:\n{caption[:100]}...")

    # MP4 indir
    print(f"📥 Video indiriliyor ({mp4_obj['name']})...")
    req_mp4 = drive.files().get_media(fileId=mp4_obj["id"])
    with io.FileIO(raw_mp4, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req_mp4, chunksize=1024*1024*4)
        done = False
        while not done:
            st, done = downloader.next_chunk()
            if st:
                print(f"-> İndirme: %{int(st.progress() * 100)}", end="\r", flush=True)
    print("\n-> İndirme tamamlandı!")

    # FFmpeg Meta Temizliği
    print("🧹 FFmpeg ile meta verileri sıfırlanıyor (-map_metadata -1)...")
    cmd = [
        "ffmpeg", "-y", "-i", str(raw_mp4),
        "-map_metadata", "-1",
        "-c", "copy",
        str(clean_mp4)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Facebook Reels Yükle
    print("🚀 Facebook Sayfasına Reels olarak yükleniyor...")
    fb_id = upload_facebook_reel(meta_page, str(clean_mp4), caption)

    # Instagram Reels Yükle
    print("🚀 Instagram Hesabına Reels olarak yükleniyor...")
    ig_id = upload_instagram_reel(meta_page, str(clean_mp4), caption)

    # Drive durumunu 'uploaded' yap
    print("💾 Drive durumu güncelleniyor...")
    drive.files().update(
        fileId=mp4_obj["id"],
        body={
            "appProperties": {
                "meta_state": "uploaded",
                "meta_fb_id": str(fb_id),
                "meta_ig_id": str(ig_id)
            }
        }
    ).execute()

    # Temizle
    for f in [raw_mp4, clean_mp4, local_txt]:
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
## 🌿 Meta (Facebook & Instagram) Reels Yayını Başarılı!
| Bilgi | Değer |
| :--- | :--- |
| 📊 **İlerleme Durumu** | **{current_number} / {total_count}** (%{progress_pct:.1f}) |
| ⏳ **Kalan Video** | **{remaining_count - 1} adet** |
| 🎬 **Yüklenen Video** | `{mp4_obj['name']}` |
| 📘 **Facebook Sayfası** | Tarladaki Fasulye (Reels ID: `{fb_id}`) |
| 📸 **Instagram Hesabı** | @tarladakifasulye_ (Reels ID: `{ig_id}`) |
"""
        with open(summary_file, "a", encoding="utf-8") as sf:
            sf.write(summary_md)

    print("\n" + "=" * 65)
    print(f"🎉 GÖREV BAŞARIYLA TAMAMLANDI! [ {current_number} / {total_count} ]")
    print(f"📘 Facebook Reels ID : {fb_id}")
    print(f"📸 Instagram Reels ID: {ig_id}")
    print("=" * 65)

if __name__ == "__main__":
    if os.environ.get("ENABLE_LEGACY_PUBLISHER") != "I_UNDERSTAND":
        raise SystemExit("Eski motor devre dışı. Aktif giriş: scheduled_multi_publisher.py")
    run_cloud_meta()
