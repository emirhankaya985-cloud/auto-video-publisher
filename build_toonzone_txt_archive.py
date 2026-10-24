"""Build an inspectable archive of deterministic ToonZone captions from public Drive names.

No Google Drive write permission and no secret tokens are required. The live
Meta publisher generates identical .txt files and uses them automatically.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from public_link_runtime import FOLDERS, exact_txt_coverage, generate_toonzone_txts, inventory, toonzone_cover_coverage


def main():
    files = inventory(FOLDERS["toonzone"])
    covers = inventory(FOLDERS["covers"])
    dest = Path("toonzone-generated-txt")
    generated, invalid = generate_toonzone_txts(files, dest)
    expected = sum(name.lower().endswith(".mp4") for name in files)
    covered, uncovered = toonzone_cover_coverage(files, covers)
    other_inventories = {source: inventory(FOLDERS[source])
                         for source in ("humor", "gonle", "daily_laugh", "film")}
    other_sources = {source: exact_txt_coverage(catalog)
                     for source, catalog in other_inventories.items()}
    daily_catalog = other_inventories["daily_laugh"]
    daily_txt_names = sorted(n for n in daily_catalog if n.lower().endswith(".txt"))
    daily_video_names = sorted(n for n in daily_catalog if n.lower().endswith(".mp4"))
    other_sources["daily_laugh"]["txt_filename_samples"] = daily_txt_names[:38] + daily_txt_names[-12:]
    other_sources["daily_laugh"]["video_filename_samples"] = daily_video_names[:38] + daily_video_names[-12:]
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "public ToonZone Drive filenames",
        "mp4_count": expected,
        "txt_generated": generated,
        "invalid_video_names": invalid,
        "exact_png_covers": covered,
        "missing_exact_png_covers": uncovered,
        "other_account_exact_txt_coverage": other_sources,
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
