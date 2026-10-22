"""Disabled-by-default Google Drive cover artwork support.

No publisher imports this module yet. Activation requires both
``COVER_FEATURE_ENABLED=true`` and ``COVER_DRIVE_FOLDER_ID`` plus an explicit
channel/source scope, preventing same-named videos from crossing channels.
"""

from __future__ import annotations

import os
import io
import struct
from dataclasses import dataclass

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png"}


@dataclass(frozen=True)
class CoverScope:
    channel_key: str
    source_folder_id: str
    cover_subfolder_id: str


def cover_config() -> str | None:
    enabled = os.getenv("COVER_FEATURE_ENABLED", "false").strip().lower() == "true"
    folder_id = os.getenv("COVER_DRIVE_FOLDER_ID", "").strip()
    if not enabled:
        return None
    if not folder_id:
        raise RuntimeError("Kapak özelliği açık ancak COVER_DRIVE_FOLDER_ID eksik")
    return folder_id


def match_cover(files: list[dict], video_stem: str, scope: CoverScope) -> dict | None:
    """Match one exact stem inside the channel-specific cover subfolder."""
    matches = []
    for item in files:
        name = item.get("name", "")
        stem, dot, extension = name.rpartition(".")
        if not dot or f".{extension.lower()}" not in SUPPORTED_EXTENSIONS:
            continue
        if stem != video_stem or scope.cover_subfolder_id not in item.get("parents", []):
            continue
        # Normal Drive uploads do not carry appProperties. The channel-specific
        # parent folder is the mandatory isolation boundary. If metadata is
        # present, validate it as an additional guard.
        properties = item.get("appProperties") or {}
        if properties.get("cover_channel_key") not in {None, scope.channel_key}:
            continue
        if properties.get("cover_source_folder_id") not in {None, scope.source_folder_id}:
            continue
        matches.append(item)
    if len(matches) > 1:
        raise RuntimeError(f"Birden fazla kapak bulundu: {scope.channel_key}/{video_stem}")
    return matches[0] if matches else None


def match_toonzone_cover(video: dict, cover_files: list[dict], scope: CoverScope) -> dict:
    """Fail-closed exact video/cover pairing for ToonZone dry-runs.

    The cover stem must equal the MP4 stem (for example
    ``S01E01_The_Power_Part1``).  This prevents a cover from another episode,
    part, or channel being attached silently.
    """
    name = str(video.get("name") or "")
    if not name.casefold().endswith(".mp4"):
        raise RuntimeError("ToonZone videos must be MP4 files")
    video_stem = name[:-4]
    cover = match_cover(cover_files, video_stem, scope)
    if cover is None:
        raise RuntimeError(f"ToonZone kapağı bulunamadı: {video_stem}")
    return cover


def image_dimensions(data: bytes, mime_type: str) -> tuple[int, int]:
    if mime_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if mime_type == "image/jpeg" and data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 <= len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset:offset + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if offset + 7 > len(data):
                    break
                return (
                    int.from_bytes(data[offset + 5:offset + 7], "big"),
                    int.from_bytes(data[offset + 3:offset + 5], "big"),
                )
            if length < 2:
                break
            offset += length
    raise ValueError("Geçersiz veya desteklenmeyen kapak görseli")


def validate_cover(data: bytes, mime_type: str) -> tuple[int, int]:
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError("Kapak yalnızca JPG/JPEG veya PNG olabilir")
    width, height = image_dimensions(data, mime_type)
    if width <= 0 or height <= 0 or abs((width / height) - 0.75) > 0.002:
        raise ValueError(f"Kapak oranı 3:4 değil: {width}x{height}")
    return width, height


def download_and_validate_cover(drive, cover: dict) -> tuple[bytes, tuple[int, int]]:
    """Download one already-scoped Drive image and validate it in memory."""
    mime_type = cover.get("mimeType", "")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, drive.files().get_media(fileId=cover["id"]))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    data = buffer.getvalue()
    return data, validate_cover(data, mime_type)


def set_youtube_thumbnail(youtube, video_id: str, image_path: str, mime_type: str):
    """Prepared API call; callers must treat failure as non-fatal to the video."""
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError("YouTube kapağı için desteklenmeyen MIME türü")
    return youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(image_path, mimetype=mime_type, resumable=False),
    ).execute()


PLATFORM_COVER_POLICY = {
    "youtube": "api_thumbnail_set",
    # Instagram cover_url requires a publicly fetchable image URL. Private
    # Drive bytes cannot safely be passed directly, so activation stays blocked.
    "instagram": "requires_public_cover_url",
    # The reviewed Page video_reels publish endpoint exposes no custom cover.
    "facebook": "unsupported",
}

FIXED_ACCOUNT_COVER_FILENAMES = {
    "tarladaki": "tarladaki.jpg",
    "penguen": "penguen.jpg",
    "gonle": "gonle.jpg",
    "daily": "daily.jpg",
    "film": "film.jpg",
    "cartoon_tr": "cizgifilm.jpg",
    "oddframes": "oddframes.jpg",
}


def match_fixed_account_cover(files: list[dict], scope: CoverScope) -> dict | None:
    """Return one channel-scoped fixed cover without crossing folders."""
    filename = FIXED_ACCOUNT_COVER_FILENAMES.get(scope.channel_key)
    if not filename:
        raise RuntimeError(f"Sabit kapak adı tanımsız: {scope.channel_key}")
    matches = [
        item for item in files
        if item.get("name", "").casefold() == filename.casefold()
        and scope.cover_subfolder_id in item.get("parents", [])
    ]
    if len(matches) > 1:
        raise RuntimeError(f"Birden fazla sabit kapak bulundu: {scope.channel_key}/{filename}")
    return matches[0] if matches else None

