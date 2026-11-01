"""No-network tests for YouTube OAuth secret-check workflow."""
import json
import unittest
from unittest.mock import Mock, patch

from youtube_readonly_connection import TARGETS, check_channel, main

AUTH_DATA = {
    "client_id": "mock-client",
    "client_secret": "private_client_secret",
    "refresh_token": "private_refresh_token",
    "token_uri": "https://oauth2.googleapis.com/token",
    "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
}


def session_for(title, channel_id="some_channel_id", http_status=200):
    session = Mock()
    session.get.return_value = Mock(
        status_code=http_status,
        json=lambda: {"items": [{"id": channel_id, "snippet": {"title": title}}]},
    )
    return Mock(return_value=session), session


class YouTubeReadOnlyCheckTests(unittest.TestCase):
    def test_missing_credentials_is_safe_and_does_not_connect(self):
        factory = Mock()
        verdict = check_channel("channel1", environ={}, session_factory=factory)
        self.assertEqual(verdict["status"], "missing_github_secret")
        self.assertEqual(verdict["secret_name"], "TOKEN_CHANNEL1_JSON")
        factory.assert_not_called()

    def test_malformed_json_or_client_file_rejected(self):
        self.assertEqual(check_channel("channel1",
            environ={"TOKEN_CHANNEL1_JSON": "not-json"})["status"], "invalid_authorized_user_json")
        self.assertEqual(check_channel("channel1",
            environ={"TOKEN_CHANNEL1_JSON": '{"installed": {"client_id": "foo"}}'})["status"],
            "not_an_authorized_user_token")

    def test_oauth_client_json_is_diagnosed_without_disclosing_values(self):
        client = {"installed": {"client_id": "private-client-id",
                                "client_secret": "private-secret"}}
        report = check_channel("channel1",
            environ={"TOKEN_CHANNEL1_JSON": json.dumps(client)})
        self.assertEqual(report["status"], "not_an_authorized_user_token")
        self.assertEqual(report["json_kind"], "oauth_client_json")
        self.assertEqual(report["missing_fields"],
                         ["client_id", "client_secret", "refresh_token", "token_uri"])
        self.assertNotIn("private-", json.dumps(report))

    def test_missing_refresh_token_identified_safely(self):
        partial = dict(AUTH_DATA)
        partial.pop("refresh_token")
        report = check_channel("channel2",
            environ={"TOKEN_CHANNEL2_JSON": json.dumps(partial)})
        self.assertEqual(report["status"], "not_an_authorized_user_token")
        self.assertEqual(report["json_kind"], "incomplete_authorized_user_json")
        self.assertEqual(report["missing_fields"], ["refresh_token"])
        self.assertNotIn(partial["client_secret"], json.dumps(report))

    def test_required_upload_scope(self):
        data = dict(AUTH_DATA, scopes=["https://www.googleapis.com/auth/youtube.readonly"])
        self.assertEqual(check_channel("channel1",
            environ={"TOKEN_CHANNEL1_JSON": json.dumps(data)})["status"],
            "youtube_upload_scope_missing")

    def test_first_channel_identity_and_no_writes(self):
        factory, session = session_for("Tarladaki Fasulye")
        with patch("youtube_readonly_connection.Credentials.from_authorized_user_info") as creds:
            verdict = check_channel("channel1",
                environ={"TOKEN_CHANNEL1_JSON": json.dumps(AUTH_DATA)}, session_factory=factory)
        self.assertEqual(verdict["status"], "verified")
        self.assertEqual(verdict["channel_title"], "Tarladaki Fasulye")
        session.post.assert_not_called()
        session.put.assert_not_called()
        session.patch.assert_not_called()
        session.delete.assert_not_called()
        args, kwargs = session.get.call_args
        self.assertTrue(args[0].endswith("/channels"))
        self.assertEqual(kwargs["params"]["mine"], "true")
        self.assertFalse(kwargs["allow_redirects"])
        creds.assert_called_once()

    def test_wrong_channel_is_not_accepted(self):
        factory, session = session_for("Beyinsiz Penguen")
        with patch("youtube_readonly_connection.Credentials.from_authorized_user_info"):
            verdict = check_channel("channel1",
                environ={"TOKEN_CHANNEL1_JSON": json.dumps(AUTH_DATA)}, session_factory=factory)
        self.assertEqual(verdict["status"], "wrong_channel")

    def test_daily_laugh_must_match_channel_id(self):
        factory, _ = session_for("Daily Laugh Lab", "incorrect_id")
        with patch("youtube_readonly_connection.Credentials.from_authorized_user_info"):
            verdict = check_channel("daily_laugh",
                environ={"TOKEN_DAILY_LAUGH_LAB_JSON": json.dumps(AUTH_DATA)},
                session_factory=factory)
        self.assertEqual(verdict["status"], "wrong_channel")
        factory, _ = session_for("Daily Laugh Lab", "UCF4KwI3alXzlExviMFmmJAA")
        with patch("youtube_readonly_connection.Credentials.from_authorized_user_info"):
            verdict = check_channel("daily_laugh",
                environ={"TOKEN_DAILY_LAUGH_LAB_JSON": json.dumps(AUTH_DATA)},
                session_factory=factory)
        self.assertEqual(verdict["status"], "verified")

    def test_transport_rejection_only_prints_safe_code(self):
        factory, session = session_for("unused", http_status=403)
        with patch("youtube_readonly_connection.Credentials.from_authorized_user_info"):
            verdict = check_channel("channel2",
                environ={"TOKEN_CHANNEL2_JSON": json.dumps(AUTH_DATA)}, session_factory=factory)
        self.assertEqual(verdict["status"], "youtube_api_rejected")
        self.assertNotIn(AUTH_DATA["refresh_token"], json.dumps(verdict))
        self.assertEqual(verdict["http_status"], 403)

    def test_auth_failure_redacts_private_data(self):
        factory=Mock(side_effect=RuntimeError("private_refresh_token"))
        with patch("youtube_readonly_connection.Credentials.from_authorized_user_info"):
            verdict = check_channel("channel1",
                environ={"TOKEN_CHANNEL1_JSON": json.dumps(AUTH_DATA)}, session_factory=factory)
        self.assertEqual(verdict["status"], "authorization_or_connection_failed")
        self.assertNotIn(AUTH_DATA["refresh_token"], json.dumps(verdict))

    def test_gonle_dusen_secret_and_exact_channel_id(self):
        self.assertEqual(check_channel("gonle_dusen", environ={})["secret_name"],
                         "TOKEN_GONLE_DUSEN_JSON")
        for channel, expected_status in (
            ("UCvSvo5WghuXqsjwLRmIz22g", "verified"),
            ("different-channel", "wrong_channel"),
        ):
            with self.subTest(channel=channel):
                factory, session = session_for("Gönle Düşen", channel)
                with patch("youtube_readonly_connection.Credentials.from_authorized_user_info"):
                    verdict = check_channel(
                        "gonle_dusen",
                        environ={"TOKEN_GONLE_DUSEN_JSON": json.dumps(AUTH_DATA)},
                        session_factory=factory,
                    )
                self.assertEqual(verdict["status"], expected_status)
                session.post.assert_not_called()

    def test_invalid_target(self):
        self.assertEqual(check_channel("other")["status"], "invalid_target")
        self.assertEqual(set(TARGETS), {"channel1", "channel2", "daily_laugh", "gonle_dusen"})


if __name__ == "__main__":
    unittest.main()
