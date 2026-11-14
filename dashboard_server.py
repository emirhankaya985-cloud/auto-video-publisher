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
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS metric_snapshots_idempotency_idx ON metric_snapshots(account_id, metric, measurement_key)")
        cur.execute("CREATE INDEX IF NOT EXISTS metric_snapshots_account_metric_period_idx ON metric_snapshots(account_id, metric, period_date)")
        cur.execute("CREATE TABLE IF NOT EXISTS dashboard_schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        cur.execute("INSERT INTO dashboard_schema_migrations(version) VALUES ('2026-11-neon-dashboard-v1') ON CONFLICT(version) DO NOTHING")


def build_payload():
    with _db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT a.account_name, a.platform, a.status, a.last_verified_at,
                   m.metric, m.value, m.status, m.reason, m.measured_at, m.period_date
              FROM social_accounts a
              LEFT JOIN metric_snapshots m ON m.account_id = a.id
             ORDER BY a.account_name, a.platform, m.period_date, m.measured_at
        """)
        records = cur.fetchall()

    grouped = {}
    for account, platform, account_status, verified, metric, value, status, reason, measured_at, period_date in records:
        key = (account, platform)
        group = grouped.setdefault(key, {"account": account, "platform": platform,
                                         "status": account_status, "verified_at": verified,
                                         "snapshots": {}})
        if not metric:
            continue
        day = period_date.isoformat() if period_date else (measured_at.date().isoformat() if measured_at else None)
        if not day:
            continue
        snap = group["snapshots"].setdefault(day, {})
        snap[metric] = {"value": int(value) if value is not None else None,
                        "status": status, "reason": reason, "measured_at": measured_at}

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
        latest_measure = view.get("measured_at") or follower.get("measured_at")
        reason_items = [item.get("reason") for item in current.values()
                        if item.get("status") != "ok" and item.get("reason")]
        accounts.append({
            "account": group["account"], "platform": group["platform"],
            "current_views": metric_value(latest, "lifetime_views"),
            "followers": metric_value(latest, "follower_count"),
            "video_count": metric_value(latest, "snapshot_status"),
            "engagement": metric_value(latest, "engagement_count"),
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
            "data_reason": "; ".join(dict.fromkeys(reason_items)) if reason_items else
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
            inserted = 0
            try:
                with _db() as conn, conn.cursor() as cur:
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        account, platform = row.get("account"), row.get("platform")
                        metric, period = row.get("metric"), row.get("period")
                        if not all(isinstance(x, str) and x for x in (account, platform, metric, period)):
                            continue
                        try:
                            day = date.fromisoformat(period[:10])
                        except ValueError:
                            continue
                        raw_time = row.get("measured_at")
                        measured_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00")) if isinstance(raw_time, str) else None
                        value = row.get("value")
                        if isinstance(value, bool) or not (value is None or isinstance(value, (int, float))):
                            continue
                        cur.execute("""
                            INSERT INTO social_accounts(account_name, platform, platform_account_id, status, last_verified_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT(account_name, platform, platform_account_id) DO UPDATE
                              SET status=EXCLUDED.status,
                                  last_verified_at=GREATEST(social_accounts.last_verified_at, EXCLUDED.last_verified_at)
                            RETURNING id
                        """, (account, platform, str(row.get("platform_account_id") or row.get("entity_id") or ""),
                              row.get("status", "unknown"),
                              measured_at if row.get("status") == "ok" else None))
                        account_id = cur.fetchone()[0]
                        cur.execute("""
                            INSERT INTO metric_snapshots(account_id, metric, value, status, reason, measured_at, period_date, source, measurement_key)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(account_id, metric, measurement_key) DO UPDATE SET
                              value=EXCLUDED.value, status=EXCLUDED.status, reason=EXCLUDED.reason,
                              period_date=EXCLUDED.period_date, source=EXCLUDED.source
                        """, (account_id, metric, value, row.get("status", "unknown"),
                              row.get("reason") or (("API verisi " + str(row.get("status")) + ": " +
                                  str(row.get("source_api") or row.get("source_metric") or "kaynak ayrıntısı yok"))
                                  if row.get("status") != "ok" else None),
                              measured_at, day, "github-actions-analytics-archive",
                              measured_at.isoformat() if measured_at else day))
                        inserted += 1
                self._json(200, {"accepted": inserted})
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
