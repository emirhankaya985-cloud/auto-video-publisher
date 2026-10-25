"""No-send regression guards for commit-triggered Meta source audit."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publisher_incident_report as incidents


class SafeAuditTriggerTests(unittest.TestCase):
    def test_marker_push_must_never_publish_or_notify(self):
        workflow = Path(".github/workflows/public_link_schedule.yml").read_text(encoding="utf-8")
        self.assertIn("'docs/publisher-safe-audit-2026-10-25.md'", workflow)
        self.assertIn("github.event_name == 'push' && 'audit'", workflow)
        publisher_step = workflow.split("- name: Publish explicitly planned Meta videos", 1)[1].split(
            "- name: Preserve all results", 1)[0]
        self.assertIn("github.event_name == 'schedule' || inputs.mode == 'publish'", publisher_step)
        self.assertNotIn("github.event_name == 'push'", publisher_step)
        notifications = workflow.split("- name: Per-post Telegram and ntfy", 1)[1].split(
            "- name: Generate final per-run incident", 1)[0]
        self.assertNotIn("github.event_name == 'push'", notifications)
        self.assertIn("github.event_name == 'schedule' || inputs.mode == 'publish'", notifications)

    def test_missing_publication_id_fails_after_preserving_incident(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            (root / "state.json").write_text(json.dumps({"entries": {
                "test": {"run_id": "12345", "route": "film", "platform": "instagram",
                         "status": "done", "file": "clip.mp4"}
            }}), encoding="utf-8")
            with patch.object(incidents, "ROOT", root), patch.object(
                incidents, "read_errors", return_value=[]
            ), patch.dict(os.environ, {"GITHUB_RUN_ID": "12345"}):
                with self.assertRaises(SystemExit):
                    incidents.main()
            saved = json.loads((root / "incidents.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["confirmed_new_posts"], 0)
            self.assertEqual(saved["unverified_done_entries"], 1)
            self.assertEqual(saved["incidents"][0]["reason"], "missing_confirmed_post_id")


if __name__ == "__main__":
    unittest.main()
