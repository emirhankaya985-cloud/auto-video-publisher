"""Read-only ToonZone daily video discovery and staggered Telegram review.

No likes, saves, reposts, or cross-account API writes. Times are Istanbul local.
"""
import argparse
import json
import os
import re
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from meta_auth_loader import discover_pages
from meta_cross_engagement import graph, stamp
from telegram_notifications import send_telegram

ISTANBUL = ZoneInfo("Europe/Istanbul")
START_DATE = date(2026, 11, 9)
SLOT_NAMES = (
    "Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen",
    "Daily Laugh Lab", "Film Mağarası", "Filmmagrasi", "ToonZone",
)
VIDEO_TYPES = {"VIDEO", "REELS"}  # Never include images in video review.
IG_HOSTS = {"www.instagram.com", "instagram.com"}
ID = re.compile(r"\d{4,30}\Z")


def choose_slot(now):
    local = now.astimezone(ISTANBUL)
    if local.date() < START_DATE or local.hour < 15:
        return None
    minutes = (local.hour - 15) * 60 + local.minute
    if not 0 <= minutes < 15 * len(SLOT_NAMES):
        return None
    # Late GitHub jobs may not impersonate an older slot.
    index = minutes // 15
    return index, SLOT_NAMES[index], local.date()


def safe_link(value):
    if not isinstance(value, str) or len(value) > 250:
        return ""
    parts = urlsplit(value)
    if (parts.scheme == "https" and parts.hostname in IG_HOSTS and
            not parts.username and not parts.password and not parts.query and
            re.fullmatch(r"/(reel|p)/[A-Za-z0-9_-]{5,}/?", parts.path)):
        return f"https://{parts.hostname}{parts.path}"
    return ""


def collect_today(now, *, loader=discover_pages, get=graph):
    pages = loader(os.environ.get("META_ACCESS_TOKEN", "")).get("pages", [])
    matches = [p for p in pages if p.get("page_name") == "ToonZone"
               and str(p.get("page_id")) == "1298191963387372"]
    if len(matches) != 1:
        raise ValueError("ToonZone Page not uniquely verified")
    page = matches[0]
    ig_id, token = str(page.get("instagram_id") or ""), page.get("page_token") or ""
    if not ID.fullmatch(ig_id) or not token:
        raise ValueError("ToonZone Instagram account unavailable")
    response = get("GET", f"{ig_id}/media", token,
                   {"fields": "id,timestamp,permalink,media_type", "limit": 100})
    media = response.get("data")
    if not isinstance(media, list) or response.get("error"):
        raise ValueError("invalid Instagram media list")
    found = {}
    for row in media:
        if not isinstance(row, dict):
            raise ValueError("invalid Instagram media row")
        media_id = str(row.get("id", ""))
        if row.get("media_type") not in VIDEO_TYPES or not ID.fullmatch(media_id):
            continue
        published = stamp(row.get("timestamp"))
        if published > now + timedelta(minutes=2):
            raise ValueError("future media timestamp")
        if published.astimezone(ISTANBUL).date() != now.astimezone(ISTANBUL).date():
            continue
        link = safe_link(row.get("permalink"))
        if link:
            found[media_id] = (published, link)
    # One page includes up to 100 recent items; refuse incomplete daily coverage.
    paging = response.get("paging") or {}
    if paging.get("next") and len(media) == 100:
        raise ValueError("media pagination incomplete")
    return [link for _, link in sorted(found.values(), key=lambda item: item[0])]


def build_message(actor, day, links):
    if actor not in SLOT_NAMES:
        raise ValueError("invalid review actor")
    header = f"ToonZone · {day.isoformat()} · {len(links)} günlük video"
    if not links:
        body = "Bugün için doğrulanmış yeni ToonZone videosu bulunamadı."
    else:
        body = "\n".join(f"• {link}" for link in links[:15])
        if len(links) > 15:
            body += f"\n+{len(links)-15} diğer video (rapora sığmadı)"
    return f"{actor} için içerik inceleme ve organik tanıtım önerisi\n{header}\n{body}\nOtomatik beğeni/kaydetme yapılmadı."


def main(now=None):
    now = now or datetime.now(timezone.utc)
    slot = choose_slot(now)
    if slot is None:
        print(json.dumps({"status": "outside_schedule", "writes": 0}))
        return 0
    index, actor, day = slot
    links = collect_today(now)
    # Explicitly run in read-only mode in CI and on PRs.
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        print(json.dumps({"status": "preview", "slot": index, "videos": len(links), "writes": 0}))
        return 0
    if os.getenv("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("duplicate workflow attempt blocked")
    if os.getenv("TOONZONE_REVIEW_NOTIFICATIONS_ENABLED", "true") != "true":
        print(json.dumps({"status": "disabled", "slot": index, "writes": 0}))
        return 0
    send_telegram("🎬 ToonZone günlük video kontrolü", build_message(actor, day, links))
    print(json.dumps({"status": "telegram_sent", "slot": index, "videos": len(links),
                      "meta_writes": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
