import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ig_180s_under12mb_diagnostic as diag


class LongNoPublishDiagnosticTests(unittest.TestCase):
    def test_unpublished_upload_passes_explicit_false_and_keeps_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "input.mp4"
            original.write_bytes(b"some original file")
            def compress(_src, target):
                target.write_bytes(b"verified-180s-video")
                return target
            uploader = Mock(return_value={"status": "FINISHED", "published": False,
                                          "container_id": "17903738595599675"})
            outcome = diag.trial({"page_token": "SENSITIVE"}, original, "Part16.mp4",
                                 root, encode=compress, upload=uploader)
            self.assertEqual(outcome["status"], "FINISHED_NOT_PUBLISHED")
            self.assertIs(uploader.call_args.kwargs["publish"], False)
            self.assertIs(uploader.call_args.kwargs["append_store_link"], False)
            self.assertEqual(uploader.call_count, 1)

    def test_oversized_diagnostic_is_blocked_before_meta(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"input")
            def oversized(_, target):
                with target.open("wb") as out:
                    out.truncate(diag.MAX_TEST_BYTES + 1)
                return target
            upload = Mock()
            with self.assertRaisesRegex(RuntimeError, "not eligible"):
                diag.trial({}, source, "source.mp4", root, encode=oversized, upload=upload)
            upload.assert_not_called()

    def test_claim_of_published_result_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"clip")
            result = Mock(return_value={"status": "FINISHED", "published": True,
                                        "container_id": "123"})
            with self.assertRaisesRegex(RuntimeError, "without publishing"):
                diag.trial({}, source, "source.mp4", root, encode=lambda _s, t: source, upload=result)

    def test_ffmpeg_command_retains_full_length_with_strict_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output = root / "source.mp4", root / "out.mp4"
            source.write_bytes(b"x" * 1024)
            media = {"format": {"duration": "180.0"}}
            def ffmpeg(args, **kwargs):
                output.write_bytes(b"encoded-verified")
            with patch("instagram_media_compat.probe", return_value=media), \
                 patch("instagram_media_compat.mp4_atom_structure", return_value={
                     "moov_front": True, "edit_list": False, "valid": True,
                 }), \
                 patch("instagram_media_compat.compatibility_issues", return_value=[]), \
                 patch("instagram_media_compat.check_full_decode", return_value=True):
                path = diag.low_size_full_clip(source, output, run=ffmpeg)
            self.assertEqual(path, output)
            self.assertEqual(output.read_bytes(), b"encoded-verified")

    def test_one_time_gate_and_unchanged_intents(self):
        with patch.dict(os.environ, {"IG_LONGCLIP_UPLOADONLY_APPROVED": "false"}), \
             patch.object(diag, "execute") as execute:
            with self.assertRaisesRegex(RuntimeError, "dedicated one-time"):
                diag.main()
            execute.assert_not_called()

    def test_source_has_no_publication_calls(self):
        src = Path(diag.__file__).read_text()
        self.assertIn("publish=False", src)
        self.assertNotIn("requests.post(", src)
        self.assertNotIn("media_publish(", src)


if __name__ == "__main__":
    unittest.main()
