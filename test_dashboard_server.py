import os
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
        self.assertIsNone(row["current_views"])
        self.assertEqual(row["last_verified_views"]["value"], 100)
        self.assertEqual(row["last_verified_views"]["date"], "2026-11-01")
        self.assertIn("izin reddedildi", row["data_reason"])

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


if __name__ == "__main__":
    unittest.main()
