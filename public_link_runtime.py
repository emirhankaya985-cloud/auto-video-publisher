"""Meta-only publishing from the owner's shared links, without Drive OAuth.

The workflow persists its complete intent before uploading any media. An
uncertain publication is held for reconciliation, never blindly retried.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import time
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import gdown
import requests

from cloud_omnichannel_publisher import (
    GRAPH_API_VERSION, MetaAPIError, create_instagram_cover_video,
    upload_facebook_reel, upload_instagram_reel, _sanitize_meta_text,
)
from instagram_media_compat import prepare_instagram_upload
from meta_auth_loader import load_meta_auth
from ordered_channels import TOONZONE_ETSY_LINK, parse_order, toonzone_metadata
from publication_safety import route_paused
from publisher_recovery import read_with_retry, classify_meta_failure
from scheduled_multi_publisher import (
    platform_content_from_txt, TARLADAKI_HOURS, PENGUEN_HOURS,
    GONLE_HOURS, FILM_HOURS, daily_laugh_hours_for_date,
)

TR = ZoneInfo("Europe/Istanbul")
ROOT = Path("link-runtime")
STATE = ROOT / "state.json"
PLAN = ROOT / "plan.json"
FOLDERS = {
    "humor": "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M",
    "gonle": "1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt",
    "daily_laugh": "137--TeBht1yikZpMfV9VSEADbKuXZtLT",
    "film": "1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW",
    "toonzone": "14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF",
    "covers": "1YlGz6rKfW_S2eMW82zOs09flCGtwYWMO",
}
ROUTES = {
    "tarladaki": ("humor", "Tarladaki Fasulye"),
    "penguen": ("humor", "Beyinsiz Penguen"),
    "gonle": ("gonle", "Gönle Düşen"),
    "daily_laugh": ("daily_laugh", "Daily Laugh Lab"),
    "film": ("film", "Film Mağarası"),
    "film_second": ("film", "Filmmagrasi"),
    "toonzone": ("toonzone", "ToonZone"),
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def caption_key(value):
    value = re.sub(r"https://www\.etsy\.com/\S+", "", value or "")
    value = re.sub(r"\bEtsy:\s*", "", value, flags=re.I)
    return hashlib.sha256(" ".join(value.split()).encode()).hexdigest()


def github_get(path):
    repo = os.environ["GITHUB_REPOSITORY"]
    response = read_with_retry(
        requests.get, f"https://api.github.com/repos/{repo}/{path}",
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"}, timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"GitHub durum kaydı okunamadı: HTTP {response.status_code}")
    return response


def restore():
    """Newest run's result wins; otherwise its pre-upload intent is authoritative."""
    def artifact_list(name):
        payload = github_get(f"actions/artifacts?per_page=100&name={name}").json()
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
            raise RuntimeError("GitHub durum listesi geçersiz; otomatik sıfırlama yapılmadı")
        return payload["artifacts"]
    artifacts = artifact_list("link-state-result")
    intents = artifact_list("link-state-intent")
    rows = [x for x in artifacts + intents if not x.get("expired")]
    if not rows:
        if artifacts or intents:
            raise RuntimeError("Önceki durum kaydının süresi dolmuş; otomatik sıfırlama yapılmadı")
        return {"schema": 1, "entries": {}, "episode_days": {}}
    rows.sort(key=lambda x: (int(x["workflow_run"]["id"]), x["name"] == "link-state-result"), reverse=True)
    response = github_get(f"actions/artifacts/{rows[0]['id']}/zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = [name for name in archive.namelist() if name.endswith("state.json")]
        if len(names) != 1:
            raise RuntimeError("Önceki durum arşivi geçersiz; otomatik sıfırlama yapılmadı")
        state = json.loads(archive.read(names[0]))
    if state.get("schema") != 1 or not isinstance(state.get("entries"), dict):
        raise RuntimeError("Önceki yayın durumu geçersiz")
    return state


def inventory(folder):
    # Drive folder metadata is a read-only operation; retry transient failures.
    files = None
    for attempt in range(3):
        try:
            files = gdown.download_folder(id=folder, skip_download=True, quiet=True,
                                         use_cookies=False, timeout=40)
            if files is not None:
                break
        except Exception:
            if attempt == 2:
                raise
        if attempt < 2:
            time.sleep(2 ** attempt)
    if files is None:
        raise RuntimeError("Paylaşılan Drive klasör listesi 3 denemede alınamadı")
    result, ambiguous = {}, set()
    for item in files:
        if len(Path(item.path).parts) != 1:
            continue
        name = Path(item.path).name
        # Exclude recursive child folders: they must use their own approved source.
        if name in result and result[name]["id"] != item.id:
            if folder != FOLDERS["daily_laugh"]:
                raise RuntimeError("Aynı adlı birden çok Drive dosyası bulundu")
            ambiguous.add(name)
        result[name] = {"id": item.id, "name": name}
    for name in ambiguous:
        result.pop(name, None)
    if not result:
        raise RuntimeError("Paylaşılan klasör boş veya erişilemiyor")
    return result


def download(file_id, path):
    """Retry transient read-only Drive transfers before touching Meta.

    Never return partial files; exhaust retries rather than reusing corrupted
    content. The publication intent ledger still controls all Meta retries.
    """
    failures = []
    for attempt in range(3):
        try:
            result = gdown.download(id=file_id, output=str(path), quiet=True,
                                    use_cookies=True, timeout=40)
            if result and path.is_file() and path.stat().st_size > 0:
                return path
            failures.append("empty_or_missing")
        except Exception as exc:
            # The Drive provider can raise FileURLRetrievalError on a transient
            # shared-link fetch. Do not log untrusted exception URLs/tokens.
            failures.append(type(exc).__name__)
        if path.exists():
            path.unlink()
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError(
        "Paylaşılan Drive dosyası 3 denemede indirilemedi "
        f"({','.join(failures)})"
    ) from None


def graph_rows(page, platform):
    object_id = page["page_id"] if platform == "facebook" else page.get("instagram_id")
    if not object_id:
        return []
    fields = "id,description,created_time" if platform == "facebook" else "id,caption,timestamp,permalink,media_type"
    edge = "videos" if platform == "facebook" else "media"
    params = {"fields": fields, "limit": 100}
    rows, seen = [], set()
    for _ in range(40):
        response = read_with_retry(
            requests.get, f"https://graph.facebook.com/{GRAPH_API_VERSION}/{object_id}/{edge}",
            headers={"Authorization": f"Bearer {page['page_token']}"},
            params=params, timeout=30,
        )
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("Meta geçmiş yanıtı geçersiz") from None
        if response.status_code != 200 or not isinstance(payload.get("data"), list):
            error = payload.get("error") or {}
            raise RuntimeError(f"Meta geçmişi okunamadı: HTTP {response.status_code}, kod {error.get('code', 'unknown')}")
        for media in payload["data"]:
            if not isinstance(media, dict):
                raise RuntimeError("Meta geçmişinde geçersiz medya kaydı")
            if platform == "instagram":
                media_type = media.get("media_type")
                if not isinstance(media_type, str):
                    raise RuntimeError("Instagram medya türü alınamadı; güvenli sayım mümkün değil")
                # Only video/reel media count toward the video publication target.
                # Instagram photos must never satisfy a missing Reels slot.
                if media_type != "VIDEO":
                    continue
            rows.append(media)
        paging = payload.get("paging") or {}
        if not paging.get("next"):
            return rows
        after = (paging.get("cursors") or {}).get("after")
        if not after or after in seen:
            raise RuntimeError("Meta geçmişi eksik; yayın durduruldu")
        seen.add(after)
        params["after"] = after
    raise RuntimeError("Meta geçmiş sınırı aşıldı; yayın durduruldu")


def timestamp(row):
    value = row.get("created_time") or row.get("timestamp")
    if not value:
        raise RuntimeError("Meta geçmişinde yayın zamanı eksik")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TR)


def exact_txt_coverage(files):
    """Audit exact case-sensitive MP4/TXT stem pairs (the publish-time rule)."""
    videos = {name[:-4] for name in files if name.lower().endswith(".mp4")}
    txts = {name[:-4] for name in files if name.endswith(".txt")}
    missing = sorted(videos - txts)
    return {"mp4": len(videos), "matched": len(videos) - len(missing),
            "missing": len(missing), "missing_examples": missing[:12]}


def toonzone_txt_text(stem):
    """Publish a short sourced Turkish episode plot, season/part and hashtags."""
    from toonzone_episode_summaries import episode_summary

    metadata = toonzone_metadata(stem)
    season = metadata["season"]
    episode = metadata["episode"]
    part = metadata["part"]
    short_plot = episode_summary(season, episode)
    display_title = metadata["title"].split(" — Part ", 1)[0]
    if display_title.endswith(" Tr"):
        display_title = display_title[:-3].strip()
    episode_tag = f"S{season:02d}E{episode:02d}"
    return (
        f"🎬 Regular Show | {display_title}\n"
        f"📺 Sezon {season} • Bölüm {episode} • Part {part}/4\n\n"
        f"📖 {short_plot}\n\n"
        f"💬 Bu bölüm hakkındaki düşünceni yorumlara yaz!\n\n"
        f"🛍️ Etsy: {TOONZONE_ETSY_LINK}\n\n"
        f"#RegularShow #ToonZone #Mordecai #Rigby "
        f"#ÇizgiFilm #CartoonNetwork #{episode_tag} #Part{part}"
    )


def generate_toonzone_txts(files, output_dir):
    """Create one stable UTF-8 TXT for each validated ToonZone MP4 part."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated, invalid = 0, 0
    for name in sorted(files):
        if not name.lower().endswith(".mp4"):
            continue
        stem = Path(name).stem
        try:
            content = toonzone_txt_text(stem)
        except ValueError:
            invalid += 1
            continue
        (output_dir / (stem + ".txt")).write_text(content + "\n", encoding="utf-8")
        generated += 1
    return generated, invalid


def daily_laugh_txt_text(stem):
    """A unique English caption without guessing what happens in a video."""
    if not re.fullmatch(r"[1-9][0-9]{0,5}", stem):
        raise ValueError("Daily Laugh video filename is not a positive numeric ID")
    return (
        "😂 Take a quick laugh break!\\n\\n"
        "What made you smile today? Tag a friend who needs a laugh! 😄\\n\\n"
        "#DailyLaughLab #FunnyVideos #Comedy #DailyLaughs #Reels"
    ).replace("\\n", "\n")


def generate_daily_laugh_txts(files, output_dir):
    """Create exact-stem TXT only for missing Daily Laugh source captions."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated, invalid = 0, 0
    for name in sorted(files):
        if not name.lower().endswith(".mp4"):
            continue
        stem = Path(name).stem
        if stem + ".txt" in files:
            continue
        try:
            content = daily_laugh_txt_text(stem)
        except ValueError:
            invalid += 1
            continue
        (output_dir / (stem + ".txt")).write_text(content + "\n", encoding="utf-8")
        generated += 1
    return generated, invalid


def copies(route, item, files, temp, use_txt=True):
    stem = Path(item["name"]).stem
    text = files.get(stem + ".txt") if use_txt else None
    raw = None
    origin = "matching-txt"
    if text:
        try:
            raw = download(text["id"], temp / "caption.txt").read_text(encoding="utf-8-sig").strip()
        except Exception as exc:
            if route != "toonzone":
                raise RuntimeError(f"Eşleşen TXT indirilemedi: {route}/{item['name']} ({type(exc).__name__})") from None
            # A future optional ToonZone TXT must not stop validated metadata copy.
    elif route == "daily_laugh":
        # The source archive has clips without matching TXT. Materialize a
        # deterministic caption before planning a publication; never invent
        # dialogue or specific events in the video.
        generated = ROOT / "daily_laugh_txt" / (stem + ".txt")
        content = daily_laugh_txt_text(stem)
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text(content + "\n", encoding="utf-8")
        raw = content
        origin = "generated-daily-laugh-txt"
    elif route != "toonzone":
        raise RuntimeError(f"Eşleşen TXT bulunamadı: {route}/{item['name']}")
    if text and not raw and route != "toonzone":
        raise RuntimeError(f"Eşleşen TXT boş: {route}/{item['name']}")
    if raw:
        _, _, fb, ig, _ = platform_content_from_txt(raw, stem, route.removesuffix("_second"))
    elif route == "toonzone":
        generated = ROOT / "toonzone_txt" / (stem + ".txt")
        fb = ig = generated.read_text(encoding="utf-8").strip() if generated.exists() else toonzone_txt_text(stem)
        origin = "generated-toonzone-txt"
    else:
        # Other routes must never upload with generic filename-only captions.
        raise RuntimeError(f"Eşleşen TXT gerekli: {route}/{item['name']}")
    if route == "daily_laugh":
        # Reused TXT bodies are paired to specific videos to avoid ambiguous reconciliation.
        reference = f"Daily Laugh Lab · Video {stem}\n\n"
        fb, ig = reference + fb, reference + ig
    if not fb.strip() or not ig.strip() or len(ig) > 2200 or "<html" in fb.lower():
        raise RuntimeError("Platform açıklaması geçersiz")
    return {"facebook": fb, "instagram": ig}, origin


def seed_done(route, platform, name):
    """Only publications already verified in the AFK/985 production logs."""
    if route == "toonzone":
        order = parse_order(Path(name).stem, "cartoon")
        return bool(order and (order[:2] < (1, 2) or order[:3] == (1, 2, 1)))
    if route in {"film", "film_second"}:
        match = re.fullmatch(r"Yoksul_1986_Part_(\d+)\.mp4", name, re.I)
        return bool(match and int(match[1]) <= (6 if route == "film" else 5))
    return False


def route_enabled(route):
    return not route_paused("film" if route == "film_second" else route)


def route_clock(route, now):
    return now.astimezone(ZoneInfo("America/New_York")) if route == "daily_laugh" else now


def publication_day(route, row):
    """Use the account scheduling timezone for confirmed Meta history entries."""
    return route_clock(route, timestamp(row)).date().isoformat()


def target_count(route, now):
    clock = route_clock(route, now)
    hours = {"tarladaki": TARLADAKI_HOURS, "penguen": PENGUEN_HOURS,
             "gonle": GONLE_HOURS, "film": FILM_HOURS, "film_second": FILM_HOURS}
    if route == "daily_laugh":
        slots = [(h, 0) for h in daily_laugh_hours_for_date(clock.date())]
    elif route == "toonzone":
        slots = [(12, m) for m in (0, 10, 20, 30)]
    else:
        slots = [(h, 30 if route == "penguen" else 15 if route == "gonle" else 0) for h in hours[route]]
    if os.getenv("COMPLETE_DAY_DATE") == now.date().isoformat():
        # The second Film page still lacked the already-confirmed Part 6 at cutover.
        return len(slots) + (1 if route == "film_second" else 0)
    return sum((h, m) <= (clock.hour, clock.minute) for h, m in slots)


def apply_verified_migration(state):
    payload = json.loads(Path(__file__).with_name("migration_verified_publications.json").read_text())
    if payload.get("schema") != 1 or not isinstance(payload.get("records"), list):
        raise RuntimeError("Doğrulanmış aktarım geçmişi geçersiz")
    # The first audit incorrectly treated generic Daily captions as file IDs.
    # Remove only those derived inferences; preserve all actual upload intents/results.
    state["entries"] = {k: e for k, e in state["entries"].items()
                        if not (e["route"] == "daily_laugh" and not e.get("run_id")
                                and e.get("proof") != "verified-afk-log")}
    for row in payload["records"]:
        key = f"{row['route']}:{row['platform']}:{row['file_id']}"
        if key in state["entries"] and state["entries"][key].get("run_id"):
            continue
        recorded = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
        state["entries"][key] = {
            "route": row["route"], "platform": row["platform"], "status": "done",
            "caption_hash": "verified-file-id:" + row["file_id"],
            "post_id": row["post_id"], "file": row["file_name"],
            "day": route_clock(row["route"], recorded.astimezone(TR)).date().isoformat(),
            "proof": "verified-afk-log", "source_run_id": row["source_run_id"],
        }


def toonzone_cover_coverage(videos, covers):
    """Count exact part-specific PNG matches; never reuse another part's artwork."""
    stems = [Path(name).stem for name in videos if name.lower().endswith(".mp4")]
    matched = sum(stem + ".png" in covers for stem in stems)
    return matched, len(stems) - matched


def plan(audit=False):
    now = datetime.now(TR)
    day = now.date().isoformat()
    state = restore()
    apply_verified_migration(state)
    pages = {p["page_name"]: p for p in load_meta_auth()["pages"]}
    report = [f"# Public link publisher — {day}", "", "YouTube: disabled. Drive OAuth: not used.", ""]
    catalogs = {}
    for key, value in FOLDERS.items():
        try:
            catalogs[key] = inventory(value)
        except Exception as exc:
            catalogs[key] = {}
            report.append(f"HELD source {key}: {type(exc).__name__}")
    for key, files in catalogs.items():
        report.append(f"{key}: MP4={sum(n.lower().endswith('.mp4') for n in files)}, TXT={sum(n.lower().endswith('.txt') for n in files)}, total={len(files)}")
    if catalogs.get("daily_laugh"):
        generated, invalid = generate_daily_laugh_txts(catalogs["daily_laugh"], ROOT / "daily_laugh_txt")
        report.append(f"Daily Laugh TXT generated for missing video names: created={generated}; invalid_filenames={invalid}")
        if invalid:
            report.append("WARNING: invalid Daily Laugh MP4 filenames will not be published without a readable caption.")
    if catalogs.get("toonzone"):
        generated, invalid = generate_toonzone_txts(catalogs["toonzone"], ROOT / "toonzone_txt")
        report.append(f"ToonZone autogenerated TXT: created={generated}; invalid_filenames={invalid}")
        matched, missing = toonzone_cover_coverage(catalogs["toonzone"], catalogs["covers"])
        report.append(f"ToonZone exact part covers: matched={matched}; missing={missing}")
        if missing:
            report.append("WARNING: ToonZone videos without exact PNG artwork will be held, not posted with an incorrect cover.")
    plans = []
    planned_counts = {}
    batch_limit = 8 if os.getenv("CATCHUP_BATCH_DATE") == day else 1
    history_cache = {}
    for route, (source, page_name) in ROUTES.items():
        report.extend(["", f"## {page_name}"])
        if not route_enabled(route):
            report.append("HELD: existing route/rights switch is disabled.")
            continue
        page = pages.get(page_name)
        if not page:
            report.append("HELD: Meta page not available.")
            continue
        ig_enabled = not (route == "gonle" and route_paused("gonle_ig")) and not (route == "daily_laugh" and route_paused("daily_laugh_instagram"))
        platforms = ["facebook"] + (["instagram"] if page.get("instagram_id") and route != "film_second" and ig_enabled else [])
        clock = route_clock(route, now)
        try:
            histories = {}
            for p in platforms:
                cache_key = (page_name, p)
                if cache_key not in history_cache:
                    history_cache[cache_key] = graph_rows(page, p)
                histories[p] = history_cache[cache_key]
        except RuntimeError as exc:
            report.append("HELD: " + str(exc))
            continue
        remote = {p: {caption_key(row.get("description") or row.get("caption")): row for row in rows} for p, rows in histories.items()}
        for platform, rows in histories.items():
            count = sum(route_clock(route, timestamp(row)).date() == clock.date() for row in rows)
            report.append(f"{platform}: published_today={count}, history_records={len(rows)}")
        # Match uncertain intents by the exact platform caption before deciding.
        for key, entry in state["entries"].items():
            if entry["route"] != route or entry["platform"] not in platforms:
                continue
            match = remote[entry["platform"]].get(entry["caption_hash"])
            if entry["status"] != "done" and match:
                entry.update(status="done", post_id=str(match["id"]))
        counts = {p: max(
            sum(route_clock(route, timestamp(row)).date() == clock.date() for row in histories[p]),
            sum(e["route"] == route and e["platform"] == p and e["status"] == "done"
                and e.get("day") == clock.date().isoformat() for e in state["entries"].values())
        ) for p in platforms}
        due = target_count(route, now)
        if due == 0:
            report.append("NOT DUE: publication hours have not started for this route's local day.")
            continue
        if all(counts[p] >= due for p in platforms):
            report.append("Daily target already complete.")
            continue
        files = catalogs[source]
        videos = [v for n, v in files.items() if n.lower().endswith(".mp4")]
        other_humor_hashes = set()
        if route in {"tarladaki", "penguen"}:
            # Match the existing normal publisher's explicit TP activation gate.
            # Shared files are consumed globally across both humor accounts.
            other_name = ROUTES["penguen" if route == "tarladaki" else "tarladaki"][1]
            other_page = pages.get(other_name)
            if not other_page:
                report.append("HELD: other shared-humor account history unavailable.")
                continue
            try:
                for p in ("facebook", "instagram"):
                    if p == "instagram" and not other_page.get("instagram_id"):
                        continue
                    ck = (other_name, p)
                    if ck not in history_cache:
                        history_cache[ck] = graph_rows(other_page, p)
                    other_humor_hashes.update(caption_key(r.get("description") or r.get("caption")) for r in history_cache[ck])
            except RuntimeError as exc:
                report.append("HELD: " + str(exc))
                continue
            videos = [v for v in videos if not any(
                k.endswith(":" + v["id"]) and e["route"] in {"tarladaki", "penguen"} and e["route"] != route
                for k, e in state["entries"].items())]
        if source == "film":
            videos = [v for v in videos if parse_order(Path(v["name"]).stem, "film")]
            videos.sort(key=lambda v: (not v["name"].lower().startswith("yoksul_1986_"), parse_order(Path(v["name"]).stem, "film")))
        elif source == "toonzone":
            videos = [v for v in videos if parse_order(Path(v["name"]).stem, "cartoon")]
            videos.sort(key=lambda v: parse_order(Path(v["name"]).stem, "cartoon"))
        else:
            videos.sort(key=lambda v: v["name"])
        selected = None
        route_selected = 0
        for item in videos:
            if all(counts[p] + planned_counts.get((route, p), 0) >= target_count(route, now) for p in platforms):
                break
            if all(seed_done(route, p, item["name"]) or state["entries"].get(f"{route}:{p}:{item['id']}", {}).get("status") == "done" for p in platforms):
                continue
            if source == "toonzone":
                ep = list(parse_order(Path(item["name"]).stem, "cartoon")[:2])
                today_episode = state["episode_days"].get(day)
                if today_episode and today_episode != ep:
                    break
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    captions, origin = copies(route, item, files, Path(tmp))
            except (RuntimeError, UnicodeError, ValueError) as exc:
                report.append("HELD TXT/caption: " + str(exc))
                if source in {"film", "toonzone"}:
                    break
                continue
            if other_humor_hashes and any(caption_key(c) in other_humor_hashes for c in captions.values()):
                continue
            pending = []
            held = False
            for p in platforms:
                key = f"{route}:{p}:{item['id']}"
                existing = state["entries"].get(key, {})
                cap_hash = caption_key(captions[p])
                match = remote[p].get(cap_hash)
                if existing.get("status") == "done" or seed_done(route, p, item["name"]) or match:
                    if match:
                        state["entries"][key] = {"route": route, "platform": p, "status": "done", "caption_hash": cap_hash, "post_id": str(match["id"]), "file": item["name"], "day": publication_day(route, match)}
                    continue
                if existing and existing.get("status") != "ready":
                    report.append(f"HELD: {item['name']} {p} has an uncertain previous intent.")
                    held = True
                    continue
                target = target_count(route, now)
                today_count = sum(route_clock(route, timestamp(row)).date() == clock.date() for row in histories[p])
                confirmed_in_ledger = sum(
                    e["route"] == route and e["platform"] == p and e["status"] == "done"
                    and e.get("day") == clock.date().isoformat()
                    for e in state["entries"].values()
                )
                today_count = max(today_count, confirmed_in_ledger)
                # A tick catches up one item per account; no all-night busy polling.
                if today_count + planned_counts.get((route, p), 0) >= target:
                    continue
                pending.append(p)
            if held:
                break
            if not pending:
                continue
            selected = dict(item, route=route, page=page_name, platforms=pending, captions=captions, caption_source=origin)
            if source == "toonzone":
                cover = catalogs["covers"].get(Path(item["name"]).stem + ".png")
                if not cover:
                    report.append("HELD: exact ToonZone cover missing.")
                    break
                selected["cover_id"] = cover["id"]
                state["episode_days"][day] = ep
            report.append(f"NEXT: {item['name']}; caption_source={origin}; platforms={','.join(pending)}")
            if source == "toonzone":
                report.append("Caption preview: " + captions[pending[0]][:450].replace("\n", " "))
            if not audit:
                for p in pending:
                    state["entries"][f"{route}:{p}:{item['id']}"] = {"route": route, "platform": p, "status": "intent", "caption_hash": caption_key(captions[p]), "file": item["name"], "day": clock.date().isoformat(), "run_id": os.environ["GITHUB_RUN_ID"]}
                plans.append(selected)
                for p in pending:
                    planned_counts[(route, p)] = planned_counts.get((route, p), 0) + 1
            route_selected += 1
            if route_selected >= batch_limit:
                break
        if selected is None:
            report.append("No eligible unpublished item below the daily target.")
    save(STATE, state)
    save(PLAN, plans)
    summary = "\n".join(report) + "\n"
    (ROOT / "report.md").write_text(summary, encoding="utf-8")
    print(summary, flush=True)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as out:
        out.write(summary)


def publish():
    state = json.loads(STATE.read_text())
    plans = json.loads(PLAN.read_text())
    pages = {p["page_name"]: p for p in load_meta_auth()["pages"]}
    failures = []
    for item in plans:
        page = pages[item["page"]]
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            try:
                video = download(item["id"], temp / "source.mp4")
                if video.open("rb").read(8)[4:8] != b"ftyp":
                    raise RuntimeError("Source is not MP4")
                if item.get("approved_md5"):
                    checksum = hashlib.md5(video.read_bytes()).hexdigest()
                    if checksum != item["approved_md5"]:
                        raise RuntimeError("Human-approved content checksum mismatch")
                if item.get("cover_id"):
                    cover = download(item["cover_id"], temp / "cover.png")
                    video = create_instagram_cover_video(video, cover, temp / "covered.mp4")
            except Exception as exc:
                failures.append(item["page"] + ": " + type(exc).__name__ + ": " + _sanitize_meta_text(str(exc))[:400])
                for platform in item["platforms"]:
                    state["entries"][f"{item['route']}:{platform}:{item['id']}"]["status"] = "ready"
                save(STATE, state)
                continue
            for platform in item["platforms"]:
                key = f"{item['route']}:{platform}:{item['id']}"
                try:
                    if platform == "facebook":
                        post = upload_facebook_reel(page, str(video), item["captions"][platform])
                    else:
                        prepared = prepare_instagram_upload(video, temp / "instagram.mp4", prefer_remux=True,
                            film_compact=item["route"] in {"film", "film_second", "gonle"},
                            toonzone_compact=item["route"] == "toonzone")
                        post = upload_instagram_reel(page, str(prepared), item["captions"][platform], append_store_link=False)
                    if not post:
                        raise RuntimeError("Publication has no post ID")
                    state["entries"][key].update(status="done", post_id=str(post))
                    print(json.dumps({"page": item["page"], "file": item["name"], "platform": platform, "post_id": str(post)}, ensure_ascii=False), flush=True)
                except Exception as exc:
                    state["entries"][key]["status"] = "uncertain"
                    safe = str(exc) if isinstance(exc, MetaAPIError) else type(exc).__name__
                    failures.append(item["page"] + " " + platform + ": " + safe)
                finally:
                    save(STATE, state)
    if failures:
        print("HELD failures: " + "; ".join(failures), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("audit", "plan", "publish"))
    action = parser.parse_args().action
    if action == "publish":
        publish()
    else:
        plan(audit=action == "audit")
