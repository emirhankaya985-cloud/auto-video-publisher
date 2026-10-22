import os
import unittest
from unittest.mock import Mock, patch

import requests

from ntfy_notifications import _json_endpoint_and_topic, send_ntfy


class NtfyDeliveryTests(unittest.TestCase):
    def test_secret_topic_url_uses_json_root(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200)
        with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://ntfy.sh/secret-topic"}, clear=True):
            self.assertEqual(send_ntfy("hi", "body", session=session), 200)
        self.assertEqual(session.post.call_args.args[0], "https://ntfy.sh/")
        self.assertEqual(session.post.call_args.kwargs["json"]["topic"], "secret-topic")
        self.assertEqual(session.post.call_args.kwargs["allow_redirects"], False)
        session.post.return_value.raise_for_status.assert_called_once()

    def test_custom_ntfy_server_path_prefix(self):
        with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://host.example/ntfy/topic-name"}, clear=True):
            self.assertEqual(_json_endpoint_and_topic(), ("https://host.example/ntfy", "topic-name"))

    def test_legacy_topic_fallback(self):
        session = Mock()
        session.post.return_value = Mock(status_code=201)
        with patch.dict(os.environ, {"NTFY_TOPIC": "private-topic"}, clear=True):
            self.assertEqual(send_ntfy("title", "body", session=session), 201)
        self.assertEqual(session.post.call_args.kwargs["json"]["topic"], "private-topic")

    def test_url_credentials_and_query_are_rejected_without_leaking(self):
        invalid = [
            "https://user:password@ntfy.sh/topsecret",
            "https://ntfy.sh/topsecret?token=123",
            "https://ntfy.sh/topsecret#secret",
            "https://ntfy.sh/topsecret%2fother",
            "ftp://ntfy.sh/topsecret",
            "https://ntfy.sh/",
        ]
        for url in invalid:
            with self.subTest(url=url), patch.dict(os.environ, {"NTFY_TOPIC_URL": url}, clear=True):
                with self.assertRaises(RuntimeError) as ctx:
                    _json_endpoint_and_topic()
                self.assertNotIn("topsecret", str(ctx.exception))

    def test_no_retry_or_secret_leak_on_transport_failure(self):
        session = Mock()
        session.post.side_effect = requests.ConnectionError("https://ntfy.sh/private-topic")
        with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://ntfy.sh/private-topic"}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                send_ntfy("title", "body", session=session)
        self.assertNotIn("private-topic", str(ctx.exception))
        self.assertEqual(session.post.call_count, 1)

    def test_redirect_rejected_and_private_payload_not_forwarded(self):
        session = Mock()
        session.post.return_value = Mock(status_code=307)
        with patch.dict(os.environ, {"NTFY_TOPIC": "super-secret"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "not accepted"):
                send_ntfy("title", "body", session=session)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.post.call_args.kwargs["allow_redirects"], False)

    def test_priorities_and_click_are_validated_before_post(self):
        session = Mock()
        with patch.dict(os.environ, {"NTFY_TOPIC": "my-topic"}, clear=True):
            with self.assertRaises(ValueError):
                send_ntfy("t", "b", priority=9, session=session)
            with self.assertRaises(ValueError):
                send_ntfy("t", "b", priority=True, session=session)
            with self.assertRaises(ValueError):
                send_ntfy("t", "b", click="javascript:alert(1)", session=session)
        session.post.assert_not_called()

    def test_max_message_size_checked_in_utf8_bytes(self):
        session = Mock()
        with patch.dict(os.environ, {"NTFY_TOPIC": "my-topic"}, clear=True):
            with self.assertRaisesRegex(ValueError, "4096"):
                send_ntfy("t", "🌙" * 1200, session=session)
        session.post.assert_not_called()

    def test_server_ack_matches_private_topic_without_exposing_it(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {
            "id": "abc123", "event": "message", "topic": "private-notify", "message": "hello",
        }
        session.post.return_value = response
        with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://ntfy.sh/private-notify"}, clear=True):
            result = send_ntfy("Health", "hello", session=session, require_ack=True)
        self.assertEqual(result, {"http_status": 200, "server_ack": True})
        self.assertEqual(session.post.call_count, 1)

    def test_server_ack_mismatch_fails_closed_without_private_topic_leak(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"id": "abc123", "event": "message", "topic": "wrong-topic"}
        session.post.return_value = response
        with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://ntfy.sh/private-notify"}, clear=True):
            with self.assertRaises(RuntimeError) as err:
                send_ntfy("Health", "hello", session=session, require_ack=True)
        self.assertNotIn("private-notify", str(err.exception))
        self.assertNotIn("wrong-topic", str(err.exception))
        self.assertEqual(session.post.call_count, 1)

    def test_server_ack_invalid_json_is_sanitized(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("private-secret-body")
        session.post.return_value = response
        with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://ntfy.sh/private-notify"}, clear=True):
            with self.assertRaises(RuntimeError) as err:
                send_ntfy("Health", "hello", session=session, require_ack=True)
        self.assertNotIn("private-secret-body", str(err.exception))
        self.assertNotIn("private-notify", str(err.exception))
        self.assertEqual(session.post.call_count, 1)

    def test_default_delivery_contract_remains_plain_http_status(self):
        session = Mock()
        response = Mock(status_code=200)
        session.post.return_value = response
        with patch.dict(os.environ, {"NTFY_TOPIC": "my-topic"}, clear=True):
            self.assertEqual(send_ntfy("Health", "hello", session=session), 200)
        response.json.assert_not_called()

    def test_http_errors_do_not_expose_private_topic(self):
        response = Mock(status_code=429)
        error = requests.HTTPError("private-topic", response=response)
        session = Mock()
        session.post.return_value.raise_for_status.side_effect = error
        with patch.dict(os.environ, {"NTFY_TOPIC": "private-topic"}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                send_ntfy("t", "body", session=session)
        self.assertIn("HTTP 429", str(ctx.exception))
        self.assertNotIn("private-topic", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
