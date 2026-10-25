"""On-demand, source-accurate ToonZone cover fallback.

Uses ONLY the selected licensed MP4 as visual source and its verified
season/episode/part tuple. Never borrows artwork from a different part.
Does not call Meta/Drive write APIs. Requires ffmpeg with drawtext support.
"""
from pathlib import Path
import subprocess

from cover_artwork import validate_cover
from ordered_channels import parse_order


def generate_part_cover(source_video, original_filename, destination):
    source_video = Path(source_video)
    destination = Path(destination)
    order = parse_order(Path(original_filename).stem, "cartoon")
    if (not order or len(order) < 3 or
            any(not isinstance(n, int) or n < 0 for n in order[:3]) or
            order[2] not in (1, 2, 3, 4) or
            Path(original_filename).suffix.lower() != ".mp4"):
        raise ValueError("ToonZone part kimliği doğrulanamadı; kapak üretilmedi")
    season, episode, part = order[:3]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.name != Path(original_filename).stem + ".png":
        raise ValueError("Otomatik kapak video dosyasıyla birebir ad eşleşmeli")
    if not source_video.is_file() or source_video.stat().st_size == 0:
        raise ValueError("Kapak kaynağı MP4 bulunamadı")

    # The backdrop is taken from THIS part's actual video (not another
    # episode/part). Fixed bars/text give every fallback identical branding.
    # FFmpeg receives arguments directly, never shell=True.
    filters = ",".join((
        "scale=900:1200:force_original_aspect_ratio=increase",
        "crop=900:1200",
        "setsar=1",
        "drawbox=x=0:y=0:w=iw:h=160:color=black@0.78:t=fill",
        "drawbox=x=0:y=1020:w=iw:h=180:color=black@0.78:t=fill",
        "drawtext=font=DejaVuSans:text=TOONZONE:fontcolor=white:fontsize=78:x=(w-text_w)/2:y=38",
        f"drawtext=font=DejaVuSans:text=S{season:02d}E{episode:02d}:fontcolor=white:fontsize=65:x=(w-text_w)/2:y=1034",
        f"drawtext=font=DejaVuSans:text=PART\\ {part}\\ OF\\ 4:fontcolor=white:fontsize=45:x=(w-text_w)/2:y=1115",
    ))
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", "1", "-i", str(source_video), "-frames:v", "1",
             "-vf", filters, str(destination)],
            check=True, capture_output=True, timeout=120,
        )
        validate_cover(destination.read_bytes(), "image/png")
        return destination
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        destination.unlink(missing_ok=True)
        raise RuntimeError("Bölüme özel otomatik ToonZone kapağı hazırlanamadı") from None
