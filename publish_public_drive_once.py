"""Publish an explicitly selected, link-shared Drive video without Drive OAuth.

The file IDs must come from the approved shared folder. This is a one-shot
recovery path; it does not infer the next item from Drive's private properties.
"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from meta_auth_loader import load_meta_auth
from cloud_omnichannel_publisher import upload_facebook_reel, upload_instagram_reel


APPROVED_PAGES = {"Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen", "Daily Laugh Lab", "Film Mağarası", "Filmmagrasi", "ToonZone"}


def download(file_id: str, destination: Path) -> None:
    if not file_id or not all(c.isalnum() or c in "-_" for c in file_id):
        raise ValueError("Geçersiz Drive dosya kimliği")
    subprocess.run(
        ["gdown", "--id", file_id, "--output", str(destination)],
        check=True, timeout=300,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Paylaşılan Drive dosyası indirilemedi")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--video-id", required=True)
    p.add_argument("--text-id", required=True)
    p.add_argument("--page", choices=sorted(APPROVED_PAGES), required=True)
    p.add_argument("--expected-video-name", required=True)
    args = p.parse_args()
    if not args.expected_video_name.lower().endswith(".mp4") or "/" in args.expected_video_name:
        raise ValueError("Video adı .mp4 olmalı")
    pages = load_meta_auth()["pages"]
    matches = [x for x in pages if x["page_name"].casefold() == args.page.casefold()]
    if len(matches) != 1:
        raise RuntimeError("Meta hesap eşleşmesi tekil değil")
    page = matches[0]
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / args.expected_video_name
        caption_file = Path(tmp) / "caption.txt"
        download(args.video_id, video)
        download(args.text_id, caption_file)
        if video.stat().st_size < 1024 or video.read_bytes()[:8][4:8] != b"ftyp":
            raise RuntimeError("İndirilen dosya geçerli MP4 değil")
        caption = caption_file.read_text(encoding="utf-8-sig").strip()
        if not caption or len(caption) > 2200:
            raise RuntimeError("Açıklama boş veya çok uzun")
        fb_id = upload_facebook_reel(page, str(video), caption)
        print(json.dumps({"page": args.page, "file": args.expected_video_name, "facebook_id": str(fb_id)}, ensure_ascii=False), flush=True)
        if page.get("instagram_id"):
            ig_id = upload_instagram_reel(page, str(video), caption, append_store_link=False)
            print(json.dumps({"page": args.page, "file": args.expected_video_name, "instagram_id": str(ig_id)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
