"""Read-only exact ToonZone S01E04–S01E12 cover byte/identity acceptance.

Checks every matching Drive PNG by actual bytes and file identity. Does not
read or write Meta, does not claim the video source/remote thumbnail is verified.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, UnidentifiedImageError
from threads_toonzone_season import ordered_catalog

ROOT = Path("toonzone-cover-acceptance")
REPORT = ROOT / "result.json"
MIN_WIDTH = 320
MIN_HEIGHT = 320


def png_identity(path: Path):
    """Validate full PNG bytes, size and bounded raster characteristics."""
    if not path.is_file() or path.stat().st_size < 64:
        raise ValueError("empty_or_truncated_cover")
    with path.open("rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not_png_signature")
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError("not_png_format")
            width, height = image.size
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                raise ValueError("cover_resolution_too_small")
            image.verify()
        # Image.verify checks chunks without fully decoding pixel payload.
        # The separate load catches truncated IDAT/image-data corruption.
        with Image.open(path) as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("invalid_png_bytes") from None
    with path.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    return {"width": width, "height": height, "bytes": path.stat().st_size,
            "sha256": digest}


def verify_prepared_instagram_first_frame(cover_path, video_path, *, runner=None):
    """Fail before any Meta POST if a future ToonZone Reel loses its exact cover.

    Instagram's API selects a frame with thumb_offset=0. The actual transcoded
    MP4 (not an intermediate cover overlay) must start with this part's PNG.
    We never modify the source or published media.
    """
    import subprocess
    from PIL import ImageOps, ImageChops, ImageStat

    cover_path, video_path = Path(cover_path), Path(video_path)
    if not cover_path.is_file() or not video_path.is_file():
        raise RuntimeError("toonzone_preupload_source_or_cover_missing")
    runner = runner or subprocess.run
    with TemporaryDirectory(prefix="toonzone-reel-thumbnail-gate-") as folder:
        frame = Path(folder) / "first-frame.png"
        try:
            runner([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-y", "-i", str(video_path), "-frames:v", "1", str(frame),
            ], check=True, capture_output=True, timeout=90)
            with Image.open(cover_path) as original, Image.open(frame) as observed:
                if original.format != "PNG" or observed.width < 320 or observed.height < 320:
                    raise ValueError("toonzone_cover_or_frame_invalid")
                reference = ImageOps.pad(original.convert("RGB"), observed.size, color=(0, 0, 0))
                resized = observed.convert("RGB")
                delta = ImageChops.difference(reference.resize((90, 160)),
                                              resized.resize((90, 160)))
                distance = sum(ImageStat.Stat(delta).rms) / (3 * 255)
                if distance > 0.12:
                    raise ValueError("toonzone_transcoded_first_frame_not_original_cover")
                return {"first_frame_matches_cover": True,
                        "comparison_distance": round(distance, 6),
                        "first_frame_width": observed.width,
                        "first_frame_height": observed.height}
        except (OSError, ValueError, subprocess.SubprocessError):
            raise RuntimeError("toonzone_transcoded_first_frame_cover_held") from None


def assess(catalog_files, covers, *, download):
    """One isolated validation per part, with no source or publishing writes."""
    catalog = ordered_catalog(catalog_files)
    chosen = [row for row in catalog if 4 <= row["episode"] <= 12]
    expected = [(e, p) for e in range(4, 13) for p in range(1, 5)]
    if [(item["episode"], item["part"]) for item in chosen] != expected:
        raise ValueError("requested_episode_parts_missing_or_out_of_order")
    if len({row["id"] for row in chosen}) != 36:
        raise ValueError("duplicate_source_file_identity")

    entries = []
    with TemporaryDirectory(prefix="toonzone-36-covers-") as temporary:
        temp = Path(temporary)
        for row in chosen:
            image_name = Path(row["name"]).stem + ".png"
            entry = {"episode": row["episode"], "part": row["part"],
                     "source_name": row["name"], "cover_name": image_name,
                     "state": "held", "reason": None}
            cover = covers.get(image_name)
            if not isinstance(cover, dict) or not cover.get("id"):
                entry["reason"] = "exact_drive_cover_missing"
            else:
                destination = temp / image_name
                try:
                    transferred = Path(download(cover["id"], destination))
                    if transferred != destination:
                        raise ValueError("unexpected_download_path")
                    entry.update(png_identity(transferred))
                    entry.update(state="verified_file_bytes", reason=None)
                except (OSError, ValueError, RuntimeError):
                    entry["reason"] = "cover_download_or_image_validation_failed"
            entries.append(entry)

    hashes = {}
    for entry in entries:
        if entry["state"] == "verified_file_bytes":
            hashes.setdefault(entry["sha256"], []).append(
                f"S01E{entry['episode']:02d}-Part{entry['part']}")
    duplicate = [parts for parts in hashes.values() if len(parts) > 1]
    verified = sum(entry["state"] == "verified_file_bytes" for entry in entries)
    accepted = verified == 36 and not duplicate
    return {
        "status": "verified_exact_cover_png_bytes" if accepted else "held_cover_bytes_or_duplicates",
        "requested_parts": 36,
        "exact_cover_names_matched": sum(entry["reason"] != "exact_drive_cover_missing"
                                         for entry in entries),
        "verified_png_bytes": verified,
        "duplicate_png_sha256_groups": duplicate,
        "cover_files_all_unique": not duplicate,
        "all_exact_png_bytes_accepted": accepted,
        "cover_bytes_accepted_does_not_prove_uploaded_thumbnail": True,
        "remote_instagram_thumbnail_verified": False,
        "source_mp4_content_verified": False,
        "meta_writes": 0,
        "source_writes": 0,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "parts": entries,
    }


def main():
    from public_link_runtime import FOLDERS, download, inventory

    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        catalog = inventory(FOLDERS["toonzone"])
        covers = inventory(FOLDERS["covers"])
        result = assess(catalog, covers, download=download)
    except Exception as exc:
        # Do not log raw provider exceptions, which may contain URLs or tokens.
        result = {
            "status": "held_source_inventory_or_cover_audit_failed",
            "reason_type": type(exc).__name__,
            "meta_writes": 0, "all_exact_png_bytes_accepted": False,
            "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    missing = [row["cover_name"] for row in result.get("parts", [])
               if row.get("reason") == "exact_drive_cover_missing"]
    print(json.dumps({
        "status": result["status"],
        "requested_parts": result.get("requested_parts", 36),
        "verified_png_bytes": result.get("verified_png_bytes", 0),
        "missing_exact_cover_names": missing,
        "duplicate_group_count": len(result.get("duplicate_png_sha256_groups", [])),
        "meta_writes": 0,
    }, ensure_ascii=False), flush=True)
    return 0 if result.get("all_exact_png_bytes_accepted") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
