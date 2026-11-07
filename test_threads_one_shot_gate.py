"""One-shot owner Threads release stays bound to source and rights gates."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).parent / ".github/workflows/threads_live_publish.yml"


class ThreadsOwnerCatchupContract(unittest.TestCase):
    def test_owner_one_shot_marker_is_new_file_and_exact_subject_only(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        marker = "docs/threads-owner-catchup-2026-11-07.md"
        subject = "ops: owner-authorized-once-threads-catchup-2026-11-07"
        self.assertIn("- '" + marker + "'", content)
        self.assertIn("github.event.head_commit.message == '" + subject + "'", content)
        self.assertIn("contains(github.event.head_commit.added, '" + marker + "')",
                      content)
        self.assertNotIn("contains(github.event.head_commit.modified, '" + marker + "')",
                         content)
        self.assertIn("github.run_attempt == 1", content)
        self.assertIn("github.ref == 'refs/heads/main'", content)

    def test_legacy_and_scheduled_triggers_preserved(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("docs/threads-owner-start-2026-11-04.md", content)
        self.assertIn("github.event.workflow_run.event == 'schedule'", content)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", content)
        self.assertIn("github.event_name != 'pull_request'", content)

    def test_no_bypass_of_rights_accounts_or_durable_intent(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        for marker in ("ENABLE_TOONZONE_ROUTES: ${{ vars.ENABLE_TOONZONE_ROUTES }}",
                       "FILM_RIGHTS_APPROVED: ${{ vars.FILM_RIGHTS_APPROVED }}",
                       "ENABLE_PENGUEN_THREADS: ${{ vars.ENABLE_PENGUEN_THREADS }}",
                       "Verify route and source ownership and reserve one video per account",
                       "Archive publication reservations before writing",
                       "THREADS_INTENT_ARCHIVED",
                       "Preserve post IDs and ambiguous attempts"):
            with self.subTest(marker=marker):
                self.assertIn(marker, content)


if __name__ == "__main__":
    unittest.main()
