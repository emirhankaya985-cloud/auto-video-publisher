"""Credential-free Google Drive public-link read diagnostic.

Read only the exact source MP4s that failed in production #41197608372.
No Meta imports are called for side effects, no Graph POST/upload, no Drive
mutations and no source bytes are persisted after the test. Source IDs and
provider URLs are deliberately omitted from all output.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from public_link_runtime import FOLDERS, direct_public_drive, inventory

CASES = (
    ("gonle", "139.mp4"),
    ("toonzone", "S01E08_The_Unicorns_Have_Got_to_Go_Part1.mp4"),
)


def main():
    failed = 0
    for label, filename in CASES:
        # The existing publisher inventory is the authoritative ID source,
        # rather than hard-coding a bearer-like public file link.
        try:
            files = inventory(FOLDERS[label])
            row = files.get(filename)
            if not row:
                raise ValueError("source_not_in_approved_folder")
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "source.mp4"
                verified = direct_public_drive(row["id"], dest)
                if verified is None or verified.stat().st_size <= 1024:
                    raise ValueError("public_direct_get_blocked")
                # The helper already verified full content length + MP4 ftyp.
                size = verified.stat().st_size
            print(json.dumps({"source": label, "status": "verified_read",
                              "complete_bytes": size, "meta_writes": 0}), flush=True)
        except Exception as exc:
            failed += 1
            # Sanitized diagnostic: no provider URLs, IDs, tokens or raw
            # Drive exceptions. The next action depends on the status only.
            reason = (str(exc) if isinstance(exc, ValueError)
                      and str(exc) in {"source_not_in_approved_folder",
                                       "public_direct_get_blocked"}
                      else type(exc).__name__)
            print(json.dumps({"source": label, "status": "blocked",
                              "reason": reason, "meta_writes": 0}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
