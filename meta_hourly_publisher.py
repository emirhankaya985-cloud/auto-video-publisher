import os
import sys
import json
import time
import subprocess
from pathlib import Path
from drive_handler import get_drive_client
from meta_uploader import upload_instagram_reel, upload_facebook_reel, refresh_instagram_id, get_page_info

BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / "meta_history.json"
TEMP_DIR = BASE_DIR / "temp_meta"
TEMP_DIR.mkdir(exist_ok=True)

DRIVE_FOLDER_ID = '11zbrunHoiTZyJ8JDsj99ascO66mmCj-M'  # Drive sse klasoru
TARGET_ACCOUNT = "Tarladaki Fasulye"

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except:
            pass
    # Eski instagram_history.json varsa oradan devral
    old_ig = BASE_DIR / "instagram_history.json"
    ig_done = []
    if old_ig.exists():
        try:
            ig_done = json.loads(old_ig.read_text(encoding="utf-8"))
        except:
            pass
    return {"instagram": ig_done, "facebook": []}

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

def get_drive_pairs(service):
    """Drive'daki sse klasorundeki tum eslesen MP4 ve TXT dosyalarini sirali doner."""
    query = f"'{DRIVE_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=1000
    ).execute()
    files = results.get("files", [])
    
    mp4_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".mp4")}
    txt_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".txt")}
    
    matching_stems = sorted(list(set(mp4_files.keys()) & set(txt_files.keys())), key=lambda x: int(x) if x.isdigit() else x)
    return matching_stems, mp4_files, txt_files

def download_file(service, file_id, dest_path):
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as f:
        f.write(request.execute())

def clean_video_metadata(input_path, output_path):
    """FFmpeg ile videonun tum meta verilerini sifirlar (kayipsiz stream copy)."""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-map_metadata", "-1",
        "-c", "copy",
        str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def publish_hourly():
    print("=" * 65)
    print(f"🌿 META OTONOM YAYINCI BAŞLATILIYOR ({TARGET_ACCOUNT})")
    print("=" * 65)
    
    # 1. Instagram Hesabini Dogrula
    ig_id = refresh_instagram_id(TARGET_ACCOUNT)
    if not ig_id:
        print(f"❌ HATA: {TARGET_ACCOUNT} icin Instagram baglantisi bulunamadi!")
        return False
        
    page, _ = get_page_info(TARGET_ACCOUNT)
    print(f"📘 Facebook Sayfası: {page['page_name']} (ID: {page['page_id']})")
    print(f"📸 Instagram Hesabı: @tarladakifasulye_ (ID: {ig_id})")
    
    # 2. Gecmisi ve Siradaki Dosyalari Bul
    service = get_drive_client()
    stems, mp4_dict, txt_dict = get_drive_pairs(service)
    history = load_history()
    
    # Yuklenecek videoyu sec:
    # Oncelikle hem Instagram hem Facebook tarafinda eksik olan videolari bul
    target_stem = None
    needs_fb = False
    needs_ig = False
    
    for stem in stems:
        has_fb = stem in history.get("facebook", [])
        has_ig = stem in history.get("instagram", [])
        if not has_fb or not has_ig:
            target_stem = stem
            needs_fb = not has_fb
            needs_ig = not has_ig
            break
            
    if not target_stem:
        print("ℹ️ Yuklenecek yeni video cifti bulunamadi (Tum videolar paylasilmis)!")
        return False
        
    print(f"\n🎬 İşlenecek İçerik: Video {target_stem}")
    print(f"   -> Facebook'a yüklenecek mi?: {'EVET' if needs_fb else 'Zaten yüklü'}")
    print(f"   -> Instagram'a yüklenecek mi?: {'EVET' if needs_ig else 'Zaten yüklü'}")
    
    # 3. Gecici Olarak Indir ve Meta Verilerini Temizle
    raw_video = TEMP_DIR / f"raw_{target_stem}.mp4"
    clean_video = TEMP_DIR / f"clean_{target_stem}.mp4"
    txt_path = TEMP_DIR / f"{target_stem}.txt"
    
    print("\n📥 Drive'dan indiriliyor (Orijinallere asla dokunulmuyor)...")
    download_file(service, mp4_dict[target_stem]["id"], raw_video)
    download_file(service, txt_dict[target_stem]["id"], txt_path)
    
    caption = txt_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not caption:
        caption = "🔥 #reels #viral #shorts #keşfet"
    elif "#" not in caption:
        caption += "\n\n#reels #viral #kesfet #trend"
        
    print("🧹 FFmpeg ile meta verileri sıfırlanıyor...")
    clean_video_metadata(raw_video, clean_video)
    
    success_any = False
    
    # 4. Facebook Reels Paylasimi
    if needs_fb:
        try:
            print("\n🚀 Facebook Sayfasına Reels olarak yükleniyor...")
            fb_vid_id = upload_facebook_reel(str(clean_video), caption)
            print(f"✅ Facebook Reels Başarılı! (ID: {fb_vid_id})")
            history.setdefault("facebook", []).append(target_stem)
            save_history(history)
            success_any = True
        except Exception as e:
            print(f"❌ Facebook yükleme hatası: {e}")
            
    # 5. Instagram Reels Paylasimi
    if needs_ig:
        try:
            print("\n🚀 Instagram Hesabına Reels olarak yükleniyor...")
            ig_reel_id = upload_instagram_reel(str(clean_video), caption)
            print(f"✅ Instagram Reels Başarılı! (ID: {ig_reel_id})")
            history.setdefault("instagram", []).append(target_stem)
            save_history(history)
            success_any = True
        except Exception as e:
            print(f"❌ Instagram yükleme hatası: {e}")
            
    # Gecici Dosyalari Temizle
    for f in [raw_video, clean_video, txt_path]:
        if f.exists():
            f.unlink()
            
    print(f"\n🎉 İşlem Tamamlandı: Video {target_stem} başarıyla işlendi!")
    return success_any

if __name__ == '__main__':
    publish_hourly()
