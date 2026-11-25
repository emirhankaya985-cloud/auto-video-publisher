"""No-network Meta production notification policy tests."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_publish_report as report


class InterventionOnlyNotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"
        self.path.write_text(json.dumps({"entries": {
            "fb": {"run_id": "98765", "route": "film",
                   "platform": "facebook", "status": "done",
                   "post_id": "1234567890123456", "file": "Part17.mp4"},
        }}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, incidents=None, *, publish="success"):
        incidents = [] if incidents is None else incidents
        with patch.object(report, "STATE_PATH", self.path), \
             patch.object(report, "telegram_configured", return_value=True), \
             patch.object(report, "read_errors", return_value=incidents), \
             patch.object(report, "_prepare_durable", return_value=0) as prepare, \
             patch.dict(os.environ, {
                 "GITHUB_RUN_ID": "98765", "PUBLISH_ALERT_MODE": "prepare",
                 "PUBLISH_ALERTS_ONLY": "true", "VERIFY_STEP_OUTCOME": "success",
                 "PLAN_STEP_OUTCOME": "success", "PUBLISH_STEP_OUTCOME": publish,
                 "PUBLISH_QUIET_FAILURES": "false", "REQUIRE_DUAL_NOTIFICATIONS": "true",
             }, clear=True):
            self.assertEqual(report.main(), 0)
        return prepare

    def test_successful_posts_are_silent(self):
        prepare = self.prepare()
        prepare.assert_called_once()
        self.assertEqual(prepare.call_args.args[0], [])
        self.assertEqual(prepare.call_args.args[1], [])

    def test_two_platform_failures_merge_into_one_notice(self):
        errors = [
            {"route": "film", "platform": p, "reason": "credentials_or_permissions",
             "retry_policy": "never_blindly_retry_meta_post", "stage": "meta_account"}
            for p in ("instagram", "facebook")
        ]
        prep = self.prepare(errors, publish="failure")
        messages = prep.call_args.args[0]
        self.assertEqual(len(messages), 1)
        title, body = messages[0]
        self.assertTrue(title.startswith("🚨"))
        self.assertIn("facebook", body)
        self.assertIn("instagram", body)
        self.assertNotIn("✅", body)
        self.assertEqual(prep.call_args.args[1], [])

    def test_transient_retriable_failure_is_not_phone_alert(self):
        error = {"route": "gonle", "platform": "instagram",
                 "reason": "rate_limit", "retry_policy": "pre_upload_only",
                 "stage": "meta_history"}
        prep = self.prepare([error])
        self.assertEqual(prep.call_args.args[0], [])

    def test_unknown_failed_workflow_without_journal_is_not_silently_accepted(self):
        # A failing workflow with no structured incident is itself actionable.
        prep = self.prepare([], publish="failure")
        self.assertEqual(len(prep.call_args.args[0]), 1)

    def test_failed_delivery_does_not_reclassify_media_publish(self):
        workflow = (Path(__file__).resolve().parent /
                    ".github/workflows/public_link_schedule.yml").read_text()
        transport = workflow.split(
            "      - name: Send reserved notifications once (no video uploads)", 1
        )[1].split("      - name: Preserve notification results", 1)[0]
        self.assertIn("continue-on-error: true", transport)
        self.assertIn("steps.notify.outcome == 'failure'", transport)
        self.assertIn("link-alert-result", workflow)
        self.assertIn("OUTCOME_NOTIFY:", workflow)
        self.assertIn("steps.notify.outcome == 'failure'", workflow)
        self.assertIn("link-incident-report-", workflow)
        # Only notification transport is optional; an actual Meta upload
        # failure must still fail its run and preserve ambiguous intents.
        publish = workflow.split(
            "      - name: Publish explicitly planned Meta videos", 1
        )[1].split("      - name: ", 1)[0]
        self.assertNotIn("continue-on-error: true", publish)

    def test_workflow_enables_alerts_only_and_preserves_archived_intents(self):
        text = (Path(__file__).resolve().parent / ".github/workflows/public_link_schedule.yml").read_text()
        self.assertIn("PUBLISH_ALERTS_ONLY: 'true'", text)
        self.assertIn("PUBLISH_ALERT_MODE: prepare", text)
        self.assertIn("PUBLISH_ALERT_MODE: send", text)
        self.assertIn("link-alert-intent-", text)
        self.assertNotIn("PUBLISH_QUIET_FAILURES: 'true'", text)


if __name__ == "__main__":
    unittest.main()
