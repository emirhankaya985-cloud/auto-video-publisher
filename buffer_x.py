"""Opt-in Buffer X video queue integration.

Uses Buffer's current GraphQL API. Network publishing is disabled unless both
BUFFER_X_ENABLED=true and an explicit channel mapping/rights approval exist.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse

import requests

API_URL = "https://api.buffer.com"
FREE_LIMITS = {"channels": 3, "queued_per_channel": 10, "requests_15m": 150,
               "requests_24h": 600, "requests_30d_per_channel": 1000}
CHANNELS = (
    "Tarladaki Fasulye", "Gönle Düşen", "Beyinsiz Penguen", "Daily Laugh Lab",
    "Film Mağarası", "ToonZone", "Film Sahneleri",
)
CHANNELS_QUERY = """query BufferXChannels($org: OrganizationId!) {
  channels(input: {organizationId: $org}) {
    id name displayName descriptor service serviceId externalLink isDisconnected isLocked
  }
}"""
ORGANIZATIONS_QUERY = "query BufferXOrganizations { account { organizations { id } } }"
CREATE_POST_MUTATION = """mutation BufferXCreateVideo($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status dueAt externalLink channelId text } }
    ... on MutationError { message }
  }
}"""
POST_QUERY = """query BufferXPost($id: PostId!) {
  post(input: {id: $id}) { id status dueAt externalLink channelId text sentAt }
}"""
QUEUED_POSTS_QUERY = """query BufferXScheduledPosts($org: OrganizationId!, $channel: ChannelId!) {
  posts(input: {organizationId: $org, filter: {channelIds: [$channel], status: [scheduled, sending]}}, first: 11) {
    edges { node { id status } }
    pageInfo { hasNextPage }
  }
}"""


class BufferError(RuntimeError):
    def __init__(self, code: str, *, retry_after: int | None = None, uncertain: bool = False):
        super().__init__(code)
        self.code, self.retry_after, self.uncertain = code, retry_after, uncertain


def _safe_retry_after(headers: Any) -> int | None:
    try:
        return max(1, min(86400, int(headers.get("Retry-After", ""))))
    except (TypeError, ValueError):
        return None


class BufferClient:
    """Thin, redacted GraphQL client; injectable transport enables offline tests."""
    def __init__(self, api_key: str, post: Callable[..., Any] | None = None,
                 on_usage: Callable[[str, Any, int | None, str], None] | None = None,
                 on_quota_threshold: Callable[[str, int, int], None] | None = None):
        if not api_key or not api_key.strip():
            raise BufferError("api_key_missing")
        self._key = api_key.strip()
        self._post = post or requests.post
        self._on_usage = on_usage
        self._on_quota_threshold = on_quota_threshold
        self._latest_limits: dict[str, int | None] = {}

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> tuple[dict[str, Any], Any]:
        blocked = []
        for window in ("15m", "24h", "30d"):
            limit = self._latest_limits.get(f"{window}_limit")
            remaining = self._latest_limits.get(f"{window}_remaining")
            if limit and remaining is not None and (limit - remaining) / limit >= 0.90:
                blocked.append(self._latest_limits.get(f"{window}_reset") or 900)
        if blocked:
            raise BufferError("quota_pause", retry_after=max(1, min(blocked)))
        try:
            response = self._post(API_URL, headers={"Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json"}, json={"query": query, "variables": variables or {}}, timeout=30)
        except requests.RequestException as exc:
            if self._on_usage:
                self._on_usage("graphql", {}, None, "network_error")
            raise BufferError("network_error", uncertain=query == CREATE_POST_MUTATION) from exc
        self._latest_limits.update(parse_rate_limit_headers(response.headers))
        if self._on_quota_threshold:
            for window in ("15m", "24h", "30d"):
                limit = self._latest_limits.get(f"{window}_limit")
                remaining = self._latest_limits.get(f"{window}_remaining")
                reset = self._latest_limits.get(f"{window}_reset") or 0
                if limit and remaining is not None:
                    used_percent = int((limit - remaining) * 100 / limit)
                    if used_percent >= 80:
                        try:
                            self._on_quota_threshold(window, used_percent, int(time.time()) + reset)
                        except Exception:
                            # A notification outage must not turn a successful create into
                            # an uncertain result that could strand the durable job.
                            pass
        if self._on_usage:
            try:
                self._on_usage("graphql", response.headers, response.status_code,
                               "rate_limited" if response.status_code == 429 else "completed")
            except Exception as exc:
                raise BufferError("usage_log_failed", uncertain=query == CREATE_POST_MUTATION) from exc
        if response.status_code == 429:
            raise BufferError("rate_limited", retry_after=_safe_retry_after(response.headers))
        if response.status_code == 401:
            raise BufferError("api_key_invalid")
        if response.status_code >= 500:
            raise BufferError("buffer_server_error", uncertain=query == CREATE_POST_MUTATION)
        if response.status_code >= 400:
            raise BufferError("http_error")
        try:
            body = response.json()
        except (ValueError, AttributeError) as exc:
            raise BufferError("invalid_json", uncertain=query == CREATE_POST_MUTATION) from exc
        if body.get("errors"):
            # Avoid returning vendor message text, which can contain user data.
            raise BufferError("graphql_error", uncertain=query == CREATE_POST_MUTATION)
        if not isinstance(body.get("data"), dict):
            raise BufferError("invalid_graphql_response", uncertain=query == CREATE_POST_MUTATION)
        return body["data"], response.headers

    def discover_x_channels(self) -> list[dict[str, Any]]:
        data, _ = self.graphql(ORGANIZATIONS_QUERY)
        orgs = (data.get("account") or {}).get("organizations")
        if not isinstance(orgs, list):
            raise BufferError("organization_discovery_failed")
        found: list[dict[str, Any]] = []
        for org in orgs:
            org_id = org.get("id")
            if not org_id:
                continue
            result, _ = self.graphql(CHANNELS_QUERY, {"org": org_id})
            channels = result.get("channels")
            if not isinstance(channels, list):
                raise BufferError("channel_discovery_failed")
            found.extend({**channel, "organizationId": org_id} for channel in channels
                         if str(channel.get("service", "")).lower() in {"twitter", "x"})
        return found

    def get_post(self, post_id: str) -> dict[str, Any]:
        data, _ = self.graphql(POST_QUERY, {"id": post_id})
        post = data.get("post")
        if not isinstance(post, dict):
            raise BufferError("post_not_found")
        return post

    def scheduled_count(self, organization_id: str, channel_id: str) -> int:
        data, _ = self.graphql(QUEUED_POSTS_QUERY, {"org": organization_id, "channel": channel_id})
        result = data.get("posts")
        if not isinstance(result, dict) or not isinstance(result.get("edges"), list):
            raise BufferError("scheduled_posts_check_failed")
        # Eleven records are enough to fail closed above the Free plan cap.
        if (result.get("pageInfo") or {}).get("hasNextPage"):
            return FREE_LIMITS["queued_per_channel"] + 1
        return len(result["edges"])

    def create_video_post(self, *, channel_id: str, video_url: str, text: str,
                          due_at: datetime | None = None) -> tuple[dict[str, Any], Any]:
        parsed = urlparse(video_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise BufferError("video_url_not_public_https")
        if not video_url.lower().split("?", 1)[0].endswith(".mp4"):
            raise BufferError("video_url_must_be_mp4")
        if not channel_id or not text.strip():
            raise BufferError("post_input_invalid")
        if due_at is None:
            mode, due = "addToQueue", None
        else:
            if due_at.tzinfo is None:
                raise BufferError("due_at_requires_timezone")
            mode, due = "customScheduled", due_at.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        input_obj: dict[str, Any] = {"channelId": channel_id, "text": text.strip(),
            "schedulingType": "automatic", "mode": mode,
            "assets": [{"video": {"url": video_url}}]}
        if due:
            input_obj["dueAt"] = due
        data, headers = self.graphql(CREATE_POST_MUTATION, {"input": input_obj})
        action = data.get("createPost") or {}
        if action.get("__typename") != "PostActionSuccess" or not isinstance(action.get("post"), dict):
            raise BufferError("post_creation_rejected")
        return action["post"], headers


def validate_media_url(url: str, *, head: Callable[..., Any] = requests.head) -> bool:
    """Check a public MP4 URL with a bounded metadata/range read."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return False
    if parsed.hostname == "drive.usercontent.google.com" and parsed.path == "/download":
        file_id = dict(parse_qsl(parsed.query)).get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", file_id):
            return False
        response = None
        try:
            response = requests.get(url, headers={"Range": "bytes=0-63", "Accept": "video/mp4"},
                                    allow_redirects=True, stream=True, timeout=(10, 20))
            first = next(response.iter_content(64), b"")
            final = urlparse(response.url)
            return (response.status_code == 206 and final.scheme == "https"
                    and ((final.hostname or "").endswith("googleusercontent.com")
                         or final.hostname in {"drive.google.com", "drive.usercontent.google.com"})
                    and response.headers.get("Content-Type", "").split(";", 1)[0].lower() == "video/mp4"
                    and len(first) >= 8 and first[4:8] == b"ftyp")
        except requests.RequestException:
            return False
        finally:
            if response is not None:
                response.close()
    if not parsed.path.lower().endswith(".mp4"):
        return False
    try:
        response = head(url, allow_redirects=False, timeout=15)
    except requests.RequestException:
        return False
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    try:
        size = int(response.headers.get("Content-Length", "0"))
    except ValueError:
        return False
    # Do not guess X's media ceilings; enforce only sensible bounded preflight.
    return response.status_code == 200 and content_type == "video/mp4" and size > 0


def drive_public_video_url(file_id: str) -> str:
    """Construct the unauthenticated direct download URL for one shared file."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", str(file_id)):
        raise BufferError("drive_file_id_invalid")
    return "https://drive.usercontent.google.com/download?" + urlencode(
        {"id": file_id, "export": "download", "confirm": "t"})


def fingerprint(channel_key: str, source_id: str, text: str, video_url: str) -> str:
    value = "\0".join((channel_key, source_id, text.strip(), video_url.split("?", 1)[0]))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_rate_limit_headers(headers: Any) -> dict[str, int | None]:
    """Parse Buffer's documented structured RateLimit headers by window size."""
    result: dict[str, int | None] = {f"{window}_{part}": None for window in ("15m", "24h", "30d")
                                    for part in ("remaining", "reset", "limit")}
    raw_values = headers.get_all("RateLimit", []) if hasattr(headers, "get_all") else [
        value for key, value in headers.items() if str(key).lower() == "ratelimit"]
    for raw in raw_values:
        for match in __import__("re").finditer(
                r"(\d+)-in-(15min|1day|24h|30days).*?r=(\d+).*?t=(\d+)", str(raw)):
            _, label, remaining, reset = match.groups()
            window = {"15min": 900, "1day": 86400, "24h": 86400, "30days": 2592000}[label]
            prefix = {900: "15m", 86400: "24h", 2592000: "30d"}[window]
            result[f"{prefix}_remaining"] = int(remaining)
            result[f"{prefix}_reset"] = int(reset)
    policy_values = headers.get_all("RateLimit-Policy", []) if hasattr(headers, "get_all") else [
        value for key, value in headers.items() if str(key).lower() == "ratelimit-policy"]
    for raw in policy_values:
        for match in __import__("re").finditer(
                r"(\d+)-in-(15min|1day|24h|30days).*?q=(\d+).*?w=(\d+)", str(raw)):
            _, label, quota, seconds = match.groups()
            window = {"15min": "15m", "1day": "24h", "24h": "24h", "30days": "30d"}[label]
            result[f"{window}_limit"] = int(quota)
    return result


class NeonBufferStore:
    """Small Neon adapter for the additive migration and durable Buffer queue."""
    def __init__(self, database_url: str, connect: Callable[..., Any] | None = None):
        if not database_url:
            raise BufferError("database_url_missing")
        if connect is None:
            try:
                import psycopg
            except ImportError as exc:
                raise BufferError("postgres_driver_missing") from exc
            connect = psycopg.connect
        self._connect = connect
        self._url = database_url

    def apply_migration(self) -> None:
        sql = __import__("pathlib").Path(__file__).with_name("migrations").joinpath(
            "20261126_buffer_x.sql").read_text(encoding="utf-8")
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            # psycopg simple-query protocol supports this static, additive SQL file.
            conn.execute(sql, prepare=False)

    def active_channels(self, *, max_age_hours: int = 12) -> list[dict[str, Any]]:
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            rows = conn.execute("""SELECT channel_key,channel_name,organization_id,
              buffer_channel_id,external_link,is_disconnected,is_locked FROM buffer_x_channels
              WHERE active AND NOT is_disconnected AND NOT is_locked
                AND last_checked_at > now()-(%s * interval '1 hour')""", (max_age_hours,)).fetchall()
        keys = ("channel_key", "name", "organization_id", "id", "external_link", "isDisconnected", "isLocked")
        return [dict(zip(keys, row)) for row in rows]

    def source_exists(self, channel_key: str, source_id: str) -> bool:
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            return conn.execute("SELECT 1 FROM buffer_x_jobs WHERE channel_key=%s AND source_id=%s",
                                (channel_key, source_id)).fetchone() is not None

    def record_usage(self, operation: str, headers: Any, *, status: int | None = None,
                     outcome: str = "completed") -> None:
        limits = parse_rate_limit_headers(headers or {})
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            conn.execute("""INSERT INTO buffer_x_api_usage(operation,http_status,
              window_15m_remaining,window_15m_reset_seconds,window_24h_remaining,
              window_24h_reset_seconds,window_30d_remaining,window_30d_reset_seconds,outcome)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (operation, status, limits["15m_remaining"], limits["15m_reset"],
               limits["24h_remaining"], limits["24h_reset"], limits["30d_remaining"],
               limits["30d_reset"], outcome))

    def enqueue(self, *, channel_key: str, channel_name: str, organization_id: str,
                buffer_channel_id: str, source_id: str, video_url: str, text: str,
                rights_approved: bool, due_at: datetime | None = None) -> int | None:
        if not rights_approved:
            raise BufferError("rights_approval_required")
        idem = fingerprint(channel_key, source_id, text, video_url)
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            row = conn.execute("""SELECT 1 FROM buffer_x_channels WHERE channel_key=%s
              AND channel_name=%s AND organization_id=%s AND buffer_channel_id=%s
              AND service IN ('twitter','x') AND active AND NOT is_disconnected AND NOT is_locked""",
              (channel_key, channel_name, organization_id, buffer_channel_id)).fetchone()
            if not row:
                raise BufferError("channel_not_verified")
            created = conn.execute("""INSERT INTO buffer_x_jobs(idempotency_key,channel_key,source_id,
              video_url,text,due_at,rights_approved) VALUES (%s,%s,%s,%s,%s,%s,true)
              ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
              (idem, channel_key, source_id, video_url, text, due_at)).fetchone()
            return created[0] if created else None

    def sync_discovered_channels(self, discovered: list[dict[str, Any]],
                                 configured: dict[str, str]) -> None:
        """Persist only exact X IDs explicitly mapped by the owner; max three active."""
        if len(configured) > FREE_LIMITS["channels"]:
            raise BufferError("free_channel_limit_exceeded")
        by_id = {str(row.get("id")): row for row in discovered}
        verified: list[tuple[str, str, str, str, str | None, bool, bool]] = []
        for channel_name, channel_id in configured.items():
            if channel_name not in CHANNELS or channel_id not in by_id:
                raise BufferError("channel_mapping_not_discovered")
            ch = by_id[channel_id]
            if ch.get("isDisconnected") or ch.get("isLocked"):
                raise BufferError("channel_unavailable")
            key = {
                "Tarladaki Fasulye": "tarladaki", "Gönle Düşen": "gonle",
                "Beyinsiz Penguen": "penguen", "Daily Laugh Lab": "daily_laugh",
                "Film Mağarası": "film", "ToonZone": "toonzone", "Film Sahneleri": "film_sahneleri",
            }[channel_name]
            verified.append((key, channel_name, str(ch["organizationId"]), channel_id,
                             ch.get("externalLink"), bool(ch.get("isDisconnected")), bool(ch.get("isLocked"))))
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            # No discovery result ever implicitly turns on unmapped channels.
            conn.execute("UPDATE buffer_x_channels SET active=false,last_checked_at=now()")
            for key, name, org_id, channel_id, link, disconnected, locked in verified:
                conn.execute("""INSERT INTO buffer_x_channels(channel_key,channel_name,organization_id,
                  buffer_channel_id,service,external_link,is_disconnected,is_locked,last_checked_at,active)
                  VALUES (%s,%s,%s,%s,'twitter',%s,%s,%s,now(),true)
                  ON CONFLICT(channel_key) DO UPDATE SET channel_name=excluded.channel_name,
                  organization_id=excluded.organization_id,buffer_channel_id=excluded.buffer_channel_id,
                  service='twitter',external_link=excluded.external_link,is_disconnected=excluded.is_disconnected,
                  is_locked=excluded.is_locked,last_checked_at=now(),active=true""",
                  (key, name, org_id, channel_id, link, disconnected, locked))

    def claim_one(self) -> dict[str, Any] | None:
        """Atomically claim a due item. Network call happens after transaction commits."""
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            row = conn.execute("""WITH candidate AS (
              SELECT j.id FROM buffer_x_jobs j JOIN buffer_x_channels c USING(channel_key)
              WHERE j.status='pending' AND j.rights_approved AND c.active
                AND NOT c.is_disconnected AND NOT c.is_locked
                AND (j.due_at IS NULL OR j.due_at <= now())
                AND (j.retry_after IS NULL OR j.retry_after <= now())
              ORDER BY COALESCE(j.due_at,j.created_at),j.id
              FOR UPDATE OF j SKIP LOCKED LIMIT 1)
              UPDATE buffer_x_jobs j SET status='submitting',attempts=attempts+1,
                updated_at=now() FROM candidate WHERE j.id=candidate.id
              RETURNING j.id,j.channel_key,j.source_id,j.video_url,j.text,j.due_at""").fetchone()
            if not row:
                return None
            return dict(zip(("id","channel_key","source_id","video_url","text","due_at"), row))

    def finish(self, job_id: int, status: str, *, post_id: str | None = None,
               post_url: str | None = None, error_code: str | None = None,
               retry_seconds: int | None = None, buffer_due_at: str | None = None) -> None:
        if status not in {"uncertain", "scheduled", "sent", "failed", "pending", "held"}:
            raise BufferError("invalid_job_state")
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            conn.execute("""UPDATE buffer_x_jobs SET status=%s,buffer_post_id=COALESCE(%s,buffer_post_id),
              post_url=COALESCE(%s,post_url),buffer_due_at=COALESCE(%s::timestamptz,buffer_due_at),
              last_error_code=%s,
              retry_after=CASE WHEN %s IS NULL THEN NULL ELSE now()+(%s * interval '1 second') END,
              updated_at=now() WHERE id=%s""",
              (status, post_id, post_url, buffer_due_at, error_code, retry_seconds, retry_seconds, job_id))
            conn.execute("INSERT INTO buffer_x_events(job_id,event_type,detail_code) VALUES (%s,%s,%s)",
                         (job_id, status, error_code))

    def due_for_verification(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            rows = conn.execute("""SELECT id,buffer_post_id,channel_key FROM buffer_x_jobs
              WHERE status='scheduled' AND buffer_post_id IS NOT NULL
                AND COALESCE(buffer_due_at,due_at) < now()-interval '5 minutes'
                AND (last_verified_at IS NULL OR last_verified_at < now()-interval '6 hours')
              ORDER BY COALESCE(buffer_due_at,due_at) LIMIT %s""", (limit,)).fetchall()
        return [dict(zip(("id", "post_id", "channel_key"), row)) for row in rows]

    def verify_post(self, job_id: int, status: str, post_url: str | None) -> None:
        if status not in {"scheduled", "sent", "error"}:
            status = "scheduled"
        new_status = "sent" if status == "sent" else "failed" if status == "error" else "scheduled"
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            conn.execute("""UPDATE buffer_x_jobs SET status=%s,post_url=COALESCE(%s,post_url),
              last_verified_at=now(),updated_at=now(),
              last_error_code=CASE WHEN %s='error' THEN 'buffer_post_failed' ELSE last_error_code END
              WHERE id=%s""", (new_status, post_url, status, job_id))
            conn.execute("INSERT INTO buffer_x_events(job_id,event_type,detail_code) VALUES (%s,%s,%s)",
                         (job_id, "status_verified", status))

    def queue_summary(self) -> dict[str, int]:
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            rows = conn.execute("SELECT status,count(*) FROM buffer_x_jobs GROUP BY status").fetchall()
        return {str(status): int(count) for status, count in rows}

    def claim_notification(self, notification_key: str, event_type: str) -> bool:
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            row = conn.execute("""INSERT INTO buffer_x_notifications(notification_key,event_type)
              VALUES (%s,%s) ON CONFLICT(notification_key) DO NOTHING RETURNING notification_key""",
              (notification_key, event_type)).fetchone()
            return row is not None

    def mark_notification_delivery(self, notification_key: str, *, ntfy_ack: bool = False,
                                   telegram_ack: bool = False) -> None:
        with self._connect(self._url, connect_timeout=10, sslmode="require") as conn:
            conn.execute("""UPDATE buffer_x_notifications SET ntfy_ack=ntfy_ack OR %s,
              telegram_ack=telegram_ack OR %s WHERE notification_key=%s""",
              (ntfy_ack, telegram_ack, notification_key))


def process_one(store: NeonBufferStore, client: BufferClient,
                channel_map: dict[str, dict[str, str]], discovered: list[dict[str, Any]]) -> str:
    job = store.claim_one()
    if not job:
        return "empty"
    channel = channel_map.get(job["channel_key"])
    if not channel or not check_channel_allowlist(channel.get("name", ""), channel.get("id", ""),
                                                   discovered, {channel.get("name", ""): channel.get("id", "")}):
        store.finish(job["id"], "held", error_code="channel_not_verified")
        return "held"
    if not validate_media_url(job["video_url"]):
        store.finish(job["id"], "held", error_code="media_preflight_failed")
        return "held"
    try:
        queued = client.scheduled_count(channel["organization_id"], channel["id"])
        if queued >= FREE_LIMITS["queued_per_channel"]:
            store.finish(job["id"], "pending", error_code="free_channel_queue_full",
                         retry_seconds=6 * 60 * 60)
            return "queue_full"
        post, headers = client.create_video_post(channel_id=channel["id"], video_url=job["video_url"],
                                                  text=job["text"], due_at=job["due_at"])
        if post.get("status") != "scheduled":
            store.finish(job["id"], "uncertain", post_id=post.get("id"),
                         error_code="buffer_status_not_scheduled")
            return "uncertain"
        store.finish(job["id"], "scheduled", post_id=post["id"], post_url=post.get("externalLink"),
                     buffer_due_at=post.get("dueAt"))
        return "scheduled"
    except BufferError as exc:
        if exc.uncertain:
            store.finish(job["id"], "uncertain", error_code=exc.code)
            return "uncertain"
        if exc.code in {"rate_limited", "quota_pause"}:
            store.finish(job["id"], "pending", error_code=exc.code,
                         retry_seconds=exc.retry_after or 900)
            return exc.code
        store.finish(job["id"], "failed", error_code=exc.code)
        return "failed"


def check_channel_allowlist(channel_name: str, channel_id: str, discovered: list[dict[str, Any]],
                            configured: dict[str, str]) -> bool:
    """Only exact, currently connected Buffer X identities can be targeted."""
    if channel_name not in CHANNELS or configured.get(channel_name) != channel_id:
        return False
    return any(c.get("id") == channel_id and c.get("service", "").lower() in {"twitter", "x"}
               and not c.get("isDisconnected") and not c.get("isLocked") for c in discovered)


def main() -> int:
    # Read-only check is allowed with a key. Publishing requires an explicit
    # account/channel map plus content-rights approval and a non-dry-run flag.
    key = os.getenv("BUFFER_API_KEY", "")
    if not key:
        print("BUFFER_API_KEY eksik; Buffer özelliği kapalı, diğer kanallar etkilenmedi.")
        return 0
    client = BufferClient(key)
    try:
        channels = client.discover_x_channels()
    except BufferError as exc:
        print(f"Buffer bağlantı kontrolü başarısız: {exc.code}")
        return 1
    print(f"Buffer bağlantısı doğrulandı; bağlı X kanalı: {len(channels)}")
    # Queue execution is intentionally gated until rights-reviewed source
    # enqueueing is wired into the existing publisher ledger.
    if os.getenv("BUFFER_X_ENABLED", "false").lower() != "true":
        print("X yayın modu kapalı (BUFFER_X_ENABLED=false).")
        return 0
    print("X kuyruk tüketicisi etkinleştirme için kalıcı kaynak kuyruğu bağlantısı bekliyor.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
