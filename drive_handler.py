import os
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent
SOURCE_FOLDER = os.getenv(
    "DRIVE_SOURCE_FOLDER_ID",
    "12lHQ531AfiHf9gEMMSBB1I2NI_yHoRHZ"
)
DEST_FOLDER = os.getenv(
    "DRIVE_DEST_FOLDER_ID",
    "1q-QBn7fvjvqwWri4YFwTExbOCeL8BzD1"
)
SCOPES = [
    "https://www.googleapis.com/auth/drive"
]

def get_drive_client():
    """Yerel dosyadan veya GitHub Secrets'tan yetkilendir."""
    secret = os.getenv("DRIVE_TOKEN_JSON")
    if secret:
        token_data = json.loads(secret)
    else:
        token_file = BASE_DIR / "drive_token.json"
        if not token_file.exists():
            raise FileNotFoundError("drive_token.json bulunamadi.")
        token_data = json.loads(token_file.read_text(encoding="utf-8"))

    credentials = Credentials.from_authorized_user_info(token_data, SCOPES)

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_file = BASE_DIR / "drive_token.json"
        if token_file.exists():
            token_file.write_text(credentials.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=credentials)

def get_next_video_pair(service, folder_id=SOURCE_FOLDER):
    """Klasördeki eşleşen MP4 ve TXT dosyalarını bulup sıradakini döner."""
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=100
    ).execute()
    files = results.get("files", [])

    mp4_files = {
        Path(f["name"]).stem: f
        for f in files
        if f["name"].lower().endswith(".mp4")
    }
    txt_files = {
        Path(f["name"]).stem: f
        for f in files
        if f["name"].lower().endswith(".txt")
    }

    matching_stems = sorted(list(set(mp4_files.keys()) & set(txt_files.keys())))

    if not matching_stems:
        return None, None

    next_stem = matching_stems[0]
    return mp4_files[next_stem], txt_files[next_stem]

if __name__ == "__main__":
    try:
        service = get_drive_client()
        print("Google Drive baglantisi basarili.")
        
        mp4_file, txt_file = get_next_video_pair(service)
        if mp4_file and txt_file:
            print(f"Siradaki video: {mp4_file['name']}")
            print(f"Aciklama dosyasi: {txt_file['name']}")
        else:
            print("Yuklenecekler klasorunde eslesen MP4 ve TXT cifti bulunamadi (Klasor bos olabilir).")
    except Exception as e:
        print(f"HATA: {e}")
