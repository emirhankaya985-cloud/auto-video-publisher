"""Idempotent, local failure-alert ledger.

Only a provider-acknowledged message is marked sent. An unsuccessful attempt
must never suppress the next retry. The workspace is per GitHub run; this is
not a substitute for a durable cross-run notification store.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

LEDGER = Path(os.getenv("NOTIFICATION_DEDUP_PATH", "link-runtime/notification-alerts.json"))


def _digest(key):
    if not isinstance(key, str) or not key.strip():
        raise ValueError("notification key required")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _load():
    try:
        obj = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return []
    entries = obj.get("sent") if isinstance(obj, dict) else None
    return entries if isinstance(entries, list) else []


def already_sent(key):
    return _digest(key) in _load()


def mark_sent(key):
    digest = _digest(key)
    sent = _load()
    if digest in sent:
        return False
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    sent.append(digest)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sent": sent[-2000:]}), encoding="utf-8")
    os.replace(tmp, LEDGER)
    return True


def should_send(key):
    """Retained for existing callers; prefer already_sent + mark_sent after ACK."""
    if already_sent(key):
        return False
    return mark_sent(key)
