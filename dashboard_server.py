"""Private analytics dashboard backed by Neon Postgres."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
ARCHIVE = Path(os.getenv("ANALYTICS_ARCHIVE_PATH", ROOT / "dashboard-data" / "daily_video_views.jsonl"))
SESSION_COOKIE = "social_dashboard_session"
SESSION_SECONDS = 8 * 60 * 60

KNOWN_ACCOUNTS = {
    "🌱 Tarladaki Fasulye", "🐧 Beyinsiz Penguen", "❤️ Gönle Düşen",
    "😂 Daily Laugh Lab", "🎬 Film Mağarası + Filmmagrasi", "📺 ToonZone",
}
PLATFORM_ALIASES = {
    "facebook": "Facebook", "facebook 1": "Facebook", "facebook 2": "Facebook",
    "instagram": "Instagram", "threads": "Threads", "youtube": "YouTube",
    "tiktok": "TikTok",
}


def classify_archive_row(row):
    """Validate one source row without guessing account/content identifiers."""
    if not isinstance(row, dict):
        return None, "row_not_object"
    if isinstance(row.get("_review_reason"), str) and row["_review_reason"]:
        return None, row["_review_reason"][:120]
    account = row.get("account")
    raw_platform = row.get("platform")
    if account not in KNOWN_ACCOUNTS:
        return None, "unmapped_account"
    if not isinstance(raw_platform, str) or raw_platform.casefold() not in PLATFORM_ALIASES:
        return None, "unmapped_platform"
    platform = PLATFORM_ALIASES[raw_platform.casefold()]
    entity_type = row.get("entity_type")
    entity_id = row.get("entity_id")
    metric = row.get("metric")
    period = row.get("period")
    if entity_type not in {"account", "video", "post"}:
        return None, "unmapped_entity_type"
    if not isinstance(entity_id, str) or not entity_id.strip():
        return None, "missing_entity_id"
    if len(entity_id) > 1024:
        return None, "entity_id_too_long"
    if not isinstance(metric, str) or not metric.strip():
        return None, "missing_metric"
    if len(metric) > 250:
        return None, "metric_name_too_long"
    if not isinstance(period, str):
        return None, "missing_period"
    try:
        period_date = date.fromisoformat(period[:10])
    except ValueError:
        return None, "invalid_period"
    raw_value = row.get("value")
    status = row.get("status", "unknown")
    if not isinstance(status, str) or not status.strip():
        return None, "invalid_status"
    if isinstance(raw_value, bool) or not (raw_value is None or isinstance(raw_value, (int, float))):
        return None, "invalid_metric_value"
    if status == "ok" and raw_value is None:
        return None, "successful_metric_without_value"
    measured = row.get("measured_at")
    try:
        observed_at = datetime.fromisoformat(measured.replace("Z", "+00:00")) if isinstance(measured, str) else None
    except ValueError:
        return None, "invalid_observed_at"
    if observed_at is not None and observed_at.tzinfo is None:
        return None, "observed_at_missing_timezone"
    platform_account_id = row.get("platform_account_id")
    if platform_account_id is not None and not isinstance(platform_account_id, str):
        return None, "invalid_platform_account_id"
    if isinstance(platform_account_id, str) and len(platform_account_id) > 1024:
        return None, "platform_account_id_too_long"
    if row.get("reason") is not None and not isinstance(row.get("reason"), str):
        return None, "invalid_reason"
    # This internal key distinguishes source subaccounts such as Facebook 1/2;
    # it is not represented as a provider-issued platform account ID.
    source_key = hashlib.sha256((account + "\x1f" + raw_platform).encode("utf-8")).hexdigest()
    normalized = dict(row)
    normalized.update({
        "account": account, "platform": platform, "source_platform": raw_platform,
        "source_key": source_key, "platform_account_id": platform_account_id,
        "entity_type": entity_type, "entity_id": entity_id.strip(), "metric": metric.strip(),
        "period": period_date.isoformat(), "measured_at": observed_at.isoformat() if observed_at else None,
        "value": raw_value, "status": status,
        "video_id": row.get("video_id") or (entity_id.strip() if entity_type == "video" else None),
        "post_id": row.get("post_id") if isinstance(row.get("post_id"), str) else None,
    })
    return normalized, None


def _db():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    import psycopg
    return psycopg.connect(url, connect_timeout=5)


def migrate_schema():
    with _db() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE metric_snapshots ALTER COLUMN measured_at DROP NOT NULL")
        cur.execute("ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS period_date DATE")
        cur.execute("ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS reason TEXT")
        cur.execute("ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS measurement_key TEXT")
        cur.execute("UPDATE metric_snapshots SET measurement_key = COALESCE(measured_at::text, period_date::text) WHERE measurement_key IS NULL")
        cur.execute("ALTER TABLE metric_snapshots ALTER COLUMN measurement_key SET NOT NULL")
        cur.execute("ALTER TABLE social_accounts ADD COLUMN IF NOT EXISTS source_key TEXT")
        cur.execute("ALTER TABLE social_accounts ADD COLUMN IF NOT EXISTS platform_account_label TEXT")
        cur.execute("UPDATE social_accounts SET source_key = 'legacy:' || id::text WHERE source_key IS NULL OR source_key = ''")
        cur.execute("ALTER TABLE social_accounts ALTER COLUMN source_key SET NOT NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS social_accounts_source_key_idx ON social_accounts(source_key)")
        cur.execute("ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS entity_type TEXT")
        cur.execute("ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS entity_id TEXT")
        cur.execute("ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS video_id TEXT")
        cur.execute("ALTER TABLE metric_snapshots ADD COLUMN IF NOT EXISTS post_id TEXT")
        cur.execute("UPDATE metric_snapshots SET entity_type = COALESCE(entity_type, 'account'), entity_id = COALESCE(entity_id, 'legacy:' || id::text)")
        cur.execute("ALTER TABLE metric_snapshots ALTER COLUMN entity_type SET NOT NULL")
        cur.execute("ALTER TABLE metric_snapshots ALTER COLUMN entity_id SET NOT NULL")
        cur.execute("DROP INDEX IF EXISTS metric_snapshots_idempotency_idx")
        cur.execute("ALTER TABLE metric_snapshots DROP CONSTRAINT IF EXISTS metric_snapshots_account_id_metric_measured_at_key")
        cur.execute("DROP INDEX IF EXISTS metric_snapshots_account_id_metric_measured_at_key")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS metric_snapshots_idempotency_idx ON metric_snapshots(account_id, metric, entity_type, entity_id, measurement_key)")
        cur.execute("CREATE INDEX IF NOT EXISTS metric_snapshots_account_metric_period_idx ON metric_snapshots(account_id, metric, period_date)")
        cur.execute("CREATE TABLE IF NOT EXISTS archive_review_queue (id BIGSERIAL PRIMARY KEY, row_hash TEXT NOT NULL UNIQUE, reason TEXT NOT NULL, raw_record JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), resolved_at TIMESTAMPTZ)")
        cur.execute("CREATE TABLE IF NOT EXISTS archive_import_runs (id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, archive_sha256 TEXT NOT NULL, rows_seen INTEGER NOT NULL, rows_deduplicated INTEGER NOT NULL, rows_accepted INTEGER NOT NULL, rows_review_queued INTEGER NOT NULL, rows_rejected INTEGER NOT NULL, dry_run BOOLEAN NOT NULL, details JSONB NOT NULL DEFAULT '{}'::jsonb, started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        cur.execute("CREATE TABLE IF NOT EXISTS dashboard_schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        cur.execute("INSERT INTO dashboard_schema_migrations(version) VALUES ('2026-11-neon-dashboard-v1') ON CONFLICT(version) DO NOTHING")


def build_payload():
    with _db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT a.account_name, a.platform, a.platform_account_label, a.source_key,
                   a.status, a.last_verified_at, a.source_reason,
                   m.metric, m.value, m.status, m.reason, m.measured_at, m.period_date,
                   m.entity_type, m.entity_id, m.video_id, m.post_id
              FROM social_accounts a
              LEFT JOIN metric_snapshots m ON m.account_id = a.id
             ORDER BY a.account_name, a.platform, m.period_date, m.measured_at
        """)
        records = cur.fetchall()

    grouped = {}
    content_metrics = {}
    for record in records:
        if len(record) >= 17:
            (account, platform, platform_label, source_key, account_status, verified, account_reason,
             metric, value, status, reason, measured_at, period_date, entity_type, entity_id, video_id, post_id) = record
        else:  # Compatibility for older callers and test fixtures.
            (account, platform, account_status, verified, account_reason, metric, value, status, reason, measured_at, period_date) = record
            platform_label, source_key, entity_type, entity_id, video_id, post_id = None, None, "account", "", None, None
        key = (account, platform, source_key)
        group = grouped.setdefault(key, {"account": account, "platform": platform,
                                         "platform_account_label": platform_label,
                                         "status": account_status, "verified_at": verified, "account_reason": account_reason,
                                         "snapshots": {}, "content": {}})
        if not metric:
            continue
        day = period_date.isoformat() if period_date else (measured_at.date().isoformat() if measured_at else None)
        if not day:
            continue
        if entity_type == "video":
            video_key = (key, day, video_id or entity_id)
            video = content_metrics.setdefault(video_key, {"group_key": key, "date": day, "video_id": video_id or entity_id, "metrics": {}})
            old = video["metrics"].get(metric)
            if old is None or (measured_at and (old.get("measured_at") is None or measured_at > old["measured_at"])):
                video["metrics"][metric] = {"value": int(value) if value is not None else None,
                                            "status": status, "reason": reason, "measured_at": measured_at}
            continue
        snap = group["snapshots"].setdefault(day, {})
        metric = "follower_count" if metric == "followers" else metric
        snap[metric] = {"value": int(value) if value is not None else None,
                        "status": status, "reason": reason, "measured_at": measured_at}

    for video in content_metrics.values():
        group = grouped.get(video["group_key"])
        if group is None:
            continue
        snapshot = group["content"].setdefault(video["date"], {"views": 0, "view_items": 0, "likes": 0, "comments": 0})
        for source_metric, target_metric in (("view_count", "views"), ("like_count", "likes"), ("comment_count", "comments")):
            metric = video["metrics"].get(source_metric)
            if metric and metric["status"] == "ok" and metric["value"] is not None:
                snapshot[target_metric] += metric["value"]
                if source_metric == "view_count":
                    snapshot["view_items"] += 1

    accounts = []
    for group in grouped.values():
        snaps = group.pop("snapshots")
        days = sorted(snaps)
        latest = days[-1] if days else None
        current = snaps.get(latest, {}) if latest else {}
        def metric_value(day, name):
            item = snaps.get(day, {}).get(name)
            return item.get("value") if item and item.get("status") == "ok" else None
        def delta(days_back, metric):
            if not latest:
                return None
            try:
                base_day = (date.fromisoformat(latest) - timedelta(days=days_back)).isoformat()
            except ValueError:
                return None
            now, base = metric_value(latest, metric), metric_value(base_day, metric)
            return now - base if now is not None and base is not None else None
        view = current.get("lifetime_views", {})
        follower = current.get("follower_count", {})
        def last_verified(metric):
            for past_day in reversed(days):
                item = snaps.get(past_day, {}).get(metric, {})
                if item.get("status") == "ok" and item.get("value") is not None:
                    return {"value": item["value"], "date": past_day,
                            "measured_at": item["measured_at"].isoformat() if item.get("measured_at") else None}
            return None
        last_views = last_verified("lifetime_views")
        last_followers = last_verified("follower_count")
        account_views_now = metric_value(latest, "lifetime_views")
        account_followers_now = metric_value(latest, "follower_count")
        display_views = account_views_now if account_views_now is not None else (last_views["value"] if last_views else None)
        display_followers = account_followers_now if account_followers_now is not None else (last_followers["value"] if last_followers else None)
        latest_measure = (view.get("measured_at") or follower.get("measured_at") or
                          (datetime.fromisoformat(last_views["measured_at"]) if last_views and last_views.get("measured_at") else None) or
                          (datetime.fromisoformat(last_followers["measured_at"]) if last_followers and last_followers.get("measured_at") else None))
        reason_items = [item.get("reason") for item in current.values()
                        if item.get("status") != "ok" and item.get("reason")]
        content_days = group.get("content", {})
        content_latest_day = max(content_days) if content_days else None
        content_latest = content_days.get(content_latest_day, {}) if content_latest_day else {}
        engagement_items = [metric_value(latest, name) for name in ("likes", "replies", "reposts", "quotes", "shares", "like_count", "comment_count")]
        engagement_values = [value for value in engagement_items if value is not None]
        explanation = ([group["account_reason"]] if group.get("account_reason") else []) + reason_items
        if account_views_now is None and last_views:
            explanation.append("Toplam görüntülenme güncel değil; son doğrulanan değer " + last_views["date"] + " tarihinde alındı")
        elif account_views_now is None and content_latest_day:
            explanation.append("Hesap toplamı alınamadı; video bazlı görüntülenmeler ayrıca gösteriliyor")
        if account_followers_now is None and last_followers:
            explanation.append("Takipçi sayısı güncel değil; son doğrulanan değer " + last_followers["date"] + " tarihinde alındı")
        elif account_followers_now is None:
            explanation.append("Takipçi verisi arşivde yok")
        accounts.append({
            "account": group["account"], "platform": group["platform"],
            "platform_account_label": group.get("platform_account_label"),
            "current_views": display_views,
            "current_views_is_stale": account_views_now is None and last_views is not None,
            "current_views_verified_at": last_views["measured_at"] if last_views else None,
            "followers": display_followers,
            "followers_is_stale": account_followers_now is None and last_followers is not None,
            "followers_verified_at": last_followers["measured_at"] if last_followers else None,
            "video_count": metric_value(latest, "snapshot_status"),
            "engagement": sum(engagement_values) if engagement_values else metric_value(latest, "engagement_count"),
            "video_views": content_latest.get("views") if content_latest.get("view_items") else None,
            "video_view_count": content_latest.get("view_items", 0),
            "video_views_measured_at": content_latest_day,
            "status": "ok" if metric_value(latest, "lifetime_views") is not None else "incomplete",
            "measured_at": latest_measure.isoformat() if latest_measure else None,
            "latest_day": latest, "verified_at": group["verified_at"].isoformat() if group["verified_at"] else None,
            "history": [{"date": day, "value": metric_value(day, "lifetime_views")} for day in days],
            "daily_delta": delta(1, "lifetime_views"),
            "weekly_delta": delta(7, "lifetime_views"),
            "monthly_delta": delta(30, "lifetime_views"),
            "all_delta": (metric_value(latest, "lifetime_views") - metric_value(days[0], "lifetime_views"))
                         if len(days) > 1 and metric_value(latest, "lifetime_views") is not None
                         and metric_value(days[0], "lifetime_views") is not None else None,
            "last_verified_views": last_views,
            "last_verified_followers": last_followers,
            "data_reason": "; ".join(dict.fromkeys(explanation)) if explanation else
                           ("Kıyas ölçümü arşivde yok" if latest else "Henüz doğrulanmış ölçüm yok"),
        })
    measured = [a["measured_at"] for a in accounts if a.get("measured_at")]
    return {"measured_at": max(measured) if measured else None, "accounts": accounts}


def _client_fingerprint(handler):
    address = handler.client_address[0] if handler.client_address else "unknown"
    salt = os.getenv("LOGIN_LOG_SALT", os.getenv("DASHBOARD_PASSWORD", ""))
    return hashlib.sha256((salt + address).encode()).hexdigest()


def _record_login(handler, outcome):
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO login_events(outcome, client_fingerprint) VALUES (%s, %s)",
                (outcome, _client_fingerprint(handler)),
            )
        return True
    except Exception:
        # Do not leak credentials; reject authentication if its audit record cannot be saved.
        return False


def _security_login_notice():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    event_key = "admin-login:" + str(uuid.uuid4())
    status, error = "failed", None
    try:
        data = urlencode({"chat_id": chat_id, "text": "🔐 Sosyal medya yönetim paneline başarılı yönetici girişi yapıldı."}).encode()
        request = Request("https://api.telegram.org/bot" + token + "/sendMessage", data=data, method="POST")
        with urlopen(request, timeout=8) as response:
            result = json.loads(response.read(65536).decode("utf-8"))
        if result.get("ok") is True:
            status = "sent"
        else:
            error = "telegram_api_rejected"
    except Exception:
        error = "telegram_delivery_failed"
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notification_events(event_key, channel, status, payload_redacted, delivered_at, error) "
                "VALUES (%s, 'telegram_security', %s, %s, CASE WHEN %s='sent' THEN now() ELSE NULL END, %s)",
                (event_key, status, "admin_login_success", status, error),
            )
    except Exception:
        pass


def _session_token(password, timestamp):
    signature = hmac.new(password.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    return timestamp + "." + signature


def _valid_session(handler):
    password = os.getenv("DASHBOARD_PASSWORD", "")
    if not password:
        return False
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie", ""))
        token = cookie[SESSION_COOKIE].value
        timestamp, signature = token.split(".", 1)
        issued = int(timestamp)
    except Exception:
        return False
    if time.time() - issued > SESSION_SECONDS or issued > time.time() + 60:
        return False
    expected = hmac.new(password.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload, headers=()):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            try:
                with _db() as conn:
                    conn.execute("SELECT 1")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            except Exception:
                self.send_error(503, "database unavailable")
            return
        if path in ("/", "/index.html", "/chart.js"):
            name = "chart.js" if path == "/chart.js" else "dashboard.html"
            content_type = "application/javascript; charset=utf-8" if name == "chart.js" else "text/html; charset=utf-8"
            body = (ROOT / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/analytics":
            if not _valid_session(self):
                self._json(401, {"error": "authentication_required"})
                return
            try:
                self._json(200, build_payload())
            except Exception:
                self._json(503, {"error": "analytics_unavailable", "reason": "Neon bağlantısı veya sorgusu başarısız"})
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid_content_length"})
            return
        if size < 0 or size > 10_000_000:
            self._json(413, {"error": "payload_too_large"})
            return
        try:
            payload = json.loads(self.rfile.read(size) or b"{}")
        except (ValueError, TypeError):
            self._json(400, {"error": "invalid_json"})
            return

        if path == "/api/login":
            password = os.getenv("DASHBOARD_PASSWORD", "")
            supplied = payload.get("password", "") if isinstance(payload, dict) else ""
            valid = bool(password) and isinstance(supplied, str) and hmac.compare_digest(password, supplied)
            if not _record_login(self, "success" if valid else "failure"):
                self._json(503, {"error": "audit_unavailable"})
                return
            if not valid:
                self._json(401, {"error": "invalid_credentials"})
                return
            _security_login_notice()
            timestamp = str(int(time.time()))
            token = _session_token(password, timestamp)
            self._json(200, {"ok": True}, (("Set-Cookie", f"{SESSION_COOKIE}={token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}"),))
            return

        if path == "/api/archive/import-run":
            expected = os.getenv("DASHBOARD_INGEST_TOKEN", "")
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not expected or not hmac.compare_digest(expected, supplied):
                self._json(401, {"error": "ingest_unauthorized"})
                return
            if not isinstance(payload, dict):
                self._json(400, {"error": "invalid_import_summary"})
                return
            try:
                with _db() as conn, conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO archive_import_runs(source, archive_sha256, rows_seen, rows_deduplicated,
                            rows_accepted, rows_review_queued, rows_rejected, dry_run, details, started_at, completed_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                        RETURNING id
                    """, (str(payload.get("source", "github-actions-history")),
                          str(payload.get("archive_sha256", "")), int(payload.get("rows_seen", 0)),
                          int(payload.get("rows_deduplicated", 0)), int(payload.get("rows_accepted", 0)),
                          int(payload.get("rows_review_queued", 0)), int(payload.get("rows_rejected", 0)),
                          bool(payload.get("dry_run", False)), json.dumps(payload.get("details", {}), ensure_ascii=False),
                          payload.get("started_at"), payload.get("completed_at")))
                    run_id = cur.fetchone()[0]
                self._json(200, {"recorded": True, "id": run_id})
            except Exception:
                self._json(503, {"error": "import_audit_write_failed"})
            return

        if path == "/api/archive":
            expected = os.getenv("DASHBOARD_INGEST_TOKEN", "")
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not expected or not hmac.compare_digest(expected, supplied):
                self._json(401, {"error": "ingest_unauthorized"})
                return
            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                self._json(400, {"error": "rows_required"})
                return
            accepted = review_queued = rejected = 0
            try:
                with _db() as conn, conn.cursor() as cur:
                    for row in rows:
                        normalized, reason = classify_archive_row(row)
                        if reason:
                            try:
                                raw_json = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                            except (TypeError, ValueError):
                                rejected += 1
                                continue
                            row_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
                            cur.execute("""
                                INSERT INTO archive_review_queue(row_hash, reason, raw_record)
                                VALUES (%s, %s, %s::jsonb) ON CONFLICT(row_hash) DO NOTHING
                            """, (row_hash, reason, raw_json))
                            review_queued += max(cur.rowcount, 0)
                            continue
                        account, platform = normalized["account"], normalized["platform"]
                        metric, period = normalized["metric"], normalized["period"]
                        day = date.fromisoformat(period)
                        measured_at = datetime.fromisoformat(normalized["measured_at"]) if normalized["measured_at"] else None
                        value = normalized["value"]
                        cur.execute("""
                            INSERT INTO social_accounts(account_name, platform, platform_account_id, status,
                                last_verified_at, source_reason, source_key, platform_account_label)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(source_key) DO UPDATE
                              SET status=EXCLUDED.status,
                                  last_verified_at=GREATEST(social_accounts.last_verified_at, EXCLUDED.last_verified_at),
                                  source_reason=EXCLUDED.source_reason,
                                  platform_account_id=COALESCE(EXCLUDED.platform_account_id, social_accounts.platform_account_id),
                                  platform_account_label=EXCLUDED.platform_account_label
                            RETURNING id
                        """, (account, platform, normalized.get("platform_account_id"),
                              normalized["status"] if normalized["entity_type"] == "account" else "unknown",
                              measured_at if normalized["status"] == "ok" and normalized["entity_type"] == "account" else None,
                              (normalized.get("reason") or (("API verisi " + str(normalized["status"]) + ": " +
                                  str(normalized.get("source_api") or normalized.get("source_metric") or "kaynak ayrıntısı yok"))
                                  if normalized["status"] != "ok" else None)) if normalized["entity_type"] == "account" else None,
                              normalized["source_key"],
                              normalized["source_platform"] if normalized["source_platform"] != platform else None))
                        account_id = cur.fetchone()[0]
                        cur.execute("""
                            INSERT INTO metric_snapshots(account_id, metric, value, status, reason, measured_at,
                                period_date, source, measurement_key, entity_type, entity_id, video_id, post_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(account_id, metric, entity_type, entity_id, measurement_key) DO UPDATE SET
                              value=EXCLUDED.value, status=EXCLUDED.status, reason=EXCLUDED.reason,
                              period_date=EXCLUDED.period_date, source=EXCLUDED.source,
                              video_id=EXCLUDED.video_id, post_id=EXCLUDED.post_id
                        """, (account_id, metric, value, normalized["status"],
                              normalized.get("reason") or (("API verisi " + str(normalized["status"]) + ": " +
                                  str(normalized.get("source_api") or normalized.get("source_metric") or "kaynak ayrıntısı yok"))
                                  if normalized["status"] != "ok" else None),
                              measured_at, day, "github-actions-analytics-archive",
                              measured_at.isoformat() if measured_at else day,
                              normalized["entity_type"], normalized["entity_id"], normalized["video_id"], normalized["post_id"]))
                        accepted += 1
                self._json(200, {"accepted": accepted, "review_queued": review_queued, "rejected": rejected})
            except Exception:
                self._json(503, {"error": "database_write_failed"})
            return
        self.send_error(404)

    def log_message(self, *args):
        return


if __name__ == "__main__":
    if not os.getenv("DASHBOARD_PASSWORD") or not os.getenv("DASHBOARD_INGEST_TOKEN") or not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL, DASHBOARD_PASSWORD and DASHBOARD_INGEST_TOKEN are required")
    migrate_schema()
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "10000"))), Handler).serve_forever()

