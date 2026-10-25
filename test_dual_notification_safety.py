"""No-network regression for required dual-channel post notifications."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_publish_report as notifier


class DualNotificationSafetyTests(unittest.TestCase):
    def test_missing_telegram_reports_failure_but_still_sends_ntfy(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"entries": {"p": {
                "run_id": "12345", "route": "film", "platform": "instagram",
                "status": "done", "post_id": "ig-123", "file": "clip.mp4"
            }}}), encoding="utf-8")
            with patch.object(notifier, "STATE_PATH", state), patch.object(
                notifier, "telegram_configured", return_value=False
            ), patch.object(notifier, "send_telegram") as telegram, patch.object(
                notifier, "send_ntfy", return_value={"server_ack": True}
            ) as ntfy, patch.object(notifier, "record_error") as errors, patch.object(
                notifier, "read_errors", return_value=[]
            ), patch.dict(os.environ, {
                "GITHUB_RUN_ID": "12345", "PLAN_STEP_OUTCOME": "success",
                "PUBLISH_STEP_OUTCOME": "success", "VERIFY_STEP_OUTCOME": "success",
                "REQUIRE_DUAL_NOTIFICATIONS": "true", "NTFY_TOPIC": "mock-topic",
                "NTFY_TOPIC_URL": ""
            }):
                self.assertEqual(notifier.main(), 1)
            telegram.assert_not_called()
            self.assertEqual(ntfy.call_count, 2)  # post + missing-channel alert
            self.assertTrue(any(c.args[0] == "telegram_notification"
                                for c in errors.call_args_list))

    def test_no_configured_channel_cannot_claim_delivery_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"entries": {"p": {
                "run_id": "12345", "route": "toonzone", "platform": "facebook",
                "status": "done", "post_id": "fb-123", "file": "clip.mp4"
            }}}), encoding="utf-8")
            with patch.object(notifier, "STATE_PATH", state), patch.object(
                notifier, "telegram_configured", return_value=False
            ), patch.object(notifier, "send_telegram") as telegram, patch.object(
                notifier, "send_ntfy"
            ) as ntfy, patch.object(notifier, "record_error") as errors, patch.object(
                notifier, "read_errors", return_value=[]
            ), patch.dict(os.environ, {
                "GITHUB_RUN_ID": "12345", "PLAN_STEP_OUTCOME": "success",
                "PUBLISH_STEP_OUTCOME": "success", "VERIFY_STEP_OUTCOME": "success",
                "REQUIRE_DUAL_NOTIFICATIONS": "true", "NTFY_TOPIC": "",
                "NTFY_TOPIC_URL": ""
            }):
                self.assertEqual(notifier.main(), 1)
            telegram.assert_not_called()
            ntfy.assert_not_called()
            self.assertEqual(errors.call_count, 2)

    def test_no_post_does_not_generate_false_phone_alarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-created.json"
            with patch.object(notifier, "STATE_PATH", missing), patch.object(
                notifier, "telegram_configured", return_value=False
            ), patch.object(notifier, "record_error") as errors, patch.object(
                notifier, "read_errors", return_value=[]
            ), patch.dict(os.environ, {
                "GITHUB_RUN_ID": "12345", "PLAN_STEP_OUTCOME": "success",
                "PUBLISH_STEP_OUTCOME": "success", "VERIFY_STEP_OUTCOME": "success",
                "REQUIRE_DUAL_NOTIFICATIONS": "true", "NTFY_TOPIC": "",
                "NTFY_TOPIC_URL": ""
            }):
                self.assertEqual(notifier.main(), 0)
            errors.assert_not_called()


if __name__ == "__main__":
    unittest.main()
