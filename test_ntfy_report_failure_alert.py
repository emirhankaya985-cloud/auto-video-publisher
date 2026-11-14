import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import ntfy_report_failure_alert as alert


class FailureAlertTests(unittest.TestCase):
    def setUp(self):
        self.dedup = patch("ntfy_report_failure_alert.should_send", return_value=True)
        self.dedup.start()
        self.addCleanup(self.dedup.stop)
        self.result = patch("ntfy_report_failure_alert.mark_result")
        self.result.start()
        self.addCleanup(self.result.stop)

    def test_missing_secret_skips_without_send(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch(
            "ntfy_report_failure_alert.send_ntfy"
        ) as send, redirect_stdout(output):
            result = alert.notify_failure()
        self.assertEqual(result, 0)
        self.assertIn("notification_secret_missing", output.getvalue())
        send.assert_not_called()

    def test_alert_requires_server_ack_and_sanitizes_secret(self):
        output = io.StringIO()
        env = {
            "NTFY_TOPIC_URL": "https://ntfy.sh/private-notification",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "emirhankaya-AFK/auto-video-publisher",
            "GITHUB_RUN_ID": "1234",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "ntfy_report_failure_alert.send_ntfy",
            return_value={"http_status": 200, "server_ack": True}
        ) as sender, redirect_stdout(output):
            result = alert.notify_failure()
        self.assertEqual(result, 0)
        self.assertEqual(sender.call_count, 1)
        self.assertTrue(sender.call_args.kwargs["require_ack"])
        self.assertEqual(sender.call_args.kwargs["priority"], 4)
        self.assertEqual(sender.call_args.kwargs["click"],
                         "https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/1234")
        self.assertIn("server_acknowledged", output.getvalue())
        self.assertNotIn("private-notification", output.getvalue())
        self.result.return_value.assert_called_once()

    def test_untrusted_actions_url_cannot_become_click_target(self):
        env = {
            "NTFY_TOPIC": "topic",
            "GITHUB_SERVER_URL": "https://evil.example",
            "GITHUB_REPOSITORY": "attacker/repository",
            "GITHUB_RUN_ID": "1234",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "ntfy_report_failure_alert.send_ntfy",
            return_value={"http_status": 200, "server_ack": True}
        ) as sender, redirect_stdout(io.StringIO()):
            self.assertEqual(alert.notify_failure(), 0)
        self.assertIsNone(sender.call_args.kwargs["click"])

    def test_delivery_failure_is_recorded_and_retryable(self):
        self.dedup.return_value = True
        output = io.StringIO()
        with patch.dict(os.environ, {"NTFY_TOPIC": "private-topic"}, clear=True), patch(
            "ntfy_report_failure_alert.send_ntfy",
            side_effect=RuntimeError("https://ntfy.sh/private-topic")
        ) as sender, redirect_stdout(output):
            result = alert.notify_failure()
        self.assertEqual(result, 1)
        self.assertEqual(sender.call_count, 1)
        self.assertNotIn("private-topic", output.getvalue())
        self.assertIn("failure_alert_not_delivered", output.getvalue())
        self.result.return_value.assert_called_once_with(
            "||🚨 Gün sonu raporu başarısız", False, "notification_delivery_failed"
        )

    def test_quiet_mode_does_not_suppress_critical_failure(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"QUIET_FAILURE_NOTIFICATIONS": "true",
                                    "NTFY_TOPIC": "private-topic"}, clear=True), patch(
            "ntfy_report_failure_alert.send_ntfy",
            return_value={"http_status": 200, "server_ack": True}
        ) as ntfy, redirect_stdout(output):
            self.assertEqual(alert.notify_failure(), 0)
        ntfy.assert_called_once()
        self.assertIn("server_acknowledged", output.getvalue())

    def test_existing_deduplication_suppresses_resend(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"NTFY_TOPIC": "topic"}, clear=True), patch(
            "ntfy_report_failure_alert.should_send", return_value=False
        ), patch("ntfy_report_failure_alert.send_ntfy") as sender, redirect_stdout(output):
            self.assertEqual(alert.notify_failure(), 0)
        sender.assert_not_called()
        self.assertIn("duplicate_suppressed", output.getvalue())


if __name__ == "__main__":
    unittest.main()
