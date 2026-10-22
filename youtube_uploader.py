import json
import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload"
]

def get_youtube_client():
    """Yerel token veya GitHub Secrets ile baglan."""
    secret = os.getenv("YOUTUBE_TOKEN_JSON")
    if secret:
        token_data = json.loads(secret)
    elif TOKEN_FILE.exists():
        token_data = json.loads(
            TOKEN_FILE.read_text(encoding="utf-8")
        )
    else:
        raise FileNotFoundError(
            "YouTube token bulunamadi."
        )

    credentials = Credentials.from_authorized_user_info(
        token_data, SCOPES
    )

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        if TOKEN_FILE.exists():
            TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=credentials)

def upload_video(youtube, file_path, title, description, privacy_status="private"):
    """Videoyu resumable upload ile YouTube'a yukler."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Video dosyasi bulunamadi: {file_path}")

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "23"  # Komedi / Eglence
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        str(file_path),
        chunksize=4 * 1024 * 1024,
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            print(f"Yukleme durumu: %{progress}", end="\r", flush=True)

    video_id = response.get("id")
    print(f"\nYukleme tamamlandi! Video ID: {video_id}")
    return video_id
