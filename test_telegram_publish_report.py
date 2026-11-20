"""Telegram post-run reports are read-only, scoped and never fabricate uploads."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, Mock

import telegram_publish_report as report

# Intentional synthetic failures in unittest must NEVER leak into the live
# GitHub run's incident journal or trigger false Telegram/ntfy alerts.
report.record_error = Mock()


class TelegramPublishReportTests(unittest.TestCase):
    def test_fresh_stock_context_is_candidate_only_and_route_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "content-stock.json"
            now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
            path.write_text(json.dumps({"measured_at": now.isoformat(), "accounts": [
                {"route": "daily_laugh", "platform": "facebook", "remaining": 0, "held": 9},
                {"route": "penguen", "platform": "instagram", "remaining": 20, "held": 1},
            ]}), encoding="utf-8")
            lines = report.stock_context_for_routes({"daily_laugh"}, path=path, now=now)
            self.assertEqual(len(lines), 1)
            self.assertIn("0 aday, 9 bekleyen", lines[0])
            self.assertIn("kontrolünden geçmelidir", lines[0])
            self.assertNotIn("Penguen", lines[0])

    def test_stale_or_bad_stock_cannot_appear_in_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "content-stock.json"
            now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
            path.write_text(json.dumps({"measured_at": (now - timedelta(hours=3)).isoformat(),
                                         "accounts": [{"route": "daily_laugh", "platform": "facebook",
                                                       "remaining": 0, "held": 9}]}), encoding="utf-8")
            self.assertEqual(report.stock_context_for_routes({"daily_laugh"}, path=path, now=now), [])
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(report.stock_context_for_routes({"daily_laugh"}, path=path, now=now), [])

    def test_queue_deficit_is_actionable_even_if_repreparation_is_safe(self):
        event = {"run_id": "333", "route": "penguen", "platform": "unknown",
                 "stage": "planning_queue", "reason": "no_eligible_content",
                 "retry_policy": "pre_upload_only"}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(report, "STATE_PATH", Path(folder) / "missing.json"), \
                patch.object(report, "read_errors", return_value=[event]), \
                patch.object(report, "telegram_configured", return_value=True), \
                patch.object(report, "send_telegram", return_value={"server_ack": True}) as send, \
                patch.dict(os.environ, {"GITHUB_RUN_ID": "333", "PLAN_STEP_OUTCOME": "success",
                    "PUBLISH_STEP_OUTCOME": "success", "PUBLISH_ALERTS_ONLY": "true", "PUBLISH_ALERT_MODE": ""}):
            self.assertEqual(report.main(), 0)
        send.assert_called_once()
        self.assertIn("no_eligible_content", send.call_args.args[1])

    def test_daily_account_deficit_restores_scoped_history_and_deduplicates(self):
        history = {"schema": 1, "records": {}}
        events = [{"route": "penguen", "reason": "no_eligible_content", "platform": "unknown"},
                  {"route": "penguen", "reason": "credentials_or_permissions", "platform": "instagram"}]
        first = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
        planned = []
        def capture(path, value):
            if path == report.alert_history.PREPARED:
                planned.append(value["messages"])
        with patch.object(report.alert_history, "restore", return_value=history) as restore, \
                patch.object(report.alert_history, "save", side_effect=capture), \
                patch.object(report.alert_history, "now_utc", side_effect=[first, first + timedelta(hours=1), first + timedelta(days=1)]), \
                patch.dict(os.environ, {"PUBLISH_ACCOUNT_SCOPE": "penguen", "GITHUB_OUTPUT": ""}):
            for run_id in ("333", "334", "335"):
                report._prepare_durable([("🚨 Müdahale gerektiren Meta hataları", "blocked")], [], events,
                    {"entries": {}}, run_id, telegram_on=True, ntfy_on=False, base_failures=0, category="nothing_to_report")
        self.assertEqual([len(messages) for messages in planned], [1, 0, 1])
        restore.assert_called_with(names=("link-alert-intent-penguen", "link-alert-result-penguen"))
        self.assertEqual(len(planned[0][0]["keys"]), 2)  # Auth incident is preserved beside the queue deficit.

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

    def test_known_ig_holds_are_informational_not_fake_new_urgent_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({"entries": {"old": {
                "run_id": "111", "route": "film", "platform": "instagram",
                "status": "uncertain", "file": "Part16.mp4"
            }}}), encoding="utf-8")
            events = [{"run_id": "333", "stage": "previous_intent_hold",
                       "reason": "unreconciled_previous_intent", "route": route,
                       "platform": "instagram", "video": file}
                      for route, file in [("film", "Part16.mp4"),
                                          ("toonzone", "Part3.mp4")]]
            with patch.object(report, "STATE_PATH", state_path), patch.object(
                report, "read_errors", return_value=events
            ), patch.object(report, "telegram_configured", return_value=True), patch.object(
                report, "send_telegram", return_value={"server_ack": True}
            ) as telegram, patch.object(
                report, "send_ntfy", return_value={"server_ack": True}
            ) as ntfy, patch.dict(os.environ, {
                "GITHUB_RUN_ID": "333", "VERIFY_STEP_OUTCOME": "success",
                "PLAN_STEP_OUTCOME": "success", "PUBLISH_STEP_OUTCOME": "success",
                "NTFY_TOPIC": "test-ntfy", "REQUIRE_DUAL_NOTIFICATIONS": "true",
            }):
                self.assertEqual(report.main(), 0)
            telegram.assert_called_once()
            self.assertIn("Mevcut Instagram engelleri", telegram.call_args.args[0])
            self.assertIn("yeni Meta POST hatası yok", telegram.call_args.args[1])
            self.assertEqual(ntfy.call_args.kwargs["priority"], 2)
            self.assertEqual(ntfy.call_args.kwargs["tags"], ["information_source"])

    def test_new_failed_ig_post_remains_urgent_even_if_old_hold_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({"entries": {
                "ig": {"run_id": "333", "status": "uncertain",
                       "route": "film", "platform": "instagram"}
            }}), encoding="utf-8")
            events = [{"run_id": "333", "stage": "instagram_publish",
                       "reason": "invalid_media_or_graph_request", "route": "film",
                       "platform": "instagram", "video": "Part16.mp4"}]
            with patch.object(report, "STATE_PATH", state_path), patch.object(
                report, "read_errors", return_value=events
            ), patch.object(report, "telegram_configured", return_value=True), patch.object(
                report, "send_telegram", return_value={"server_ack": True}
            ) as telegram, patch.object(
                report, "send_ntfy", return_value={"server_ack": True}
            ) as ntfy, patch.dict(os.environ, {
                "GITHUB_RUN_ID": "333", "VERIFY_STEP_OUTCOME": "success",
                "PLAN_STEP_OUTCOME": "success", "PUBLISH_STEP_OUTCOME": "failure",
                "NTFY_TOPIC": "test-ntfy", "REQUIRE_DUAL_NOTIFICATIONS": "true",
            }):
                self.assertEqual(report.main(), 0)
            self.assertEqual(telegram.call_count, 1)
            self.assertTrue(telegram.call_args.args[0].startswith("🚨"))
            self.assertEqual(ntfy.call_args.kwargs["priority"], 4)
            self.assertIn("warning", ntfy.call_args.kwargs["tags"])

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

    def test_owner_quiet_mode_keeps_error_records_and_sends_only_confirmed_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({"entries": {
                "a": {"run_id": "333", "route": "tarladaki", "platform": "instagram",
                      "status": "done", "post_id": "verified-ig", "file": "306.mp4"},
                "b": {"run_id": "333", "route": "daily_laugh", "platform": "facebook",
                      "status": "held", "file": "195.mp4"},
            }}), encoding="utf-8")
            events = [{"run_id": "333", "stage": "source_video",
                       "reason": "visual_duplicate_review", "route": "daily_laugh",
                       "platform": "facebook", "video": "195.mp4"}]
            with patch.object(report, "STATE_PATH", state_path), patch.object(
                report, "read_errors", return_value=events
            ), patch.object(report, "telegram_configured", return_value=True), patch.object(
                report, "send_telegram", return_value={"server_ack": True}
            ) as telegram, patch.object(
                report, "send_ntfy", return_value={"server_ack": True}
            ) as ntfy, patch.dict(os.environ, {
                "GITHUB_RUN_ID": "333", "VERIFY_STEP_OUTCOME": "success",
                "PLAN_STEP_OUTCOME": "success", "PUBLISH_STEP_OUTCOME": "failure",
                "NTFY_TOPIC": "test-topic", "REQUIRE_DUAL_NOTIFICATIONS": "true",
                "PUBLISH_QUIET_FAILURES": "true",
            }, clear=True):
                self.assertEqual(report.main(), 0)
            telegram.assert_called_once()
            ntfy.assert_called_once()
            self.assertIn("video yayınlandı", telegram.call_args.args[0])
            self.assertNotIn("uyarısı", telegram.call_args.args[0].lower())

    def test_owner_quiet_mode_does_not_send_error_only_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
            events = [{"run_id": "333", "stage": "workflow_publish",
                       "reason": "workflow_step_failed"}]
            with patch.object(report, "STATE_PATH", state_path), patch.object(
                report, "read_errors", return_value=events
            ), patch.object(report, "telegram_configured", return_value=True), patch.object(
                report, "send_telegram"
            ) as telegram, patch.object(
                report, "send_ntfy"
            ) as ntfy, patch.dict(os.environ, {
                "GITHUB_RUN_ID": "333", "VERIFY_STEP_OUTCOME": "success",
                "PLAN_STEP_OUTCOME": "success", "PUBLISH_STEP_OUTCOME": "failure",
                "NTFY_TOPIC": "test-topic", "REQUIRE_DUAL_NOTIFICATIONS": "true",
                "PUBLISH_QUIET_FAILURES": "true",
            }, clear=True):
                self.assertEqual(report.main(), 0)
            telegram.assert_not_called()
            ntfy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
