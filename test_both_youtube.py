import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def check_token(token_file_name, channel_label):
    token_path = BASE_DIR / token_file_name
    print(f"\n--- {channel_label} ({token_file_name}) Kontrol Ediliyor ---")
    
    if not token_path.exists():
        print(f"[HATA] {token_file_name} dosyasi bulunamadi!")
        return False
        
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
        creds = Credentials.from_authorized_user_info(data, SCOPES)
        
        # Token suresi dolmussa yenile
        if creds.expired and creds.refresh_token:
            print("Token suresi dolmus, yenileniyor...")
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            print("Token basariyla yenilendi.")
            
        youtube = build("youtube", "v3", credentials=creds)
        print(f"[BASARILI] {channel_label} baglantisi aktif ve yuklemeye hazir!")
        print(f"Scopes: {creds.scopes}")
        return True
    except Exception as e:
        print(f"[HATA] {channel_label} test edilirken sorun cikti: {e}")
        return False

if __name__ == "__main__":
    ch1 = check_token("token_channel1.json", "1. YOUTUBE KANALI")
    ch2 = check_token("token_channel2.json", "2. YOUTUBE KANALI")
    
    print("\n" + "=" * 50)
    if ch1 and ch2:
        print("SONUC: HER IKI YOUTUBE KANALI DA %100 BAGLI VE AKTIF!")
    else:
        print("SONUC: Bazi kanallarda yetkilendirme eksigi var.")
    print("=" * 50)
