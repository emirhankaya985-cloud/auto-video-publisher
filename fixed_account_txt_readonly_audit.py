"""Read-only verification of owner-provided fixed caption TXT files.

Lists original public Drive folders; downloads only the four exact TXT names.
No caption generation, shared fallback, Drive writes or Meta publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from account_fixed_txt import FIXED_FILES, verify_text

FOLDER_BY_ROUTE = {
    "tarladaki": "humor", "penguen": "humor",
    "gonle": "gonle", "daily_laugh": "daily_laugh",
}
OUT = Path("fixed-txt-readonly-audit/result.json")


def audit(*, folders, inventory_fn, download_fn, environ=None):
    env = os.environ if environ is None else environ
    if set(FIXED_FILES) != set(FOLDER_BY_ROUTE):
        raise ValueError("fixed_caption_routes_changed")
    if len({spec[1] for spec in FIXED_FILES.values()}) != len(FIXED_FILES):
        raise ValueError("shared_caption_filename_forbidden")
    cache = {}
    records = []
    with tempfile.TemporaryDirectory(prefix="safe-owner-caption-") as dirname:
        for route, (prefix, name) in FIXED_FILES.items():
            folder_name = FOLDER_BY_ROUTE[route]
            if folder_name not in folders:
                raise ValueError("untrusted_drive_folder_mapping")
            if folder_name not in cache:
                try:
                    cache[folder_name] = inventory_fn(folders[folder_name])
                except Exception as exc:
                    cache[folder_name] = {"_error": type(exc).__name__}
            listing = cache[folder_name]
            record = {"route": route, "folder_alias": folder_name,
                      "exact_filename": name, "published": False}
            if not isinstance(listing, dict) or "_error" in listing:
                record.update(status="folder_inventory_unavailable",
                              error_type=listing.get("_error") if isinstance(listing, dict) else "invalid_inventory")
                records.append(record)
                continue
            info = listing.get(name)
            if not isinstance(info, dict) or not isinstance(info.get("id"), str):
                record["status"] = "owner_fixed_txt_not_present"
                records.append(record)
                continue
            path = Path(dirname) / name
            try:
                result = download_fn(info["id"], path)
                if result is None or not path.is_file():
                    raise ValueError("source_download_missing")
                text = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
                verify_text(text, digest)  # checks nonempty, HTML and IG length
                pin = str(env.get(f"FIXED_{prefix}_TXT_SHA256", "")).strip().lower()
                status = ("sha256_pin_not_configured" if not pin else
                          "verified" if pin == digest else "sha256_pin_mismatch")
                record.update(status=status, sha256_computed=digest,
                              sha256_pin_matches=(pin == digest if pin else False))
            except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
                record.update(status="source_invalid_or_unreadable",
                              error_type=type(exc).__name__)
            finally:
                path.unlink(missing_ok=True)
            records.append(record)
    verified = sum(r["status"] == "verified" for r in records)
    return {"schema": 1, "mode": "read_only_owner_source_only",
            "status": "verified_all" if verified == 4 else "held_missing_or_unpinned",
            "verified_files": verified, "required_files": 4,
            "rows": records, "caption_contents_recorded": False,
            "sources_created": 0, "publishes": 0, "safe_to_enable_without_owner_review": False}


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        if (os.getenv("GITHUB_REPOSITORY") != "emirhankaya985-cloud/auto-video-publisher"
                or os.getenv("GITHUB_REF") != "refs/heads/main"):
            raise ValueError("not_trusted_main")
        from public_link_runtime import FOLDERS, inventory, direct_public_drive
        report = audit(folders=FOLDERS, inventory_fn=inventory, download_fn=direct_public_drive)
    except Exception as exc:
        report = {"schema": 1, "mode": "read_only_owner_source_only",
                  "status": "blocked", "error_type": type(exc).__name__,
                  "publishes": 0, "sources_created": 0}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report.get("status") in {"verified_all", "held_missing_or_unpinned"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
