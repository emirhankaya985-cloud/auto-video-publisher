"""No-network tests for one-time local YouTube OAuth bootstrap."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from youtube_authorize_channel import TOKEN_PATHS, authorize, verify_selected_channel


class YoutubeOauthSetupTests(unittest.TestCase):
    def test_targets_are_exactly_four_expected_channels(self):
        self.assertEqual(set(TOKEN_PATHS), {"channel1", "channel2", "daily_laugh", "gonle_dusen"})

    def test_does_not_overwrite_existing_token_or_run_oauth(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            token = folder / TOKEN_PATHS["channel1"]
            token.write_text("DO_NOT_REPLACE")
            with self.assertRaises(FileExistsError):
                authorize("channel1", base_dir=folder)
            self.assertEqual(token.read_text(), "DO_NOT_REPLACE")

    def test_renew_existing_token_only_after_exact_verified_channel(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            token = folder / TOKEN_PATHS["channel1"]
            token.write_text("OLD_EXPIRED_TOKEN", encoding="utf-8")
            (folder / "client_secrets.json").write_text("LOCAL_CLIENT", encoding="utf-8")
            credentials = Mock(refresh_token="NEW_OFFLINE_REFRESH")
            credentials.to_json.return_value = '{"refresh_token":"NEW_OFFLINE_REFRESH"}'
            flow = Mock()
            flow.run_local_server.return_value = credentials
            with (patch("youtube_authorize_channel.InstalledAppFlow.from_client_secrets_file",
                        return_value=flow) as factory,
                  patch("youtube_authorize_channel.verify_selected_channel",
                        return_value=("UCrUF3mT4oF26JNBLcyKPcGQ", "Tarladaki Fasulye")) as verify):
                authorize("channel1", base_dir=folder, renew=True)
                self.assertEqual(token.read_text(encoding="utf-8"),
                                 '{"refresh_token":"NEW_OFFLINE_REFRESH"}')
                verify.assert_called_once_with(credentials, "channel1")
                factory.assert_called_once_with(str(folder / "client_secrets.json"), scopes=[
                    "https://www.googleapis.com/auth/youtube.upload",
                    "https://www.googleapis.com/auth/youtube.readonly",
                ])
                self.assertEqual(list(folder.glob(".youtube-token-renew-*")), [])

    def test_wrong_channel_renew_keeps_prior_token_and_no_partial_file(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            token = folder / TOKEN_PATHS["channel2"]
            token.write_text("KEEP_UNTIL_VERIFIED", encoding="utf-8")
            (folder / "client_secrets.json").write_text("LOCAL_CLIENT", encoding="utf-8")
            creds = Mock(refresh_token="NEW")
            flow = Mock()
            flow.run_local_server.return_value = creds
            with (patch("youtube_authorize_channel.InstalledAppFlow.from_client_secrets_file",
                        return_value=flow),
                  patch("youtube_authorize_channel.verify_selected_channel",
                        side_effect=RuntimeError("wrong_channel"))):
                with self.assertRaisesRegex(RuntimeError, "wrong_channel"):
                    authorize("channel2", base_dir=folder, renew=True)
            self.assertEqual(token.read_text(encoding="utf-8"), "KEEP_UNTIL_VERIFIED")
            self.assertEqual(list(folder.glob(".youtube-token-renew-*")), [])

    def test_missing_refresh_token_never_overwrites_existing_secret(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            token = folder / TOKEN_PATHS["daily_laugh"]
            token.write_text("CURRENT_TOKEN", encoding="utf-8")
            (folder / "client_secrets.json").write_text("LOCAL_CLIENT", encoding="utf-8")
            flow = Mock()
            flow.run_local_server.return_value = Mock(refresh_token=None)
            with patch("youtube_authorize_channel.InstalledAppFlow.from_client_secrets_file",
                       return_value=flow):
                with self.assertRaisesRegex(RuntimeError, "refresh token"):
                    authorize("daily_laugh", base_dir=folder, renew=True)
            self.assertEqual(token.read_text(encoding="utf-8"), "CURRENT_TOKEN")

    def test_missing_oauth_client_fails_without_token_creation(self):
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaises(FileNotFoundError):
                authorize("daily_laugh", base_dir=dirname)
            self.assertFalse((Path(dirname) / TOKEN_PATHS["daily_laugh"]).exists())
            with self.assertRaises(FileNotFoundError):
                authorize("gonle_dusen", base_dir=dirname)
            self.assertFalse((Path(dirname) / TOKEN_PATHS["gonle_dusen"]).exists())

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
