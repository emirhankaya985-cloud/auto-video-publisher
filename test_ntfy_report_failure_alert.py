import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import ntfy_report_failure_alert as alert


class FailureAlertTests(unittest.TestCase):
    def test_missing_secret_skips_without_send(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch(
            "ntfy_report_failure_alert.send_ntfy"
        ) as send, redirect_stdout(output):
            result = alert.notify_failure()
        self.assertEqual(result, 0)
        self.assertIn("ntfy_secret_missing", output.getvalue())
        send.assert_not_called()

    def test_alert_only_once_and_requires_server_ack(self):
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

    def test_api_exception_never_prints_secret_or_retries(self):
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


if __name__ == "__main__":
    unittest.main()
