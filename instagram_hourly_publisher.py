import os
import sys
import json
import time
import subprocess
from pathlib import Path
from drive_handler import get_drive_client
from meta_uploader import upload_instagram_reel, refresh_instagram_id

BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / "instagram_history.json"
TEMP_DIR = BASE_DIR / "temp_ig"
TEMP_DIR.mkdir(exist_ok=True)

DRIVE_FOLDER_ID = '11zbrunHoiTZyJ8JDsj99ascO66mmCj-M'  # sse klasoru

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except:
            return []
    return []

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

def get_next_pair():
    """Drive'daki sse klasorunden henuz Instagram'a yuklenmemis siradaki video ciftini bulur."""
    service = get_drive_client()
    history = load_history()
    
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
    
    for stem in matching_stems:
        if stem not in history:
            return mp4_files[stem], txt_files[stem], stem
            
    return None, None, None

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

def publish_next_reel():
    print("=" * 60)
    print("📸 INSTAGRAM REELS OTONOM YAYINCI BAŞLATILIYOR...")
    print("=" * 60)
    
    # 1. Instagram Hesabini Kontrol Et
    ig_id = refresh_instagram_id()
    if not ig_id:
        print("❌ HATA: Instagram hesabi bagli degil veya yetkilendirilmemis!")
        return False
        
    # 2. Siradaki Videoyu Drive'dan Bul
    service = get_drive_client()
    mp4_file, txt_file, stem = get_next_pair()
    if not mp4_file:
        print("ℹ️ Yuklenecek yeni video bulunamadi!")
        return False
        
    print(f"🎬 Siradaki Icerik: Video {stem} ({mp4_file['name']})")
    
    # 3. Gecici Olarak Indir (Drive'daki orijinallere ASLA dokunulmaz)
    raw_video = TEMP_DIR / f"raw_{stem}.mp4"
    clean_video = TEMP_DIR / f"clean_{stem}.mp4"
    txt_path = TEMP_DIR / f"{stem}.txt"
    
    print("📥 Drive'dan indiriliyor (Orijinallere dokunulmuyor)...")
    download_file(service, mp4_file["id"], raw_video)
    download_file(service, txt_file["id"], txt_path)
    
    # Metni Oku (Orijinal aciklama)
    caption = txt_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not caption:
        caption = "🔥 #reels #viral #shorts #keşfet"
    else:
        # Eger etiket yoksa Reels icin populer etiketler ekle
        if "#" not in caption:
            caption += "\n\n#reels #viral #kesfet #trend"
            
    print(f"📝 Aciklama Metni ({len(caption)} karakter):\n{caption[:100]}...")
    
    # 4. Meta Verileri Temizle
    print("🧹 FFmpeg ile meta verileri sifirlaniyor...")
    clean_video_metadata(raw_video, clean_video)
    
    # 5. Instagram Reels Olarak Yukle
    print("🚀 Instagram Reels sunucusuna gonderiliyor...")
    try:
        reel_id = upload_instagram_reel(str(clean_video), caption)
        print(f"✅ TEBRIKLER! Instagram Reels yayinda! (Reel ID: {reel_id})")
        
        # Gecmise kaydet
        history = load_history()
        history.append(stem)
        save_history(history)
        
        # Temizlik
        for f in [raw_video, clean_video, txt_path]:
            if f.exists():
                f.unlink()
        return True
    except Exception as e:
        print(f"❌ Yukleme sirasinda hata olustu: {e}")
        return False

if __name__ == '__main__':
    publish_next_reel()
