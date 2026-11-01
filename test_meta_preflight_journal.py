"""Regressions for metadata-only early Meta authentication failures."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publisher_error_journal import read_errors, record_error


class MetaPreflightJournalTests(unittest.TestCase):
    def test_preflight_failure_is_redacted_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"GITHUB_RUN_ID": "41294422455", "META_ACCESS_TOKEN": "USER_PRIVATE_VALUE"},
        ):
            path = Path(tmp) / "errors.jsonl"
            record_error("workflow_verify", "workflow_step_failed", path=path)
            events = read_errors(path, run_id="41294422455")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["stage"], "workflow_verify")
        self.assertEqual(events[0]["reason"], "workflow_step_failed")
        self.assertEqual(events[0]["retry_policy"], "never_blindly_retry_meta_post")
        self.assertNotIn("USER_PRIVATE_VALUE", str(events))

    def test_workflow_records_failure_before_artifact_upload(self):
        workflow = Path(".github/workflows/public_link_schedule.yml").read_text(encoding="utf-8")
        self.assertIn("Preserve rejected Meta preflight in structured incident journal", workflow)
        self.assertIn("steps.meta_preflight.outcome == 'failure'", workflow)
        self.assertIn("record_error('workflow_verify', 'workflow_step_failed')", workflow)
        self.assertLess(
            workflow.index("Preserve rejected Meta preflight in structured incident journal"),
            workflow.index("name: link-error-journal"),
        )
        self.assertIn("if: always()", workflow)


if __name__ == "__main__":
    unittest.main()
