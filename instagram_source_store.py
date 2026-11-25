"""Idempotent source-video inventory and daily 3+3 selection in existing Neon."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

MIGRATION = "2026-11-instagram-source-ingestion-v1"
ROUTES = {"tarladaki", "penguen", "gonle", "daily_laugh", "film", "toonzone"}
LEGACY_ROUTES = ROUTES | {"film_second"}
PLATFORMS = {"facebook", "instagram", "threads", "youtube"}

DDL = """
CREATE TABLE IF NOT EXISTS instagram_source_migrations (
  version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS instagram_source_posts (
  source_username TEXT NOT NULL,
  source_post_id TEXT NOT NULL,
  route TEXT NOT NULL,
  source_permalink TEXT,
  source_published_at TIMESTAMPTZ NOT NULL,
  discovered_at TIMESTAMPTZ NOT NULL,
  discovered_day DATE NOT NULL,
  caption TEXT NOT NULL DEFAULT '',
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  asset_sha256 CHAR(64),
  drive_video_id TEXT,
  drive_txt_id TEXT,
  drive_cover_id TEXT,
  status TEXT NOT NULL DEFAULT 'newly_found',
  error_code TEXT,
  PRIMARY KEY (source_username, source_post_id, route),
  CHECK (route IN ('tarladaki','penguen','gonle','daily_laugh','film','film_second','toonzone'))
);
CREATE TABLE IF NOT EXISTS instagram_source_assets (
  sha256 CHAR(64) PRIMARY KEY,
  byte_size BIGINT NOT NULL CHECK (byte_size > 0),
  video_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS instagram_target_assets (
  route TEXT NOT NULL,
  sha256 CHAR(64) NOT NULL REFERENCES instagram_source_assets(sha256),
  drive_video_id TEXT NOT NULL,
  drive_txt_id TEXT,
  drive_cover_id TEXT,
  discovered_day DATE NOT NULL,
  pool TEXT NOT NULL CHECK (pool IN ('new','archive')),
  status TEXT NOT NULL DEFAULT 'available',
  source_username TEXT NOT NULL,
  source_post_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (route, sha256),
  FOREIGN KEY (source_username, source_post_id, route)
    REFERENCES instagram_source_posts(source_username, source_post_id, route)
);
CREATE INDEX IF NOT EXISTS instagram_target_assets_select_idx
  ON instagram_target_assets(route, pool, status, discovered_day);
CREATE TABLE IF NOT EXISTS instagram_target_daily_plans (
  route TEXT NOT NULL,
  local_day DATE NOT NULL,
  pool TEXT NOT NULL CHECK (pool IN ('new','archive')),
  ordinal INTEGER NOT NULL CHECK (ordinal > 0),
  sha256 CHAR(64) NOT NULL,
  source_username TEXT NOT NULL,
  source_post_id TEXT NOT NULL,
  drive_video_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'waiting_publication',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (route, local_day, pool, ordinal),
  UNIQUE (route, local_day, sha256),
  FOREIGN KEY (route, sha256) REFERENCES instagram_target_assets(route, sha256)
);
CREATE TABLE IF NOT EXISTS instagram_target_publications (
  route TEXT NOT NULL,
  platform TEXT NOT NULL CHECK (platform IN ('facebook','instagram','threads','youtube')),
  sha256 CHAR(64) NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('waiting_publication','intent','published','error','uncertain')),
  post_id TEXT,
  published_at TIMESTAMPTZ,
  error_code TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (route, platform, sha256),
  FOREIGN KEY (route, sha256) REFERENCES instagram_target_assets(route, sha256)
);
CREATE UNIQUE INDEX IF NOT EXISTS instagram_target_publication_post_id_uq
  ON instagram_target_publications(platform, post_id) WHERE post_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS instagram_source_events (
  id BIGSERIAL PRIMARY KEY,
  route TEXT NOT NULL,
  source_username TEXT,
  source_post_id TEXT,
  sha256 CHAR(64),
  event TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);
INSERT INTO instagram_source_migrations(version) VALUES ('2026-11-instagram-source-ingestion-v1')
  ON CONFLICT(version) DO NOTHING;
CREATE TABLE IF NOT EXISTS instagram_source_accounts (
  route TEXT NOT NULL CHECK (route IN ('tarladaki','penguen','gonle','daily_laugh','film','toonzone')),
  source_username TEXT NOT NULL,
  instagram_user_id TEXT,
  content_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  rights_approved BOOLEAN NOT NULL DEFAULT FALSE,
  rights_evidence TEXT NOT NULL DEFAULT '',
  official_api_download_allowed BOOLEAN NOT NULL DEFAULT FALSE,
  configured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_scan_at TIMESTAMPTZ,
  last_successful_scan_at TIMESTAMPTZ,
  last_scan_status TEXT NOT NULL DEFAULT 'never_scanned',
  last_scan_error TEXT,
  total_found BIGINT NOT NULL DEFAULT 0,
  total_downloaded BIGINT NOT NULL DEFAULT 0,
  total_duplicates BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY(route, source_username)
);
CREATE TABLE IF NOT EXISTS instagram_source_rights (
  route TEXT NOT NULL,
  source_username TEXT NOT NULL,
  evidence_sha256 CHAR(64) NOT NULL,
  evidence_text TEXT NOT NULL,
  approved BOOLEAN NOT NULL,
  official_api_download_allowed BOOLEAN NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(route, source_username, evidence_sha256),
  FOREIGN KEY(route, source_username)
    REFERENCES instagram_source_accounts(route, source_username)
);
CREATE TABLE IF NOT EXISTS instagram_source_scan_runs (
  id BIGSERIAL PRIMARY KEY,
  route TEXT NOT NULL,
  source_username TEXT NOT NULL,
  instagram_user_id TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running','completed','partial','failed')),
  found_count INTEGER NOT NULL DEFAULT 0 CHECK (found_count >= 0),
  downloaded_count INTEGER NOT NULL DEFAULT 0 CHECK (downloaded_count >= 0),
  duplicate_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
  api_status TEXT NOT NULL DEFAULT 'unknown',
  drive_status TEXT NOT NULL DEFAULT 'unknown',
  neon_status TEXT NOT NULL DEFAULT 'connected',
  storage_status TEXT NOT NULL DEFAULT 'unknown',
  drive_usage_bytes BIGINT,
  drive_limit_bytes BIGINT,
  error_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
  FOREIGN KEY(route, source_username)
    REFERENCES instagram_source_accounts(route, source_username)
);
CREATE INDEX IF NOT EXISTS instagram_source_scan_runs_daily_idx
  ON instagram_source_scan_runs(route, started_at);
ALTER TABLE instagram_source_scan_runs ADD COLUMN IF NOT EXISTS drive_usage_bytes BIGINT;
ALTER TABLE instagram_source_scan_runs ADD COLUMN IF NOT EXISTS drive_limit_bytes BIGINT;
INSERT INTO instagram_source_migrations(version) VALUES ('2026-11-instagram-source-ingestion-v2')
  ON CONFLICT(version) DO NOTHING;
"""


def validate_neon_url(url: str) -> str:
    parts = urlsplit(url or "")
    if (parts.scheme not in {"postgres", "postgresql"}
            or not (parts.hostname or "").endswith(".neon.tech")
            or parts.path.lstrip("/") != "neondb"):
        raise ValueError("wrong_neon_connection_scope")
    return url


def connect(url: str | None = None):
    url = validate_neon_url(url or os.getenv("DASHBOARD_DATABASE_URL", "").strip())
    import psycopg
    return psycopg.connect(url, connect_timeout=10, sslmode="require")


def migrate(conn) -> None:
    with conn.cursor() as cur:
        for statement in DDL.split(";"):
            if statement.strip():
                cur.execute(statement)
    conn.commit()


def sync_source_account(conn, *, route: str, source: dict) -> None:
    """Persist non-secret source identity, category and rights configuration."""
    if route not in ROUTES:
        raise ValueError("invalid_source_route")
    username = str(source.get("username", "")).strip().lstrip("@").lower()
    if not username or len(username) > 30:
        raise ValueError("invalid_source_username")
    categories = source.get("content_categories", [])
    evidence = str(source.get("rights_evidence") or "").strip()
    approved = source.get("rights_approved") is True
    api_allowed = source.get("official_api_download_allowed") is True
    if source.get("enabled") is True and (not approved or not evidence or not api_allowed):
        raise ValueError("enabled_source_missing_rights_or_api_permission")
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO instagram_source_accounts
          (route,source_username,instagram_user_id,content_categories,enabled,
           rights_approved,rights_evidence,official_api_download_allowed,updated_at)
          VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,now())
          ON CONFLICT(route,source_username) DO UPDATE SET
            instagram_user_id=COALESCE(EXCLUDED.instagram_user_id,instagram_source_accounts.instagram_user_id),
            content_categories=EXCLUDED.content_categories,enabled=EXCLUDED.enabled,
            rights_approved=EXCLUDED.rights_approved,rights_evidence=EXCLUDED.rights_evidence,
            official_api_download_allowed=EXCLUDED.official_api_download_allowed,updated_at=now()""",
                    (route, username, source.get("instagram_user_id"), json.dumps(categories),
                     source.get("enabled") is True, approved, evidence, api_allowed))
        if evidence:
            evidence_hash = hashlib.sha256(json.dumps(
                [evidence, approved, api_allowed], separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            cur.execute("""INSERT INTO instagram_source_rights
              (route,source_username,evidence_sha256,evidence_text,approved,official_api_download_allowed)
              VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (route, username, evidence_hash, evidence, approved, api_allowed))
    conn.commit()


def start_source_scan(conn, *, route: str, source: dict,
                      started_at: str | datetime | None = None) -> int:
    if route not in ROUTES:
        raise ValueError("invalid_source_route")
    username = str(source.get("username", "")).strip().lstrip("@").lower()
    sync_source_account(conn, route=route, source=source)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO instagram_source_scan_runs
          (route,source_username,instagram_user_id,started_at)
          VALUES (%s,%s,%s,%s) RETURNING id""",
                    (route, username, source.get("instagram_user_id"),
                     _timestamp(started_at) if started_at else datetime.now(timezone.utc)))
        scan_id = int(cur.fetchone()[0])
    conn.commit()
    return scan_id


def finish_source_scan(conn, *, scan_id: int, route: str, username: str,
                       status: str, found: int = 0, downloaded: int = 0,
                       duplicates: int = 0, api_status: str = "unknown",
                       drive_status: str = "unknown", storage_status: str = "unknown",
                       drive_usage_bytes: int | None = None,
                       drive_limit_bytes: int | None = None,
                       instagram_user_id: str | None = None,
                       error_codes: list[str] | None = None,
                       finished_at: str | datetime | None = None) -> None:
    if (route not in ROUTES or status not in {"completed", "partial", "failed"}
            or any(type(value) is not int or value < 0 for value in (found, downloaded, duplicates))):
        raise ValueError("invalid_source_scan_result")
    if api_status not in {"ok", "error", "unknown"} or drive_status not in {"ok", "error", "unknown"}:
        raise ValueError("invalid_source_scan_health")
    errors = [str(code)[:60] for code in (error_codes or []) if isinstance(code, str)]
    ended = _timestamp(finished_at) if finished_at else datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("""UPDATE instagram_source_scan_runs SET finished_at=%s,status=%s,
          instagram_user_id=COALESCE(%s,instagram_user_id),found_count=%s,
          downloaded_count=%s,duplicate_count=%s,api_status=%s,
          drive_status=%s,neon_status='connected',storage_status=%s,
          drive_usage_bytes=%s,drive_limit_bytes=%s,error_codes=%s::jsonb
          WHERE id=%s AND route=%s AND source_username=%s AND status='running'""",
                    (ended, status, instagram_user_id, found, downloaded, duplicates, api_status,
                     drive_status, storage_status, drive_usage_bytes, drive_limit_bytes,
                     json.dumps(errors), scan_id,
                     route, username))
        if cur.rowcount != 1:
            raise ValueError("source_scan_not_running")
        cur.execute("""UPDATE instagram_source_accounts SET last_scan_at=%s,
          last_successful_scan_at=CASE WHEN %s='ok' THEN %s ELSE last_successful_scan_at END,
          last_scan_status=%s,last_scan_error=%s,
          total_found=(SELECT count(*) FROM instagram_source_posts
            WHERE route=%s AND source_username=%s),
          total_downloaded=(SELECT count(*) FROM instagram_source_posts
            WHERE route=%s AND source_username=%s
              AND status IN ('downloaded','drive_uploaded','duplicate_reused')),
          total_duplicates=(SELECT count(*) FROM instagram_source_posts
            WHERE route=%s AND source_username=%s AND status='duplicate_reused'),
          instagram_user_id=COALESCE(%s,instagram_user_id),updated_at=now()
          WHERE route=%s AND source_username=%s""",
                    (ended, api_status, ended, status,
                     errors[0] if errors else None, route, username, route, username,
                     route, username, instagram_user_id, route, username))
    conn.commit()


def _timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("source_published_at_requires_timezone")
    return result.astimezone(timezone.utc)


def quality_score(row: dict, content_keywords: list[str] | None = None) -> float:
    """Use measured video metadata and available counts only; unknowns stay unknown."""
    score = 0.0
    width = int(row.get("width") or 0)
    height = int(row.get("height") or 0)
    if width and height:
        score += min(width * height / 1_000_000, 2.5)
    try:
        bitrate = float(row.get("bit_rate") or row.get("video_bit_rate") or 0)
    except (TypeError, ValueError):
        bitrate = 0
    if bitrate > 0:
        score += min(bitrate / 4_000_000, 1.5)
    duration = float(row.get("duration") or 0)
    if 5 <= duration <= 180:
        score += 1.0
    for key, weight in (("view_count", 0.0001), ("like_count", 0.001), ("comments_count", 0.005)):
        value = row.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            score += min(float(value) * weight, 1.0)
    caption = str(row.get("caption") or "").casefold()
    if content_keywords:
        matched = sum(str(keyword).casefold() in caption for keyword in content_keywords)
        score += min(float(matched) * 0.5, 2.0)
    return score


def choose_daily_assets(candidates: list[dict], *, daily_new: int = 3,
                        daily_archive: int = 3, max_per_source: int = 2,
                        prior_source_counts: dict[str, int] | None = None,
                        content_keywords: list[str] | None = None) -> dict:
    """Deterministic, source-diverse 3+3 plan. Never backfills one pool from the other."""
    if daily_new < 0 or daily_archive < 0 or max_per_source < 1:
        raise ValueError("invalid_daily_plan_limits")
    selected = {"new": [], "archive": []}
    source_counts: dict[str, int] = dict(prior_source_counts or {})
    ordered = sorted(candidates, key=lambda row: (
        -quality_score(row, content_keywords),
        _timestamp(row["source_published_at"]),
        str(row.get("sha256", "")),
    ))
    for pool, limit in (("new", daily_new), ("archive", daily_archive)):
        for row in ordered:
            if row.get("pool") != pool or len(selected[pool]) >= limit:
                continue
            source = str(row.get("source_username", "")).casefold()
            if not source or source_counts.get(source, 0) >= max_per_source:
                continue
            if row.get("status", "available") != "available":
                continue
            selected[pool].append(row)
            source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "selected": selected,
        "deficit": {
            "new": max(0, daily_new - len(selected["new"])),
            "archive": max(0, daily_archive - len(selected["archive"])),
        },
        "remaining": {
            "new": max(0, sum(row.get("pool") == "new" and row.get("status", "available") == "available" for row in candidates) - len(selected["new"])),
            "archive": max(0, sum(row.get("pool") == "archive" and row.get("status", "available") == "available" for row in candidates) - len(selected["archive"])),
        },
    }


def rollover_pool(pool: str, discovered_day: str, today: str) -> str:
    """Carry prior Istanbul-day unselected assets from new to archive exactly once."""
    if pool not in {"new", "archive"}:
        raise ValueError("invalid_pool")
    return "archive" if pool == "new" and date.fromisoformat(discovered_day) < date.fromisoformat(today) else pool


def record_source_post(conn, *, route: str, source_username: str, source_post_id: str,
                       source_permalink: str | None, source_published_at: str | datetime,
                       discovered_at: str | datetime, discovered_day: str,
                       caption: str, metrics: dict) -> bool:
    """Insert one source attribution without replacing history; False means already seen."""
    if route not in ROUTES:
        raise ValueError("invalid_route")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO instagram_source_posts
               (source_username,source_post_id,route,source_permalink,source_published_at,
                discovered_at,discovered_day,caption,metrics,status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'newly_found')
               ON CONFLICT(source_username,source_post_id,route) DO NOTHING""",
            (source_username, source_post_id, route, source_permalink,
             _timestamp(source_published_at), _timestamp(discovered_at),
             date.fromisoformat(discovered_day), caption, __import__("json").dumps(metrics)),
        )
        inserted = cur.rowcount == 1
    conn.commit()
    return inserted


def persist_target_asset(conn, *, route: str, username: str, post_id: str,
                         sha256: str, byte_size: int, metadata: dict,
                         drive_video_id: str, drive_txt_id: str | None,
                         drive_cover_id: str | None, discovered_day: str) -> bool:
    if route not in ROUTES or not re_full_sha256(sha256) or byte_size <= 0:
        raise ValueError("invalid_target_asset")
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO instagram_source_assets(sha256,byte_size,video_metadata)
                       VALUES (%s,%s,%s::jsonb) ON CONFLICT(sha256) DO NOTHING""",
                    (sha256, byte_size, __import__("json").dumps(metadata)))
        cur.execute("""UPDATE instagram_source_posts SET asset_sha256=%s,
                       drive_video_id=%s,drive_txt_id=%s,drive_cover_id=%s,
                       metrics=metrics || %s::jsonb,status='drive_uploaded'
                       WHERE source_username=%s AND source_post_id=%s AND route=%s""",
                    (sha256, drive_video_id, drive_txt_id, drive_cover_id,
                     __import__("json").dumps(metadata), username, post_id, route))
        cur.execute("""INSERT INTO instagram_target_assets
                       (route,sha256,drive_video_id,drive_txt_id,drive_cover_id,discovered_day,
                        pool,status,source_username,source_post_id)
                       VALUES (%s,%s,%s,%s,%s,%s,'new','available',%s,%s)
                       ON CONFLICT(route,sha256) DO NOTHING""",
                    (route, sha256, drive_video_id, drive_txt_id, drive_cover_id,
                     date.fromisoformat(discovered_day), username, post_id))
        inserted = cur.rowcount == 1
        cur.execute("""INSERT INTO instagram_source_events
                       (route,source_username,source_post_id,sha256,event)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (route, username, post_id, sha256,
                     "drive_uploaded" if inserted else "duplicate_asset_reused"))
    conn.commit()
    return inserted


def record_downloaded_asset(conn, *, route: str, username: str, post_id: str,
                            sha256: str, byte_size: int, metadata: dict) -> None:
    if route not in ROUTES or not re_full_sha256(sha256) or byte_size <= 0:
        raise ValueError("invalid_downloaded_source_asset")
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO instagram_source_assets(sha256,byte_size,video_metadata)
                       VALUES (%s,%s,%s::jsonb) ON CONFLICT(sha256) DO NOTHING""",
                    (sha256, byte_size, __import__("json").dumps(metadata)))
        cur.execute("""UPDATE instagram_source_posts SET asset_sha256=%s,status='downloaded'
                       WHERE route=%s AND source_username=%s AND source_post_id=%s
                         AND status IN ('newly_found','error','downloaded')""",
                    (sha256, route, username, post_id))
        cur.execute("""INSERT INTO instagram_source_events
                       (route,source_username,source_post_id,sha256,event)
                       VALUES (%s,%s,%s,%s,'downloaded')""",
                    (route, username, post_id, sha256))
    conn.commit()


def record_source_error(conn, *, route: str, username: str, post_id: str,
                        error_code: str) -> None:
    if route not in ROUTES:
        raise ValueError("invalid_source_error")
    if not isinstance(error_code, str) or not error_code.replace("_", "").isalnum() or len(error_code) > 60:
        raise ValueError("invalid_source_error_code")
    with conn.cursor() as cur:
        cur.execute("""UPDATE instagram_source_posts SET status='error',error_code=%s
                       WHERE route=%s AND source_username=%s AND source_post_id=%s""",
                    (error_code, route, username, post_id))
        cur.execute("""INSERT INTO instagram_source_events
                       (route,source_username,source_post_id,event,details)
                       VALUES (%s,%s,%s,'error',%s::jsonb)""",
                    (route, username, post_id, __import__("json").dumps({"error_code": error_code})))
    conn.commit()


def re_full_sha256(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def create_daily_plan(conn, *, route: str, local_day: str,
                      daily_new: int = 3, daily_archive: int = 3,
                      max_per_source: int = 2,
                      content_keywords: list[str] | None = None) -> dict:
    """Freeze one route/day plan; retries read back the original candidate set."""
    if route not in ROUTES:
        raise ValueError("invalid_route")
    day = date.fromisoformat(local_day)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"instagram-source:{route}:{local_day}",))
        cur.execute("""UPDATE instagram_target_assets SET pool='archive'
                       WHERE route=%s AND pool='new' AND discovered_day < %s
                         AND status='available'""", (route, day))
        cur.execute("""SELECT p.route,p.local_day,p.pool,p.ordinal,p.sha256,p.source_username,
                              p.source_post_id,p.drive_video_id,p.status,
                              s.source_published_at,s.metrics,a.video_metadata,s.caption
                       FROM instagram_target_daily_plans p
                       JOIN instagram_source_posts s USING(source_username,source_post_id,route)
                       JOIN instagram_source_assets a USING(sha256)
                       WHERE p.route=%s AND p.local_day=%s ORDER BY p.pool,p.ordinal""",
                    (route, day))
        columns = [desc[0] for desc in cur.description]
        existing_rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        for row in existing_rows:
            row["plan_status"] = row["status"]
        selected = {pool: [row for row in existing_rows if row["pool"] == pool]
                    for pool in ("new", "archive")}
        prior_source_counts: dict[str, int] = {}
        for row in existing_rows:
            source = row["source_username"].casefold()
            prior_source_counts[source] = prior_source_counts.get(source, 0) + 1
        missing_new = max(0, daily_new - len(selected["new"]))
        missing_archive = max(0, daily_archive - len(selected["archive"]))
        if not missing_new and not missing_archive:
            conn.commit()
            return {"selected": selected, "deficit": {"new": 0, "archive": 0}, "frozen": True}
        planned_hashes = {row["sha256"] for row in existing_rows}
        cur.execute("""SELECT ta.route,ta.sha256,ta.drive_video_id,ta.pool,ta.status,
                              ta.source_username,ta.source_post_id,sp.source_published_at,
                              sp.metrics,sa.video_metadata,sp.caption
                       FROM instagram_target_assets ta
                       JOIN instagram_source_posts sp USING(source_username,source_post_id,route)
                       JOIN instagram_source_assets sa USING(sha256)
                       WHERE ta.route=%s AND ta.status='available' AND ta.pool IN ('new','archive')
                         AND ta.drive_txt_id IS NOT NULL AND ta.drive_cover_id IS NOT NULL
                         AND NOT EXISTS (
                           SELECT 1 FROM instagram_target_publications pub
                           WHERE pub.route=ta.route AND pub.sha256=ta.sha256
                             AND pub.status IN ('published','intent','uncertain'))
                       ORDER BY ta.discovered_day,sp.source_published_at""", (route,))
        columns = [desc[0] for desc in cur.description]
        candidates = []
        for raw in cur.fetchall():
            item = dict(zip(columns, raw))
            item.update(item.pop("video_metadata") or {})
            item.update(item.pop("metrics") or {})
            if item["sha256"] not in planned_hashes:
                candidates.append(item)
        plan = choose_daily_assets(candidates, daily_new=missing_new,
                                   daily_archive=missing_archive,
                                   max_per_source=max_per_source,
                                   prior_source_counts=prior_source_counts,
                                   content_keywords=content_keywords)
        for pool in ("new", "archive"):
            start_ordinal = len(selected[pool]) + 1
            for ordinal, row in enumerate(plan["selected"][pool], start=start_ordinal):
                row["plan_status"] = "waiting_publication"
                cur.execute("""INSERT INTO instagram_target_daily_plans
                               (route,local_day,pool,ordinal,sha256,source_username,
                                source_post_id,drive_video_id)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT DO NOTHING""",
                            (route, day, pool, ordinal, row["sha256"],
                             row["source_username"], row["source_post_id"], row["drive_video_id"]))
                selected[pool].append(row)
        cur.execute("""INSERT INTO instagram_source_events(route,event,details)
                       VALUES (%s,'daily_plan_created',%s::jsonb)""",
                    (route, __import__("json").dumps({"day": local_day,
                     "new": len(plan["selected"]["new"]), "archive": len(plan["selected"]["archive"]),
                     "deficit": plan["deficit"]})))
    conn.commit()
    return {"selected": selected,
            "deficit": {"new": max(0, daily_new-len(selected["new"])),
                        "archive": max(0, daily_archive-len(selected["archive"]))},
            "remaining": plan["remaining"], "frozen": False}


def record_platform_result(conn, *, route: str, platform: str, sha256: str,
                           status: str, post_id: str | None = None,
                           published_at: str | datetime | None = None,
                           error_code: str | None = None,
                           local_day: str | None = None,
                           required_platforms: list[str] | None = None) -> None:
    if route not in ROUTES or platform not in PLATFORMS:
        raise ValueError("invalid_publication_route")
    if status not in {"waiting_publication", "intent", "published", "error", "uncertain"}:
        raise ValueError("invalid_publication_status")
    timestamp = _timestamp(published_at) if published_at else None
    local_day = date.fromisoformat(local_day or datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat())
    required_platforms = required_platforms or [platform]
    if any(item not in PLATFORMS for item in required_platforms):
        raise ValueError("invalid_required_platform")
    with conn.cursor() as cur:
        cur.execute("""SELECT status,post_id FROM instagram_target_publications
                       WHERE route=%s AND platform=%s AND sha256=%s FOR UPDATE""",
                    (route, platform, sha256))
        previous = cur.fetchone()
        if previous:
            previous_status, previous_post_id = previous
            if previous_status == "published" and status != "published":
                conn.commit()
                return
            if previous_status in {"intent", "uncertain"} and status in {"waiting_publication", "intent"}:
                conn.commit()
                return
            if previous_post_id and post_id and previous_post_id != post_id:
                raise ValueError("publication_post_id_conflict")
        cur.execute("""INSERT INTO instagram_target_publications
                       (route,platform,sha256,status,post_id,published_at,error_code,updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                       ON CONFLICT(route,platform,sha256) DO UPDATE SET
                         status=EXCLUDED.status,
                         post_id=COALESCE(instagram_target_publications.post_id,EXCLUDED.post_id),
                         published_at=COALESCE(instagram_target_publications.published_at,EXCLUDED.published_at),
                         error_code=EXCLUDED.error_code,updated_at=now()
                       WHERE instagram_target_publications.status <> 'published'""",
                    (route, platform, sha256, status, post_id, timestamp, error_code))
        cur.execute("""SELECT count(*) FROM instagram_target_publications
                       WHERE route=%s AND sha256=%s AND platform=ANY(%s) AND status='published'""",
                    (route, sha256, required_platforms))
        published_count = int(cur.fetchone()[0])
        if published_count == len(set(required_platforms)):
            plan_status = "published"
        elif status in {"intent", "error", "uncertain"}:
            plan_status = status
        else:
            plan_status = "waiting_publication"
        cur.execute("""UPDATE instagram_target_daily_plans SET status=%s
                       WHERE route=%s AND sha256=%s AND local_day=%s""",
                    (plan_status, route, sha256, local_day))
    conn.commit()
