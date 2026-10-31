"""Pure mocked regressions; this test suite MUST NOT upload or publish."""
import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import tracked_meta_routes as watch

UTC = timezone.utc
TOON_TIME = datetime(2026, 10, 27, 10, 40, tzinfo=UTC)
DAILY_TIME = datetime(2026, 10, 27, 5, 40, tzinfo=UTC)
ACCOUNTS = {"pages": [
    {"page_name": "ToonZone", "page_id": "1298191963387372", "instagram_id": "111"},
    {"page_name": "Daily Laugh Lab", "page_id": "222", "instagram_id": "333"},
]}


def rows(count, stamp):
    return [
        {"id": str(100000 + i), "created_time": stamp, "timestamp": stamp,
         "media_type": "VIDEO"}
        for i in range(count)
    ]


def reader(fb, ig, fb_stamp="2026-10-27T09:10:00Z",
           ig_stamp="2026-10-27T09:11:00Z"):
    return Mock(side_effect=lambda page, platform: rows(
        fb if platform == "facebook" else ig,
        fb_stamp if platform == "facebook" else ig_stamp
    ))


class TrackedRoutesTests(unittest.TestCase):
    def test_toonzone_four_parts_per_platform_verified(self):
        get = reader(4, 4)
        result = watch.check_route(
            "toonzone", now=TOON_TIME, page_loader=lambda: ACCOUNTS,
            history_reader=get, paused=lambda route: False
        )
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["day"], "2026-10-27")
        self.assertEqual(result["counts"], {"facebook": 4, "instagram": 4})
        self.assertEqual(get.call_count, 2)

    def test_toonzone_one_missing_reel_is_not_green(self):
        result = watch.check_route(
            "toonzone", now=TOON_TIME, page_loader=lambda: ACCOUNTS,
            history_reader=reader(4, 3), paused=lambda route: False
        )
        self.assertEqual(result["status"], "behind")
        self.assertEqual(result["missing"], {"facebook": 0, "instagram": 1})

    def test_daily_laugh_previous_new_york_day_has_eight_per_platform(self):
        # At 08:40 Istanbul in summer, NY is 01:40: check yesterday,
        # NOT the zero-post day just beginning in New York.
        result = watch.check_route(
            "daily_laugh", now=DAILY_TIME, page_loader=lambda: ACCOUNTS,
            history_reader=reader(8, 7, "2026-10-26T17:00:00Z",
                                  "2026-10-26T17:05:00Z"),
            paused=lambda route: False,
        )
        self.assertEqual(result["day"], "2026-10-26")
        self.assertEqual(result["status"], "behind")
        self.assertEqual(result["missing"]["instagram"], 1)
        self.assertEqual(result["missing"]["facebook"], 0)

    def test_new_york_winter_dst_deadline_keeps_previous_day(self):
        at = datetime(2026, 11, 10, 5, 40, tzinfo=UTC)
        self.assertEqual(watch.target_day("daily_laugh", at).isoformat(), "2026-11-09")

    def test_disabled_route_never_queries_meta(self):
        loader = Mock(side_effect=AssertionError("Must not contact Meta"))
        result = watch.check_route(
            "toonzone", now=TOON_TIME, page_loader=loader,
            paused=lambda route: True,
        )
        self.assertEqual(result["status"], "disabled")
        loader.assert_not_called()

    def test_disabled_daily_instagram_does_not_create_false_alarm(self):
        get = reader(8, 0, "2026-10-26T17:00:00Z")
        result = watch.check_route(
            "daily_laugh", now=DAILY_TIME, page_loader=lambda: ACCOUNTS,
            history_reader=get,
            paused=lambda route: route == "daily_laugh_instagram",
        )
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["instagram"]["status"], "disabled")
        self.assertEqual(get.call_count, 1)

    def test_duplicate_remote_post_id_does_not_count_twice(self):
        duplicate = rows(4, "2026-10-27T09:15:00Z")
        duplicate[3]["id"] = duplicate[2]["id"]
        get = Mock(side_effect=lambda _page, platform: duplicate)
        result = watch.check_route(
            "toonzone", now=TOON_TIME, page_loader=lambda: ACCOUNTS,
            history_reader=get, paused=lambda route: False,
        )
        self.assertEqual(result["counts"]["instagram"], 3)
        self.assertEqual(result["status"], "behind")

    def test_meta_failure_cannot_look_healthy_or_expose_private_urls(self):
        result = watch.check_route(
            "toonzone", now=TOON_TIME, page_loader=lambda: ACCOUNTS,
            history_reader=Mock(side_effect=RuntimeError("TOKEN private-url")),
            paused=lambda route: False,
        )
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("TOKEN", str(result))
        self.assertEqual(result["error_type"], "RuntimeError")

    def test_missing_required_ig_identity_is_unknown(self):
        result = watch.check_route(
            "toonzone", now=TOON_TIME, page_loader=lambda: {
                "pages": [{"page_name": "ToonZone", "page_id": "1"}]
            }, history_reader=reader(4, 4), paused=lambda route: False,
        )
        self.assertEqual(result["status"], "unknown")

    def test_timestamp_from_other_date_never_satisfies_goal(self):
        result = watch.check_route(
            "toonzone", now=TOON_TIME, page_loader=lambda: ACCOUNTS,
            history_reader=reader(4, 4, "2026-10-26T09:10:00Z",
                                  "2026-10-26T09:10:00Z"),
            paused=lambda route: False,
        )
        self.assertEqual(result["counts"], {"facebook": 0, "instagram": 0})
        self.assertEqual(result["status"], "behind")

    def test_config_error_no_notification(self):
        with patch.dict(os.environ, {"TARGET_ROUTE": "unapproved"},
                        clear=False), redirect_stdout(io.StringIO()) as capture, \
             patch.object(watch, "send_ntfy") as ntfy:
            self.assertEqual(watch.main(), 1)
        ntfy.assert_not_called()
        self.assertIn("configuration_error", capture.getvalue())

    def test_healthy_does_not_send_phone_alerts(self):
        with patch.dict(os.environ, {"TARGET_ROUTE": "toonzone",
                                     "GITHUB_STEP_SUMMARY": ""}), \
             patch.object(watch, "check_route", return_value={
                 "route": "toonzone", "status": "healthy", "day": "2026-10-27",
                 "target_per_platform": 4, "counts": {"facebook": 4, "instagram": 4},
             }), patch.object(watch, "send_ntfy") as ntfy, \
             patch.object(watch, "send_telegram") as tg:
            self.assertEqual(watch.main(), 0)
        ntfy.assert_not_called()
        tg.assert_not_called()

    def test_missing_post_sends_alert_without_meta_post(self):
        output = io.StringIO()
        with patch.dict(os.environ, {
            "TARGET_ROUTE": "toonzone", "GITHUB_STEP_SUMMARY": "",
            "NTFY_TOPIC": "private-topic", "NTFY_TOPIC_URL": "",
        }), patch.object(watch, "check_route", return_value={
            "route": "toonzone", "status": "behind", "day": "2026-10-27",
            "target_per_platform": 4,
            "counts": {"facebook": 4, "instagram": 3},
            "missing": {"facebook": 0, "instagram": 1},
        }), patch.object(watch, "send_ntfy", return_value=True) as ntfy, \
             patch.object(watch, "telegram_configured", return_value=True), \
             patch.object(watch, "send_telegram", return_value=True) as tg, \
             redirect_stdout(output):
            self.assertEqual(watch.main(), 1)
        self.assertEqual(ntfy.call_count, 1)
        self.assertEqual(tg.call_count, 1)
        self.assertIn("instagram: 1 eksik", tg.call_args.args[1])
        self.assertNotIn("private-topic", output.getvalue())

    def test_unknown_meta_read_alert_does_not_claim_eight_missing_videos(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"TARGET_ROUTE": "daily_laugh", "GITHUB_STEP_SUMMARY": "",
                                     "NTFY_TOPIC": "", "NTFY_TOPIC_URL": ""}),
            patch.object(watch, "check_route", return_value={
                "route": "daily_laugh", "status": "unknown", "day": "2026-10-30",
                "target_per_platform": 8, "reason": "meta_read_failed"}),
            patch.object(watch, "telegram_configured", return_value=True),
            patch.object(watch, "send_telegram", return_value=True) as tg,
            redirect_stdout(output),
        ):
            self.assertEqual(watch.main(), 1)
        sent = tg.call_args.args[1]
        self.assertIn("Hedefte video eksikliği kanıtlanmadı", sent)
        self.assertIn("META_ACCESS_TOKEN", sent)
        self.assertNotIn("8 eksik", sent)

    def test_safe_page_token_fallback_wired_to_read_and_publish(self):
        from pathlib import Path
        base = Path(__file__).parent / ".github" / "workflows"
        publisher = (base / "public_link_schedule.yml").read_text(encoding="utf-8")
        targets = (base / "tracked_meta_routes.yml").read_text(encoding="utf-8")
        env = "META_AUTH_JSON: " + "${{ secrets.META_AUTH_JSON }}"
        self.assertIn(env, publisher)
        self.assertIn(env, targets)
        self.assertIn('if [ -n "$META_AUTH_JSON" ]; then', publisher)
        self.assertLess(publisher.index("python meta_page_token_health.py"),
                        publisher.index("run: python public_link_runtime.py publish"))
        self.assertIn("python meta_schedule_preflight.py", publisher)
        self.assertLess(publisher.index("python meta_schedule_preflight.py"),
                        publisher.index("pip install gdown==6.4.2"))

    def test_notification_error_redacts_private_provider_detail(self):
        capture = io.StringIO()
        with patch.dict(os.environ, {
            "TARGET_ROUTE": "toonzone", "GITHUB_STEP_SUMMARY": "",
            "NTFY_TOPIC": "private-topic", "NTFY_TOPIC_URL": "",
        }), patch.object(watch, "check_route", return_value={
            "route": "toonzone", "status": "unknown", "day": "2026-10-27",
            "target_per_platform": 4, "reason": "meta_read_failed"
        }), patch.object(watch, "send_ntfy",
                         side_effect=RuntimeError("secret-private-token")), \
             patch.object(watch, "telegram_configured", return_value=False), \
             redirect_stdout(capture):
            self.assertEqual(watch.main(), 1)
        self.assertIn("ntfy_failed", capture.getvalue())
        self.assertNotIn("secret-private-token", capture.getvalue())


if __name__ == "__main__":
    unittest.main()
