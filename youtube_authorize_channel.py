"""One-time LOCAL YouTube OAuth setup for three channels (never uploads media).

Run on a trusted computer with a browser. The resulting authorized-user JSON
goes to GitHub Actions Secrets, NOT to Git. The scheduled runtime stays in cloud.
"""
import argparse
import os
from pathlib import Path
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import AuthorizedSession

from youtube_readonly_connection import CHANNELS_URL, TARGETS, YOUTUBE_UPLOAD_SCOPE

TOKEN_PATHS = {
    "channel1": "token_channel1.json",
    "channel2": "token_channel2.json",
    "daily_laugh": "token_daily_laugh_lab.json",
}
ROOT = Path(__file__).resolve().parent


def verify_selected_channel(credentials, target, *, session_factory=AuthorizedSession):
    """Read profile identity before storing the credential."""
    _, expected_title, expected_id = TARGETS[target]
    session = session_factory(credentials)
    response = session.get(CHANNELS_URL, params={"part": "id,snippet", "mine": "true"},
                           timeout=20, allow_redirects=False)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise RuntimeError("YouTube kanal kimliği alınamadı.")
    channel = items[0]
    channel_id = channel.get("id")
    title = (channel.get("snippet") or {}).get("title")
    if not isinstance(channel_id, str) or not isinstance(title, str):
        raise RuntimeError("YouTube kanal kimliği eksik.")
    valid = channel_id == expected_id if expected_id else title.strip().casefold() == expected_title.casefold()
    if not valid:
        raise RuntimeError("Yetkilendirilen YouTube kanalı seçilen hesapla eşleşmiyor.")
    return channel_id, title


def authorize(target, *, base_dir=ROOT):
    if target not in TARGETS:
        raise ValueError("YouTube kanalı geçersiz.")
    base_dir = Path(base_dir)
    dest = base_dir / TOKEN_PATHS[target]
    client_path = base_dir / "client_secrets.json"
    if dest.exists():
        raise FileExistsError("Bu kanalın OAuth token dosyası zaten mevcut; üzerine yazılmadı.")
    if not client_path.is_file():
        raise FileNotFoundError("client_secrets.json yerel OAuth istemcisi bulunamadı.")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes=[YOUTUBE_UPLOAD_SCOPE])
    credentials = flow.run_local_server(host="localhost", port=0, open_browser=True,
                                        access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise RuntimeError("OAuth refresh token verilmedi.")
    channel_id, title = verify_selected_channel(credentials, target)
    # Exclusive create prevents overwriting an already-authorized channel.
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())
    print(f"PASS: {target} -> {title} ({channel_id}); token saved locally: {dest.name}.")
    print("Entire JSON should be stored in the selected TOKEN_*_JSON Actions secret. Do not paste it into chat.")
    return dest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe, local YouTube OAuth setup")
    parser.add_argument("channel", choices=TOKEN_PATHS)
    args = parser.parse_args(argv)
    try:
        authorize(args.channel)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}. No upload was attempted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
