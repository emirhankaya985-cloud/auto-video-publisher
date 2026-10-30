"""No-network tests for one-time local YouTube OAuth bootstrap."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from youtube_authorize_channel import TOKEN_PATHS, authorize, verify_selected_channel


class YoutubeOauthSetupTests(unittest.TestCase):
    def test_targets_are_exactly_three_expected_channels(self):
        self.assertEqual(set(TOKEN_PATHS), {"channel1", "channel2", "daily_laugh"})

    def test_does_not_overwrite_existing_token_or_run_oauth(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            token = folder / TOKEN_PATHS["channel1"]
            token.write_text("DO_NOT_REPLACE")
            with self.assertRaises(FileExistsError):
                authorize("channel1", base_dir=folder)
            self.assertEqual(token.read_text(), "DO_NOT_REPLACE")

    def test_missing_oauth_client_fails_without_token_creation(self):
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaises(FileNotFoundError):
                authorize("daily_laugh", base_dir=dirname)
            self.assertFalse((Path(dirname) / TOKEN_PATHS["daily_laugh"]).exists())

    def test_readonly_identity_verification_and_no_post(self):
        fake = Mock()
        fake.get.return_value = Mock(
            json=lambda: {"items": [{"id": "UCF4KwI3alXzlExviMFmmJAA", "snippet": {"title": "Daily Laugh Lab"}}]},
            raise_for_status=Mock(),
        )
        self.assertEqual(
            verify_selected_channel(Mock(), "daily_laugh", session_factory=lambda _creds: fake)[0],
            "UCF4KwI3alXzlExviMFmmJAA",
        )
        self.assertFalse(fake.get.call_args.kwargs["allow_redirects"])
        fake.post.assert_not_called()
        fake.put.assert_not_called()

    def test_wrong_channel_not_authorized(self):
        fake = Mock()
        fake.get.return_value = Mock(
            json=lambda: {"items": [{"id": "not-that-channel", "snippet": {"title": "Daily Laugh Lab"}}]},
            raise_for_status=Mock(),
        )
        with self.assertRaisesRegex(RuntimeError, "eşleşmiyor"):
            verify_selected_channel(Mock(), "daily_laugh", session_factory=lambda _: fake)


if __name__ == "__main__":
    unittest.main()
