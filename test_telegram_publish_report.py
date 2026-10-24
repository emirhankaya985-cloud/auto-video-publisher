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
                self.assertIn("🎬 Film Mağarası", send.call_args.args[1])
                self.assertIn("Instagram", send.call_args.args[1])
                self.assertIn("Gönderi ID: 123", send.call_args.args[1])

    def test_each_confirmed_platform_post_sends_separate_telegram_and_ntfy(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            state_file.write_text(json.dumps({"entries": {
                "fb": {"run_id": "333", "route": "penguen", "platform": "facebook",
                       "status": "done", "post_id": "fb-101", "file": "101.mp4"},
                "ig": {"run_id": "333", "route": "penguen", "platform": "instagram",
                       "status": "done", "post_id": "ig-101", "file": "101.mp4"},
                "other": {"run_id": "332", "route": "gonle", "platform": "instagram",
                          "status": "done", "post_id": "old-id", "file": "103.mp4"},
            }}, ensure_ascii=False))
            with patch.object(report, "STATE_PATH", state_file), \
                    patch.object(report, "telegram_configured", return_value=True), \
                    patch.object(report, "send_telegram", return_value={"server_ack": True}) as telegram, \
                    patch.object(report, "send_ntfy", return_value={"server_ack": True}) as ntfy, \
                    patch.dict(os.environ, {"GITHUB_RUN_ID": "333", "PLAN_STEP_OUTCOME": "success",
                                            "PUBLISH_STEP_OUTCOME": "success",
                                            "NTFY_TOPIC": "mock-topic", "NTFY_TOPIC_URL": ""}):
                self.assertEqual(report.main(), 0)
            self.assertEqual(telegram.call_count, 2)
            self.assertEqual(ntfy.call_count, 2)
            bodies = [call.args[1] for call in telegram.call_args_list]
            self.assertTrue(any("Facebook" in body and "fb-101" in body for body in bodies))
            self.assertTrue(any("Instagram" in body and "ig-101" in body for body in bodies))
            self.assertTrue(all("old-id" not in body for body in bodies))
            self.assertTrue(all(call.kwargs["require_ack"] for call in ntfy.call_args_list))

    def test_notification_transport_failure_does_not_retry_meta_or_block_other_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            state_file.write_text(json.dumps({"entries": {"ig": {
                "run_id": "333", "route": "toonzone", "platform": "instagram",
                "status": "done", "post_id": "verified-ig", "file": "S01E01_The_Power_Part1.mp4"
            }}}))
            with patch.object(report, "STATE_PATH", state_file), \
                    patch.object(report, "telegram_configured", return_value=True), \
                    patch.object(report, "send_telegram",
                                 side_effect=RuntimeError("secret-provider-response")), \
                    patch.object(report, "send_ntfy", return_value={"server_ack": True}) as ntfy, \
                    patch.dict(os.environ, {"GITHUB_RUN_ID": "333", "PLAN_STEP_OUTCOME": "success",
                                            "PUBLISH_STEP_OUTCOME": "success",
                                            "NTFY_TOPIC_URL": "", "NTFY_TOPIC": "mock-topic"}):
                self.assertEqual(report.main(), 1)
            ntfy.assert_called_once()

    def test_ntfy_only_works_without_telegram_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            state_file.write_text(json.dumps({"entries": {"ig": {
                "run_id": "333", "route": "film", "platform": "instagram",
                "status": "done", "post_id": "verified-ig", "file": "film.mp4"
            }}}))
            with patch.object(report, "STATE_PATH", state_file), \
                    patch.object(report, "telegram_configured", return_value=False), \
                    patch.object(report, "send_telegram") as telegram, \
                    patch.object(report, "send_ntfy", return_value={"server_ack": True}) as ntfy, \
                    patch.dict(os.environ, {"GITHUB_RUN_ID": "333", "PLAN_STEP_OUTCOME": "success",
                                            "PUBLISH_STEP_OUTCOME": "success",
                                            "NTFY_TOPIC_URL": "", "NTFY_TOPIC": "mock-topic"}):
                self.assertEqual(report.main(), 0)
            telegram.assert_not_called()
            ntfy.assert_called_once()

    def test_per_post_notification_requires_actual_post_id_and_run_id(self):
        state = {"entries": {
            "a": {"run_id": "333", "route": "film", "platform": "instagram", "status": "done"},
            "b": {"run_id": "332", "route": "film", "platform": "instagram", "status": "done", "post_id": "old"},
            "c": {"run_id": "333", "route": "film", "platform": "facebook", "status": "done", "post_id": "valid"},
            "d": {"run_id": "333", "route": "film", "platform": "instagram", "status": "uncertain", "post_id": "wrong"},
        }}
        posts = report.confirmed_posts(state, "333")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["post_id"], "valid")

    def test_unconfigured_credentials_never_interrupt_publisher(self):
        with patch.object(report, "telegram_configured", return_value=False), \
                patch.object(report, "send_telegram") as send:
            self.assertEqual(report.main(), 0)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
