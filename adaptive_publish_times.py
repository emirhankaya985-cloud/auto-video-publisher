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


def observations_from_archive(records, state):
    """Join only identical real platform post IDs in the authoritative ledger."""
    links, collision = {}, set()
    for entry in state.get("entries", {}).values():
        if not isinstance(entry, dict) or entry.get("status") != "done":
            continue
        post = str(entry.get("post_id") or "").strip()
        route, platform = entry.get("route"), entry.get("platform")
        if not post or not route or platform not in {"facebook", "instagram"}:
            continue
        if post in links and links[post] != (route, platform):
            collision.add(post)
        links[post] = (route, platform)
    video = {}
    for row in records:
        if (not isinstance(row, dict) or row.get("entity_type") != "video"
                or row.get("status") != "ok"
                or row.get("metric") not in {"view_count", "like_count", "comment_count"}):
            continue
        ident = str(row.get("entity_id") or "")
        if ident not in links or ident in collision:
            continue
        route, platform = links[ident]
        source_platform = str(row.get("platform") or "").lower()
        if platform not in source_platform:
            continue
        stamp = row.get("measured_at")
        if not isinstance(stamp, str):
            continue
        key = (ident, row["metric"])
        current = video.get(key)
        if current is None or stamp > current["measured_at"]:
            video[key] = row
    observations = []
    for ident, (route, platform) in links.items():
        if ident in collision:
            continue
        found = {metric: video.get((ident, metric))
                 for metric in ("view_count", "like_count", "comment_count")}
        if not all(found.values()):
            continue
        published_at = found["view_count"].get("published_at")
        if not isinstance(published_at, str) or not published_at:
            continue
        observations.append({
            "route": route, "platform": platform, "post_id": ident,
            "published_at": published_at,
            "measured_at": max(r["measured_at"] for r in found.values()),
            "views": found["view_count"].get("value"),
            "like_count": found["like_count"].get("value"),
            "comment_count": found["comment_count"].get("value"),
        })
    return observations


def main():
    """GET-only nightly recommendations; no automatic clock or route edits."""
    import json
    import os
    from pathlib import Path
    from publication_github_progress import restore_publication_state

    archive = Path("link-runtime/daily_video_views.jsonl")
    target = Path("link-runtime/time-recommendations.json")
    if not archive.is_file():
        raise RuntimeError("verified analytics archive missing")
    if not os.getenv("GITHUB_TOKEN"):
        raise RuntimeError("read-only GitHub token missing")
    state = restore_publication_state()
    history = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    observations = observations_from_archive(history, state)
    rows = recommend_hours(observations)
    from adaptive_schedule import build_schedule
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "status": "recommendation_only" if rows else "insufficient_verified_samples",
        "source_posts": len(observations), "recommendations": rows,
        "schedule": build_schedule(rows, generated_at=datetime.now(timezone.utc)),
        "auto_changed_schedule": False
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
