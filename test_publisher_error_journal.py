"""Verify per-run errors are complete, redacted and never fake publications."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publisher_error_journal import error_event, record_error, read_errors
from publisher_incident_report import build_incident_report


class DiagnosticMetaError(RuntimeError):
    http_status = 400
    code = 100
    subcode = 2207009
    stage = "Instagram ikili video aktarımı"


class ErrorJournalTests(unittest.TestCase):
    def test_preserves_every_error_with_video_stage_codes_and_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GITHUB_RUN_ID": "915"}):
            f = Path(tmp) / "events.jsonl"
            record_error("instagram_publish", "invalid_media_or_graph_request",
                         route="penguen", platform="instagram", video="111.mp4",
                         error=DiagnosticMetaError("https://example.org/?access_token=secret"),
                         status="uncertain", path=f)
            record_error("toonzone_cover", "cover_missing",
                         route="toonzone", video="S02E01_Part1.mp4", path=f)
            items = read_errors(f, run_id="915")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["http_status"], 400)
        self.assertEqual(items[0]["graph_subcode"], 2207009)
        self.assertEqual(items[0]["meta_stage"], "Instagram ikili video aktarımı")
        self.assertEqual(items[0]["video"], "111.mp4")
        self.assertEqual(items[1]["reason"], "cover_missing")
        self.assertNotIn("access_token", json.dumps(items))
        self.assertNotIn("secret", json.dumps(items))

    def test_real_publisher_meta_and_youtube_errors_are_registered(self):
        # Each pair below occurs in production code; an unknown journal label
        # must not replace the original error with an unexpected ValueError.
        pairs = [
            ("publication_preflight", "intent_validation_failed", "facebook"),
            ("instagram_publish", "existing_container_reconciliation_failed", "instagram"),
            ("youtube_prepare", "missing_secret", "youtube"),
            ("youtube_publish", "youtube_publication_unverified", "youtube"),
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GITHUB_RUN_ID": "9321"}):
            path = Path(tmp) / "events.jsonl"
            for stage, reason, platform in pairs:
                record_error(stage, reason, route="penguen", platform=platform,
                             error=RuntimeError("private-token-goes-here"), path=path)
            events = read_errors(path, run_id="9321")
        self.assertEqual(len(events), len(pairs))
        self.assertEqual([(x["stage"], x["reason"], x["platform"]) for x in events], pairs)
        self.assertTrue(all(x["retry_policy"] == "never_blindly_retry_meta_post" for x in events))
        self.assertNotIn("private-token-goes-here", json.dumps(events))

    def test_rejects_paths_urls_in_identifiers_and_unsafe_reason(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "915"}):
            event = error_event("txt_caption", "txt_unavailable",
                                video="https://signed.example/video.mp4?token=secret",
                                route="/home/runner/secret")
        self.assertEqual(event["video"], "[redacted]")
        self.assertEqual(event["route"], "[redacted]")
        with self.assertRaises(ValueError):
            error_event("not-a-stage", "txt_unavailable")

    def test_report_contains_all_errors_and_failing_ci_steps(self):
        event = {"run_id": "915", "reason": "txt_unavailable",
                 "stage": "txt_caption", "video": "13.mp4"}
        result = build_incident_report({"entries": {}}, "915",
                                       errors=[event, event, {**event, "run_id": "914"}],
                                       step_outcomes={"verify": "failure", "publish": "skipped",
                                                      "notify": "success", "other": "failure"})
        self.assertEqual(result["schema"], 2)
        self.assertEqual(result["error_event_count"], 2)
        self.assertEqual(result["step_outcomes"]["verify"], "failure")
        self.assertNotIn("other", result["step_outcomes"])
        self.assertIn("actions/runs/915", result["run_url"])

    def test_read_filters_old_run_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "journal"
            f.write_text('{"run_id":"914","stage":"txt_caption"}\n'
                         '{"run_id":"915","stage":"drive_inventory"}\n', encoding="utf-8")
            self.assertEqual([r["stage"] for r in read_errors(f, run_id="915")],
                             ["drive_inventory"])


if __name__ == "__main__":
    unittest.main()
