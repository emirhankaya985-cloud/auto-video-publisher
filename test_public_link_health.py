"""Credential-free tests for the Meta-only production health watchdog."""
import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import public_link_health as health

NOW = datetime(2026, 10, 24, 8, 40, tzinfo=timezone.utc)


def run(time="2026-10-24T08:07:00Z", conclusion="success",
        event="schedule", branch="main", path=".github/workflows/public_link_schedule.yml"):
    return {"created_at": time, "conclusion": conclusion, "status": "completed",
            "event": event, "head_branch": branch, "path": path}


def fake_get(rows, *, status=200):
    response = Mock(status_code=status)
    response.json.return_value = {"workflow_runs": rows}
    return Mock(return_value=response)


class PublicLinkHealthTests(unittest.TestCase):
    def test_one_recent_success_is_healthy(self):
        get = fake_get([run()])
        result = health.check_publisher(now=NOW, token="test-token", get=get)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(get.call_args.kwargs["params"]["event"], "schedule")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_consecutive_failures_trigger_alert(self):
        result = health.check_publisher(now=NOW, token="test", get=fake_get([
            run("2026-10-24T08:37:00Z", "failure"),
            run("2026-10-24T08:07:00Z", "failure"),
            run("2026-10-24T07:37:00Z", "success")]))
        self.assertEqual(result["status"], "unhealthy")
        self.assertEqual(result["reason"], "consecutive_failures")

    def test_single_failure_after_success_is_not_consecutive(self):
        result = health.check_publisher(now=NOW, token="test", get=fake_get([
            run("2026-10-24T08:37:00Z", "failure"),
            run("2026-10-24T08:07:00Z", "success")]))
        self.assertEqual(result["status"], "healthy")

    def test_no_recent_success_triggers_alert(self):
        result = health.check_publisher(now=NOW, token="test", get=fake_get([
            run("2026-10-24T08:07:00Z", "failure")]))
        self.assertEqual(result["reason"], "no_recent_success")

    def test_wrong_branch_manual_or_old_run_cannot_mask_failure(self):
        get = fake_get([
            run("2026-10-24T08:07:00Z", event="workflow_dispatch"),
            run("2026-10-24T08:07:00Z", branch="test"),
            run("2026-10-24T08:07:00Z", path=".github/workflows/migration_ci.yml"),
            run("2026-10-24T04:00:00Z")])
        result = health.check_publisher(now=NOW, token="test", get=get)
        self.assertEqual(result["reason"], "no_recent_scheduled_runs")

    def test_empty_or_invalid_api_is_not_green(self):
        self.assertEqual(health.check_publisher(
            now=NOW, token="test", get=fake_get([]))["status"], "unhealthy")
        self.assertEqual(health.check_publisher(
            now=NOW, token="test", get=fake_get([], status=403))["status"], "unknown")

    def test_missing_github_token_never_calls_api(self):
        get = Mock()
        result = health.check_publisher(now=NOW, token="", get=get)
        self.assertEqual(result["reason"], "github_token_missing")
        get.assert_not_called()

    def test_green_main_never_sends_alert(self):
        with patch.object(health, "check_publisher", return_value={"status": "healthy"}), \
                patch.object(health, "send_ntfy") as send, \
                patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(health.main(), 0)
        send.assert_not_called()

    def test_failed_alert_redacts_private_topic(self):
        output = io.StringIO()
        with patch.object(health, "check_publisher",
                          return_value={"status": "unhealthy", "reason": "consecutive_failures"}), \
                patch.object(health, "send_ntfy", side_effect=RuntimeError("my-secret-topic")), \
                patch.dict(os.environ, {"NTFY_TOPIC": "my-secret-topic", "NTFY_TOPIC_URL": "",
                                        "GITHUB_STEP_SUMMARY": ""}), redirect_stdout(output):
            self.assertEqual(health.main(), 1)
        self.assertNotIn("my-secret-topic", output.getvalue())


    def test_unhealthy_alerts_telegram_without_ntfy(self):
        output = io.StringIO()
        with patch.object(health, "check_publisher",
                          return_value={"status": "unhealthy", "reason": "no_recent_success"}), \
                patch.object(health, "telegram_configured", return_value=True), \
                patch.object(health, "send_telegram",
                             return_value={"server_ack": True}) as telegram, \
                patch.object(health, "send_ntfy") as ntfy, \
                patch.dict(os.environ, {"NTFY_TOPIC": "", "NTFY_TOPIC_URL": "",
                                        "GITHUB_STEP_SUMMARY": ""}), redirect_stdout(output):
            self.assertEqual(health.main(), 1)
        ntfy.assert_not_called()
        telegram.assert_called_once()
        self.assertIn("telegram_server_ack", output.getvalue())

    def test_telegram_failure_never_logs_token(self):
        output = io.StringIO()
        with patch.object(health, "check_publisher",
                          return_value={"status": "unknown", "reason": "github_api_unavailable"}), \
                patch.object(health, "telegram_configured", return_value=True), \
                patch.object(health, "send_telegram",
                             side_effect=RuntimeError("BOT-TOKEN-SHOULD-NOT-LEAK")), \
                patch.dict(os.environ, {"NTFY_TOPIC": "", "NTFY_TOPIC_URL": "",
                                        "GITHUB_STEP_SUMMARY": ""}), redirect_stdout(output):
            self.assertEqual(health.main(), 1)
        self.assertNotIn("BOT-TOKEN-SHOULD-NOT-LEAK", output.getvalue())
        self.assertIn("telegram_failed", output.getvalue())


if __name__ == "__main__":
    unittest.main()
