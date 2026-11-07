import os
from publication_safety import route_paused
import time
from datetime import datetime

import requests

from cloud_omnichannel_publisher import GRAPH_API_VERSION
from scheduled_multi_publisher import TZ, meta_page, run


TARGET_PER_DAY = int(os.environ.get("TARGET_PER_DAY", "7"))
ROUTES = {
    "gonle_fb": ("Gönle Düşen", "facebook"),
    "gonle_ig": ("Gönle Düşen", "instagram"),
    "daily_laugh": ("Daily Laugh Lab", "facebook"),
    "tarladaki": ("Tarladaki Fasulye", "facebook"),
    "penguen": ("Beyinsiz Penguen", "facebook"),
}


def facebook_posts_today(page, now):
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{page['page_id']}/videos",
        params={
            "fields": "id,created_time",
            "limit": 100,
            "access_token": page["page_token"],
        },
        timeout=30,
    )
    response.raise_for_status()
    today = now.date()
    return sum(
        1
        for item in response.json().get("data", [])
        if item.get("created_time")
        and datetime.fromisoformat(item["created_time"].replace("Z", "+00:00"))
        .astimezone(TZ)
        .date()
        == today
    )


def instagram_posts_today(page, now):
    instagram_id = page.get("instagram_id")
    if not instagram_id:
        return None
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{instagram_id}/media",
        params={
            "fields": "id,media_type,timestamp",
            "limit": 100,
            "access_token": page["page_token"],
        },
        timeout=30,
    )
    response.raise_for_status()
    today = now.date()
    return sum(
        1
        for item in response.json().get("data", [])
        if item.get("media_type") in {"VIDEO", "REELS"}
        and item.get("timestamp")
        and datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        .astimezone(TZ)
        .date()
        == today
    )


def main():
    now = datetime.now(TZ)
    only_route = os.environ.get("BACKFILL_ROUTE", "").strip().lower()
    audit_only = os.environ.get("BACKFILL_AUDIT_ONLY", "").strip().lower() == "true"
    routes = list(ROUTES) if only_route in {"", "all"} else [only_route]
    failures = []
    for route in routes:
        if route_paused(route) and not audit_only:
            print(f"Duraklatılan rota atlandı: {route}", flush=True)
            continue
        if route not in ROUTES:
            raise RuntimeError(f"Geçersiz BACKFILL_ROUTE: {route}")
        page_name, target_platform = ROUTES[route]
        page = meta_page(page_name)
        facebook_current = facebook_posts_today(page, now)
        instagram_current = instagram_posts_today(page, now)
        if target_platform == "instagram":
            if instagram_current is None:
                raise RuntimeError(f"{page_name}: Instagram bağlı değil")
            current = instagram_current
        else:
            current = facebook_current
        missing = max(0, TARGET_PER_DAY - current)
        instagram_text = "bağlı değil" if instagram_current is None else str(instagram_current)
        print(
            f"{page_name} [{target_platform}]: Facebook bugün {facebook_current}, "
            f"Instagram bugün {instagram_text}, hedef platform eksiği {missing}",
            flush=True,
        )
        if audit_only:
            continue
        for index in range(missing):
            os.environ["FORCE_ROUTE"] = route
            # Only the missing platform. A network exception after a POST is
            # ambiguous; the legacy three-attempt loop could duplicate posts.
            os.environ["FORCE_PLATFORM"] = target_platform
            os.environ["FORCE_SLOT_SUFFIX"] = f"backfill-{now:%Y%m%d}-{index + 1}"
            try:
                run()
            except Exception:
                # Preserve the original intent and let the next scheduled
                # read-only platform history reconcile it. Never blindly retry.
                failures.append(f"{page_name} [{target_platform}] gönderi {index + 1}")
                print(f"{page_name} [{target_platform}] belirsiz/başarısız gönderi "
                      f"{index + 1}: uzaktan geçmiş denetlenmeden POST tekrar edilmeyecek.",
                      flush=True)
                break
            time.sleep(5)

    if failures:
        raise RuntimeError("Tamamlanamayan yayınlar: " + ", ".join(failures))


if __name__ == "__main__":
    main()
