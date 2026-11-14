"""Persistent notification deduplication backed by Neon, with local fallback."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

LEDGER = Path(os.getenv("NOTIFICATION_DEDUP_PATH", "link-runtime/notification-alerts.json"))


def _digest(key: str) -> str:
    if not isinstance(key, str) or not key.strip():
        raise ValueError("notification key required")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _database_claim(key: str) -> bool | None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    try:
        import psycopg
        digest = _digest(key)
        with psycopg.connect(url, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO notification_events(event_key, channel, status, payload_redacted)
                VALUES (%s, 'combined', 'pending', %s)
                ON CONFLICT(event_key) DO NOTHING
                RETURNING id
            """, (digest, "sha256:" + digest))
            if cur.fetchone():
                return True
            cur.execute("SELECT status, attempted_at FROM notification_events WHERE event_key=%s", (digest,))
            row = cur.fetchone()
            if not row:
                return True
            status, attempted_at = row
            if status == "sent":
                return False
            if status == "pending" and attempted_at and time.time() - attempted_at.timestamp() < 900:
                return False
            cur.execute("""
                UPDATE notification_events SET status='pending', attempted_at=now(), error=NULL
                 WHERE event_key=%s
            """, (digest,))
            return True
    except Exception:
        return None


def _local_update(key: str, status: str) -> None:
    digest = _digest(key)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    events = data.get("events")
    if not isinstance(events, dict):
        events = {}
        for old in data.get("sent", []):
            if isinstance(old, str):
                events[old] = {"status": "sent", "updated": int(time.time())}
    events[digest] = {"status": status, "updated": int(time.time())}
    data = {"events": dict(list(events.items())[-2000:])}
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, LEDGER)


def should_send(key: str) -> bool:
    digest = _digest(key)
    result = _database_claim(key)
    if result is not None:
        return result
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        data = {}
    events = data.get("events", {}) if isinstance(data, dict) else {}
    entry = events.get(digest, {}) if isinstance(events, dict) else {}
    if entry.get("status") == "sent":
        return False
    if entry.get("status") == "pending" and time.time() - entry.get("updated", 0) < 900:
        return False
    _local_update(key, "pending")
    return True


def mark_result(key: str, delivered: bool, error_category: str | None = None) -> None:
    digest = _digest(key)
    status = "sent" if delivered else "failed"
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        try:
            import psycopg
            with psycopg.connect(url, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute("""
                    UPDATE notification_events
                       SET status=%s, delivered_at=CASE WHEN %s THEN now() ELSE delivered_at END,
                           attempted_at=now(), error=%s
                     WHERE event_key=%s
                """, (status, delivered, error_category, digest))
        except Exception:
            pass
    _local_update(key, status)


def resolve(key: str) -> None:
    digest = _digest(key)
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        try:
            import psycopg
            with psycopg.connect(url, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute("UPDATE notification_events SET status='resolved', error=NULL WHERE event_key=%s", (digest,))
        except Exception:
            pass
    _local_update(key, "resolved")


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 2 and sys.argv[1] == "resolve":
        key = os.getenv("NOTIFICATION_INCIDENT_KEY", "")
        if not key:
            raise SystemExit("NOTIFICATION_INCIDENT_KEY is required")
        resolve(key)
        print("notification_incident=resolved")
    else:
        raise SystemExit("usage: notification_dedup.py resolve <incident-key>")
