"""Read-only inventory of alternative Film Mağarası Bıçkın Part 8 sources.

Output is an audit only. This module NEVER creates or clears Meta intents, never
marks a part published, and never sends a Meta POST. A filename is not evidence
that video content is the correct part.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

FOLDER_ID = "1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW"
OUTPUT = Path("film-part8-source-candidates.json")
NAME = re.compile(r"^Bickin_Part_(3|8)(?: \([0-9]+\))?\.mp4$", re.IGNORECASE)
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def matching_sources(items):
    """Collect all uniquely identified, top-level Part 3 and Part 8 MP4 files."""
    found = {}
    for item in items:
        name = Path(str(item.path))
        if len(name.parts) != 1 or not NAME.fullmatch(name.name):
            continue
        file_id = str(item.id)
        if not FILE_ID.fullmatch(file_id):
            raise ValueError("invalid_source_id")
        if name.name in found and found[name.name] != file_id:
            raise ValueError("ambiguous_duplicate_filename")
        found[name.name] = file_id
    return [{"filename": name, "drive_file_id": found[name]}
            for name in sorted(found, key=str.casefold)]


def summarize(items):
    candidates = matching_sources(items)
    part8 = [c for c in candidates
             if c["filename"].lower().startswith("bickin_part_8")]
    return {
        "mode": "readonly",
        "target": "Film Mağarası Bıçkın Part 8 source inventory",
        "part8_candidate_count": len(part8),
        "part3_candidate_count": len(candidates) - len(part8),
        "source_candidates": candidates,
        "media_downloads": 0,
        "meta_post_requests": 0,
        "ledger_writes": 0,
        "verified_correct_part8": False,
        "safe_to_publish": False,
    }


def main():
    # No provider access from untrusted branch or rerun context.
    if (os.getenv("GITHUB_REPOSITORY") !=
            "emirhankaya985-cloud/auto-video-publisher"
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1"):
        raise RuntimeError("untrusted_live_audit_context")
    import gdown
    files = gdown.download_folder(
        id=FOLDER_ID, skip_download=True, quiet=True,
        use_cookies=False, timeout=40)
    if files is None:
        raise RuntimeError("film_drive_inventory_unavailable")
    result = summarize(files)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("mode", "part8_candidate_count",
                       "part3_candidate_count", "media_downloads",
                       "meta_post_requests", "ledger_writes",
                       "verified_correct_part8")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
