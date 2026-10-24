"""Build an inspectable archive of deterministic ToonZone captions from public Drive names.

No Google Drive write permission and no secret tokens are required. The live
Meta publisher generates identical .txt files and uses them automatically.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from public_link_runtime import FOLDERS, generate_toonzone_txts, inventory, toonzone_cover_coverage


def main():
    files = inventory(FOLDERS["toonzone"])
    covers = inventory(FOLDERS["covers"])
    dest = Path("toonzone-generated-txt")
    generated, invalid = generate_toonzone_txts(files, dest)
    expected = sum(name.lower().endswith(".mp4") for name in files)
    covered, uncovered = toonzone_cover_coverage(files, covers)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "public ToonZone Drive filenames",
        "mp4_count": expected,
        "txt_generated": generated,
        "invalid_video_names": invalid,
        "exact_png_covers": covered,
        "missing_exact_png_covers": uncovered,
        "destination": "GitHub Actions artifact; Drive is read-only",
        "content_rule": "season, episode, part and filename title only; no invented scene details",
    }
    dest.mkdir(exist_ok=True)
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    if not expected or generated + invalid != expected or invalid:
        # Keep output for forensic audit, but never report incomplete TXT coverage as green.
        raise SystemExit("ToonZone TXT generation incomplete (invalid MP4 filenames).")


if __name__ == "__main__":
    main()
