"""Disabled-by-default ordered content infrastructure for future channels.

This module only audits and selects exact MP4/TXT pairs. It deliberately has
no social upload call and is not referenced by a scheduled workflow.
"""

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from cloud_omnichannel_publisher import get_drive_client


FILM_FOLDER_ID = "1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW"
CARTOON_FOLDER_ID = "14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF"
FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class ChannelSpec:
    key: str
    label: str
    folder_id: str
    parser: str
    language_policy: str | None = None

    @property
    def history_key(self):
        digest = hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:16]
        return f"ordered_done_{digest}"


CHANNELS = {
    "film_primary": ChannelSpec("film_primary", "Film", FILM_FOLDER_ID, "film"),
    "cartoon_tr": ChannelSpec("cartoon_tr", "Türkçe Çizgi Film", CARTOON_FOLDER_ID, "cartoon"),
    "oddframes": ChannelSpec(
        "oddframes", "OddFrames", CARTOON_FOLDER_ID, "cartoon",
        language_policy="english_audio_or_subtitles_required",
    ),
}

FILM_RE = re.compile(r"^(?P<title>.+?)_Part_?(?P<part>\d+)(?: \(\d+\))?$", re.IGNORECASE)
CARTOON_RE = re.compile(
    r"^S(?P<season>\d+)E(?P<episode>\d+)_(?P<title>.+?)_Part_?(?P<part>\d+)(?: \(\d+\))?$",
    re.IGNORECASE,
)
TOONZONE_PART_MINUTES = {1: 0, 2: 10, 3: 20, 4: 30}
TOONZONE_ETSY_LINK = "https://www.etsy.com/shop/MiroviaStudio?ref=dashboard-header"
TOONZONE_STATE_KEYS = (
    "claimed_route_slot", "claimed_at", "failed_route_slot",
    "done_fb_slot", "done_ig_slot", "intent_fb_slot", "intent_ig_slot",
    "result_fb", "result_ig", "last_route_slot",
)


def parse_order(stem, parser):
    pattern = FILM_RE if parser == "film" else CARTOON_RE
    match = pattern.fullmatch(stem)
    if not match:
        return None
    data = match.groupdict()
    title = re.sub(r"_+", " ", data["title"]).strip().casefold()
    if parser == "film":
        return title, int(data["part"])
    return int(data["season"]), int(data["episode"]), int(data["part"]), title


def toonzone_metadata(stem):
    """Create deterministic baseline metadata from a validated ToonZone stem."""
    order = parse_order(stem, "cartoon")
    if order is None:
        raise ValueError("Geçersiz ToonZone dosya adı")
    season, episode, part, title = order
    if part not in TOONZONE_PART_MINUTES:
        raise ValueError("ToonZone bölümleri yalnızca Part 1-4 olabilir")
    display_title = title.title()
    episode_copy = (
        f"{display_title} | Sezon {season}, Bölüm {episode}. "
        f"Bu bölümde neler olduğunu yorumlarda paylaş!"
    )
    description = (
        f"{episode_copy}\n\n"
        f"#RegularShow #ToonZone #ÇizgiFilm #Cartoon "
        f"#S{season:02d}E{episode:02d}\n\n"
        f"Etsy: {TOONZONE_ETSY_LINK}"
    )
    return {
        "season": season, "episode": episode, "part": part,
        "title": f"{display_title} — Part {part}",
        "description": description,
        "minute": TOONZONE_PART_MINUTES[part],
    }


def list_folder_files(drive, folder_id):
    folder = drive.files().get(fileId=folder_id, fields="id,name,mimeType,trashed").execute()
    if folder.get("id") != folder_id or folder.get("mimeType") != FOLDER_MIME or folder.get("trashed"):
        raise RuntimeError("Sıralı kanal Drive klasörü doğrulanamadı")
    files, token = [], None
    while True:
        page = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,parents,appProperties,mimeType,md5Checksum,size)",
            pageSize=1000,
            pageToken=token,
        ).execute()
        files.extend(page.get("files", []))
        token = page.get("nextPageToken")
        if not token:
            return folder, files


def analyze_files(files, spec):
    videos, texts, duplicate_names = {}, {}, []
    for item in files:
        stem = Path(item["name"]).stem
        target = videos if item["name"].lower().endswith(".mp4") else texts if item["name"].lower().endswith(".txt") else None
        if target is None:
            continue
        if stem in target:
            duplicate_names.append(stem)
            continue
        target[stem] = item
    valid, invalid, duplicate_variants = [], [], []
    for stem, video in videos.items():
        order = parse_order(stem, spec.parser)
        if order is None:
            # Drive exports sometimes append ``_2`` after the complete Part
            # name. Treat it as a duplicate only when the canonical sibling
            # exists and its checksum is identical; otherwise remain blocked.
            canonical = stem[:-2] if stem.endswith("_2") else None
            original = videos.get(canonical) if canonical else None
            if (original and video.get("md5Checksum") and
                    video.get("md5Checksum") == original.get("md5Checksum")):
                duplicate_variants.append(stem)
                continue
            invalid.append(stem)
            continue
        valid.append((order, stem, video, texts.get(stem)))
    valid.sort(key=lambda row: row[0])
    blocked_series = []
    if spec.parser == "film":
        by_title = {}
        for order, stem, video, text in valid:
            by_title.setdefault(order[0], []).append(order[1])
        blocked_series = sorted(title for title, parts in by_title.items()
                                if sorted(parts) != list(range(1, max(parts) + 1)))
    return {
        "video_count": len(videos),
        "txt_count": len(texts),
        "ordered": valid,
        "missing_txt": sorted(stem for _, stem, _, text in valid if text is None),
        "invalid_names": sorted(invalid),
        "orphan_txt": sorted(set(texts) - set(videos)),
        "duplicate_names": sorted(set(duplicate_names)),
        "duplicate_variants": sorted(duplicate_variants),
        "blocked_series": blocked_series,
    }


def next_ready_pair(files, channel_key):
    spec = CHANNELS[channel_key]
    report = analyze_files(files, spec)
    for order, stem, video, text in report["ordered"]:
        if spec.parser == "film" and order[0] in report["blocked_series"]:
            continue
        if text is None:
            continue
        properties = video.get("appProperties") or {}
        if properties.get(spec.history_key) == "1":
            continue
        if spec.language_policy and properties.get("oddframes_language_verified") != "1":
            continue
        return order, stem, video, text
    return None


def toonzone_publication_state(video):
    """Return only non-empty publication/claim markers for safe read-only audits."""
    properties = video.get("appProperties") or {}
    keys = (CHANNELS["cartoon_tr"].history_key, *TOONZONE_STATE_KEYS)
    return {key: properties[key] for key in keys if properties.get(key)}


def assert_publish_ready(channel_key, account_config):
    """Future activation gate. No account details are invented or optional."""
    if channel_key not in CHANNELS:
        raise RuntimeError("Bilinmeyen sıralı kanal")
    if not account_config or account_config.get("enabled") is not True:
        raise RuntimeError("Yeni kanal devre dışı; gerçek yayın engellendi")
    required = {"platform", "account_id", "account_name"}
    if not required.issubset(account_config) or not all(account_config.get(key) for key in required):
        raise RuntimeError("Yeni kanal hesap bağlantısı tamamlanmadı; gerçek yayın engellendi")
    if CHANNELS[channel_key].language_policy and account_config.get("language_policy") != "verified_english":
        raise RuntimeError("OddFrames İngilizce dil politikası doğrulanmadı; gerçek yayın engellendi")
    return True


def audit(drive=None):
    drive = drive or get_drive_client()
    folder_cache = {}
    reports = {}
    for key, spec in CHANNELS.items():
        if spec.folder_id not in folder_cache:
            folder_cache[spec.folder_id] = list_folder_files(drive, spec.folder_id)
        folder, files = folder_cache[spec.folder_id]
        report = analyze_files(files, spec)
        reports[key] = report
        print(
            f"AUDIT {key} | klasör={folder.get('name')} | mp4={report['video_count']} | "
            f"txt={report['txt_count']} | eksik_txt={len(report['missing_txt'])} | "
            f"geçersiz_ad={len(report['invalid_names'])}",
            flush=True,
        )
        if report["missing_txt"]:
            print(f"MISSING_TXT {key}: {', '.join(report['missing_txt'][:100])}", flush=True)
        if report["invalid_names"]:
            print(f"INVALID_NAME {key}: {', '.join(report['invalid_names'][:100])}", flush=True)
        if key == "cartoon_tr":
            for order, stem, video, _text in report["ordered"]:
                if order[:2] != (1, 1):
                    continue
                state = toonzone_publication_state(video)
                print(
                    f"TOONZONE_STATE | file_id={video.get('id', 'unknown')} | "
                    f"name={stem} | markers={state or 'none'}",
                    flush=True,
                )
        if spec.language_policy:
            verified = sum(
                1 for _, _, video, text in report["ordered"]
                if text is not None and (video.get("appProperties") or {}).get("oddframes_language_verified") == "1"
            )
            print(f"LANGUAGE_READY {key}: {verified}/{len(report['ordered'])}", flush=True)
    print("Yeni sıralı kanallar DEVRE DIŞI; hiçbir platform yayını yapılmadı.", flush=True)
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true", required=True)
    parser.parse_args()
    audit()
