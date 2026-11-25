"""Conservative ToonZone filename matcher for review-only cover candidates.

This module never writes publisher state or marks a candidate publishable. A
unique season/episode/part key is useful for discovery, but localized titles
or matching filenames alone do not prove that the image depicts the video.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePath
import re
import unicodedata


_ASSET_NAME = re.compile(
    r"^S(?P<season>\d{1,2})E(?P<episode>\d{1,2})[_ .-]+"
    r"(?P<title>.+?)[_ .-]+Part(?P<part>\d{1,2})(?:-\d{1,2})?$",
    re.IGNORECASE,
)


def normalize_title(value: str) -> str:
    """Normalize punctuation, underscores and accents without translating."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    value = re.sub(r"(?:[_ .-]+)tr$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def parse_asset_name(filename: str) -> dict[str, object] | None:
    """Return the structured episode key/title for a named asset."""
    stem = PurePath(filename.replace("\\", "/")).stem
    match = _ASSET_NAME.fullmatch(stem)
    if not match:
        return None
    return {
        "key": (
            int(match.group("season")),
            int(match.group("episode")),
            int(match.group("part")),
        ),
        "title": match.group("title").strip(" _.-"),
    }


def _field(asset: str | dict[str, object], name: str) -> str:
    if isinstance(asset, str):
        return asset if name in {"name", "id"} else ""
    value = asset.get(name, "")
    return value if isinstance(value, str) else ""


def match_cover_assets(
    videos: list[str | dict[str, object]],
    covers: list[str | dict[str, object]],
    *,
    verified_title_aliases: dict[tuple[int, int, int], set[str]] | None = None,
) -> dict[str, object]:
    """Build conservative filename-key candidates; never authorize posting.

    ``verified_title_aliases`` must contain independently verified localized
    titles for a key. Without that explicit evidence, different titles remain
    HIGH_CONFIDENCE_REVIEW even when their numeric keys match uniquely.
    """
    verified_title_aliases = verified_title_aliases or {}
    video_groups: dict[tuple[int, int, int], list[dict[str, object]]] = defaultdict(list)
    cover_groups: dict[tuple[int, int, int], list[dict[str, object]]] = defaultdict(list)
    unparsed_videos: list[dict[str, object]] = []
    unparsed_covers: list[dict[str, object]] = []

    for kind, assets, groups, unparsed in (
        ("video", videos, video_groups, unparsed_videos),
        ("cover", covers, cover_groups, unparsed_covers),
    ):
        for asset in assets:
            name = _field(asset, "name")
            parsed = parse_asset_name(name)
            record = {"id": _field(asset, "id"), "name": name, "title": ""}
            if parsed is None:
                unparsed.append(record)
                continue
            record.update(parsed)
            groups[parsed["key"]].append(record)

    rows: list[dict[str, object]] = []
    used_cover_records: set[int] = set()
    for key, video_records in sorted(video_groups.items()):
        cover_records = cover_groups.get(key, [])
        if len(video_records) > 1:
            for video in video_records:
                rows.append({
                    "season": key[0], "episode": key[1], "part": key[2],
                    "video_id": video["id"], "video_name": video["name"],
                    "cover_id": "", "cover_name": "",
                    "classification": "AMBIGUOUS",
                    "reason": "duplicate video season/episode/part key",
                    "publication_eligible": False,
                })
            continue
        base: dict[str, object] = {
            "season": key[0], "episode": key[1], "part": key[2],
            "video_id": video_records[0]["id"] if len(video_records) == 1 else "",
            "video_name": video_records[0]["name"],
            "cover_id": "", "cover_name": "",
            "publication_eligible": False,
        }
        if len(cover_records) > 1:
            base.update(classification="AMBIGUOUS", reason="multiple covers share this episode key")
        elif not cover_records:
            base.update(classification="UNMATCHED", reason="no cover with this episode key")
        else:
            video, cover = video_records[0], cover_records[0]
            base["cover_id"], base["cover_name"] = cover["id"], cover["name"]
            used_cover_records.add(id(cover))
            video_title = normalize_title(str(video["title"]))
            cover_title = normalize_title(str(cover["title"]))
            if video_title == cover_title:
                classification = "EXACT_MATCH"
                reason = "unique episode key and normalized title match"
            else:
                aliases = {
                    normalize_title(alias)
                    for alias in verified_title_aliases.get(key, set())
                }
                if video_title in aliases and cover_title in aliases:
                    classification = "VERIFIED_MATCH"
                    reason = "unique episode key and both titles occur in verified alias set"
                else:
                    classification = "HIGH_CONFIDENCE_REVIEW"
                    reason = "unique episode key; localized titles or image content need review"
            base.update(classification=classification, reason=reason)
        rows.append(base)

    for record in unparsed_videos:
        rows.append({
            "season": None, "episode": None, "part": None,
            "video_id": record["id"], "video_name": record["name"],
            "cover_id": "", "cover_name": "", "classification": "UNMATCHED",
            "reason": "video filename has no parseable SxxExx/Part key",
            "publication_eligible": False,
        })

    unmatched_covers = [
        record for records in cover_groups.values() for record in records
        if id(record) not in used_cover_records
    ] + unparsed_covers
    counts = Counter(str(row["classification"]) for row in rows)
    return {
        "rows": rows,
        "unmatched_covers": unmatched_covers,
        "summary": {
            "video_count": len(videos),
            "cover_count": len(covers),
            "matched_candidate_count": sum(bool(row["cover_id"]) for row in rows),
            "unmatched_cover_count": len(unmatched_covers),
            "classification_counts": dict(sorted(counts.items())),
            "publication_eligible_count": 0,
        },
    }
