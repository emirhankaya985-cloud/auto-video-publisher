"""Buffer sidecar for the existing public-link publisher plan artifacts.

Runs independently after Meta publication. It never mutates the Meta ledger and
an X failure cannot change the Facebook/Instagram job result.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

from buffer_x import (CHANNELS, FREE_LIMITS, BufferClient, BufferError,
                      NeonBufferStore, drive_public_video_url, fingerprint)

CHANNEL_CONFIG = {
    "tarladaki": ("Tarladaki Fasulye", "TARLADAKI"),
    "gonle": ("Gönle Düşen", "GONLE"),
    "penguen": ("Beyinsiz Penguen", "PENGUEN"),
    "daily_laugh": ("Daily Laugh Lab", "DAILY_LAUGH"),
    "film": ("Film Mağarası", "FILM"),
    "toonzone": ("ToonZone", "TOONZONE"),
    "film_sahneleri": ("Film Sahneleri", "FILM_SAHNELERI"),
}


class Notifier:
    def __init__(self, store: NeonBufferStore):
        self.store = store

    def send_once(self, key: str, event_type: str, title: str, message: str) -> None:
        if not self.store.claim_notification(key, event_type):
            return
        ntfy_ack = telegram_ack = False
        try:
            from ntfy_notifications import send_ntfy
            if os.getenv("NTFY_TOPIC_URL") or os.getenv("NTFY_TOPIC"):
                send_ntfy(title, message, priority=3, tags=["outbox_tray"])
                ntfy_ack = True
        except Exception:
            pass
        token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            try:
                response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": f"{title}\n{message}"}, timeout=15)
                telegram_ack = response.status_code == 200 and response.json().get("ok") is True
            except Exception:
                pass
        self.store.mark_notification_delivery(key, ntfy_ack=ntfy_ack, telegram_ack=telegram_ack)


def configured_channels() -> dict[str, str]:
    configured = {}
    for _key, (name, suffix) in CHANNEL_CONFIG.items():
        value = os.getenv(f"BUFFER_X_CHANNEL_ID_{suffix}", "").strip()
        if value:
            configured[name] = value
    if len(configured) > FREE_LIMITS["channels"]:
        raise BufferError("free_channel_limit_exceeded")
    if len(set(configured.values())) != len(configured):
        raise BufferError("duplicate_channel_mapping")
    return configured


def channel_route_map(store: NeonBufferStore, client: BufferClient,
                      configured: dict[str, str]) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    cached = store.active_channels(max_age_hours=12)
    by_name = {row["name"]: row for row in cached}
    if configured and all(name in by_name and by_name[name]["id"] == channel_id
                          for name, channel_id in configured.items()):
        discovered = [{**row, "organizationId": row["organization_id"],
                       "service": "twitter", "isDisconnected": False, "isLocked": False}
                      for row in cached]
    else:
        discovered = client.discover_x_channels()
        if configured:
            store.sync_discovered_channels(discovered, configured)
        else:
            return {}, discovered
    channel_map = {}
    for key, (name, _suffix) in CHANNEL_CONFIG.items():
        row = next((c for c in discovered if c.get("id") == configured.get(name)), None)
        if row and not row.get("isDisconnected") and not row.get("isLocked"):
            channel_map[key] = {"name": name, "id": row["id"],
                                "organization_id": row["organizationId"]}
    return channel_map, discovered


def plan_artifacts(root: Path = Path(".")) -> list[tuple[str, dict[str, Any]]]:
    plans = []
    for path in sorted(root.glob("link-state-intent-*/plan.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if isinstance(item, dict) and item.get("route") in CHANNEL_CONFIG:
                plans.append((path.parent.name.removeprefix("link-state-intent-"), item))
    return plans


def stage_film_scenes(store: NeonBufferStore, channel: dict[str, str]) -> int:
    """Stage at most one exact MP4/TXT pair from its own approved Drive folder."""
    folder_id = os.getenv("FILM_SAHNELERI_DRIVE_FOLDER_ID", "").strip()
    if not folder_id or os.getenv("BUFFER_X_RIGHTS_FILM_SAHNELERI", "false").lower() != "true":
        return 0
    import gdown
    files = gdown.download_folder(id=folder_id, skip_download=True, quiet=True,
                                  use_cookies=False, timeout=40) or []
    videos, captions = {}, {}
    ambiguous = set()
    for entry in files:
        path = Path(entry.path)
        if len(path.parts) != 1:
            continue
        suffix = path.suffix.lower()
        stem = path.stem.casefold()
        target = videos if suffix == ".mp4" else captions if suffix == ".txt" else None
        if target is None:
            continue
        if stem in target and target[stem].id != entry.id:
            ambiguous.add(stem)
        target[stem] = entry
    def natural_key(value: str):
        return [(0, int(part)) if part.isdecimal() else (1, part.casefold())
                for part in re.split(r"(\d+)", value)]
    for stem in sorted(videos, key=natural_key):
        video, caption = videos[stem], captions.get(stem)
        if stem in ambiguous or not caption or store.source_exists("film_sahneleri", video.id):
            continue
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "caption.txt"
            downloaded = gdown.download(id=caption.id, output=str(target), quiet=True,
                                        use_cookies=False, timeout=40)
            if not downloaded or not target.is_file() or target.stat().st_size > 16_384:
                continue
            text = target.read_text(encoding="utf-8-sig").strip()
        if not text:
            continue
        media_url = drive_public_video_url(video.id)
        if not __import__("buffer_x").validate_media_url(media_url):
            continue
        store.enqueue(channel_key="film_sahneleri", channel_name="Film Sahneleri",
            organization_id=channel["organization_id"], buffer_channel_id=channel["id"],
            source_id=video.id, video_url=media_url, text=text, rights_approved=True)
        return 1
    return 0


def notify_quota(notifier: Notifier, window: str, used_percent: int, reset_at: int) -> None:
    level = 90 if used_percent >= 90 else 80
    reset = __import__("datetime").datetime.fromtimestamp(reset_at, tz=__import__("datetime").timezone.utc)
    notifier.send_once(f"quota:{window}:{reset_at}", "quota_warning",
                       "Buffer API kota uyarısı",
                       f"{window} penceresinde kullanım %{used_percent}. Yenilenme: {reset:%d.%m %H:%M} UTC.")


def run(root: Path = Path(".")) -> dict[str, Any]:
    key = os.getenv("BUFFER_API_KEY", "").strip()
    if not key:
        return {"status": "skipped", "reason": "api_key_missing"}
    database_url = os.getenv("DASHBOARD_DATABASE_URL", "").strip()
    if not database_url:
        return {"status": "skipped", "reason": "neon_unavailable"}

    store = NeonBufferStore(database_url)
    store.apply_migration()
    notifier = Notifier(store)
    client = BufferClient(key,
        on_usage=lambda op, hdrs, status, outcome: store.record_usage(
            op, hdrs, status=status, outcome=outcome),
        on_quota_threshold=lambda window, pct, reset: notify_quota(notifier, window, pct, reset))
    configured = configured_channels()
    try:
        channels, discovered = channel_route_map(store, client, configured)
    except BufferError as exc:
        if exc.code == "api_key_invalid":
            notifier.send_once("api-key-invalid", "connection_error", "Buffer API anahtarı geçersiz",
                               "BUFFER_API_KEY doğrulanamadı; X kuyruğu bekletildi.")
        else:
            notifier.send_once(f"connection:{exc.code}", "connection_error", "Buffer bağlantı sorunu",
                               f"Buffer bağlantısı doğrulanamadı ({exc.code}); X kuyruğu bekletildi.")
        raise
    names = sorted({c.get("name") or c.get("displayName") or c.get("id") for c in discovered})
    results: dict[str, Any] = {"status": "connected", "x_channels_discovered": len(discovered),
                               "mapped_channels": len(channels), "channel_names": names,
                               "queued": 0, "results": []}

    publish_enabled = os.getenv("BUFFER_X_ENABLED", "false").lower() == "true"
    dry_run = os.getenv("BUFFER_X_DRY_RUN", "true").lower() != "false"
    if not publish_enabled or dry_run:
        results["status"] = "dry_run" if publish_enabled else "connection_checked"
        return results

    # Reconcile previously accepted scheduled posts before consuming new queue.
    for row in store.due_for_verification():
        try:
            post = client.get_post(row["post_id"])
            store.verify_post(row["id"], str(post.get("status", "")), post.get("externalLink"))
            if post.get("status") == "sent":
                notifier.send_once(f"published:{row['post_id']}", "published",
                    "X videosu yayımlandı", f"Buffer gönderi durumu yayımlandı. {post.get('externalLink') or ''}".strip())
            elif post.get("status") == "error":
                notifier.send_once(f"failed:{row['post_id']}", "failed", "X yayını başarısız",
                    "Buffer gönderi durumu hata gösteriyor; otomatik yeniden gönderim yapılmadı.")
        except BufferError as exc:
            if exc.code == "quota_pause":
                break
            # A status read failure does not alter the scheduled post or retry it.

    candidates = plan_artifacts(root)
    for route, item in candidates:
        channel_info = CHANNEL_CONFIG.get(route)
        channel = channels.get(route)
        rights_name = channel_info[1] if channel_info else ""
        if not channel or os.getenv(f"BUFFER_X_RIGHTS_{rights_name}", "false").lower() != "true":
            continue
        captions = item.get("captions") if isinstance(item.get("captions"), dict) else {}
        text = str(captions.get("facebook") or captions.get("instagram") or "").strip()
        source_id = str(item.get("id") or "")
        if not source_id or not text:
            continue
        media_url = drive_public_video_url(source_id)
        if not __import__("buffer_x").validate_media_url(media_url):
            continue
        job_id = store.enqueue(channel_key=route, channel_name=channel["name"],
            organization_id=channel["organization_id"], buffer_channel_id=channel["id"],
            source_id=source_id, video_url=media_url, text=text, rights_approved=True)
        if job_id:
            results["queued"] += 1

    if (channel := channels.get("film_sahneleri")) and os.getenv(
            "BUFFER_X_RIGHTS_FILM_SAHNELERI", "false").lower() == "true":
        results["queued"] += stage_film_scenes(store, channel)

    # Existing schedule ticks are sparse; process only this run's bounded queue
    # so one stale backlog cannot fill all free Buffer slots.
    for _ in range(min(3, max(1, results["queued"]))):
        outcome = __import__("buffer_x").process_one(store, client, channels, discovered)
        results["results"].append(outcome)
        if outcome == "empty":
            break
    scheduled = results["results"].count("scheduled")
    if scheduled:
        notifier.send_once(f"scheduled:{os.getenv('GITHUB_RUN_ID','local')}:{scheduled}",
            "scheduled", "X videosu Buffer'da planlandı",
            f"Bu çalışmada {scheduled} video Buffer kuyruğuna eklendi.")
    failures = [status for status in results["results"] if status in {"failed", "uncertain", "held", "queue_full"}]
    if failures:
        notifier.send_once(f"queue-failure:{os.getenv('GITHUB_RUN_ID','local')}", "failed",
            "X kuyruğunda bekleyen sorun", f"Bu çalışmada başarısız/bekleyen X işi sayısı: {len(failures)}.")
    if os.getenv("BUFFER_X_SEND_DAILY_SUMMARY", "false").lower() == "true":
        summary = store.queue_summary()
        pending = summary.get("pending", 0) + summary.get("submitting", 0) + summary.get("uncertain", 0)
        day = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
        active = ", ".join(sorted(c["name"] for c in channels.values())) or "Bağlı X hesabı eşleşmedi"
        notifier.send_once(f"daily-summary:{day}", "daily_summary", "Günlük X yayın özeti",
            f"Bağlı X hesapları: {active}. Bekleyen video: {pending}. Kuyruk durumu: {summary}.")
        results["daily_summary"] = {"pending": pending, "queue": summary}
    results["status"] = "processed"
    return results


if __name__ == "__main__":
    try:
        report = run()
        Path("link-runtime").mkdir(exist_ok=True)
        Path("link-runtime/buffer-x-summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    except BufferError as exc:
        # Stable code only: no HTTP bodies, API keys, Drive URLs or tokens.
        report = {"status": "held", "reason": exc.code}
        Path("link-runtime").mkdir(exist_ok=True)
        Path("link-runtime/buffer-x-summary.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        sys.exit(0)
    except Exception as exc:
        report = {"status": "held", "reason": type(exc).__name__}
        Path("link-runtime").mkdir(exist_ok=True)
        Path("link-runtime/buffer-x-summary.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        sys.exit(0)
