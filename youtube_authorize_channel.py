"""One-time LOCAL YouTube OAuth setup for four channels (never uploads media).

Run on a trusted computer with a browser. The resulting authorized-user JSON
goes to GitHub Actions Secrets, NOT to Git. The scheduled runtime stays in cloud.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import AuthorizedSession

from youtube_readonly_connection import CHANNELS_URL, TARGETS, YOUTUBE_AUTH_SCOPES

TOKEN_PATHS = {
    "channel1": "token_channel1.json",
    "channel2": "token_channel2.json",
    "daily_laugh": "token_daily_laugh_lab.json",
    "gonle_dusen": "token_gonle_dusen.json",
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


def authorize(target, *, base_dir=ROOT, renew=False):
    if target not in TARGETS:
        raise ValueError("YouTube kanalı geçersiz.")
    base_dir = Path(base_dir)
    dest = base_dir / TOKEN_PATHS[target]
    client_path = base_dir / "client_secrets.json"
    if dest.is_symlink():
        raise RuntimeError("Token yolu sembolik bağ; güvenli yenileme durduruldu.")
    if dest.exists() and renew is not True:
        raise FileExistsError("Bu kanalın OAuth token dosyası zaten mevcut; --renew gerekli.")
    if not client_path.is_file():
        raise FileNotFoundError("client_secrets.json yerel OAuth istemcisi bulunamadı.")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes=list(YOUTUBE_AUTH_SCOPES))
    credentials = flow.run_local_server(host="localhost", port=0, open_browser=True,
                                        access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise RuntimeError("OAuth refresh token verilmedi.")
    channel_id, title = verify_selected_channel(credentials, target)
    # Only after an exact live channel GET succeeds may an expired local token
    # be replaced. The same-directory atomic replace keeps the old token
    # untouched if consent or identity verification fails.
    serialized = credentials.to_json()
    if dest.exists():
        fd, tmp_path = tempfile.mkstemp(prefix=".youtube-token-renew-", suffix=".tmp",
                                       dir=str(base_dir))
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, dest)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    else:
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(serialized)
    print(f"PASS: {target} -> {title} ({channel_id}); token saved locally: {dest.name}.")
    print("Entire JSON should be stored in the selected TOKEN_*_JSON Actions secret. Do not paste it into chat.")
    return dest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe, local YouTube OAuth setup")
    parser.add_argument("channel", choices=TOKEN_PATHS)
    parser.add_argument("--renew", action="store_true",
                        help="Refresh a local token only after fresh OAuth consent and exact channel verification")
    args = parser.parse_args(argv)
    try:
        authorize(args.channel, renew=args.renew)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}. No upload was attempted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
