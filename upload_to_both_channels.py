import os
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_client(token_filename):
    token_path = BASE_DIR / token_filename
    data = json.loads(token_path.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)

def upload_and_report(token_file, channel_label, video_path, title, description, privacy="public"):
    print("\n" + "=" * 60)
    print(f"[{channel_label}] YUKLEME BASLATILIYOR...")
    print(f"Video : {os.path.basename(video_path)}")
    print(f"Baslik: {title}")
    print(f"Mod   : {privacy}")
    print("=" * 60)

    youtube = get_client(token_file)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "23" # Mizah / Komedi
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        str(video_path),
        chunksize=1024 * 1024 * 4,
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
            print(f"-> Yukleme durumu: %{int(status.progress() * 100)}", end="\r", flush=True)

    video_id = response.get("id")
    snippet = response.get("snippet", {})
    channel_title = snippet.get("channelTitle", "Bilinmiyor")
    channel_id = snippet.get("channelId", "Bilinmiyor")
    published_status = response.get("status", {}).get("privacyStatus")

    print(f"\n[BASARILI] {channel_label} yuklemesi tamamlandi!")
    print(f"-> KANAL ADI       : {channel_title}")
    print(f"-> KANAL ID        : {channel_id}")
    print(f"-> VIDEO ID        : {video_id}")
    print(f"-> YAYIN DURUMU    : {published_status}")
    print(f"-> YOUTUBE LINKI   : https://youtube.com/shorts/{video_id}")

    return {
        "channel_title": channel_title,
        "video_id": video_id,
        "link": f"https://youtube.com/shorts/{video_id}"
    }

if __name__ == "__main__":
    v1 = r"C:\Users\emirh\Desktop\mahmut\Sosyal Medya 5\videos\primemizah0\10k_Icin_Takip_2.mp4"
    t1 = "10k için takip #shorts #mizah #komik"
    d1 = "10k için takip 😂\n\n👇 Abone olmayı ve beğenmeyi unutmayın! 🎬\n\n#Mizah #Komedi #Shorts"

    v2 = r"C:\Users\emirh\Desktop\mahmut\Sosyal Medya 5\videos\primemizah0\10k_Icin_Takip_Dostlar_Mizah_Tayfa8.mp4"
    t2 = "10k için takip dostlar #shorts #mizah #komik"
    d2 = "10k için takip dostlar 😂\n\n👇 Abone olmayı unutmayın! 🎬\n\n#Mizah #Komedi #Shorts"

    res1 = upload_and_report("token_channel1.json", "1. KANAL", v1, t1, d1, privacy="public")
    res2 = upload_and_report("token_channel2.json", "2. KANAL", v2, t2, d2, privacy="public")

    print("\n" + "=" * 60)
    print("🎉 HER İKİ KANALA DA VİDEO YÜKLENDİ VE YAYINLANDI!")
    print(f"1. Kanal Adı: {res1['channel_title']} -> {res1['link']}")
    print(f"2. Kanal Adı: {res2['channel_title']} -> {res2['link']}")
    print("=" * 60)
