import os
from pathlib import Path
from collections import Counter
from drive_handler import get_drive_client, SOURCE_FOLDER

def audit_drive_folder():
    service = get_drive_client()
    print("Google Drive baglantisi basarili.")
    print(f"Klasor ID: {SOURCE_FOLDER} taraniyor...\n" + "=" * 50)

    # Tum dosyalari sayfalama (pagination) ile cek
    files = []
    page_token = None
    query = f"'{SOURCE_FOLDER}' in parents and trashed = false"

    while True:
        results = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=1000,
            pageToken=page_token
        ).execute()

        files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    # 1. Tum isimleri ve tekrarlari analiz et
    all_names = [f["name"] for f in files]
    name_counts = Counter(all_names)
    duplicates = [name for name, count in name_counts.items() if count > 1]

    # MP4 ve TXT dosyalarini ayir
    mp4_files = [f for f in files if f["name"].lower().endswith(".mp4")]
    txt_files = [f for f in files if f["name"].lower().endswith(".txt")]

    mp4_stems = {Path(f["name"]).stem: f for f in mp4_files}
    txt_stems = {Path(f["name"]).stem: f for f in txt_files}

    # Eslestirme analizi
    matched_stems = sorted(list(set(mp4_stems.keys()) & set(txt_stems.keys())))
    unmatched_mp4 = sorted(list(set(mp4_stems.keys()) - set(txt_stems.keys())))
    unmatched_txt = sorted(list(set(txt_stems.keys()) - set(mp4_stems.keys())))

    # Sonuclari ekrana yazdir
    print(f"1. Toplam MP4 Sayisi: {len(mp4_files)}")
    print(f"2. Toplam TXT Sayisi: {len(txt_files)}")
    print(f"3. Eslesen Cift Sayisi (MP4 + TXT): {len(matched_stems)}")

    print(f"4. Eslestirilemeyen Dosyalar:")
    if unmatched_mp4:
        print(f"   - TXT'si Olmayan MP4'ler ({len(unmatched_mp4)} adet): {unmatched_mp4[:5]}")
    else:
        print("   - TXT'si Olmayan MP4: Yok (Hepsi eslesiyor)")

    if unmatched_txt:
        print(f"   - MP4'u Olmayan TXT'ler ({len(unmatched_txt)} adet): {unmatched_txt[:5]}")
    else:
        print("   - MP4'u Olmayan TXT: Yok (Hepsi eslesiyor)")

    print(f"5. Ayni Isimde Birden Fazla Olan Dosyalar:")
    if duplicates:
        print(f"   - UYARI! Tekrarlanan dosya isimleri: {duplicates}")
    else:
        print("   - Tekrarlanan dosya adi yok (Tertemiz)")

    print(f"6. Siradaki Yuklenecek Video Cifti:")
    if matched_stems:
        first = matched_stems[0]
        print(f"   - MP4: {mp4_stems[first]['name']}")
        print(f"   - TXT: {txt_stems[first]['name']}")
    else:
        print("   - Yuklenecek eslesen cift bulunamadi.")

    print("=" * 50)

if __name__ == "__main__":
    audit_drive_folder()
