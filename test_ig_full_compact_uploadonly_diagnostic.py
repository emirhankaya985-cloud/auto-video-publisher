"""Regression: full-length IG diagnostic cannot publish or bypass gate."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ig_full_compact_uploadonly_diagnostic as diag


class FullCompactUnpublishedTests(unittest.TestCase):
    def test_gate_rejects_manual_and_unapproved(self):
        with patch.dict(os.environ, {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "emirhankaya985-cloud/auto-video-publisher",
            "IG_FULL_COMPACT_APPROVED": "true",
        }):
            with self.assertRaisesRegex(RuntimeError, "not authorized"):
                diag.require_exact_commit_gate()

    def test_gate_needs_exact_added_marker_and_subject(self):
        env = {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "emirhankaya985-cloud/auto-video-publisher",
            "IG_FULL_COMPACT_APPROVED": "true",
        }
        def output(cmd, **kwargs):
            return diag.SUBJECT if "log" in cmd else diag.MARKER
        with patch.dict(os.environ, env), patch.object(
            diag.subprocess, "check_output", side_effect=output
        ) as git:
            diag.require_exact_commit_gate()
            self.assertEqual(git.call_count, 2)
        with patch.dict(os.environ, env), patch.object(
            diag.subprocess, "check_output",
            side_effect=lambda args, **_: "wrong-subject" if "log" in args else diag.MARKER
        ):
            with self.assertRaisesRegex(RuntimeError, "release marker"):
                diag.require_exact_commit_gate()

    def test_180_second_media_is_processed_without_any_publish_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"source")
            target = Path(tmp) / "full_compact_unpublished.mp4"
            def encode(_src, _output, **kwargs):
                self.assertTrue(kwargs["film_compact"])
                self.assertTrue(kwargs["return_method"])
                target.write_bytes(b"fake-video")
                return (target, "transcode")
            with patch("instagram_media_compat.prepare_instagram_upload",
                       side_effect=encode), patch(
                "instagram_media_compat.probe",
                return_value={"format": {"duration": "180.1"}}
            ), patch("cloud_omnichannel_publisher.upload_instagram_reel",
                     return_value={"published": False, "status": "FINISHED",
                                   "container_id": "123456"}) as upload:
                out = diag.full_compact_trial(
                    {"page_token": "MOCK"}, source, "exact.mp4", tmp)
            self.assertEqual(out["status"], "FINISHED_NOT_PUBLISHED")
            self.assertIsNone(out["post_id"])
            upload.assert_called_once()
            self.assertFalse(upload.call_args.kwargs["publish"])
            self.assertFalse(upload.call_args.kwargs["append_store_link"])

    def test_wrong_duration_cannot_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "full_compact_unpublished.mp4"
            with patch("instagram_media_compat.prepare_instagram_upload",
                       return_value=(path, "transcode")), patch(
                "instagram_media_compat.probe",
                return_value={"format": {"duration": "15"}}
            ), patch("cloud_omnichannel_publisher.upload_instagram_reel") as upload:
                with self.assertRaisesRegex(RuntimeError, "180-second"):
                    diag.full_compact_trial({}, Path(tmp) / "source.mp4", "clip.mp4", tmp)
                upload.assert_not_called()

    def test_main_uses_strict_gate_and_cannot_claim_publication(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            diag, "execute", return_value={
                "schema": 1, "files": [
                    {"status": "FINISHED_NOT_PUBLISHED",
                     "published": False, "post_id": None}
                ], "media_publish_calls": 0
            }
        ) as execute, patch.object(diag, "Path") as _mock:
            # Avoid writing to repository in a synthetic CI run.
            _mock.return_value.write_text = Mock()
            self.assertEqual(diag.main(), 0)
            self.assertIs(execute.call_args.kwargs["gate"], diag.require_exact_commit_gate)
            self.assertIs(execute.call_args.kwargs["trial"], diag.full_compact_trial)


if __name__ == "__main__":
    unittest.main()
