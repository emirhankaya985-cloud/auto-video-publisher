"""Per-account fixed TXT selection; opt-in and fail-closed.

No fallback to a shared TXT or another account when enabled. Existing
per-video captions stay in place until explicitly configured by the owner.
Film and ToonZone always retain their part-specific caption logic.
"""
from __future__ import annotations

import hashlib
import os
import re

FIXED_FILES = {
    "tarladaki": ("TARLADAKI", "Tarladaki_Fasulye_ACCOUNT.txt"),
    "penguen": ("PENGUEN", "Beyinsiz_Penguen_ACCOUNT.txt"),
    "gonle": ("GONLE", "Gonle_Dusen_ACCOUNT.txt"),
    "daily_laugh": ("DAILY_LAUGH", "Daily_Laugh_Lab_ACCOUNT.txt"),
}


def selected_txt(route, files, *, environ=None):
    env = os.environ if environ is None else environ
    if str(env.get("ENABLE_FIXED_ACCOUNT_TXT", "")).strip().lower() != "true":
        return None
    if route in {"toonzone", "film", "film_second"}:
        return None
    spec = FIXED_FILES.get(route)
    if spec is None:
        raise RuntimeError("account_fixed_txt_unknown_route")
    if not isinstance(files, dict):
        raise RuntimeError("account_fixed_txt_catalog_invalid")
    prefix, filename = spec
    record = files.get(filename)
    if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{10,128}", record["id"])):
        raise RuntimeError("account_fixed_txt_missing_or_unverified")
    checksum = str(env.get(f"FIXED_{prefix}_TXT_SHA256", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise RuntimeError("account_fixed_txt_checksum_not_configured")
    return {"id": record["id"], "name": filename, "sha256": checksum}


def verify_text(value, expected_checksum):
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("account_fixed_txt_empty")
    value = value.strip()
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if digest != expected_checksum:
        raise RuntimeError("account_fixed_txt_content_changed")
    if len(value) > 2200:
        # There is no silent trimming of the owner's fixed caption.
        raise RuntimeError("account_fixed_txt_exceeds_instagram_limit")
    if "<html" in value.lower():
        raise RuntimeError("account_fixed_txt_invalid_document")
    return value
