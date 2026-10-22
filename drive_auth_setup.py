import os
import sys
import webbrowser
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

sys.stdout.reconfigure(line_buffering=True)

BASE_DIR = Path(__file__).resolve().parent
CLIENT_FILE = BASE_DIR / "client_secrets.json"
DRIVE_TOKEN_FILE = BASE_DIR / "drive_token.json"
URL_FILE = BASE_DIR / "drive_auth_url.txt"

# Google Drive'daki dosyalari okuma, indirme ve tasima izinleri
SCOPES = [
    "https://www.googleapis.com/auth/drive"
]

def main():
    if not CLIENT_FILE.exists():
        print("HATA: client_secrets.json bulunamadi.", flush=True)
        return

    if DRIVE_TOKEN_FILE.exists():
        print("drive_token.json zaten mevcut.", flush=True)
        print("Mevcut yetkilendirme dosyasi korunuyor.")
        return

    print("Google Drive yetkilendirmesi baslatiliyor...", flush=True)
    print("DIKKAT: Bu adimda BIRINCI Gmail hesabini (Drive'inin oldugu ana hesap) sececeksin!", flush=True)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_FILE),
        scopes=SCOPES
    )

    class CustomBrowser:
        def open(self, url, new=0, autoraise=True):
            try:
                URL_FILE.write_text(url, encoding="utf-8")
                os.system(f'start "" "{url}"')
            except Exception as e:
                print(f"Start hatasi: {e}", flush=True)
            return True

    webbrowser.register("windows_start_drive", None, CustomBrowser(), preferred=True)

    print("Yetkilendirme sunucusu hazirlaniyor...", flush=True)
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        authorization_prompt_message="\nLUTFEN BU LINKI TARAYICINIZDA ACIN:\n{url}\n",
        access_type="offline",
        prompt="consent",
        browser="windows_start_drive"
    )

    if not credentials.refresh_token:
        print("HATA: Refresh token alinamadi.", flush=True)
        return

    DRIVE_TOKEN_FILE.write_text(
        credentials.to_json(),
        encoding="utf-8"
    )

    if URL_FILE.exists():
        try:
            URL_FILE.unlink()
        except Exception:
            pass

    print("\n" + "=" * 50, flush=True)
    print("BASARILI: drive_token.json olusturuldu!", flush=True)
    print(f"Konum: {DRIVE_TOKEN_FILE}", flush=True)
    print("=" * 50, flush=True)

if __name__ == "__main__":
    main()
