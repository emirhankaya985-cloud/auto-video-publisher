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


CANONICAL_FILM = re.compile(r"^(?P<title>.+?)_Part_(?P<part>[0-9]+)\\.mp4$", re.IGNORECASE)


def inventory_film_series(items, state):
    """GET-only source candidate summary; never grants publication permission.

    A missing part, missing TXT, historical post or source ambiguity disqualifies
    the series as a *new* film candidate. A candidate still requires fresh Meta
    history, actual content inspection and a separately authorized publish.
    """
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise ValueError("film_ledger_unavailable")
    names = {}
    by_series = {}
    all_txt = set()
    for item in items:
        path = Path(str(item.path))
        if len(path.parts) != 1:
            continue
        name = path.name
        if name in names and names[name] != str(item.id):
            raise ValueError("ambiguous_duplicate_filename")
        names[name] = str(item.id)
        if name.casefold().endswith(".txt"):
            all_txt.add(name.casefold())
            continue
        match = CANONICAL_FILM.fullmatch(name)
        if not match:
            continue
        title = match.group("title").replace("_", " ").strip()
        key = title.casefold()
        part = int(match.group("part"))
        if part < 1 or part > 500:
            raise ValueError("film_part_out_of_range")
        row = by_series.setdefault(key, {"series": title, "parts": set(), "names": {}})
        if part in row["parts"]:
            raise ValueError("ambiguous_canonical_part")
        row["parts"].add(part)
        row["names"][part] = name

    published = {}
    for row in state["entries"].values():
        if not isinstance(row, dict) or row.get("route") not in {"film", "film_second"}:
            continue
        filename = str(row.get("file") or "")
        # Filename aliases may have been posted historically. Normalize the
        # same film title without treating a caption alone as proof.
        stem = Path(filename).stem
        m = re.fullmatch(r"(.+?)_Part_?([0-9]+)(?: \\([0-9]+\\))?", stem, re.I)
        if not m:
            continue
        title = m.group(1).replace("_", " ").strip().casefold()
        if row.get("status") == "done" and str(row.get("post_id") or "").strip():
            published.setdefault(title, set()).add(int(m.group(2)))
    out = []
    for key, data in sorted(by_series.items()):
        parts = sorted(data["parts"])
        missing = [n for n in range(1, max(parts) + 1) if n not in data["parts"]]
        missing_txt = [n for n in parts if
                       str(Path(data["names"][n]).with_suffix(".txt")).casefold() not in all_txt]
        existing = sorted(published.get(key, set()))
        # This is source discovery, never a "safe_to_publish" verdict.
        candidate = (key != "bickin" and len(parts) >= 4 and
                     parts[0] == 1 and not missing and not missing_txt and
                     not existing)
        out.append({
            "series": data["series"], "source_part_count": len(parts),
            "first_part": parts[0], "last_part": parts[-1],
            "missing_parts": missing[:30], "missing_txt_parts": missing_txt[:30],
            "confirmed_existing_ledger_parts": existing,
            "candidate_new_film": candidate,
        })
    return out


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
    from publication_github_progress import restore_publication_state
    ledger = restore_publication_state()
    result["all_film_series"] = inventory_film_series(files, ledger)
    result["new_film_candidates"] = [row["series"] for row in result["all_film_series"]
                                     if row["candidate_new_film"]]
    result["ledger_compared"] = True
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("mode", "part8_candidate_count",
                       "part3_candidate_count", "media_downloads",
                       "meta_post_requests", "ledger_writes",
                       "verified_correct_part8")}
                     | {"film_series_count": len(result["all_film_series"]),
                        "new_film_candidates": result["new_film_candidates"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
