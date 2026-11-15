"""Offline tests: local token reuse requires exact live YouTube identity."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import youtube_local_token_probe as target
from youtube_readonly_connection import TARGETS
from youtube_authorize_channel import TOKEN_PATHS


def token_info():
    return json.dumps({"client_id": "test.apps.googleusercontent.com",
                       "client_secret": "TEST_SECRET",
                       "refresh_token": "TEST_REFRESH",
                       "token_uri": "https://oauth2.googleapis.com/token",
                       "scopes": ["https://www.googleapis.com/auth/youtube.upload"]})


class LocalTokenProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)

    def put(self, route="channel1", content=None):
        path = self.path / TOKEN_PATHS[route]
        path.write_text(token_info() if content is None else content, encoding="utf-8")
        return path

    def test_missing_token_does_not_access_google(self):
        getter = Mock()
        report = target.inspect_local("channel1", base_dir=self.path, checker=getter)
        self.assertEqual(report["status"], "local_token_missing")
        self.assertTrue(report["renewal_needed"])
        getter.assert_not_called()

    def test_existing_valid_token_reused_without_refresh_rotation(self):
        for route, (_, _, expected) in TARGETS.items():
            with self.subTest(route=route):
                local = self.put(route)
                before = local.read_text(encoding="utf-8")
                checker = Mock(return_value={"status": "verified",
                                             "channel_id": expected,
                                             "upload_scope_in_file": True})
                result = target.inspect_local(route, base_dir=self.path, checker=checker)
                self.assertEqual(result["status"], "verified_local_exact_channel")
                self.assertFalse(result["renewal_needed"])
                self.assertEqual(local.read_text(encoding="utf-8"), before)
                checker.assert_called_once_with(
                    route, environ={TARGETS[route][0]: before})
                self.assertNotIn("TEST_SECRET", str(result))

    def test_wrong_channel_cannot_be_reused(self):
        self.put("channel2")
        checker = Mock(return_value={"status": "verified", "channel_id": "UCWRONG",
                                     "upload_scope_in_file": True})
        result = target.inspect_local("channel2", base_dir=self.path, checker=checker)
        self.assertEqual(result["status"], "wrong_channel")
        self.assertTrue(result["renewal_needed"])

    def test_expired_token_retains_original_until_browser_authorization(self):
        file = self.put("channel1")
        checker = Mock(return_value={"status": "authorization_or_connection_failed",
                                     "error_type": "RefreshError"})
        before = file.read_bytes()
        result = target.inspect_local("channel1", base_dir=self.path, checker=checker)
        self.assertEqual(result["status"], "authorization_or_connection_failed")
        self.assertEqual(file.read_bytes(), before)
        self.assertNotIn("RefreshError", str(result))

    def test_declared_missing_youtube_upload_scope_never_reuses(self):
        self.put("gonle_dusen")
        checker = Mock(return_value={"status": "verified",
                                     "channel_id": TARGETS["gonle_dusen"][2],
                                     "upload_scope_in_file": False})
        result = target.inspect_local("gonle_dusen", base_dir=self.path, checker=checker)
        self.assertNotEqual(result["status"], "verified_local_exact_channel")
        self.assertTrue(result["renewal_needed"])

    def test_symlink_and_oversize_file_are_blocked_without_google(self):
        checker = Mock()
        other = self.put("channel1")
        link = self.path / TOKEN_PATHS["channel2"]
        try:
            link.symlink_to(other)
        except (NotImplementedError, OSError):
            pass
        else:
            result = target.inspect_local("channel2", base_dir=self.path, checker=checker)
            self.assertEqual(result["status"], "unsafe_local_symlink")
            self.assertFalse(result["renewal_needed"])
        big = self.put("daily_laugh", content="x" * (target.MAX_TOKEN_BYTES + 1))
        result = target.inspect_local("daily_laugh", base_dir=self.path, checker=checker)
        self.assertEqual(result["status"], "invalid_authorized_user_json")
        checker.assert_not_called()

    def test_malformed_target_is_not_accepted(self):
        getter = Mock()
        x = target.inspect_local("../../secrets", base_dir=self.path, checker=getter)
        self.assertEqual(x["status"], "invalid_target")
        getter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
