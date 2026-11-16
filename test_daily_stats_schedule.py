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

    def test_missing_optional_dashboard_secrets_do_not_fail_daily_report(self):
        workflow = (ROOT / ".github/workflows/daily_stats.yml").read_text(encoding="utf-8")
        sync_step = workflow.split("      - name: Sync private analytics archive to dashboard", 1)[1].split(
            "      - name: Recommend posting hours", 1
        )[0]
        self.assertIn('if [ -z "$DASHBOARD_INGEST_URL" ] || [ -z "$DASHBOARD_INGEST_TOKEN" ]; then', sync_step)
        self.assertIn('dashboard_sync=blocked_missing_ingest_configuration', sync_step)
        self.assertIn('exit 0', sync_step)
        self.assertIn('python dashboard_archive_push.py', sync_step)
        self.assertNotIn('continue-on-error: true', sync_step)

    def test_backup_target_follows_report(self):
        workflow = (ROOT / ".github/workflows/publication_backup.yml").read_text(encoding="utf-8")
        # Backup targets 00:23 Turkey time, after the 23:59 report trigger.
        self.assertIn("    - cron: '23 21 * * *'", workflow)


if __name__ == "__main__":
    unittest.main()
