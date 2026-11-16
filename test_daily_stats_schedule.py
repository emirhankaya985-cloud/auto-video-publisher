"""Regression guard: daily status report targets 23:59 Turkey time.

GitHub Actions cron can run late; the guard asserts the requested schedule,
not an exact provider delivery-time SLA.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class DailyStatsScheduleTest(unittest.TestCase):
    def test_report_requested_at_2359_turkey_time(self):
        workflow = (ROOT / ".github/workflows/daily_stats.yml").read_text(encoding="utf-8")
        self.assertIn("    - cron: '59 20 * * *'", workflow)
        self.assertNotIn("    - cron: '15 20 * * *'", workflow)

    def test_report_has_room_for_slow_read_only_collection(self):
        workflow = (ROOT / ".github/workflows/daily_stats.yml").read_text(encoding="utf-8")
        self.assertIn("    timeout-minutes: 35", workflow)
        report_step = workflow.split("      - name: Istatistikleri Telefona Gonder", 1)[1].split(
            "      - name: Record separate, non-blocking Neon archive transfer", 1
        )[0]
        self.assertIn("        timeout-minutes: 28", report_step)
        self.assertIn("run: python -u stats_reporter.py", report_step)

    def test_dashboard_sync_is_independent_and_never_double_posts(self):
        workflow = (ROOT / ".github/workflows/daily_stats.yml").read_text(encoding="utf-8")
        archive = (ROOT / ".github/workflows/dashboard_archive_sync.yml").read_text(encoding="utf-8")
        step = workflow.split("      - name: Record separate, non-blocking Neon archive transfer", 1)[1].split(
            "      - name: Recommend posting hours", 1
        )[0]
        self.assertIn("archive_sync=pending_independent_workflow_run", step)
        self.assertNotIn("python dashboard_archive_push.py", workflow)
        self.assertNotIn("python neon_archive_sync.py", workflow)
        self.assertIn("meta-daily-analytics-history", workflow)
        self.assertIn("workflow_run:", archive)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", archive)
        self.assertIn("SOURCE_RUN_ID:", archive)
        self.assertIn("DASHBOARD_DATABASE_URL:", archive)
        self.assertIn("python neon_archive_sync.py", archive)
        self.assertIn("python dashboard_archive_push.py", archive)
        self.assertIn("exit 2", archive)
        self.assertNotIn("continue-on-error: true", step)

    def test_backup_target_follows_report(self):
        workflow = (ROOT / ".github/workflows/publication_backup.yml").read_text(encoding="utf-8")
        # Backup targets 00:23 Turkey time, after the 23:59 report trigger.
        self.assertIn("    - cron: '23 21 * * *'", workflow)


if __name__ == "__main__":
    unittest.main()
