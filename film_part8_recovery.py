"""Exact, owner-authorized Film Mağarası Bıçkın Part 8 false-dHash rescue.

Only the original Drive source 1eRB2... is eligible, not its (1) export.
Both the source SHA and previous local-only held receipt must match. The
three-frame visual heuristic also matched Part 3, a distinct exact SHA.
Before any Meta POST, re-download archived Part 3 and compare eight *new*
whole-frame samples of both source files. If inconclusive, stay HELD.
No stale Meta 'done', intent or uncertain entry is ever cleared or retried.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from media_similarity import conflicts, visual_fingerprint

SOURCE_ID = "1eRB2kU1E5KfECZfuFgN7Orzk-sJ8k-AJ"
SOURCE_NAME = "Bickin_Part_8.mp4"
SOURCE_SHA = "2366ca629ae0a41577e4f89b36f07f3367937971de969a846abea9702f273813"
OLDER_PART3_SHA = "dd025d4e163a467696fc55d7c4e1ed0f7d323ddb2e3ebd751c4c79ac30f4635d"
OLDER_PART3_ID = "1nFQ_L5unBjOvqI3nUhCTOcSqoS8UlTpH"
FRACTIONS = (0.07, 0.23, 0.33, 0.41, 0.59, 0.67, 0.77, 0.93)


def source_digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as f:
        for buf in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(buf)
    return sha.hexdigest()


def eligible_original_held(item, entry):
    failure = entry.get("failure") if isinstance(entry, dict) else None
    return (
        isinstance(item, dict) and item.get("id") == SOURCE_ID
        and item.get("name") == SOURCE_NAME
        and entry.get("route") == "film"
        and entry.get("status") == "held"
        and entry.get("platform") in {"facebook", "instagram"}
        and entry.get("file") == SOURCE_NAME
        and entry.get("source_sha256") == SOURCE_SHA
        and not entry.get("post_id")
        and isinstance(failure, dict)
        and failure.get("reason") == "visual_duplicate_review"
        and failure.get("external_post_attempted") is False
        and failure.get("safe_to_repost") is False
        and isinstance(failure.get("conflicting_platforms"), list)
    )


def allowed_old_collision(key, entry):
    if not isinstance(entry, dict):
        return False
    file = entry.get("file")
    if (file in {"Bickin_Part_3.mp4", "Bickin_Part_3 (1).mp4"}
            and entry.get("status") == "done"
            and str(entry.get("post_id") or "").isdecimal()
            and entry.get("source_sha256") == OLDER_PART3_SHA):
        return True
    if (file == "Bickin_Part_8 (1).mp4"
            and entry.get("status") == "held" and not entry.get("post_id")
            and entry.get("source_sha256") == SOURCE_SHA
            and isinstance(entry.get("failure"), dict)
            and entry["failure"].get("reason") == "visual_duplicate_review"
            and entry["failure"].get("external_post_attempted") is False):
        return True
    return False


def allowed_visual_collisions(item, state, fp):
    """Every colliding entry must be an exact known Part 3 or unposted export."""
    if (item.get("route") != "film" or item.get("name") != SOURCE_NAME
            or item.get("id") != SOURCE_ID
            or not item.get("film_part8_strict_recheck")):
        return False
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        return False
    found_part3 = set()
    for platform in item.get("platforms", []):
        keys = conflicts(state, route="film", platform=platform,
                         source_id=SOURCE_ID, fingerprint=fp)
        if not keys:
            return False
        for key in keys:
            record = state["entries"].get(key)
            if not allowed_old_collision(key, record):
                return False
            if record["file"] in {"Bickin_Part_3.mp4", "Bickin_Part_3 (1).mp4"}:
                found_part3.add(platform)
    return found_part3 == set(item.get("platforms", []))


def _duration(path, runner):
    p = runner(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(path)],
               capture_output=True, timeout=30)
    if p.returncode:
        raise RuntimeError("film_part8_extended_probe_failed")
    try:
        d = float(p.stdout.strip())
    except (ValueError, TypeError):
        raise RuntimeError("film_part8_extended_probe_invalid") from None
    if not 90 <= d <= 300:
        raise RuntimeError("film_part8_extended_probe_out_of_range")
    return d


def _sample(path, duration, fraction, runner):
    p = runner(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{duration*fraction:.3f}",
                "-i", str(path), "-an", "-frames:v", "1",
                "-vf", "scale=32:18:flags=area,format=gray",
                "-f", "rawvideo", "-"],
               capture_output=True, timeout=35)
    if p.returncode or len(p.stdout) != 576:
        raise RuntimeError("film_part8_extended_frame_unavailable")
    return p.stdout


def clearly_distinct_sources(part8, part3, *, runner=subprocess.run):
    """Only independent additional frames can release the old 3-frame alarm.

    Strong condition: at least five of eight new time positions differ by a
    large mean pixel intensity, and at least one is very different.
    Otherwise retain the original visual hold (no video upload).
    """
    d8, d3 = _duration(part8, runner), _duration(part3, runner)
    if abs(d8 - d3) > 1.0:
        # A substantially different duration does not alone prove distinct
        # copyrighted film content, so still require frame differences.
        pass
    differences = []
    for f in FRACTIONS:
        x = _sample(part8, d8, f, runner)
        y = _sample(part3, d3, f, runner)
        differences.append(sum(abs(a - b) for a, b in zip(x, y)) / len(x))
    return {
        "schema": 1, "additional_sample_count": len(FRACTIONS),
        "substantially_different_samples": sum(d >= 24 for d in differences),
        "largest_sample_distance": round(max(differences), 2),
        "distinct": sum(d >= 24 for d in differences) >= 5 and max(differences) >= 40,
        "source8_sha_verified": True,
        "source3_sha_verified": True,
        "no_meta_api_writes_during_comparison": True,
    }


def audit_part8_before_publish(item, state, path, prior_download, temp):
    """Call only after durable intents exist and fresh Meta history was read."""
    if source_digest(path) != SOURCE_SHA:
        raise RuntimeError("film_part8_source_sha_mismatch")
    fp = visual_fingerprint(path)
    if not allowed_visual_collisions(item, state, fp):
        raise RuntimeError("film_part8_collision_evidence_changed")
    part3 = prior_download(OLDER_PART3_ID, Path(temp) / "verified-original-part3.mp4")
    if source_digest(part3) != OLDER_PART3_SHA:
        raise RuntimeError("film_part3_source_sha_mismatch")
    result = clearly_distinct_sources(path, part3)
    if not result["distinct"]:
        raise RuntimeError("film_part8_extended_similarity_inconclusive")
    return fp, result
