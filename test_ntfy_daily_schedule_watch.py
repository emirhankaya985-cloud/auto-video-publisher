import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import ntfy_daily_schedule_watch as watch

NOW = datetime(2026, 10, 21, 4, 10, tzinfo=timezone.utc)


def mock_response(runs, *, status=200):
    response = Mock(status_code=status)
    response.json.return_value = {"workflow_runs": runs}
    return response


def scheduled(created_at, status="completed", conclusion="success", event="schedule",
              branch="master"):
    return {"created_at": created_at, "status": status, "conclusion": conclusion,
            "event": event, "head_branch": branch}


class MissingDailyReportTests(unittest.TestCase):
    def test_previous_day_window_respects_turkey_local_report_date(self):
        first, last = watch.expected_window(NOW)
        self.assertEqual(first.isoformat(), "2026-10-20T20:54:00+00:00")
        self.assertEqual(last.isoformat(), "2026-10-20T22:59:00+00:00")

    def test_successful_automatic_report_is_healthy(self):
        response = mock_response([
            scheduled("2026-10-20T20:59:35Z"),
            scheduled("2026-10-20T21:03:00Z", event="workflow_dispatch"),
        ])
        get = Mock(return_value=response)
        actual = watch.check_daily_run(now=NOW, token="test-token", get=get)
        self.assertEqual(actual["status"], "healthy")
        self.assertFalse(any("test-token" in str(v) for v in actual.values()))
        self.assertEqual(get.call_args.kwargs["params"]["event"], "schedule")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_manual_run_cannot_mask_missed_schedule(self):
        response = mock_response([
            scheduled("2026-10-20T20:59:35Z", event="workflow_dispatch"),
        ])
        result = watch.check_daily_run(now=NOW, token="test-token",
                                       get=Mock(return_value=response))
        self.assertEqual(result["status"], "missing_or_failed")

    def test_failed_or_active_run_does_not_count_as_success(self):
        response = mock_response([
            scheduled("2026-10-20T20:59:35Z", status="completed", conclusion="failure"),
            scheduled("2026-10-20T21:10:35Z", status="in_progress", conclusion=None),
        ])
        actual = watch.check_daily_run(now=NOW, token="test-token",
                                       get=Mock(return_value=response))
        self.assertEqual(actual["status"], "missing_or_failed")
        self.assertEqual(actual["matched_runs"], 2)

    def test_wrong_day_branch_or_late_run_cannot_mask_missing_schedule(self):
        response = mock_response([
            scheduled("2026-10-20T20:59:35Z", branch="test-branch"),
            scheduled("2026-10-19T20:59:35Z"),
            scheduled("2026-10-20T23:59:35Z"),
        ])
        result = watch.check_daily_run(now=NOW, token="test-token",
                                       get=Mock(return_value=response))
        self.assertEqual(result["status"], "missing_or_failed")

    def test_api_error_or_malformed_response_fails_closed(self):
        bad = Mock(status_code=401)
        result = watch.check_daily_run(now=NOW, token="test-token",
                                       get=Mock(return_value=bad))
        self.assertEqual(result["status"], "audit_unavailable")
        self.assertEqual(result["http_status"], 401)
        other = mock_response(["malformed-run"])
        result = watch.check_daily_run(now=NOW, token="test-token",
                                       get=Mock(return_value=other))
        self.assertEqual(result["status"], "audit_unavailable")

    def test_missing_token_does_not_call_api(self):
        get = Mock()
        result = watch.check_daily_run(now=NOW, token="", get=get)
        self.assertEqual(result["reason"], "github_token_missing")
        get.assert_not_called()

    def test_main_healthy_does_not_send_any_notification(self):
        output = io.StringIO()
        with patch("ntfy_daily_schedule_watch.check_daily_run",
                   return_value={"status": "healthy"}), patch(
            "ntfy_daily_schedule_watch.send_ntfy"
        ) as send, redirect_stdout(output):
            self.assertEqual(watch.main(), 0)
        send.assert_not_called()
        self.assertIn('"alert_sent": false', output.getvalue())

    def test_main_missing_run_sends_one_sanitized_alert(self):
        output = io.StringIO()
        with patch("ntfy_daily_schedule_watch.check_daily_run",
                   return_value={"status": "missing_or_failed"}), patch(
            "ntfy_daily_schedule_watch.send_ntfy",
            return_value={"http_status": 200, "server_ack": True}
        ) as sender, redirect_stdout(output):
            self.assertEqual(watch.main(), 1)
        self.assertEqual(sender.call_count, 1)
        self.assertTrue(sender.call_args.kwargs["require_ack"])
        self.assertEqual(sender.call_args.kwargs["priority"], 4)
        self.assertIn('"phone_delivery_verified": false', output.getvalue())

    def test_main_api_inaccessible_alerts_without_claiming_missed_run(self):
        output = io.StringIO()
        with patch("ntfy_daily_schedule_watch.check_daily_run",
                   return_value={"status": "audit_unavailable"}), patch(
            "ntfy_daily_schedule_watch.send_ntfy",
            return_value={"http_status": 200, "server_ack": True}
        ) as sender, redirect_stdout(output):
            self.assertEqual(watch.main(), 1)
        self.assertIn("durumuna erişilemedi", sender.call_args.args[1])
        self.assertNotIn("başarılı otomatik", sender.call_args.args[1])

    def test_failed_ntfy_attempt_does_not_echo_secret_credentials(self):
        output = io.StringIO()
        with patch("ntfy_daily_schedule_watch.check_daily_run",
                   return_value={"status": "missing_or_failed"}), patch(
            "ntfy_daily_schedule_watch.send_ntfy",
            side_effect=RuntimeError("private-topic-url")
        ) as sender, redirect_stdout(output):
            self.assertEqual(watch.main(), 1)
        self.assertEqual(sender.call_count, 1)
        self.assertNotIn("private-topic-url", output.getvalue())


if __name__ == "__main__":
    unittest.main()
