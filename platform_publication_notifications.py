"""Notify the owner of newly verified Threads and YouTube publications."""
import argparse
import json
import os
from datetime import timedelta
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

import publisher_alert_history as history_io
from publisher_recovery import read_with_retry
from telegram_notifications import send_telegram, telegram_configured
from threads_accounts import THREADS_ROUTE_PREFIXES, threads_account_config
from threads_publisher import validate_threads_identity
from youtube_accepted_audit import VIDEO_ID, load_archived_state
from youtube_main_bridge import ROUTES as YOUTUBE_ROUTES
from youtube_readonly_connection import check_channel

ARTIFACTS = ("platform-notification-intent", "platform-notification-result")
WORKFLOW = ".github/workflows/platform_publication_notifications.yml"
RUNTIME = Path("platform-notification-runtime")
HISTORY = RUNTIME / "alert-history.json"
PLAN = RUNTIME / "notification-plan.json"
LOOKBACK = timedelta(days=2)
THREADS_ID = re.compile(r"[0-9]{1,30}\Z")
THREADS_FEED_URL = "https://graph.threads.com/v1.0/me/threads"
THREADS_HOSTS = {"threads.net", "www.threads.net", "threads.com", "www.threads.com"}
PLATFORMS = {"threads": "Threads", "youtube": "YouTube"}
ROUTE_LABELS = {
    "tarladaki": "Tarladaki Fasulye",
    "penguen": "Beyinsiz Penguen",
    "gonle": "Gönle Düşen",
    "daily_laugh": "Daily Laugh Lab",
    "film": "Film Mağarası",
    "toonzone": "ToonZone",
}


def threads_link(value):
    if not isinstance(value, str) or len(value) > 180 or any(ch.isspace() for ch in value):
        return ""
    url = urlsplit(value)
    if (url.scheme == "https" and url.netloc.lower() in THREADS_HOSTS
            and re.fullmatch(r"/@[A-Za-z0-9_.]+/post/[A-Za-z0-9_-]+/?", url.path)):
        return f"https://{url.netloc.lower()}{url.path}"
    return ""


def threads_posts(route, cutoff):
    account = threads_account_config(route, require_enabled=False, require_media=False)
    identity = validate_threads_identity(token=account.token, expected_username=account.username)
    user_id = identity["id"]
    if not THREADS_ID.fullmatch(user_id) or (account.expected_user_id and account.expected_user_id != user_id):
        raise ValueError("unexpected Threads user ID")
    params = {"fields": "id,timestamp,permalink", "limit": 50, "since": cutoff.date().isoformat()}
    posts, cursors = [], set()
    for _ in range(5):
        response = read_with_retry(
            requests.get, THREADS_FEED_URL,
            params=params, headers={"Authorization": f"Bearer {account.token}"},
            timeout=20, allow_redirects=False, graph_read=True,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get("data"), list) or data.get("error"):
            raise ValueError("invalid Threads feed response")
        for row in data["data"]:
            post_id = row.get("id", "")
            published = history_io.stamp(row.get("timestamp"))
            if not isinstance(post_id, str) or not THREADS_ID.fullmatch(post_id):
                raise ValueError("invalid Threads post identity")
            if published >= cutoff:
                posts.append((post_id, published, threads_link(row.get("permalink"))))
        paging = data.get("paging") or {}
        if not paging.get("next"):
            return user_id, posts
        after = (paging.get("cursors") or {}).get("after")
        if not isinstance(after, str) or not after or after in cursors or len(after) > 1024:
            raise ValueError("invalid Threads feed cursor")
        cursors.add(after)
        params["after"] = after
    raise ValueError("Threads feed pagination exceeded")


def youtube_posts(route, ledger, cutoff):
    target, secret, channel = YOUTUBE_ROUTES[route]
    identity = check_channel(target)
    if identity.get("status") != "verified" or identity.get("channel_id") != channel:
        raise ValueError("unexpected YouTube channel identity")
    # Prioritize recent runs. Fifty candidates cover several days even for
    # accounts on an eight-video quota, and fit one videos.list request.
    candidates = {}
    for row in ledger.values():
        if not isinstance(row, dict) or row.get("route") != route:
            continue
        post_id, run = row.get("post_id"), str(row.get("run_id", ""))
        if (row.get("channel_id") == channel and row.get("status") in {"accepted", "done"}
                and isinstance(post_id, str) and VIDEO_ID.fullmatch(post_id) and run.isascii() and run.isdigit()):
            candidates[post_id] = max(candidates.get(post_id, 0), int(run))
    post_ids = sorted(candidates, key=candidates.get, reverse=True)[:50]
    if not post_ids:
        return channel, []
    credentials = Credentials.from_authorized_user_info(json.loads(os.environ[secret]))
    with AuthorizedSession(credentials) as session:
        response = read_with_retry(
            session.get, "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,status", "id": ",".join(post_ids)},
            timeout=20, allow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data.get("items"), list):
        raise ValueError("invalid YouTube verification response")
    posts = []
    for row in data["items"]:
        snippet, status = row.get("snippet", {}), row.get("status", {})
        post_id = row.get("id")
        if post_id not in post_ids or snippet.get("channelId") != channel:
            raise ValueError("unexpected YouTube video identity")
        if status.get("privacyStatus") != "public" or status.get("uploadStatus") != "processed":
            continue
        published = history_io.stamp(snippet.get("publishedAt"))
        if published >= cutoff:
            posts.append((post_id, published, f"https://www.youtube.com/watch?v={post_id}"))
    return channel, posts


def collect(cutoff):
    """Failures on one platform/account do not suppress another account."""
    sources, failures = {}, {}
    try:
        ledger = load_archived_state().get("youtube_entries", {})
        if not isinstance(ledger, dict):
            raise ValueError("invalid archived YouTube ledger")
    except Exception:
        failures["youtube"] = "publication_archive_unavailable"
    else:
        for route in YOUTUBE_ROUTES:
            try:
                sources["youtube", route] = youtube_posts(route, ledger, cutoff)
            except Exception as exc:
                failures[f"youtube:{route}"] = safe_read_error(exc)
    for route in THREADS_ROUTE_PREFIXES:
        try:
            sources["threads", route] = threads_posts(route, cutoff)
        except Exception as exc:
            failures[f"threads:{route}"] = safe_read_error(exc)
    return sources, failures


def safe_read_error(exc):
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"read_failed_http_{status}" if type(status) is int and 400 <= status <= 599 else "read_failed"


def reserve_notices(history, sources, run_id, now):
    baselines = history.setdefault("baselines", {})
    if (not isinstance(baselines, dict)
            or any(not isinstance(value, str) for value in baselines.values())):
        raise ValueError("invalid account baselines")
    records = history["records"]
    # Input feeds only carry the last two days; old reservations can expire
    # without making any still-eligible publication announce again.
    for key in list(records):
        if history_io.stamp(records[key]["last_seen"]) < now - timedelta(days=7):
            del records[key]
    messages = []
    seeded = 0
    for (platform, route), (identity, posts) in sources.items():
        account = f"{platform}:{route}"
        first_read = baselines.get(account) != identity
        baselines[account] = identity
        new = {}
        for post_id, published, link in sorted(posts, key=lambda post: post[1]):
            if not now - LOOKBACK <= published <= now:
                continue
            key = history_io.identity("post", route, platform, extra=f"{identity}:{post_id}")
            if key in records:
                continue
            descriptor = {"kind": "post", "route": route, "platform": platform}
            if first_read:
                records[key] = dict(descriptor, last_seen=now.isoformat(), last_intent=now.isoformat())
                seeded += 1
            else:
                new[key] = (descriptor, link or f"Gönderi ID: {post_id}")
        keys = list(new)
        for start in range(0, len(keys), 12):
            chunk = keys[start:start + 12]
            label = PLATFORMS[platform]
            title = f"✅ {label} yayın bildirimi"
            body = f"{ROUTE_LABELS[route]} · {len(chunk)} yeni gönderi\n"
            body += "\n".join(f"• {new[key][1]}" for key in chunk)
            message = history_io.reserve(history, title, body,
                {key: new[key][0] for key in chunk}, run_id, now=now)
            messages.append(message)
    return messages, seeded


def prepare(run_id):
    now = history_io.now_utc()
    history = history_io.restore(names=ARTIFACTS, workflow_path=WORKFLOW)
    sources, failures = collect(now - LOOKBACK)
    messages, seeded = reserve_notices(history, sources, run_id, now)
    history_io.save(HISTORY, history_io.validate(history))
    history_io.save(PLAN, {"run_id": run_id, "messages": messages, "failures": failures})
    print(json.dumps({"checked_accounts": len(sources), "baseline_posts": seeded,
                      "reserved_messages": len(messages), "read_failures": failures}), flush=True)


def send(run_id):
    if os.getenv("PLATFORM_NOTICE_INTENT_ARCHIVED") != "true":
        raise ValueError("platform notification intent not archived")
    plan = history_io.read(PLAN)
    history = history_io.validate(history_io.read(HISTORY))
    if plan["run_id"] != run_id:
        raise ValueError("platform notification run mismatch")
    records = history["records"]
    messages = plan["messages"]
    if any(records[key].get("intent_run_id") != run_id for msg in messages for key in msg["keys"]):
        raise ValueError("platform notification reservation mismatch")
    acknowledged = failed = 0
    for message in messages:
        rows = [records[key] for key in message["keys"]]
        if any("telegram" in row.get("attempted_channels", ()) for row in rows):
            if not all("telegram" in row.get("server_acks", ()) for row in rows):
                failed += 1
            continue
        for row in rows:
            row.setdefault("attempted_channels", []).append("telegram")
        history_io.save(HISTORY, history)
        try:
            if send_telegram(message["title"], message["body"]).get("server_ack") is not True:
                raise RuntimeError("missing Telegram acknowledgement")
        except Exception:
            failed += 1
        else:
            history_io.mark_ack(history, message, "telegram")
            acknowledged += 1
        history_io.save(HISTORY, history)
    print(json.dumps({"telegram_server_acks": acknowledged, "delivery_failures": failed,
                      "read_failures": plan["failures"]}), flush=True)
    return int(bool(failed))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "send"))
    action = parser.parse_args().action
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if (os.getenv("GITHUB_REPOSITORY") != history_io.REPO or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1" or not run_id.isascii() or not run_id.isdigit()):
        print("Platform bildirimi çalışma kimliği doğrulanmadı.", flush=True)
        return 1
    if not telegram_configured():
        print("Platform bildirimi için Telegram yapılandırması eksik.", flush=True)
        return 1
    try:
        if action == "prepare":
            prepare(run_id)
            return 0
        return send(run_id)
    except Exception:
        print("Platform bildirim kaydı doğrulanamadı.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
