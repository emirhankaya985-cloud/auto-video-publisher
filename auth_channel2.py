import os
import sys
import webbrowser
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

sys.stdout.reconfigure(line_buffering=True)

BASE_DIR = Path(__file__).resolve().parent
CLIENT_FILE = BASE_DIR / "client_secrets.json"
TOKEN_FILE = BASE_DIR / "token_channel2.json"
URL_FILE = BASE_DIR / "auth_channel2_url.txt"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload"
]

def main():
    if not CLIENT_FILE.exists():
        print("HATA: client_secrets.json bulunamadi.", flush=True)
        return

    print("=" * 60, flush=True)
    print("   2. YOUTUBE KANALI YETKİLENDİRMESİ", flush=True)
    print("=" * 60, flush=True)
    print("Tarayicida ayni Gmail hesabini sectikten sonra 2. KANALINI sececeksin!", flush=True)

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

    webbrowser.register("windows_start_ch2", None, CustomBrowser(), preferred=True)

    print("Yetkilendirme sunucusu hazirlaniyor...", flush=True)
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        authorization_prompt_message="\nLUTFEN BU LINKI TARAYICINIZDA ACIN:\n{url}\n",
        access_type="offline",
        prompt="select_account consent",
        browser="windows_start_ch2"
    )

    if not credentials.refresh_token:
        print("HATA: Refresh token alinamadi.", flush=True)
        return

    TOKEN_FILE.write_text(
        credentials.to_json(),
        encoding="utf-8"
    )

    if URL_FILE.exists():
        try:
            URL_FILE.unlink()
        except Exception:
            pass

    print("\n" + "=" * 60, flush=True)
    print("🎉 BASARILI: 2. KANALIN token_channel2.json DOSYASI OLUSTURULDU!", flush=True)
    print(f"Konum: {TOKEN_FILE}", flush=True)
    print("=" * 60, flush=True)

if __name__ == "__main__":
    main()
