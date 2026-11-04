"""Mirror confirmed, owned Instagram videos into their matching Threads account."""
import argparse
import hashlib
import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests

import publisher_alert_history as archive
from meta_auth_loader import load_meta_auth
from publication_github_progress import restore_publication_state
from publication_safety import route_paused
from publisher_recovery import read_with_retry
from threads_accounts import THREADS_ROUTE_PREFIXES, threads_account_config

WORKFLOW = ".github/workflows/threads_live_publish.yml"
NAMES = ("threads-publish-intent", "threads-publish-result")
ROOT = Path("threads-runtime")
HISTORY = ROOT / "alert-history.json"
PLAN = ROOT / "plan.json"
THREADS = "https://graph.threads.com/v1.0"
META = "https://graph.facebook.com/v24.0"
ROUTES = {
    "tarladaki": "Tarladaki Fasulye", "penguen": "Beyinsiz Penguen",
    "gonle": "Gönle Düşen", "daily_laugh": "Daily Laugh Lab",
    "film": "Film Mağarası", "toonzone": "ToonZone",
}
ID = re.compile(r"[0-9]{1,30}\Z")
DRIVE_ID = re.compile(r"[A-Za-z0-9_-]{20,128}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FIRST_PREPUBLISH_FAILURE = "41869402302"
REEL = re.compile(r"https://www\.instagram\.com/(?:reel|p)/[A-Za-z0-9_-]+/?\Z")


class ProviderError(RuntimeError):
    def __init__(self, stage, response):
        self.stage = stage
        self.status = response.status_code
        try:
            code = response.json().get("error", {}).get("code")
        except (ValueError, AttributeError):
            code = None
        self.code = code if type(code) is int else None
        super().__init__(f"{stage}_http_{self.status}_code_{self.code}")


def graph(base, path, token, *, payload=None, **fields):
    url = f"{base}/{path}"
    headers = {"Authorization": f"Bearer {token}"}
    if payload is None:
        response = read_with_retry(requests.get, url, headers=headers, params=fields,
                                   timeout=20, allow_redirects=False, graph_read=True)
    else:
        response = requests.post(url, headers=headers, data=payload, timeout=30,
                                 allow_redirects=False)
    if response.status_code != 200:
        raise ProviderError("write" if payload is not None else "read", response)
    data = response.json()
    if not isinstance(data, dict) or data.get("error"):
        raise ProviderError("write" if payload is not None else "read", response)
    return data


def profile(account):
    row = graph(THREADS, "me", account.token, fields="id,username")
    identifier = str(row.get("id", ""))
    if (not ID.fullmatch(identifier) or str(row.get("username", "")).casefold() != account.username.casefold()
            or (account.expected_user_id and account.expected_user_id != identifier)):
        raise RuntimeError("threads_identity_mismatch")
    return identifier


def rows(base, path, token, fields):
    """Only fixed endpoint GETs; the returned next URL is never followed."""
    cursor = None
    seen = set()
    for _ in range(4):
        params = {"fields": fields, "limit": 50}
        if cursor:
            params["after"] = cursor
        data = graph(base, path, token, **params)
        batch = data.get("data")
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise RuntimeError("invalid_account_history")
        yield from batch
        paging = data.get("paging") or {}
        if not paging.get("next"):
            return
        cursor = (paging.get("cursors") or {}).get("after")
        if not isinstance(cursor, str) or not cursor or len(cursor) > 1024 or cursor in seen:
            raise RuntimeError("invalid_account_cursor")
        seen.add(cursor)
    raise RuntimeError("account_history_limit")


def link_for(row):
    link = row.get("permalink")
    if not isinstance(link, str) or not REEL.fullmatch(link):
        raise RuntimeError("invalid_instagram_permalink")
    return link.rstrip("/") + "/"


def safe_media_url(url):
    if not isinstance(url, str) or len(url) > 4000:
        return False
    p = urlsplit(url)
    host = p.hostname or ""
    return (p.scheme == "https" and p.netloc == host and not p.fragment
            and (host == "drive.usercontent.google.com" or host.endswith(".googleusercontent.com")))


def ready_media(source_id, expected_hash):
    """Validate the actual, already shared source before exposing its URL to Threads."""
    if not DRIVE_ID.fullmatch(source_id) or not SHA256.fullmatch(expected_hash):
        raise RuntimeError("unverified_drive_source")
    url = "https://drive.usercontent.google.com/download?" + urlencode(
        {"id": source_id, "export": "download", "confirm": "t"})
    for _ in range(4):
        with requests.get(url, timeout=(8, 25), stream=True, allow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                url = response.headers.get("Location", "")
                if not safe_media_url(url):
                    raise RuntimeError("untrusted_drive_redirect")
                continue
            if response.status_code != 200:
                raise RuntimeError(f"drive_video_http_{response.status_code}")
            digest, total, head = hashlib.sha256(), 0, b""
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                if not total:
                    head = chunk[:8]
                    if head[4:8] != b"ftyp":
                        raise RuntimeError("drive_source_not_mp4")
                total += len(chunk)
                if total > 300_000_000:
                    raise RuntimeError("drive_source_too_large")
                digest.update(chunk)
            if not total or digest.hexdigest() != expected_hash:
                raise RuntimeError("drive_source_hash_changed")
            return url
    raise RuntimeError("drive_redirect_limit")


def sources(route, state, feed, now):
    accepted = {}
    for key, row in state["entries"].items():
        prefix = f"{route}:instagram:"
        if (not key.startswith(prefix) or row.get("route") != route or row.get("platform") != "instagram"
                or row.get("status") != "done" or not ID.fullmatch(str(row.get("post_id", "")))):
            continue
        source = row.get("duplicate_of_file_id") or key.removeprefix(prefix)
        accepted.setdefault(str(row["post_id"]), (str(source), str(row.get("source_sha256") or "")))
    candidates = []
    for row in feed:
        identifier = str(row.get("id", ""))
        if identifier not in accepted or row.get("media_type") != "VIDEO":
            continue
        timestamp = archive.stamp(row.get("timestamp"))
        if not now - timedelta(days=2) <= timestamp <= now:
            continue
        source_id, digest = accepted[identifier]
        candidates.append((timestamp, identifier, source_id, dict(row, source_sha256=digest)))
    return sorted(candidates, key=lambda item: item[:3])


def caption_for(row):
    body = str(row.get("caption") or "").strip()
    suffix = "\n\nInstagram: " + link_for(row)
    # The Threads reference counts emojis by their UTF-8 byte length.
    budget = 500 - len(suffix.encode("utf-8"))
    body = body.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return (body + suffix).strip()


def owns_post(row, user, marker):
    identifier = str(row.get("id", ""))
    link = row.get("permalink")
    text = row.get("text")
    if not isinstance(link, str) or not isinstance(text, str) or not ID.fullmatch(identifier):
        return False
    p = urlsplit(link)
    return (p.scheme == "https" and p.netloc in {"www.threads.com", "threads.com", "www.threads.net", "threads.net"}
            and re.fullmatch(r"/@" + re.escape(user) + r"/post/[A-Za-z0-9_-]+/?", p.path, re.I)
            and row.get("media_type") == "VIDEO" and marker in text.splitlines())


def choose(route, account, target, candidates, history, own_posts, run_id, now):
    records = history["records"]
    prior = [row for row in records.values() if row.get("route") == route]
    recovery = None
    for record in prior:
        if record["user_id"] != target:
            raise RuntimeError("archived_threads_identity_changed")
        if record["status"] != "verified":
            matches = [p for p in own_posts if owns_post(p, account.username, record["marker"])]
            if not matches and (record["intent_run_id"] == FIRST_PREPUBLISH_FAILURE
                                and record["status"] == "attempted"
                                and record.get("failure") == "container_error"
                                and not record.get("post_id") and recovery is None):
                # The audited first run exited during container processing.
                # No threads_publish call was reached for these exact rows.
                recovery = record
                continue
            if len(matches) != 1:
                raise RuntimeError("previous_threads_intent_unresolved")
            record.update(status="verified", post_id=matches[0]["id"], permalink=matches[0]["permalink"])
    newest = max((archive.stamp(row["source_published_at"]) for row in prior), default=None)
    seen = {row["source_id"] for row in prior}
    seen_posts = {row["instagram_id"] for row in prior}
    eligible = [p for p in candidates if p[2] not in seen and p[1] not in seen_posts
                and (newest is None or p[0] > newest)]
    if recovery:
        eligible = [p for p in candidates if p[1] == recovery["instagram_id"]
                    and p[2] == recovery["source_id"] and "Instagram: " + link_for(p[3]) == recovery["marker"]]
        if len(eligible) != 1:
            raise RuntimeError("recovery_source_unavailable")
    if not eligible:
        return None
    timestamp, ig_id, source_id, row = eligible[-1] if newest is None else eligible[0]
    marker = "Instagram: " + link_for(row)
    matches = [p for p in own_posts if owns_post(p, account.username, marker)]
    if len(matches) > 1:
        raise RuntimeError("threads_duplicate_history")
    key = archive.identity("threads_video", route, "threads", source_id)
    url = None if matches else ready_media(source_id, row.get("source_sha256", ""))
    record = dict(route=route, source_id=source_id, instagram_id=ig_id, user_id=target,
                  source_published_at=timestamp.isoformat(), marker=marker,
                  last_seen=now.isoformat(), intent_run_id=run_id, status="reserved")
    if matches:
        record.update(status="verified", post_id=matches[0]["id"], permalink=matches[0]["permalink"])
    if recovery:
        record["initial_failed_run_id"] = FIRST_PREPUBLISH_FAILURE
    records[key] = record
    if matches:
        return None
    return dict(key=key, route=route, url=url, text=caption_for(row))


def error_label(exc):
    if isinstance(exc, ProviderError):
        return str(exc)
    # Only internal literal failure codes. Never emit response bodies or URLs.
    if type(exc) is RuntimeError and re.fullmatch(r"[a-z0-9_]{1,80}", str(exc)):
        return str(exc)
    return type(exc).__name__


def account_config(route):
    return threads_account_config(route, require_enabled=False, require_media=False)


def prepare(run_id):
    history = archive.restore(names=NAMES, workflow_path=WORKFLOW)
    state = restore_publication_state()
    pages = {p["page_name"]: p for p in load_meta_auth()["pages"]}
    now = archive.now_utc()
    plans, status = [], {}
    for route, name in ROUTES.items():
        if (os.getenv(f"ENABLE_{THREADS_ROUTE_PREFIXES[route]}_THREADS", "true").lower() == "false"
                or route_paused(route)
                or (route == "daily_laugh" and route_paused("daily_laugh_instagram"))
                or (route == "gonle" and route_paused("gonle_ig"))):
            status[route] = "route_or_rights_disabled"
            continue
        try:
            account = account_config(route)
            target = profile(account)
            page = pages[name]
            ig = str(page.get("instagram_id") or "")
            if not ID.fullmatch(ig):
                raise RuntimeError("source_instagram_not_linked")
            owned = rows(META, f"{ig}/media", page["page_token"],
                         "id,caption,media_type,permalink,timestamp")
            # Instagram supplies newest first; current sources need only one
            # page, and the publisher ledger independently supplies post IDs.
            from itertools import islice
            candidates = sources(route, state, islice(owned, 50), now)
            own = list(islice(rows(THREADS, "me/threads", account.token,
                                   "id,text,media_type,permalink,timestamp"), 50))
            plan = choose(route, account, target, candidates, history, own, run_id, now)
            if plan:
                plans.append(plan)
            status[route] = "reserved" if plan else "no_new_eligible_video"
        except Exception as exc:
            status[route] = error_label(exc)
    archive.save(HISTORY, archive.validate(history))
    archive.save(PLAN, {"run_id": run_id, "plans": plans})
    print(json.dumps({"routes": status, "reserved": len(plans), "threads_posts_sent": 0}), flush=True)


def publish(plan, record, account):
    if profile(account) != record["user_id"] or not safe_media_url(plan["url"]):
        raise RuntimeError("publish_identity_or_source_changed")
    target = record["user_id"]
    container = graph(THREADS, f"{target}/threads", account.token,
                      payload={"media_type": "VIDEO", "video_url": plan["url"], "text": plan["text"]})
    identifier = str(container.get("id", ""))
    if not ID.fullmatch(identifier):
        raise RuntimeError("container_id_missing")
    for _ in range(30):
        time.sleep(4)
        status = graph(THREADS, identifier, account.token, fields="status,error_message")
        phase = status.get("status")
        if phase == "FINISHED":
            break
        if phase in {"ERROR", "EXPIRED", "PUBLISHED"}:
            message = str(status.get("error_message", "")).lower()
            if phase == "ERROR":
                if any(word in message for word in ("fetch", "download", "url", "access")):
                    raise RuntimeError("container_source_download_rejected")
                if any(word in message for word in ("format", "codec", "duration", "size", "resolution")):
                    raise RuntimeError("container_media_format_rejected")
            raise RuntimeError("container_" + phase.lower())
    else:
        raise RuntimeError("container_not_finished")
    post = graph(THREADS, f"{target}/threads_publish", account.token,
                 payload={"creation_id": identifier})
    post_id = str(post.get("id", ""))
    if not ID.fullmatch(post_id):
        raise RuntimeError("published_id_missing")
    record["post_id"] = post_id
    evidence = graph(THREADS, post_id, account.token, fields="id,text,media_type,permalink")
    if str(evidence.get("id")) != post_id or not owns_post(evidence, account.username, record["marker"]):
        raise RuntimeError("published_post_unverified")
    return {"status": "verified", "post_id": post_id, "permalink": evidence["permalink"]}


def execute(run_id):
    if os.getenv("THREADS_INTENT_ARCHIVED") != "true":
        raise RuntimeError("threads_intent_not_archived")
    data, history = archive.read(PLAN), archive.validate(archive.read(HISTORY))
    if data["run_id"] != run_id:
        raise RuntimeError("threads_intent_run_mismatch")
    failed = False
    for plan in data["plans"]:
        record = history["records"][plan["key"]]
        if (record["route"] != plan["route"] or record["intent_run_id"] != run_id
                or record["status"] != "reserved" or record["marker"] not in plan["text"].splitlines()):
            raise RuntimeError("invalid_threads_reservation")
        record["status"] = "attempted"
        archive.save(HISTORY, history)
        try:
            record.update(publish(plan, record, account_config(plan["route"])))
            print(json.dumps({"route": plan["route"], "status": "verified",
                              "post_id": record["post_id"], "permalink": record["permalink"]}), flush=True)
        except Exception as exc:
            failed = True
            record["failure"] = error_label(exc)
            print(json.dumps({"route": plan["route"], "status": "held",
                              "reason": record["failure"]}), flush=True)
        archive.save(HISTORY, history)
    return int(failed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "publish"))
    action = parser.parse_args().action
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if (os.getenv("GITHUB_REPOSITORY") != archive.REPO or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1" or not ID.fullmatch(run_id)):
        return 1
    try:
        if action == "prepare":
            prepare(run_id)
            return 0
        return execute(run_id)
    except Exception as exc:
        print(json.dumps({"status": "blocked", "reason": error_label(exc)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
