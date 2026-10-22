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
from cloud_omnichannel_publisher import upload_facebook_reel, upload_instagram_reel, create_instagram_cover_video
from instagram_media_compat import prepare_instagram_upload
from scheduled_multi_publisher import platform_content_from_txt
from ordered_channels import toonzone_metadata


APPROVED_PAGES = {"Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen", "Daily Laugh Lab", "Film Mağarası", "Filmmagrasi", "ToonZone"}


def download(file_id: str, destination: Path) -> None:
    if not file_id or not all(c.isalnum() or c in "-_" for c in file_id):
        raise ValueError("Geçersiz Drive dosya kimliği")
    subprocess.run(
        ["gdown", f"https://drive.google.com/uc?id={file_id}", "--output", str(destination)],
        check=True, timeout=300,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Paylaşılan Drive dosyası indirilemedi")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--video-id", required=True)
    p.add_argument("--text-id", default="")
    p.add_argument("--cover-id", default="")
    p.add_argument("--page", choices=sorted(APPROVED_PAGES), required=True)
    p.add_argument("--platform", choices=("both", "facebook", "instagram"), default="both")
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
        if args.text_id:
            download(args.text_id, caption_file)
        with video.open("rb") as fh:
            header = fh.read(8)
        if video.stat().st_size < 1024 or header[4:8] != b"ftyp":
            raise RuntimeError("İndirilen dosya geçerli MP4 değil")
        if args.page == "ToonZone":
            if not args.cover_id:
                raise ValueError("ToonZone için eşleşen kapak kimliği gerekli")
            facebook_copy = instagram_copy = toonzone_metadata(video.stem)["description"]
            cover = Path(tmp) / "cover.png"
            download(args.cover_id, cover)
            video = create_instagram_cover_video(video, cover, Path(tmp) / "toonzone-with-cover.mp4")
        else:
            if not args.text_id:
                raise ValueError("Bu kanal için eşleşen açıklama dosyası gerekli")
            raw_copy = caption_file.read_text(encoding="utf-8-sig").strip()
            _, _, facebook_copy, instagram_copy, _ = platform_content_from_txt(
                raw_copy, video.stem, "film" if args.page in {"Film Mağarası", "Filmmagrasi"} else "tarladaki"
            )
        if not facebook_copy or not instagram_copy or len(instagram_copy) > 2200:
            raise RuntimeError("Platform açıklaması boş veya Instagram sınırını aşıyor")
        if args.platform in ("both", "facebook"):
            fb_id = upload_facebook_reel(page, str(video), facebook_copy)
            print(json.dumps({"page": args.page, "file": args.expected_video_name, "facebook_id": str(fb_id)}, ensure_ascii=False), flush=True)
        if args.platform in ("both", "instagram"):
            if not page.get("instagram_id"):
                raise RuntimeError("Seçilen sayfaya bağlı Instagram hesabı yok")
            prepared = prepare_instagram_upload(
                video, Path(tmp) / "instagram.mp4",
                prefer_remux=True, film_compact=args.page in {"Film Mağarası", "Filmmagrasi"},
                toonzone_compact=args.page == "ToonZone",
            )
            ig_id = upload_instagram_reel(page, str(prepared), instagram_copy, append_store_link=False)
            print(json.dumps({"page": args.page, "file": args.expected_video_name, "instagram_id": str(ig_id)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
