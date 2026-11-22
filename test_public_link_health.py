"""Credential-free tests for the Meta-only production health watchdog."""
import io
import os
from pathlib import Path
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
    def setUp(self):
        # These tests isolate scheduler checks; receipt parsing has separate tests.
        patcher = patch.object(health, "check_publication_receipts", return_value={"status": "healthy"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_recent_success_is_healthy(self):
        get = fake_get([run()])
        result = health.check_publisher(now=NOW, token="test-token", get=get)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(get.call_args.kwargs["params"]["event"], "schedule")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_failed_matrix_runs_do_not_hide_healthy_account_receipts(self):
        runs = [
            dict(run("2026-10-24T08:37:00Z", "failure"), id=101),
            dict(run("2026-10-24T08:07:00Z", "failure"), id=102),
            dict(run("2026-10-24T07:37:00Z", "success"), id=103),
        ]
        result = health.check_publisher(now=NOW, token="test", get=fake_get(runs))
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["recent_runs"], 3)
        self.assertEqual(result["failed_run_ids"], ["101", "102"])

    def test_single_failure_after_success_is_not_consecutive(self):
        result = health.check_publisher(now=NOW, token="test", get=fake_get([
            run("2026-10-24T08:37:00Z", "failure"),
            run("2026-10-24T08:07:00Z", "success")]))
        self.assertEqual(result["status"], "healthy")

    def test_failed_matrix_runs_report_only_accounts_with_blocked_receipts(self):
        with patch.object(health, "check_publication_receipts", return_value={
                "status": "unhealthy", "reason": "publication_blocked",
                "blocked_routes": ["penguen"], "receipt_accounts": 7}):
            result = health.check_publisher(now=NOW, token="test", get=fake_get([
                run("2026-10-24T08:07:00Z", "failure")]))
        self.assertEqual(result["status"], "unhealthy")
        self.assertEqual(result["reason"], "publication_blocked")
        self.assertEqual(result["blocked_routes"], ["penguen"])

    def test_failed_matrix_runs_with_unavailable_receipts_stay_unknown(self):
        with patch.object(health, "check_publication_receipts", return_value={
                "status": "unknown", "reason": "publication_receipts_unavailable"}):
            result = health.check_publisher(now=NOW, token="test", get=fake_get([
                run("2026-10-24T08:07:00Z", "failure")]))
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "publication_receipts_unavailable")

    def test_wrong_branch_manual_or_old_run_cannot_mask_failure(self):
        get = fake_get([
            run("2026-10-24T08:07:00Z", event="workflow_dispatch"),
            run("2026-10-24T08:07:00Z", branch="test"),
            run("2026-10-24T08:07:00Z", path=".github/workflows/migration_ci.yml"),
            run("2026-10-24T03:00:00Z")])
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

    def test_watchdog_suppresses_acknowledged_repeat_but_alerts_new_failure(self):
        workflow = Path(".github/workflows/public_link_health.yml").read_text(encoding="utf-8")
        self.assertNotIn("META_OUTAGE_REPEAT_ALERTS: 'true'", workflow)

        verdict = {"status": "unhealthy", "reason": "publication_blocked",
                   "blocked_routes": ["penguen"]}
        env = {"CORRELATE_PUBLISHER_ALERTS": "true", "NTFY_TOPIC": "test-topic",
               "NTFY_TOPIC_URL": "", "GITHUB_STEP_SUMMARY": "",
               "META_OUTAGE_REPEAT_ALERTS": ""}

        with patch.object(health, "check_publisher", return_value=verdict), \
                patch.object(health, "blocked_route_alerts_acknowledged", return_value=True), \
                patch.object(health, "send_ntfy") as ntfy, \
                patch.object(health, "telegram_configured", return_value=False), \
                patch.dict(os.environ, env), redirect_stdout(io.StringIO()):
            self.assertEqual(health.main(), 1)
        ntfy.assert_not_called()

        with patch.object(health, "check_publisher", return_value=verdict), \
                patch.object(health, "blocked_route_alerts_acknowledged", return_value=False), \
                patch.object(health, "send_ntfy", return_value={"server_ack": True}) as ntfy, \
                patch.object(health, "telegram_configured", return_value=False), \
                patch.dict(os.environ, env), redirect_stdout(io.StringIO()):
            self.assertEqual(health.main(), 1)
        ntfy.assert_called_once()

    def test_repeating_outage_sends_both_channels_each_run_despite_prior_ack(self):
        for verdict in ({"status": "unhealthy", "reason": "publication_blocked", "blocked_routes": ["penguen"]},
                        {"status": "unhealthy", "reason": "consecutive_failures", "failed_run_ids": ["100"]}):
            with patch.object(health, "check_publisher", return_value=verdict), \
                    patch.object(health, "blocked_route_alerts_acknowledged", return_value=True) as daily, \
                    patch.object(health.alert_history, "restore") as restore, \
                    patch.object(health, "telegram_configured", return_value=True), \
                    patch.object(health, "send_telegram", return_value={"server_ack": True}) as telegram, \
                    patch.object(health, "send_ntfy", return_value={"server_ack": True}) as ntfy, \
                    patch.dict(os.environ, {"META_OUTAGE_REPEAT_ALERTS": "true", "CORRELATE_PUBLISHER_ALERTS": "true",
                                            "NTFY_TOPIC": "mock-topic", "GITHUB_STEP_SUMMARY": ""}), \
                    redirect_stdout(io.StringIO()):
                for _ in range(2):
                    self.assertEqual(health.main(), 1)
                self.assertEqual(telegram.call_count, 2)
                self.assertEqual(ntfy.call_count, 2)
                daily.assert_not_called()
                restore.assert_not_called()

    def test_repeating_mode_stays_silent_once_healthy(self):
        with patch.object(health, "check_publisher", return_value={"status": "healthy"}), \
                patch.object(health, "send_ntfy") as ntfy, \
                patch.object(health, "send_telegram") as telegram, \
                patch.dict(os.environ, {"META_OUTAGE_REPEAT_ALERTS": "true", "GITHUB_STEP_SUMMARY": ""}), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(health.main(), 0)
            telegram.assert_not_called()
            ntfy.assert_not_called()

    def test_overnight_three_hour_gap_is_not_a_missing_schedule_outage(self):
        verdict = health.check_publisher(now=NOW, token="test", get=fake_get([run("2026-10-24T05:07:00Z")]))
        self.assertEqual(verdict["status"], "healthy")

    def test_receipt_evidence_keeps_daily_account_blockers_beyond_scheduler_window(self):
        rows = [run(), run("2026-10-23T12:07:00Z")]
        with patch.object(health, "check_publication_receipts", return_value={"status": "healthy"}) as receipts:
            health.check_publisher(now=NOW, token="test", get=fake_get(rows))
        self.assertEqual(len(receipts.call_args.args[0]), 2)

    def test_scoped_daily_ack_correlation_requires_every_blocked_account(self):
        def history(route, day="2026-10-24", ack=True):
            return {"schema": 1, "records": {"a" * 64: {
                "kind": "incident", "route": route, "family": "publication_deficit",
                "local_day": day, "last_seen": NOW.isoformat(), "resolved": False,
                "server_acks": ["telegram"] if ack else []}}}
        with patch.object(health.alert_history, "restore", side_effect=[history("penguen"), history("tarladaki")]) as restore:
            self.assertTrue(health.blocked_route_alerts_acknowledged(["penguen", "tarladaki"], now=NOW))
            self.assertEqual(restore.call_args.kwargs["names"], ("link-alert-intent-tarladaki", "link-alert-result-tarladaki"))
        for stale in (history("penguen", day="2026-10-23"), history("penguen", ack=False)):
            with patch.object(health.alert_history, "restore", return_value=stale):
                self.assertFalse(health.blocked_route_alerts_acknowledged(["penguen"], now=NOW))
        with patch.object(health.alert_history, "restore", side_effect=ValueError("archive unavailable")):
            self.assertFalse(health.blocked_route_alerts_acknowledged(["penguen"], now=NOW))


class PublicationReceiptTests(unittest.TestCase):
    def receipt_get(self, reports):
        import zipfile
        archives = {}
        artifacts = []
        for number, (route, receipt) in enumerate(reports.items(), 1):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("incidents.json", __import__("json").dumps(receipt))
            archives[str(number)] = stream.getvalue()
            artifacts.append({"id": number, "name": "link-incident-report-" + route,
                              "workflow_run": {"id": 123}, "expired": False})
        def get(url, **kwargs):
            result = Mock(status_code=200)
            if url.endswith("/artifacts"):
                result.json.return_value = {"artifacts": artifacts}
            else:
                result.content = archives[url.split("/")[-2]]
            return result
        return get

    def test_green_runs_with_zero_post_blocked_receipt_are_unhealthy(self):
        receipt = {"run_id": "123", "confirmed_new_posts": 0,
                   "planning_blocker_counts": {"no_eligible_content": 1},
                   "step_outcomes": {"publish": "success"}}
        verdict = health.check_publication_receipts([(NOW, {"id": 123, "status": "completed"})],
            get=self.receipt_get({"penguen": receipt}), headers={})
        self.assertEqual(verdict["status"], "unhealthy")
        self.assertEqual(verdict["blocked_routes"], ["penguen"])

    def test_one_successful_account_cannot_mask_another_blocked_account(self):
        okay = {"run_id": "123", "confirmed_new_posts": 2,
                "planning_blocker_counts": {}, "step_outcomes": {"publish": "success"}}
        blocked = dict(okay, confirmed_new_posts=0, planning_blocker_counts={"no_eligible_content": 1})
        verdict = health.check_publication_receipts([(NOW, {"id": 123, "status": "completed"})],
            get=self.receipt_get({"gonle": okay, "penguen": blocked}), headers={})
        self.assertEqual(verdict["status"], "unhealthy")
        self.assertEqual(verdict["confirmed_new_posts_in_latest_receipts"], 2)

    def test_blocked_account_reports_only_allowlisted_platform_evidence(self):
        blocked = {"run_id": "123", "confirmed_new_posts": 0,
                   "planning_blocker_counts": {"no_eligible_content": 1},
                   "step_outcomes": {"publish": "success"},
                   "incidents": [{"route": "penguen", "platform": "instagram"}],
                   "all_error_events": [
                       {"route": "penguen", "platform": "facebook"},
                       {"route": "gonle", "platform": "instagram"},
                       {"route": "penguen", "platform": "threads"},
                   ]}
        verdict = health.check_publication_receipts([(NOW, {"id": 123, "status": "completed"})],
            get=self.receipt_get({"penguen": blocked}), headers={})
        self.assertEqual(verdict["blocked_platforms"], {
            "penguen": ["facebook", "instagram", "unknown"]})

    def test_blocked_account_without_platform_evidence_is_unknown(self):
        receipt = {"run_id": "123", "confirmed_new_posts": 0,
                   "planning_blocker_counts": {"no_eligible_content": 1},
                   "step_outcomes": {"publish": "success"}}
        verdict = health.check_publication_receipts([(NOW, {"id": 123, "status": "completed"})],
            get=self.receipt_get({"penguen": receipt}), headers={})
        self.assertEqual(verdict["blocked_platforms"], {"penguen": ["unknown"]})

    def test_youtube_step_failure_does_not_raise_meta_outage(self):
        receipt = {"run_id": "123", "confirmed_new_posts": 0,
                   "planning_blocker_counts": {}, "step_outcomes": {"publish": "success", "youtube_publish": "failure"}}
        verdict = health.check_publication_receipts([(NOW, {"id": 123, "status": "completed"})],
            get=self.receipt_get({"penguen": receipt}), headers={})
        self.assertEqual(verdict["status"], "healthy")

    def test_missing_receipts_are_unknown_not_healthy(self):
        verdict = health.check_publication_receipts([(NOW, {"id": 123, "status": "completed"})],
            get=self.receipt_get({}), headers={})
        self.assertEqual(verdict["status"], "unknown")

    def test_receipt_from_wrong_run_is_rejected(self):
        receipt = {"run_id": "999", "confirmed_new_posts": 5,
                   "planning_blocker_counts": {}, "step_outcomes": {}}
        verdict = health.check_publication_receipts([(NOW, {"id": 123, "status": "completed"})],
            get=self.receipt_get({"gonle": receipt}), headers={})
        self.assertEqual(verdict["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
