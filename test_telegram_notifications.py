import os
import unittest
from unittest.mock import Mock, patch

import requests

from telegram_notifications import telegram_configured, send_telegram

ENV = {"TELEGRAM_BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
       "TELEGRAM_CHAT_ID": "-1001234567890"}


class TelegramNotificationTests(unittest.TestCase):
    def test_missing_credentials_send_nothing(self):
        transport = Mock()
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(telegram_configured())
            with self.assertRaisesRegex(RuntimeError, "credentials"):
                send_telegram("title", "message", session=transport)
        transport.post.assert_not_called()

    def test_valid_receipt_and_plain_text(self):
        transport = Mock()
        transport.post.return_value = Mock(
            status_code=200, json=lambda: {
                "ok": True, "result": {"message_id": 42}})
        with patch.dict(os.environ, ENV, clear=True):
            self.assertTrue(telegram_configured())
            result = send_telegram("✅ Test", "Daily report", session=transport)
        self.assertEqual(result["server_ack"], True)
        args, kw = transport.post.call_args
        self.assertTrue(args[0].startswith("https://api.telegram.org/bot"))
        self.assertEqual(kw["json"]["chat_id"], ENV["TELEGRAM_CHAT_ID"])
        self.assertIn("Daily report", kw["json"]["text"])
        self.assertNotIn("parse_mode", kw["json"])
        self.assertIs(kw["allow_redirects"], False)
        self.assertEqual(transport.post.call_count, 1)

    def test_redirect_refused_no_credential_echo(self):
        transport = Mock()
        transport.post.return_value = Mock(status_code=302)
        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaises(RuntimeError) as error:
                send_telegram("title", "body", session=transport)
        self.assertNotIn(ENV["TELEGRAM_BOT_TOKEN"], str(error.exception))
        self.assertEqual(transport.post.call_count, 1)

    def test_server_rejection_sanitized(self):
        transport = Mock()
        transport.post.return_value = Mock(status_code=200,
                                           json=lambda: {"ok": False, "description": "private"})
        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaises(RuntimeError) as error:
                send_telegram("title", "body", session=transport)
        self.assertNotIn("private", str(error.exception))

    def test_transport_error_sanitized_without_retry(self):
        transport = Mock()
        transport.post.side_effect = requests.ConnectionError(ENV["TELEGRAM_BOT_TOKEN"])
        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaises(RuntimeError) as error:
                send_telegram("title", "body", session=transport)
        self.assertNotIn(ENV["TELEGRAM_BOT_TOKEN"], str(error.exception))
        self.assertEqual(transport.post.call_count, 1)

    def test_large_report_is_bounded(self):
        transport = Mock()
        transport.post.return_value = Mock(
            status_code=200, json=lambda: {"ok": True, "result": {"message_id": 1}})
        with patch.dict(os.environ, ENV, clear=True):
            send_telegram("Report", "🌙" * 5000, session=transport)
        self.assertLessEqual(len(transport.post.call_args.kwargs["json"]["text"]), 3900)

    def test_malformed_bot_credentials_do_not_hit_network(self):
        transport = Mock()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "malicious/path", "TELEGRAM_CHAT_ID": "1"}, clear=True):
            with self.assertRaises(RuntimeError):
                send_telegram("title", "body", session=transport)
        transport.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
