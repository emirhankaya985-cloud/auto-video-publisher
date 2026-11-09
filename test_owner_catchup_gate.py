"""Owner-authorized one-day catch-up must never become a recurring upload bypass."""
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from publisher_one_shot_gate import (
    OWNER_CATCHUP_MARKER, OWNER_CATCHUP_SUBJECT, determine_mode,
    is_owner_catchup_push, is_today_catchup_push, TODAY_CATCHUP_MARKER, TODAY_CATCHUP_SUBJECT,
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

    def test_nov2_explicit_marker_first_run_only(self):
        args = ("push", "refs/heads/main", TODAY_CATCHUP_SUBJECT, [TODAY_CATCHUP_MARKER])
        self.assertTrue(is_today_catchup_push(*args, today="2026-11-02", run_attempt="1"))
        self.assertFalse(is_today_catchup_push(*args, today="2026-11-01", run_attempt="1"))
        self.assertFalse(is_today_catchup_push(*args, today="2026-11-03", run_attempt="1"))
        self.assertFalse(is_today_catchup_push(*args, today="2026-11-02", run_attempt="2"))
        self.assertFalse(is_today_catchup_push("push", "refs/heads/other", TODAY_CATCHUP_SUBJECT,
                                               [TODAY_CATCHUP_MARKER], today="2026-11-02", run_attempt="1"))
        self.assertFalse(is_today_catchup_push("pull_request", "refs/heads/main", TODAY_CATCHUP_SUBJECT,
                                               [TODAY_CATCHUP_MARKER], today="2026-11-02", run_attempt="1"))
        self.assertEqual(determine_mode("pull_request", "refs/heads/main", TODAY_CATCHUP_SUBJECT,
                                        [TODAY_CATCHUP_MARKER]), "audit")
        self.assertEqual(determine_mode("push", "refs/heads/main", "wrong",
                                        [TODAY_CATCHUP_MARKER]), "audit")

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
        self.assertIn("cron: '7 6,9,12,15,18 * * *'", workflow)
        self.assertIn("cron: '7 7,9,11,13,15 * * *'", workflow)
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


    def test_nov7_one_shot_never_allows_rerun_or_nonowner_marker(self):
        from publisher_one_shot_gate import (
            NOV7_CATCHUP_MARKER, NOV7_CATCHUP_SUBJECT, is_nov7_catchup_push)
        good = ("push", "refs/heads/main", NOV7_CATCHUP_SUBJECT,
                [NOV7_CATCHUP_MARKER])
        self.assertTrue(is_nov7_catchup_push(*good,
                         today="2026-11-07", run_attempt="1"))
        for day, attempt in (("2026-11-06", "1"), ("2026-11-08", "1"),
                             ("2026-11-07", "2")):
            with self.subTest(day=day, attempt=attempt):
                self.assertFalse(is_nov7_catchup_push(*good,
                                 today=day, run_attempt=attempt))
        for event, ref, subject, paths in (
            ("pull_request", good[1], good[2], good[3]),
            ("push", "refs/heads/other", good[2], good[3]),
            ("push", good[1], "any other commit", good[3]),
            ("push", good[1], good[2], []),
        ):
            self.assertFalse(is_nov7_catchup_push(event, ref, subject, paths,
                             today="2026-11-07", run_attempt="1"))

    def test_nov7_push_is_publish_only_when_added_marker_and_attempt_one(self):
        from publisher_one_shot_gate import (
            NOV7_CATCHUP_MARKER, NOV7_CATCHUP_SUBJECT, main)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'push',
                     'GITHUB_REF': 'refs/heads/main',
                     'GITHUB_RUN_ATTEMPT': '1',
                     'GITHUB_OUTPUT': str(Path(tmp)/'output')}, clear=True), \
             patch('publisher_one_shot_gate._git',
                   side_effect=[NOV7_CATCHUP_SUBJECT, NOV7_CATCHUP_MARKER, '']), \
             patch('publisher_one_shot_gate.datetime') as clock:
            clock.now.return_value.date.return_value.isoformat.return_value = '2026-11-07'
            self.assertEqual(main(), 0)
            self.assertIn('publish_allowed=true',
                          (Path(tmp)/'output').read_text())
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'push',
                     'GITHUB_REF': 'refs/heads/main',
                     'GITHUB_RUN_ATTEMPT': '2',
                     'GITHUB_OUTPUT': str(Path(tmp)/'output')}, clear=True), \
             patch('publisher_one_shot_gate._git',
                   side_effect=[NOV7_CATCHUP_SUBJECT, NOV7_CATCHUP_MARKER, '']), \
             patch('publisher_one_shot_gate.datetime') as clock:
            clock.now.return_value.date.return_value.isoformat.return_value = '2026-11-07'
            self.assertEqual(main(), 0)
            self.assertIn('publish_allowed=false',
                          (Path(tmp)/'output').read_text())

    def test_nov7_only_uses_existing_verified_account_and_no_rights_bypass(self):
        from publisher_one_shot_gate import NOV7_CATCHUP_MARKER
        workflow = (Path(__file__).parent / '.github/workflows/public_link_schedule.yml').read_text()
        self.assertIn(NOV7_CATCHUP_MARKER, workflow)
        self.assertIn("'2026-11-07' }}", workflow)
        self.assertIn("cron: '7 6,9,12,15,18 * * *'", workflow)
        self.assertIn("cron: '7 7,9,11,13,15 * * *'", workflow)
        self.assertIn("run: python meta_page_token_health.py", workflow)
        self.assertIn("run: python public_link_runtime.py publish", workflow)
        self.assertIn("Persist intent before any Meta upload", workflow)
        self.assertIn("ENABLE_TOONZONE_ROUTES: ${{ vars.ENABLE_TOONZONE_ROUTES }}", workflow)
        self.assertIn("FILM_RIGHTS_APPROVED: ${{ vars.FILM_RIGHTS_APPROVED }}", workflow)

    def test_nov9_only_one_added_marker_push_on_main_publishes(self):
        from publisher_one_shot_gate import (
            NOV9_CATCHUP_MARKER, NOV9_CATCHUP_SUBJECT,
            is_nov9_catchup_push, main,
        )
        good = ("push", "refs/heads/main", NOV9_CATCHUP_SUBJECT,
                [NOV9_CATCHUP_MARKER])
        self.assertTrue(is_nov9_catchup_push(
            *good, today="2026-11-09", run_attempt="1"))
        for day, attempt in (("2026-11-08", "1"), ("2026-11-10", "1"),
                             ("2026-11-09", "2")):
            self.assertFalse(is_nov9_catchup_push(
                *good, today=day, run_attempt=attempt))
        for event, ref, subject, paths in (
            ("pull_request", good[1], good[2], good[3]),
            ("push", "refs/heads/other", good[2], good[3]),
            ("push", good[1], "unrelated commit", good[3]),
            ("push", good[1], good[2], []),
        ):
            self.assertFalse(is_nov9_catchup_push(
                event, ref, subject, paths, today="2026-11-09", run_attempt="1"))
        workflow = (Path(__file__).parent / ".github/workflows/public_link_schedule.yml").read_text()
        self.assertIn(NOV9_CATCHUP_MARKER, workflow)
        self.assertIn("COMPLETE_DAY_DATE: "${{ github.event_name == 'push'", workflow)
        self.assertIn("CATCHUP_BATCH_DATE: "${{ github.event_name == 'push'", workflow)
        self.assertIn("Persist intent before any Meta upload", workflow)
        self.assertIn("FILM_RIGHTS_APPROVED: ${{ vars.FILM_RIGHTS_APPROVED }}", workflow)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {
                 "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main",
                 "GITHUB_RUN_ATTEMPT": "1", "GITHUB_OUTPUT": str(Path(tmp) / "output"),
             }, clear=True), \
             patch("publisher_one_shot_gate._git", side_effect=[
                 NOV9_CATCHUP_SUBJECT, NOV9_CATCHUP_MARKER, "",
             ]), \
             patch("publisher_one_shot_gate.datetime") as clock:
            clock.now.return_value.date.return_value.isoformat.return_value = "2026-11-09"
            self.assertEqual(main(), 0)
            self.assertIn("publish_allowed=true", (Path(tmp) / "output").read_text())

    def test_nov9_catchup_rerun_is_audit(self):
        from publisher_one_shot_gate import NOV9_CATCHUP_MARKER, NOV9_CATCHUP_SUBJECT
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}), \
             patch("publisher_one_shot_gate.datetime") as fake:
            fake.now.return_value.date.return_value.isoformat.return_value = "2026-11-09"
            self.assertEqual(determine_mode(
                "push", "refs/heads/main", NOV9_CATCHUP_SUBJECT,
                [NOV9_CATCHUP_MARKER]), "audit")


if __name__ == "__main__":
    unittest.main()

