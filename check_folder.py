import json
import os
from drive_handler import get_drive_client

def inspect():
    service = get_drive_client()
    folder_id = os.environ.get('TARGET_FOLDER_ID', '11zbrunHoiTZyJ8JDsj99ascO66mmCj-M')

    try:
        folder_info = service.files().get(
            fileId=folder_id,
            fields='id, name, mimeType, owners'
        ).execute()
        
        print("=" * 60)
        print("Klasor Bilgisi:")
        print(f"ID   : {folder_info.get('id')}")
        print(f"Isim : {folder_info.get('name')}")
        owners = folder_info.get('owners', [])
        if owners:
            print(f"Sahip: {owners[0].get('displayName')} ({owners[0].get('emailAddress')})")
        print("=" * 60)

        query = f"'{folder_id}' in parents and trashed = false"
        files = []
        page_token = None
        while True:
            results = service.files().list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()
            files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        print(f"Toplam Dosya Sayisi: {len(files)}\n")

        mp4_files = [f for f in files if f["name"].lower().endswith(".mp4")]
        txt_files = [f for f in files if f["name"].lower().endswith(".txt")]
        subfolders = [f for f in files if f["mimeType"] == "application/vnd.google-apps.folder"]

        print(f"- MP4 Dosyalari: {len(mp4_files)}")
        print(f"- TXT Dosyalari: {len(txt_files)}")
        print(f"- Alt Klasorler: {len(subfolders)}")

        if subfolders:
            print("\nAlt Klasorler:")
            for sf in subfolders:
                print(f"  * {sf['name']} (ID: {sf['id']})")

        print("\nIlk 10 Dosya Listesi:")
        for f in files[:10]:
            size = f.get('size')
            size_str = f"{int(size)/(1024*1024):.2f} MB" if size else "Klasor / Bilinmiyor"
            print(f"  - {f['name']} [{size_str}]")

        # Eslesen ciftler
        mp4_stems = {f["name"].rsplit(".", 1)[0] for f in mp4_files}
        txt_stems = {f["name"].rsplit(".", 1)[0] for f in txt_files}
        matched = mp4_stems & txt_stems
        print(f"\nEslesen MP4 + TXT Cift Sayisi: {len(matched)}")
        missing_txt = sorted(mp4_stems - txt_stems)
        missing_mp4 = sorted(txt_stems - mp4_stems)
        print(f"TXT'si Olmayan MP4 Sayisi: {len(missing_txt)}")
        print(f"MP4'u Olmayan TXT Sayisi: {len(missing_mp4)}")
        if missing_txt:
            print(f"TXT'si Olmayan Ilk 20: {missing_txt[:20]}")
        if missing_mp4:
            print(f"MP4'u Olmayan Ilk 20: {missing_mp4[:20]}")

    except Exception as e:
        print(f"HATA: {e}")

if __name__ == "__main__":
    inspect()
