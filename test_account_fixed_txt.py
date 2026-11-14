"""Fail-closed owner TXT routing with no network or Meta publishing."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from account_fixed_txt import FIXED_FILES, selected_txt, verify_text
import public_link_runtime as runtime


class AccountFixedTxtTests(unittest.TestCase):
    TEXT = "Owner-approved fixed copy. #Hashtag"

    def configuration(self, route="tarladaki"):
        prefix, filename = FIXED_FILES[route]
        digest = hashlib.sha256(self.TEXT.encode()).hexdigest()
        env = {"ENABLE_FIXED_ACCOUNT_TXT": "true", f"FIXED_{prefix}_TXT_SHA256": digest}
        return env, {filename: {"id": "1234567890abcdef", "name": filename}}

    def test_all_account_names_distinct_and_no_special_series(self):
        self.assertEqual(len(FIXED_FILES), 4)
        self.assertEqual(len({s[1] for s in FIXED_FILES.values()}), 4)
        env, files = self.configuration()
        self.assertIsNone(selected_txt("toonzone", files, environ=env))
        self.assertIsNone(selected_txt("film", files, environ=env))
        self.assertIsNone(selected_txt("film_second", files, environ=env))

    def test_legacy_unchanged_by_default(self):
        self.assertIsNone(selected_txt("tarladaki", {}, environ={}))
        self.assertIsNone(selected_txt("daily_laugh", {}, environ={}))

    def test_missing_per_account_txt_or_checksum_fails_closed(self):
        env, files = self.configuration()
        with self.assertRaisesRegex(RuntimeError, "missing_or_unverified"):
            selected_txt("penguen", files, environ=env)
        with self.assertRaisesRegex(RuntimeError, "checksum_not_configured"):
            selected_txt("tarladaki", files, environ={"ENABLE_FIXED_ACCOUNT_TXT": "true"})
        with self.assertRaisesRegex(RuntimeError, "unknown_route"):
            selected_txt("oddframes", files, environ=env)

    def test_no_silent_edited_caption_or_truncation(self):
        env, files = self.configuration()
        approved = selected_txt("tarladaki", files, environ=env)
        self.assertEqual(verify_text(self.TEXT, approved["sha256"]), self.TEXT)
        for changed in ("New content", "<html>malformed</html>", "x" * 2201):
            with self.assertRaises(RuntimeError):
                verify_text(changed, approved["sha256"])

    def test_fixed_route_ignores_per_video_txt_and_preserves_exact_copy(self):
        env, files = self.configuration()
        files["101.txt"] = {"id": "different-video-caption"}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, env, clear=False):
            def fake_download(_id, target):
                target.write_text(self.TEXT, encoding="utf-8")
                return target
            with patch.object(runtime, "download", side_effect=fake_download):
                cap1, provenance1 = runtime.copies("tarladaki", {"name": "101.mp4"}, files, Path(folder))
                cap2, provenance2 = runtime.copies("tarladaki", {"name": "102.mp4"}, files, Path(folder))
        self.assertEqual((provenance1, provenance2), ("account-fixed-txt", "account-fixed-txt"))
        self.assertEqual(cap1, cap2)
        self.assertIn(self.TEXT, cap1["instagram"])

    def test_daily_laugh_fixed_copy_has_no_stem_prefix(self):
        env, files = self.configuration("daily_laugh")
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, env, clear=False):
            def fake_download(_id, target):
                target.write_text(self.TEXT, encoding="utf-8")
                return target
            with patch.object(runtime, "download", side_effect=fake_download):
                caps, source = runtime.copies("daily_laugh", {"name": "201.mp4"}, files, Path(folder))
        self.assertEqual(source, "account-fixed-txt")
        self.assertNotIn("Video 201", caps["instagram"])


if __name__ == "__main__":
    unittest.main()
