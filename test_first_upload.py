import os
import io
import sys
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload
from drive_handler import get_drive_client, SOURCE_FOLDER
from youtube_uploader import get_youtube_client, upload_video

def main():
    print("=" * 60)
    print("   ILK GERCEK YOUTUBE YUKLEME TESTI (1.mp4)")
    print("=" * 60)

    # 1. Drive ve YouTube istemcilerini baslat
    drive = get_drive_client()
    youtube = get_youtube_client()

    # 2. Drive'da 1.mp4 dosyasini bul
    query = f"'{SOURCE_FOLDER}' in parents and name = '1.mp4' and trashed = false"
    res = drive.files().list(
        q=query,
        fields="files(id, name, appProperties, size)"
    ).execute()
    files = res.get("files", [])

    if not files:
        print("[HATA] Drive'daki Yuklenecekler klasorunde '1.mp4' bulunamadi!")
        return

    target_file = files[0]
    file_id = target_file["id"]
    app_props = target_file.get("appProperties") or {}
    youtube_state = app_props.get("youtube_state")

    # 3. Mukerrer ve yarim kalma kontrolleri
    if youtube_state == "uploaded":
        y_id = app_props.get("youtube_id", "Bilinmiyor")
        print(f"[ENGEL] Bu video daha once yuklenmis! (YouTube ID: {y_id})")
        print("Mukerrer yuklemeyi onlemek icin islem durduruldu.")
        return

    if youtube_state == "uploading":
        print("[UYARI] Bu dosya daha once 'uploading' durumunda kalmis!")
        print("YouTube Studio uzerinden manuel kontrol etmeden otomatik tekrar yuklenemez.")
        return

    # 4. Gecici klasore indir
    temp_dir = Path("temp_download")
    temp_dir.mkdir(exist_ok=True)
    local_path = temp_dir / "1.mp4"

    print(f"\n[1/3] Video Drive'dan indiriliyor: {target_file['name']} ({file_id})")
    request = drive.files().get_media(fileId=file_id)
    with io.FileIO(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 4)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"-> Indirme durumu: %{int(status.progress() * 100)}", end="\r", flush=True)
    print("\n-> Indirme tamamlandi!")

    # 5. Drive uzerinde durumu 'uploading' olarak kaydet
    print("\n[2/3] Drive durumu 'uploading' olarak isaretleniyor...")
    drive.files().update(
        fileId=file_id,
        body={"appProperties": {"youtube_state": "uploading"}}
    ).execute()

    # 6. YouTube'a yukle
    video_id = None
    try:
        print("\n[3/3] YouTube'a yukleniyor (Gizlilik: private)...")
        video_id = upload_video(
            youtube=youtube,
            file_path=str(local_path),
            title="Test 1 #Shorts",
            description="",
            privacy_status="private"
        )
    except Exception as e:
        print(f"\n[HATA] YouTube yuklemesi sirasinda hata olustu: {e}")
        print("Drive durumu 'uploading' olarak kaldi, manuel kontrol gerekebilir.")
        return
    finally:
        # Gecici yerel dosyayi sil
        if local_path.exists():
            try:
                local_path.unlink()
                temp_dir.rmdir()
            except Exception:
                pass

    # 7. Basarili yukleme sonrasi Drive appProperties guncelle
    if video_id:
        drive.files().update(
            fileId=file_id,
            body={
                "appProperties": {
                    "youtube_state": "uploaded",
                    "youtube_id": video_id
                }
            }
        ).execute()

        video_url = f"https://youtube.com/shorts/{video_id}"
        print("\n" + "=" * 60)
        print("🎉 TEBRİKLER! İLK VİDEO YÜKLEMESİ BAŞARIYLA TAMAMLANDI!")
        print(f"YouTube Video ID   : {video_id}")
        print(f"YouTube Shorts Link: {video_url}")
        print("Drive Durumu       : 'uploaded' olarak isaretlendi.")
        print("=" * 60)

if __name__ == "__main__":
    main()
