"""Telegram post-run reports are read-only, scoped and never fabricate uploads."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_publish_report as report


class TelegramPublishReportTests(unittest.TestCase):
    def test_empty_scheduled_poll_is_silent(self):
        self.assertEqual(
            report.publication_summary({"entries": {}}, "12345"), (None, "nothing_to_report")
        )

    def test_old_completed_posts_not_reported_as_new(self):
        state = {"entries": {"a": {"run_id": "111", "status": "done",
                                    "post_id": "987", "route": "film", "platform": "facebook"}}}
        self.assertEqual(
            report.publication_summary(state, "222"), (None, "nothing_to_report")
        )

    def test_only_confirmed_posts_with_post_ids_count(self):
        state = {"entries": {
            "a": {"run_id": "333", "status": "done", "post_id": "987", "route": "film", "platform": "facebook"},
            "b": {"run_id": "333", "status": "done", "route": "film", "platform": "instagram"},
            "c": {"run_id": "222", "status": "done", "post_id": "888", "route": "film", "platform": "instagram"}
        }}
        message, kind = report.publication_summary(state, "333")
        self.assertEqual(kind, "published")
        self.assertIn("1 gönderi", message)
        self.assertIn("Yeni doğrulanan gönderi: 1", message)
        self.assertNotIn("2 gönderi", message)

    def test_uncertain_posts_do_not_claim_success_and_are_never_retried(self):
        state = {"entries": {
            "a": {"run_id": "333", "status": "uncertain", "route": "toonzone", "platform": "instagram"},
            "b": {"run_id": "333", "status": "intent", "route": "gonle", "platform": "facebook"}
        }}
        message, kind = report.publication_summary(state, "333")
        self.assertEqual(kind, "alert")
        self.assertIn("Belirsiz yükleme: 2", message)
        self.assertNotIn("Yeni doğrulanan gönderi", message)

    def test_failed_ig_http400_reports_safe_reason_without_remote_message(self):
        state = {"entries": {"ig": {
            "run_id": "333", "status": "uncertain", "route": "film", "platform": "instagram",
            "failure": {"reason": "invalid_media_or_graph_request",
                        "message": "top-secret-token-should-not-leak"}
        }}}
        msg, kind = report.publication_summary(state, "333", publish_outcome="failure")
        self.assertEqual(kind, "alert")
        self.assertIn("invalid_media_or_graph_request: 1", msg)
        self.assertNotIn("top-secret-token-should-not-leak", msg)

    def test_failed_publisher_alerts_without_previous_state(self):
        message, kind = report.publication_summary(
            {"entries": {}}, "333", plan_outcome="failure", publish_outcome="skipped"
        )
        self.assertEqual(kind, "alert")
        self.assertIn("başarısız", message)

    def test_prepublication_safety_failure_notifies_without_claiming_upload(self):
        msg, kind = report.publication_summary(
            {"entries": {}}, "333", verify_outcome="failure",
            plan_outcome="skipped", publish_outcome="skipped",
        )
        self.assertEqual(kind, "alert")
        self.assertIn("başarısız", msg)
        self.assertNotIn("Yeni doğrulanan", msg)

    def test_unsuccessful_post_not_claimed_published(self):
        state = {"entries": {"a": {"run_id": "333", "status": "ready", "route": "film"}}}
        self.assertEqual(report.publication_summary(state, "333"), (None, "nothing_to_report"))

    def test_invalid_run_id_never_uses_other_runs(self):
        message, kind = report.publication_summary({"entries": {}}, "../../token")
        self.assertIsNone(message)
        self.assertEqual(kind, "invalid_run_id")

    def test_main_sends_no_message_for_empty_poll(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(report, "STATE_PATH", Path(d) / "missing.json"), \
                patch.object(report, "telegram_configured", return_value=True), \
                patch.object(report, "send_telegram") as send, \
                patch.dict(os.environ, {"GITHUB_RUN_ID": "333", "PLAN_STEP_OUTCOME": "success",
                                        "PUBLISH_STEP_OUTCOME": "success"}):
            self.assertEqual(report.main(), 0)
            send.assert_not_called()

    def test_main_sends_success_message_for_real_post(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "state.json"
            f.write_text(json.dumps({"entries": {"a": {"run_id": "333", "status": "done",
                            "post_id": "123", "route": "film", "platform": "instagram"}}}))
            with patch.object(report, "STATE_PATH", f), \
                    patch.object(report, "telegram_configured", return_value=True), \
                    patch.object(report, "send_telegram", return_value={"server_ack": True}) as send, \
                    patch.dict(os.environ, {"GITHUB_RUN_ID": "333", "PLAN_STEP_OUTCOME": "success",
                                            "PUBLISH_STEP_OUTCOME": "success"}):
                self.assertEqual(report.main(), 0)
                self.assertIn("Yeni doğrulanan gönderi: 1", send.call_args.args[1])

    def test_unconfigured_credentials_never_interrupt_publisher(self):
        with patch.object(report, "telegram_configured", return_value=False), \
                patch.object(report, "send_telegram") as send:
            self.assertEqual(report.main(), 0)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
