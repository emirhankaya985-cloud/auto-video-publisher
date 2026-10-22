"""Fail-closed human-reviewed content allowlist for shared humor routes."""
from __future__ import annotations

import json
from pathlib import Path


SHARED_FOLDER_ID = "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M"
_MANIFEST = Path(__file__).parent / "manifests" / "shared-humor-approved-content.json"


def approved_shared_pairs(route: str, folder_id: str, pairs):
    """Return only human-approved files with an exact ID and checksum match.

    The shared Turkish routes must never treat folder membership or a TXT file
    as content approval.  A missing/malformed manifest yields no candidates.
    """
    if route not in {"tarladaki", "penguen"} or folder_id != SHARED_FOLDER_ID:
        return []
    try:
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if manifest.get("source_folder_id") != folder_id:
        return []
    approved = {
        (item.get("drive_file_id"), str(item.get("md5", "")).lower())
        for item in manifest.get("approved", [])
        if item.get("route") == route
    }
    return [
        pair for pair in pairs
        if (pair[1].get("id"), str(pair[1].get("md5Checksum", "")).lower()) in approved
    ]
