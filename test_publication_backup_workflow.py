"""Static fail-closed contract for one daily content-addressed Drive recovery job."""
from pathlib import Path
import unittest

WORKFLOW = Path(".github/workflows/publication_backup.yml")


class DurableBackupScheduleTests(unittest.TestCase):
    def test_one_daily_schedule_without_publisher_workflow_run_fanout(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("cron: '23 21 * * *'", text)
        self.assertNotIn("workflow_run:", text)
        self.assertIn("github.event_name == 'schedule'", text)

    def test_owner_enablement_and_explicit_disable_are_honored(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("vars.DURABLE_DRIVE_BACKUP_ENABLED != 'false'", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("github.event_name != 'pull_request'", text)

    def test_existing_private_drive_restore_and_receipt_are_required(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("run: python durable_backup.py", text)
        self.assertIn("DRIVE_TOKEN_JSON: ${{ secrets.DRIVE_TOKEN_JSON }}", text)
        self.assertIn("name: durable-backup-receipt", text)
        self.assertIn("if-no-files-found: error", text)
        self.assertNotIn("continue-on-error: true", text)


if __name__ == "__main__":
    unittest.main()
