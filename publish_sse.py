import os
import io
import re
import json
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload
from drive_handler import get_drive_client
from upload_to_both_channels import get_client, upload_and_report

SSE_FOLDER_ID = "137--TeBht1yikZpMfV9VSEADbKuXZtLT"

def parse_sse_txt_content(content: str) -> dict:
    """
    Başlık: ...
    Açıklama: ...
    Etiketler: ...
    formatındaki txt dosyasını ayıklar.
    """
    title = ""
    description = ""
    tags = []

    lines = content.splitlines()
    desc_lines = []
    
    current_section = None
    for line in lines:
        line_strip = line.strip()
        if line_strip.lower().startswith("başlık:") or line_strip.lower().startswith("baslik:"):
            title = line_strip.split(":", 1)[1].strip()
            current_section = "title"
        elif line_strip.lower().startswith("açıklama:") or line_strip.lower().startswith("aciklama:"):
            desc_lines.append(line_strip.split(":", 1)[1].strip())
            current_section = "desc"
        elif line_strip.lower().startswith("etiketler:") or line_strip.lower().startswith("tags:"):
            tag_line = line_strip.split(":", 1)[1].strip()
            tags = re.findall(r'#(\w+)', tag_line)
            current_section = "tags"
        else:
            if current_section == "desc" and line_strip:
                desc_lines.append(line_strip)

    description = "\n".join(desc_lines)
    
    # Başlıkta #Shorts yoksa ekle
    if "#shorts" not in title.lower():
        title = f"{title} #Shorts"

    # YouTube başlık limiti 100 karakter
    title = title[:100]

    return {
        "title": title,
        "description": description,
        "tags": tags[:30]
    }

def publish_next_from_sse(channel_token_file="token_channel1.json", channel_label="1. KANAL (Film Mağarası)", privacy="public"):
    drive = get_drive_client()
    print("=" * 60)
    print(f"[{channel_label}] SSE KLASORUNDEN SIRADAKI VIDEO YUKLENIYOR...")
    print(f"Klasor ID: {SSE_FOLDER_ID}")
    print("=" * 60)

    # Dosyalari cek
    query = f"'{SSE_FOLDER_ID}' in parents and trashed = false"
    res = drive.files().list(
        q=query,
        fields="files(id, name, appProperties, size)",
        pageSize=1000
    ).execute()
    files = res.get("files", [])

    mp4_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".mp4")}
    txt_files = {Path(f["name"]).stem: f for f in files if f["name"].lower().endswith(".txt")}

    # Sayisal sirala (1, 2, 3... 194 vb.)
    matched_stems = sorted(
        list(set(mp4_files.keys()) & set(txt_files.keys())),
        key=lambda x: int(x) if x.isdigit() else x
    )

    pending_target = None
    for stem in matched_stems:
        mp4_item = mp4_files[stem]
        props = mp4_item.get("appProperties") or {}
        if props.get("youtube_state") != "uploaded":
            pending_target = stem
            break

    if not pending_target:
        print("[BILGI] Yuklenecek yeni eslesmis video kalmadi! Tum eslesenler yuklendi.")
        return None

    mp4_obj = mp4_files[pending_target]
    txt_obj = txt_files[pending_target]

    print(f"\n[1/3] Secilen Video: {mp4_obj['name']} | Aciklama: {txt_obj['name']}")

    # Gecici klasore indir
    temp_dir = Path("temp_sse")
    temp_dir.mkdir(exist_ok=True)
    local_mp4 = temp_dir / mp4_obj["name"]
    local_txt = temp_dir / txt_obj["name"]

    # TXT indir ve oku
    req_txt = drive.files().get_media(fileId=txt_obj["id"])
    with io.FileIO(local_txt, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req_txt)
        downloader.next_chunk()

    txt_content = local_txt.read_text(encoding="utf-8", errors="ignore")
    parsed_meta = parse_sse_txt_content(txt_content)

    print(f"Baslik: {parsed_meta['title']}")

    # MP4 indir
    print(f"[2/3] MP4 indiriliyor ({mp4_obj['name']})...")
    req_mp4 = drive.files().get_media(fileId=mp4_obj["id"])
    with io.FileIO(local_mp4, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req_mp4, chunksize=1024*1024*4)
        done = False
        while not done:
            st, done = downloader.next_chunk()
            if st:
                print(f"-> Indirme: %{int(st.progress() * 100)}", end="\r", flush=True)
    print("\n-> Indirme tamamlandi!")

    # Drive durumunu 'uploading' yap
    drive.files().update(
        fileId=mp4_obj["id"],
        body={"appProperties": {"youtube_state": "uploading"}}
    ).execute()

    # YouTube'a yukle
    print(f"\n[3/3] YouTube'a yukleniyor ({channel_label})...")
    upload_res = upload_and_report(
        token_file=channel_token_file,
        channel_label=channel_label,
        video_path=str(local_mp4),
        title=parsed_meta["title"],
        description=f"{parsed_meta['description']}\n\n{' '.join(['#' + t for t in parsed_meta['tags']])}",
        privacy=privacy
    )

    # Drive durumunu 'uploaded' yap
    drive.files().update(
        fileId=mp4_obj["id"],
        body={"appProperties": {"youtube_state": "uploaded", "youtube_id": upload_res["video_id"]}}
    ).execute()

    # Gecici dosyalari temizle
    try:
        local_mp4.unlink()
        local_txt.unlink()
        temp_dir.rmdir()
    except Exception:
        pass

    return upload_res

if __name__ == "__main__":
    # Test: Ilk videoyu Film Magarasi kanalina yukle
    publish_next_from_sse(channel_token_file="token_channel1.json", channel_label="1. KANAL (Film Mağarası)", privacy="public")
