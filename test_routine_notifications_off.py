"""Regression: no routine Threads/YouTube Telegram success messages."""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parent / ".github/workflows/platform_publication_notifications.yml"


class SuccessNotificationSafetyTests(unittest.TestCase):
    def test_scheduled_or_workflow_completion_notice_is_retired(self):
        value = WORKFLOW.read_text(encoding="utf-8")
        triggers = value.split("permissions:", 1)[0]
        self.assertNotIn("  schedule:", triggers)
        self.assertNotIn("  workflow_run:", triggers)

    def test_notify_job_is_unconditionally_disabled(self):
        value = WORKFLOW.read_text(encoding="utf-8")
        job = value.split("  notify:\n", 1)[1].split("\n    runs-on:", 1)[0]
        self.assertRegex(job, r"(?m)^\s+if: \$\{\{ false \}\}\s*$")
        self.assertNotRegex(job, r"vars.")


if __name__ == "__main__":
    unittest.main()
