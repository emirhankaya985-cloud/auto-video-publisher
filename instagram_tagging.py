"""Explicit, video-specific Instagram mentions and Reels user tagging.

No image/video recognition and no guessed people. An approved exact-file rule
is required; unrelated posts, Facebook captions, and existing posts stay as-is.

IG media-container user_tags: JSON list of {"username": "..."} for video/Reels.
This is an *opt-in* API field, not a guarantee Instagram will accept a tag:
the target account's own privacy/tag settings still apply.
"""
import json
import re
from pathlib import Path

MANIFEST = Path(__file__).with_name("instagram_tag_rules.json")
_HANDLE = re.compile(r"^[a-zA-Z0-9._]{1,30}$")
_HASHTAG = re.compile(r"^[A-Za-z0-9_]{1,60}$")
_ALLOWED_ROUTES = frozenset({
    "tarladaki", "penguen", "gonle", "daily_laugh", "film", "toonzone",
    "film_second",
})


def _parse_rules(payload):
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("Instagram tag rules schema invalid")
    rows = payload.get("rules")
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("Instagram tag rules must be a bounded list")
    parsed = {}
    for rule in rows:
        if not isinstance(rule, dict):
            raise ValueError("Instagram tag rule invalid")
        route, stem = rule.get("route"), rule.get("stem")
        users, tags = rule.get("usernames", []), rule.get("hashtags", [])
        if (route not in _ALLOWED_ROUTES or not isinstance(stem, str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{1,130}", stem)):
            raise ValueError("Instagram tag route/stem invalid")
        if (not isinstance(users, list) or len(users) > 5 or not all(
                isinstance(user, str) and _HANDLE.fullmatch(user.lstrip("@"))
                for user in users)):
            raise ValueError("Instagram tag users invalid")
        if (not isinstance(tags, list) or len(tags) > 10 or not all(
                isinstance(tag, str) and _HASHTAG.fullmatch(tag.lstrip("#"))
                for tag in tags)):
            raise ValueError("Instagram hashtags invalid")
        key = (route, stem)
        if key in parsed:
            raise ValueError("Duplicate Instagram video tag rule")
        parsed[key] = {
            "usernames": list(dict.fromkeys(user.lstrip("@").lower() for user in users)),
            "hashtags": list(dict.fromkeys(tag.lstrip("#") for tag in tags)),
        }
    return parsed


def load_rules(path=MANIFEST):
    if not path.is_file():
        raise RuntimeError("Instagram tag rules file missing")
    return _parse_rules(json.loads(path.read_text(encoding="utf-8")))


def enhance_instagram_caption(caption, route, stem, *, rules=None):
    """Return (caption, true_reel_tags) for exactly one approved video.

    @mentions and hashtags appear once and only when a rule exists. This
    changes caption hashes only for explicit new tagged videos.
    """
    rules = load_rules() if rules is None else rules
    selected = rules.get((route, stem))
    if not selected:
        return caption, []
    output = caption.rstrip()
    additions = []
    for user in selected["usernames"]:
        if not re.search(r"(?<![\w.])@" + re.escape(user) + r"(?![\w.])", output, re.I):
            additions.append("@" + user)
    for tag in selected["hashtags"]:
        if not re.search(r"(?<![\w])#" + re.escape(tag) + r"(?![\w])", output, re.I):
            additions.append("#" + tag)
    if additions:
        output += "\n\n" + " ".join(additions)
    if len(output) > 2200:
        raise ValueError("Instagram caption exceeds limit after tagging")
    return output, selected["usernames"]


def reels_user_tags_payload(usernames):
    """JSON payload for Meta's IG REELS media container user_tags field."""
    if not isinstance(usernames, (list, tuple)) or len(usernames) > 5:
        raise ValueError("Invalid user tag count")
    normalized = []
    for user in usernames:
        if not isinstance(user, str) or not _HANDLE.fullmatch(user):
            raise ValueError("Invalid Instagram username for Reel tagging")
        if user.lower() not in normalized:
            normalized.append(user.lower())
    return json.dumps([{"username": name} for name in normalized], separators=(",", ":"))
