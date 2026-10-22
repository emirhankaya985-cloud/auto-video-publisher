import re
from pathlib import Path

def parse_video_txt(file_path):
    """Video açıklamalarını platformlara göre ayırır."""
    text = Path(file_path).read_text(
        encoding="utf-8-sig"
    )

    pattern = (
        r"(?m)^[ \t]*===\s*"
        r"(INSTAGRAM REELS|TIKTOK|YOUTUBE SHORTS|FACEBOOK REELS)"
        r"\s*===[ \t]*$"
    )

    parts = re.split(pattern, text, flags=re.IGNORECASE)

    sections = {
        parts[i].strip().upper(): parts[i + 1].strip()
        for i in range(1, len(parts) - 1, 2)
    }

    required = [
        "INSTAGRAM REELS",
        "TIKTOK",
        "YOUTUBE SHORTS",
        "FACEBOOK REELS",
    ]

    missing = [name for name in required if name not in sections]
    if missing:
        raise ValueError(f"Eksik platform bolumleri: {missing}")

    return sections
