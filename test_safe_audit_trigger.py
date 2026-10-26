"""No-network regressions for exactly one authorized production push."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publisher_incident_report as incidents
from publisher_one_shot_gate import MARKER, SUBJECT, IG_RESCUE_MARKER, IG_RESCUE_SUBJECT, is_ig_rescue_push, determine_mode


class SafeAuditTriggerTests(unittest.TestCase):
    def test_workflow_requires_verifiable_gate_for_all_meta_writes(self):
        workflow = Path(".github/workflows/public_link_schedule.yml").read_text(encoding="utf-8")
        self.assertIn("'docs/publisher-safe-audit-2026-10-25.md'", workflow)
        self.assertIn("'docs/publisher-one-shot-v2-2026-10-25.md'", workflow)
        self.assertIn("fetch-depth: 2", workflow)
        self.assertIn("run: python publisher_one_shot_gate.py", workflow)
        self.assertIn("MODE: ${{ steps.release_gate.outputs.mode }}", workflow)
        for name in ("Persist intent before any Meta upload",
                     "Publish explicitly planned Meta videos"):
            step = workflow.split("- name: " + name, 1)[1].split("- name:", 1)[0]
            self.assertIn("steps.release_gate.outputs.publish_allowed == 'true'", step)
        notifications = workflow.split("- name: Per-post Telegram and ntfy", 1)[1].split(
            "- name: Generate final per-run incident", 1)[0]
        self.assertIn("steps.release_gate.outputs.publish_allowed == 'true'", notifications)

    def test_audit_marker_or_changed_release_marker_cannot_publish(self):
        for subject, added, ref in (
            (SUBJECT, (), "refs/heads/main"),
            (SUBJECT, ("docs/publisher-safe-audit-2026-10-25.md",), "refs/heads/main"),
            (SUBJECT, (MARKER,), "refs/heads/feature"),
            ("wrong message", (MARKER,), "refs/heads/main"),
        ):
            self.assertEqual(determine_mode("push", ref, subject, added), "audit")
        self.assertEqual(
            determine_mode("push", "refs/heads/main", SUBJECT, (MARKER,)), "publish"
        )

    def test_exact_new_ig_recovery_marker_only_allows_approved_main_push(self):
        self.assertEqual(determine_mode(
            "push", "refs/heads/main", IG_RESCUE_SUBJECT, (IG_RESCUE_MARKER,)),
            "publish")
        self.assertTrue(is_ig_rescue_push(
            "push", "refs/heads/main", IG_RESCUE_SUBJECT, (IG_RESCUE_MARKER,)))
        for subject, added, ref in (
            (IG_RESCUE_SUBJECT, (), "refs/heads/main"),
            (IG_RESCUE_SUBJECT, (IG_RESCUE_MARKER,), "refs/heads/feature"),
            ("wrong", (IG_RESCUE_MARKER,), "refs/heads/main"),
            (SUBJECT, (IG_RESCUE_MARKER,), "refs/heads/main"),
        ):
            self.assertEqual(determine_mode("push", ref, subject, added), "audit")
        workflow = Path(".github/workflows/public_link_schedule.yml").read_text()
        self.assertIn(IG_RESCUE_MARKER, workflow)
        self.assertIn("IG_AUDITED_RESCUE_ONLY", workflow)

    def test_schedule_and_manual_modes_preserved(self):
        self.assertEqual(determine_mode("schedule", "refs/heads/main"), "publish")
        self.assertEqual(determine_mode("workflow_dispatch", "refs/heads/main",
                                        requested_mode="audit"), "audit")
        self.assertEqual(determine_mode("workflow_dispatch", "refs/heads/main",
                                        requested_mode="publish"), "publish")

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
