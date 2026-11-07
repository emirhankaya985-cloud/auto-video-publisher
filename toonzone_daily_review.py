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
from threads_accounts import threads_account_config, THREADS_ROUTE_PREFIXES
from platform_publication_notifications import threads_posts

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



# Slots are prompts for the named account, not provider writes.
ACCOUNT_ROUTES = {
    "Tarladaki Fasulye": "tarladaki",
    "Beyinsiz Penguen": "penguen",
    "Gönle Düşen": "gonle",
    "Daily Laugh Lab": "daily_laugh",
    "Film Mağarası": "film",
    "Filmmagrasi": None,  # separate FB/IG identity, no separate Threads route
    "ToonZone": "toonzone",
}
TOONZONE_PAGE_ID = "1298191963387372"
PLATFORMS = ("facebook", "instagram", "threads")


def video_feed_today(now, *, page, get=graph):
    """Read the ToonZone Page's own video feed; never infer a publish from CI."""
    pid, token = str(page.get("page_id", "")), page.get("page_token") or ""
    if pid != TOONZONE_PAGE_ID or not token:
        raise ValueError("ToonZone Page identity mismatch")
    body = get("GET", f"{pid}/videos", token,
               {"fields": "id,created_time,from", "limit": 100})
    data = body.get("data")
    if not isinstance(data, list) or body.get("error"):
        raise ValueError("invalid Facebook videos feed")
    if (body.get("paging") or {}).get("next") and len(data) >= 100:
        raise ValueError("Facebook video pagination incomplete")
    found = {}
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("invalid Facebook video row")
        mid = str(row.get("id") or "")
        if not ID.fullmatch(mid):
            continue
        published = stamp(row.get("created_time"))
        if published > now + timedelta(minutes=2):
            raise ValueError("future Facebook video timestamp")
        # Confirm source belongs to the known ToonZone Page, not another feed.
        owner = row.get("from")
        if not isinstance(owner, dict) or str(owner.get("id")) != pid:
            continue
        if published.astimezone(ISTANBUL).date() == now.astimezone(ISTANBUL).date():
            found[mid] = (published, "https://www.facebook.com/watch/?v=" + mid)
    return [link for _, link in sorted(found.values(), key=lambda item: item[0])]


def actor_platforms(actor, pages):
    """A platform is eligible only if that account is actually configured."""
    if actor not in ACCOUNT_ROUTES:
        raise ValueError("unknown account")
    rows = [p for p in pages if p.get("page_name") == actor]
    if len(rows) > 1:
        raise ValueError("duplicate account name")
    platforms = set()
    if len(rows) == 1:
        if str(rows[0].get("page_id", "")).isdigit() and rows[0].get("page_token"):
            platforms.add("facebook")
        if str(rows[0].get("instagram_id") or "").isdigit():
            platforms.add("instagram")
    route = ACCOUNT_ROUTES[actor]
    if route in THREADS_ROUTE_PREFIXES:
        try:
            account = threads_account_config(route, require_enabled=False, require_media=False)
        except (RuntimeError, ValueError):
            pass
        else:
            if account.token and account.username:
                platforms.add("threads")
    return platforms


def collect_platforms(now, actor, *, loader=discover_pages,
                      ig=collect_today, fb=video_feed_today, threads=threads_posts):
    """Per-platform fail isolation; a broken feed never fabricates success."""
    auth = loader(os.environ.get("META_ACCESS_TOKEN", ""))
    pages = auth.get("pages", []) if isinstance(auth, dict) else []
    matches = [p for p in pages if (p.get("page_name") == "ToonZone"
               and str(p.get("page_id")) == TOONZONE_PAGE_ID)]
    if len(matches) != 1:
        raise ValueError("ToonZone Page not uniquely verified")
    toonzone = matches[0]
    enabled = actor_platforms(actor, pages)
    output, failures = {}, {}
    if "instagram" in enabled:
        if not str(toonzone.get("instagram_id") or "").isdigit():
            failures["instagram"] = "ToonZone Instagram unavailable"
        else:
            try:
                output["instagram"] = ig(now)
            except Exception:
                failures["instagram"] = "Instagram read failed"
    if "facebook" in enabled:
        try:
            output["facebook"] = fb(now, page=toonzone)
        except Exception:
            failures["facebook"] = "Facebook read failed"
    if "threads" in enabled:
        try:
            # threads_posts validates ToonZone token username and post provenance.
            user, posts = threads("toonzone", now.astimezone(ISTANBUL).replace(
                hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc))
            output["threads"] = [
                link for post_id, published, link in sorted(posts, key=lambda p: p[1])
                if published.astimezone(ISTANBUL).date() == now.astimezone(ISTANBUL).date()
                and safe_threads_link(link)
            ]
        except Exception:
            failures["threads"] = "Threads read failed"
    return output, failures


def safe_threads_link(link):
    parts = urlsplit(link) if isinstance(link, str) else None
    return bool(parts and parts.scheme == "https" and
                parts.hostname in {"www.threads.net", "threads.net", "www.threads.com", "threads.com"} and
                re.fullmatch(r"/@[A-Za-z0-9_.]+/post/[A-Za-z0-9_-]+/?", parts.path) and
                not parts.query and not parts.fragment)


def build_platform_message(actor, day, result, failures):
    if actor not in ACCOUNT_ROUTES:
        raise ValueError("unknown account")
    lines = [f"{actor} · ToonZone · {day.isoformat()}", "Bugünkü video bağlantıları:"]
    for platform in PLATFORMS:
        if platform in failures:
            lines.append(f"{platform.title()}: doğrulama yapılamadı")
        elif platform in result:
            links = result[platform]
            lines.append(f"{platform.title()}: {len(links)} video")
            lines.extend("• " + link for link in links[:8])
            if len(links) > 8:
                lines.append(f"+{len(links) - 8} diğer video")
        else:
            lines.append(f"{platform.title()}: bu hesapta bağlantı yapılandırılmamış")
    lines.append("İnceleme ve organik tanıtım önerisi. Otomatik beğeni/kaydetme yapılmadı.")
    return "\n".join(lines)


def main(now=None):
    now = now or datetime.now(timezone.utc)
    slot = choose_slot(now)
    if slot is None:
        print(json.dumps({"status": "outside_schedule", "writes": 0}))
        return 0
    index, actor, day = slot
    results, failures = collect_platforms(now, actor)
    # Explicitly run in read-only mode in CI and on PRs.
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        print(json.dumps({"status": "preview", "slot": index, "platforms": list(results), "failures": failures, "writes": 0}))
        return 0
    if os.getenv("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("duplicate workflow attempt blocked")
    if os.getenv("TOONZONE_REVIEW_NOTIFICATIONS_ENABLED", "true") != "true":
        print(json.dumps({"status": "disabled", "slot": index, "writes": 0}))
        return 0
    send_telegram("🎬 ToonZone günlük platform kontrolü", build_platform_message(actor, day, results, failures))
    print(json.dumps({"status": "telegram_sent", "slot": index, "platforms": list(results),
                      "failures": failures, "meta_writes": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
