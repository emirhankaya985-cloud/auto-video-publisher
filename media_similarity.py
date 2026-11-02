"""Conservative visual-video duplicate detector for local prepared uploads.

Never uses a filename/caption as proof. A positive similarity match only HOLDS
a candidate; it never deletes, merges, publishes or resets remote evidence.
The original source is sampled before optional branded cover rendering.
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

_SAMPLE_FRACTIONS = (0.15, 0.50, 0.85)
_HEX = re.compile(r"^[0-9a-f]{16}$")


def _command(argv, *, timeout, runner=subprocess.run):
    try:
        result = runner(argv, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("video_fingerprint_unavailable") from None
    if result.returncode != 0:
        raise RuntimeError("video_fingerprint_decode_failed")
    return result.stdout


def visual_fingerprint(path, *, runner=subprocess.run):
    """Three sampled 64-bit dHashes; deliberately not a copyright classifier."""
    path = str(Path(path).resolve())
    output = _command(["ffprobe", "-v", "error", "-show_entries",
                       "format=duration", "-of", "default=nw=1:nk=1", path],
                      timeout=30, runner=runner)
    try:
        duration = float(output.strip())
    except (ValueError, TypeError):
        raise RuntimeError("video_fingerprint_invalid_duration") from None
    if not math.isfinite(duration) or duration < 1 or duration > 10800:
        raise RuntimeError("video_fingerprint_invalid_duration")
    frames = []
    for fraction in _SAMPLE_FRACTIONS:
        pixels = _command([
            "ffmpeg", "-nostdin", "-v", "error", "-ss",
            f"{duration * fraction:.3f}", "-i", path, "-an",
            "-frames:v", "1", "-vf", "scale=9:8:flags=area,format=gray",
            "-f", "rawvideo", "-",
        ], timeout=45, runner=runner)
        if len(pixels) != 72:
            raise RuntimeError("video_fingerprint_invalid_frame")
        bits = 0
        for row in range(8):
            offset = row * 9
            for col in range(8):
                bits = (bits << 1) | int(pixels[offset + col] > pixels[offset + col + 1])
        frames.append(f"{bits:016x}")
    return {"version": 1, "duration_ms": round(duration * 1000),
            "frames": frames}


def similar(left, right):
    """Strict multi-frame hold heuristic; never equate two sources as a fact."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if left.get("version") != 1 or right.get("version") != 1:
        return False
    a, b = left.get("duration_ms"), right.get("duration_ms")
    if type(a) is not int or type(b) is not int or abs(a - b) > 750:
        return False
    x, y = left.get("frames"), right.get("frames")
    if not (isinstance(x, list) and isinstance(y, list) and len(x) == len(y) == 3
            and all(isinstance(v, str) and _HEX.fullmatch(v) for v in x + y)):
        return False
    distances = [(int(l, 16) ^ int(r, 16)).bit_count() for l, r in zip(x, y)]
    # All-grey/black scenes are low-information and cannot prove a match.
    informative = sum(8 <= int(v, 16).bit_count() <= 56 for v in x)
    return informative >= 2 and max(distances) <= 5 and sum(distances) <= 10


def conflicts(state, *, route, platform, source_id, fingerprint):
    """Find earlier unresolved/done same-route/platform content from other IDs."""
    if platform not in {"facebook", "instagram"}:
        raise ValueError("unsupported platform")
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise ValueError("invalid publication state")
    matches = []
    for key, row in state["entries"].items():
        if not isinstance(row, dict) or not isinstance(key, str):
            continue
        if not key.startswith(f"{route}:{platform}:"):
            continue
        if key == f"{route}:{platform}:{source_id}":
            continue
        if row.get("status") not in {"done", "intent", "uncertain", "held"}:
            continue
        if similar(fingerprint, row.get("visual_fingerprint")):
            matches.append(key)
    return sorted(matches)


def hold_visual_duplicate(item, state, fingerprint):
    """Annotate today's intents before any Meta POST. Returns True when held."""
    matched = {}
    for platform in item["platforms"]:
        keys = conflicts(state, route=item["route"], platform=platform,
                         source_id=item["id"], fingerprint=fingerprint)
        if keys:
            matched[platform] = keys
    if not matched:
        for platform in item["platforms"]:
            state["entries"][f"{item['route']}:{platform}:{item['id']}"]["visual_fingerprint"] = fingerprint
        return False
    # Hold the whole video to avoid inconsistent platform side-effects; no
    # existing successful/uncertain record is modified.
    for platform in item["platforms"]:
        row = state["entries"][f"{item['route']}:{platform}:{item['id']}"]
        row.update(status="held", visual_fingerprint=fingerprint,
                   failure={"reason": "visual_duplicate_review",
                            "external_post_attempted": False,
                            "safe_to_repost": False,
                            "conflicting_platforms": sorted(matched)})
    return True
