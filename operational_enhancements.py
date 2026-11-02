"""Safe, opt-in publication enhancements; no network/API calls in this module.

These helpers cannot grant rights, skip an existing intent or authorize a POST.
Publisher's existing platform history, daily quota and ordered-part gates own
that decision. A source change is a permanent hold until reviewed.
"""
from collections import defaultdict
from datetime import datetime
import hashlib


def bounded_catchup_limit(route, due, confirmed_counts, now, *, enabled=False):
    """At most two candidate clips per normal tick after 18:00 local time.

    Applies only to a due deficit of two or more, never to ToonZone's required
    ten-minute part cadence. Does not increase target_count or release holds.
    """
    if not enabled or route == "toonzone" or not isinstance(now, datetime):
        return 1
    if not isinstance(due, int) or due < 1 or not confirmed_counts:
        return 1
    if any(type(n) is not int or n < 0 for n in confirmed_counts.values()):
        return 1
    if now.hour < 18:
        return 1
    return 2 if max(due - n for n in confirmed_counts.values()) >= 2 else 1


def bind_source_integrity(item, state, path):
    """Pin source bytes before every new upload; reject changed same-ID media.

    Only touches exact planned entries. Never downgrades existing done posts.
    A newly imported source has no historical byte digest and is therefore
    explicitly baselined, not retrospectively verified.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    current = digest.hexdigest()
    entries = state["entries"]
    keys = [f"{item['route']}:{p}:{item['id']}" for p in item["platforms"]]
    for key in keys:
        entry = entries[key]
        if (entry.get("status") != "intent"
                or entry.get("route") != item["route"]
                or entry.get("platform") != key.split(":")[1]
                or entry.get("file") != item["name"]):
            raise RuntimeError("Source integrity intent mismatch")
    if any(entries[k].get("source_sha256") not in (None, current) for k in keys):
        for key in keys:
            entry = entries[key]
            entry["status"] = "held"
            entry["failure"] = {
                "reason": "source_content_changed",
                "safe_to_repost": False,
                "external_post_attempted": False,
            }
        return False
    for key in keys:
        entries[key]["source_sha256"] = current
    return True


def rank_complete_engagement(records, *, per_account_limit=3):
    """Order only complete, same-account/platform absolute interactions.

    This is likes+comments, NOT views or a view-normalized engagement rate.
    Unknown metrics never masquerade as zero.
    """
    videos = defaultdict(dict)
    for row in records:
        if (row.get("entity_type") != "video"
                or row.get("metric") not in {"like_count", "comment_count"}):
            continue
        key = (row.get("account"), row.get("platform"), str(row.get("entity_id")))
        metric = row["metric"]
        # Partial/duplicate/conflicting observations are not trusted.
        if metric in videos[key]:
            videos[key][metric] = None
        else:
            val = row.get("value")
            videos[key][metric] = val if (
                row.get("status") == "ok" and type(val) is int and val >= 0) else None
    grouped = defaultdict(list)
    missing = 0
    for (account, platform, post_id), metrics in videos.items():
        likes, comments = metrics.get("like_count"), metrics.get("comment_count")
        if likes is None or comments is None:
            missing += 1
            continue
        grouped[(account, platform)].append({
            "post_id": post_id,
            "like_count": likes,
            "comment_count": comments,
            "interactions": likes + comments,
        })
    output = []
    for (account, platform), rows in sorted(grouped.items()):
        rows.sort(key=lambda x: (-x["interactions"], x["post_id"]))
        output.append({
            "account": account,
            "platform": platform,
            "top_posts": rows[:per_account_limit],
            "observed_complete": len(rows),
        })
    return {"method": "likes_plus_comments_absolute_not_views",
            "ranking": output, "excluded_incomplete_posts": missing,
            "status": "partial" if missing else "complete"}
