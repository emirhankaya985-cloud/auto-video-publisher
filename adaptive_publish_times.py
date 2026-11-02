"""Evidence-based publishing time recommendations. No publishing/scheduling writes.

Inputs must join real publication timestamps with subsequent recorded metrics.
Missing or stale samples never become a fabricated "best hour".
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")


def _posted_local(row):
    value = row.get("published_at")
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(TR)


def recommend_hours(rows, *, now=None, min_posts=4, min_days=3, max_age_days=30):
    """Recommend hours only from validated per-video outcomes across multiple days.

    Each input: route, platform, published_at (offset-aware), views,
    like_count, comment_count, measured_at (offset-aware). Each post receives
    only one outcome row, not multiple repeated daily measurements.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be aware")
    if not 1 <= min_posts <= 100 or not 1 <= min_days <= 100:
        raise ValueError("invalid sample thresholds")
    groups = defaultdict(dict)
    for row in rows:
        if not isinstance(row, dict):
            continue
        posted = _posted_local(row)
        try:
            measured = datetime.fromisoformat(row.get("measured_at", "").replace("Z", "+00:00"))
        except (AttributeError, ValueError, TypeError):
            continue
        if not posted or measured.tzinfo is None:
            continue
        if not (posted <= measured.astimezone(TR) <= now.astimezone(TR)
                and posted >= now.astimezone(TR) - timedelta(days=max_age_days)):
            continue
        views, likes, comments = (row.get("views"), row.get("like_count"),
                                   row.get("comment_count"))
        if any(type(n) is not int or n < 0 for n in (views, likes, comments)) or views < 100:
            continue
        route, platform, identity = row.get("route"), row.get("platform"), row.get("post_id")
        if not (isinstance(route, str) and route and
                platform in {"facebook", "instagram", "youtube", "threads"} and
                isinstance(identity, str) and identity):
            continue
        key = (route, platform, posted.hour)
        # Latest valid measurement wins. Multiple archived rows of the same post
        # must never inflate the sample count for a favorable publication hour.
        existing = groups[key].get(identity)
        if existing is None or measured > existing[0]:
            engagement = (likes + 2 * comments) * 1000 / views
            groups[key][identity] = (measured, posted.date(), engagement)
    result = []
    for (route, platform, hour), posts in sorted(groups.items()):
        days = len({value[1] for value in posts.values()})
        if len(posts) < min_posts or days < min_days:
            continue
        score = sum(value[2] for value in posts.values()) / len(posts)
        result.append({"route": route, "platform": platform, "hour_tr": hour,
                       "posts": len(posts), "days": days,
                       "engagement_per_1000_views": round(score, 3),
                       "status": "recommendation_only"})
    return sorted(result, key=lambda r: (r["route"], r["platform"],
                                         -r["engagement_per_1000_views"], r["hour_tr"]))
