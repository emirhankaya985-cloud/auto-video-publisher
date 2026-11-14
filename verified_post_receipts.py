"""Strict provider receipts: an accepted request/container is not a published video.

Call this immediately after a provider upload returns, before any success log or
ledger state transition. If it fails, preserve the existing intent as uncertain
and reconcile remotely; never blindly replay a write.
"""
from __future__ import annotations

import re

YOUTUBE_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z", re.ASCII)


def require_youtube_video_id(response):
    """Return exactly one real-shaped video ID, or fail closed.

    This guards the transport acknowledgement, not the final visibility: the
    owner-authenticated videos.list identity/status GET remains mandatory.
    """
    if not isinstance(response, dict):
        raise RuntimeError("YouTube upload response unverified; reconcile remotely")
    video_id = response.get("id")
    if not isinstance(video_id, str) or not YOUTUBE_VIDEO_ID.fullmatch(video_id):
        raise RuntimeError("YouTube upload video ID unverified; reconcile remotely")
    return video_id
