"""Owner-authorized one-day catch-up must never become a recurring upload bypass."""
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from publisher_one_shot_gate import (
    OWNER_CATCHUP_MARKER, OWNER_CATCHUP_SUBJECT, determine_mode,
    is_owner_catchup_push,
)


class OwnerCatchupGateTests(unittest.TestCase):
    def test_only_dated_catchup_modified_marker_can_authorize_another_commit(self):
        from publisher_one_shot_gate import main, MARKER
        for modified, subject, attempt, expected in (
            (OWNER_CATCHUP_MARKER, OWNER_CATCHUP_SUBJECT, '1', 'true'),
            (OWNER_CATCHUP_MARKER, 'unrelated commit', '1', 'false'),
            (OWNER_CATCHUP_MARKER, OWNER_CATCHUP_SUBJECT, '2', 'false'),
            (MARKER, 'ops: authorized-once-meta-publish-2026-10-25-v2', '1', 'false'),
        ):
            with self.subTest(modified=modified, subject=subject, attempt=attempt), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'output'
                with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
                                             'GITHUB_RUN_ATTEMPT': attempt, 'GITHUB_OUTPUT': str(output)}), \
                     patch('publisher_one_shot_gate._git', side_effect=[subject, '', modified]), \
                     patch('publisher_one_shot_gate.datetime') as clock:
                    clock.now.return_value.date.return_value.isoformat.return_value = '2026-11-01'
                    self.assertEqual(main(), 0)
                self.assertIn('publish_allowed=' + expected + '\n', output.read_text())

    def test_exact_first_attempt_on_owner_day_allows_existing_publish_pipeline(self):
        self.assertTrue(is_owner_catchup_push(
            "push", "refs/heads/main", OWNER_CATCHUP_SUBJECT,
            [OWNER_CATCHUP_MARKER], today="2026-11-01", run_attempt="1"))

    def test_rerun_next_day_wrong_subject_or_branch_fails_closed(self):
        base = ("push", "refs/heads/main", OWNER_CATCHUP_SUBJECT, [OWNER_CATCHUP_MARKER])
        self.assertFalse(is_owner_catchup_push(*base, today="2026-11-02", run_attempt="1"))
        self.assertFalse(is_owner_catchup_push(*base, today="2026-11-01", run_attempt="2"))
        self.assertFalse(is_owner_catchup_push(
            "pull_request", "refs/heads/main", OWNER_CATCHUP_SUBJECT, [OWNER_CATCHUP_MARKER],
            today="2026-11-01", run_attempt="1"))
        self.assertFalse(is_owner_catchup_push(
            "push", "refs/heads/other", OWNER_CATCHUP_SUBJECT, [OWNER_CATCHUP_MARKER],
            today="2026-11-01", run_attempt="1"))
        self.assertFalse(is_owner_catchup_push(
            "push", "refs/heads/main", "unrelated commit", [OWNER_CATCHUP_MARKER],
            today="2026-11-01", run_attempt="1"))
        self.assertFalse(is_owner_catchup_push(
            "push", "refs/heads/main", OWNER_CATCHUP_SUBJECT, [],
            today="2026-11-01", run_attempt="1"))

    def test_gate_defaults_to_audit_for_pr_and_unrelated_push(self):
        self.assertEqual(determine_mode("pull_request", "refs/heads/main"), "audit")
        self.assertEqual(determine_mode("push", "refs/heads/main", "normal", ()), "audit")
        self.assertEqual(determine_mode("workflow_dispatch", "refs/heads/main",
                                        requested_mode="audit"), "audit")

    def test_normal_schedule_is_still_publish_and_not_changed(self):
        self.assertEqual(determine_mode("schedule", "refs/heads/main"), "publish")

    def test_one_shot_marker_wired_but_no_recurring_cron_changed(self):
        from pathlib import Path
        workflow = (Path(__file__).parent / ".github/workflows/public_link_schedule.yml").read_text()
        self.assertIn(OWNER_CATCHUP_MARKER, workflow)
        self.assertIn("cron: '7,37 * * * *'", workflow)
        self.assertIn("run: python meta_page_token_health.py", workflow)
        self.assertLess(workflow.index("run: python meta_page_token_health.py"),
                        workflow.index("run: python public_link_runtime.py publish"))
        self.assertIn("Persist intent before any Meta upload", workflow)

    def test_explicit_rerun_attempt_never_uploads_owner_catchup(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}), \
             patch("publisher_one_shot_gate.datetime") as fake:
            fake.now.return_value.date.return_value.isoformat.return_value = "2026-11-01"
            self.assertEqual(determine_mode(
                "push", "refs/heads/main", OWNER_CATCHUP_SUBJECT,
                [OWNER_CATCHUP_MARKER]), "audit")


if __name__ == "__main__":
    unittest.main()

