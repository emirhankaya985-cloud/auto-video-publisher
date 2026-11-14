import http.client
import json
import os
import threading
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import dashboard_server as d


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *_args):
        return None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self.rows)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for day, views in [(date(2026, 11, 1), 100), (date(2026, 11, 7), 140), (date(2026, 11, 13), 190)]:
            stamp = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            rows.append(("Account", "Instagram", "ok", None, None, "lifetime_views", views, "ok", None, stamp, day))
            rows.append(("Account", "Instagram", "ok", None, None, "follower_count", 12, "ok", None, stamp, day))
        self.db = patch("dashboard_server._db", return_value=FakeConnection(rows))
        self.db.start()
        self.addCleanup(self.db.stop)

    def test_current_history_and_followers_use_database_snapshots(self):
        row = d.build_payload()["accounts"][0]
        self.assertEqual(row["current_views"], 190)
        self.assertEqual(len(row["history"]), 3)
        self.assertEqual(row["followers"], 12)
        self.assertEqual(row["latest_day"], "2026-11-13")

    def test_missing_baselines_remain_unknown(self):
        row = d.build_payload()["accounts"][0]
        self.assertIsNone(row["weekly_delta"])
        self.assertIsNone(row["monthly_delta"])
        self.assertIn("Kıyas ölçümü", row["data_reason"])

    def test_failed_metric_is_not_zero_and_last_verified_value_is_retained(self):
        stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
        good = ("Account", "Instagram", "ok", stamp, None, "lifetime_views", 100, "ok", None, stamp, date(2026, 11, 1))
        failed = ("Account", "Instagram", "incomplete", stamp, "API 403: izin reddedildi", "lifetime_views",
                  None, "error", "API 403: izin reddedildi", None, date(2026, 11, 13))
        with patch("dashboard_server._db", return_value=FakeConnection([good, failed])):
            row = d.build_payload()["accounts"][0]
        self.assertEqual(row["current_views"], 100)
        self.assertTrue(row["current_views_is_stale"])
        self.assertEqual(row["last_verified_views"]["value"], 100)
        self.assertEqual(row["last_verified_views"]["date"], "2026-11-01")
        self.assertIn("izin reddedildi", row["data_reason"])

    def test_archive_keeps_account_and_video_identity_separate(self):
        row = {
            "account": "🌱 Tarladaki Fasulye", "platform": "Instagram",
            "entity_type": "video", "entity_id": "video-123", "metric": "view_count",
            "period": "2026-11-13", "measured_at": "2026-11-13T20:00:00+03:00",
            "status": "ok", "value": 1234,
        }
        normalized, reason = d.classify_archive_row(row)
        self.assertIsNone(reason)
        self.assertIsNone(normalized["platform_account_id"])
        self.assertEqual(normalized["video_id"], "video-123")
        self.assertEqual(normalized["entity_id"], "video-123")
        account_row = dict(row, entity_type="account", entity_id="🌱 Tarladaki Fasulye", metric="lifetime_views")
        account, reason = d.classify_archive_row(account_row)
        self.assertIsNone(reason)
        self.assertEqual(account["source_key"], normalized["source_key"])
        self.assertEqual(account["entity_id"], "🌱 Tarladaki Fasulye")

    def test_unmapped_account_is_queued_for_review_instead_of_guessed(self):
        row = {
            "account": "unknown account", "platform": "Instagram", "entity_type": "video",
            "entity_id": "video-1", "metric": "view_count", "period": "2026-11-13",
            "status": "ok", "value": 1,
        }
        normalized, reason = d.classify_archive_row(row)
        self.assertIsNone(normalized)
        self.assertEqual(reason, "unmapped_account")

    def test_payload_sums_distinct_video_snapshots_without_adding_days(self):
        day = date(2026, 11, 13)
        stamp = datetime(2026, 11, 13, tzinfo=timezone.utc)
        prefix = ("Account", "Instagram", None, "source-key", "ok", stamp, None)
        rows = [
            prefix + ("lifetime_views", 100, "ok", None, stamp, day, "account", "Account", None, None),
            prefix + ("follower_count", 5, "ok", None, stamp, day, "account", "Account", None, None),
            prefix + ("view_count", 30, "ok", None, stamp, day, "video", "v1", "v1", None),
            prefix + ("view_count", 20, "ok", None, stamp, day, "video", "v2", "v2", None),
        ]
        with patch("dashboard_server._db", return_value=FakeConnection(rows)):
            row = d.build_payload()["accounts"][0]
        self.assertEqual(row["current_views"], 100)
        self.assertEqual(row["video_views"], 50)
        self.assertEqual(row["video_view_count"], 2)

    def test_signed_cookie_session_and_expiration(self):
        class Request:
            client_address = ("127.0.0.1", 1234)

            def __init__(self, cookie):
                self.headers = {"Cookie": cookie}

        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "strong-test-secret"}, clear=True):
            timestamp = str(int(d.time.time()))
            token = d._session_token("strong-test-secret", timestamp)
            self.assertTrue(d._valid_session(Request(f"{d.SESSION_COOKIE}={token}")))
            self.assertFalse(d._valid_session(Request(f"{d.SESSION_COOKIE}=wrong")))




class DashboardLoginHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = d.ThreadingHTTPServer(("127.0.0.1", 0), d.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=3)
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        encoded = json.dumps(body).encode() if body is not None else None
        req_headers = dict(headers or {})
        if encoded is not None:
            req_headers["Content-Type"] = "application/json"
        conn.request(method, path, body=encoded, headers=req_headers)
        response = conn.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        conn.close()
        return result

    def test_wrong_password_and_audit_failure_do_not_create_session(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "secure-test"}, clear=True), \
             patch("dashboard_server._record_login", return_value=True):
            status, headers, _ = self.request("POST", "/api/login", {"password": "wrong"})
            self.assertEqual(status, 401)
            self.assertNotIn("Set-Cookie", headers)
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "secure-test"}, clear=True), \
             patch("dashboard_server._record_login", return_value=False):
            status, headers, _ = self.request("POST", "/api/login", {"password": "secure-test"})
            self.assertEqual(status, 503)
            self.assertNotIn("Set-Cookie", headers)

    def test_success_issues_secure_cookie_and_unlocks_analytics(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "secure-test"}, clear=True), \
             patch("dashboard_server._record_login", return_value=True), \
             patch("dashboard_server._security_login_notice"), \
             patch("dashboard_server.build_payload", return_value={"accounts": [], "measured_at": None}):
            status, headers, _ = self.request("POST", "/api/login", {"password": "secure-test"})
            self.assertEqual(status, 200)
            cookie = headers["Set-Cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn("Secure", cookie)
            self.assertIn("SameSite=Strict", cookie)
            status, _, body = self.request("GET", "/api/analytics", headers={"Cookie": cookie.split(";", 1)[0]})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"accounts": [], "measured_at": None})
        status, _, _ = self.request("GET", "/api/analytics")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()

