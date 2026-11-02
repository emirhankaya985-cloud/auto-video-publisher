"""Offline contract tests for the six-token Threads read-only audit workflow.

No credentials or Threads API calls are used by these tests.
"""
from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).parent / ".github" / "workflows" / "threads_connection_audit.yml"

# Public account handles are only read-only identity-check defaults.
ROUTES = {
    "TARLADAKI": ("THREADS_TARLADAKI_FASULYE_ACCESS_TOKEN", "tarladakifasulye_"),
    "PENGUEN": ("THREADS_ACCESS_TOKEN", "beyinsiz.penguen"),
    "GONLE": ("THREADS_GONLE_DUSEN_ACCESS_TOKEN", "gonl_edusen"),
    "DAILY_LAUGH": ("THREADS_DAILY_LAUGH_LAB_ACCESS_TOKEN", "dail.ylaughlab"),
    "FILM": ("THREADS_FILM_MAGARASI_ACCESS_TOKEN", "film_magrasi"),
    "TOONZONE": ("THREADS_TOONZONE_ACCESS_TOKEN", "toonzone.tr"),
}


class ThreadsAuditWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_all_six_saved_secret_names_are_mapped(self):
        for prefix, (saved, _username) in ROUTES.items():
            with self.subTest(prefix=prefix):
                self.assertIn(f"secrets.{saved}", self.workflow)
                if prefix != "PENGUEN":
                    line = re.search(
                        rf"^\s+{prefix}_THREADS_ACCESS_TOKEN:\s+(.+)$",
                        self.workflow, re.MULTILINE,
                    )
                    self.assertIsNotNone(line)
                    self.assertIn(f"secrets.{saved}", line.group(1))
                    self.assertIn(f"secrets.{prefix}_THREADS_ACCESS_TOKEN", line.group(1))

    def test_public_handles_are_defaults_only(self):
        for prefix, (_saved, username) in ROUTES.items():
            with self.subTest(prefix=prefix):
                line = re.search(
                    rf"^\s+{prefix}_THREADS_USERNAME:\s+(.+)$",
                    self.workflow, re.MULTILINE,
                )
                self.assertIsNotNone(line)
                self.assertIn(f"vars.{prefix}_THREADS_USERNAME", line.group(1))
                self.assertIn(f"'{username}'", line.group(1))

    def test_manual_api_check_is_readonly(self):
        self.assertIn("if: github.event_name == 'workflow_dispatch' || (github.event_name == 'push' && github.ref == 'refs/heads/main')", self.workflow)
        self.assertIn("THREADS_CHECK_ROUTE: ${{ inputs.account || 'all' }}", self.workflow)
        self.assertIn("run: python check_threads_connection.py", self.workflow)
        self.assertNotIn("python scheduled_multi_publisher.py", self.workflow)
        self.assertNotIn("python public_link_runtime.py publish", self.workflow)


if __name__ == "__main__":
    unittest.main()
