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


class TelegramSmokeDiagnosticTests(unittest.TestCase):
    def test_safe_failure_code_never_echoes_secrets(self):
        from telegram_smoke_test import safe_failure_code
        codes = {
            "telegram credentials missing or invalid: bot token missing": "bot_token_missing",
            "telegram credentials missing or invalid: chat id missing": "chat_id_missing",
            "telegram credentials missing or invalid: bot token format": "bot_token_format_invalid",
            "telegram credentials missing or invalid: chat id format": "chat_id_format_invalid",
            "telegram delivery not accepted HTTP 400": "telegram_http_400",
            "telegram delivery not accepted HTTP 401": "telegram_http_401",
            "telegram delivery not accepted HTTP 403": "telegram_http_403",
            "telegram delivery not accepted HTTP 429": "telegram_http_429",
            "telegram delivery not accepted HTTP 418": "telegram_http_other",
            "telegram delivery failed (ConnectionError)": "telegram_connection_failed",
            "telegram server receipt mismatch": "telegram_rejected_response",
        }
        for message, code in codes.items():
            with self.subTest(message=message):
                self.assertEqual(safe_failure_code(RuntimeError(message)), code)
        self.assertEqual(safe_failure_code(RuntimeError(
            "HTTP response secretly includes 123456789:private-token"
        )), "telegram_error")

    def test_smoke_diagnostic_logs_only_allowlisted_code(self):
        import io
        import json
        from contextlib import redirect_stdout
        import telegram_smoke_test

        output = io.StringIO()
        with patch("telegram_smoke_test.send_telegram",
                   side_effect=RuntimeError("telegram delivery not accepted HTTP 403")), redirect_stdout(output):
            self.assertEqual(telegram_smoke_test.main(), 1)
        self.assertEqual(json.loads(output.getvalue())["error_code"], "telegram_http_403")
        self.assertNotIn("bot", output.getvalue())
        self.assertNotIn("chat", output.getvalue())

    def test_smoke_success_uses_receipt(self):
        import io
        import json
        from contextlib import redirect_stdout
        import telegram_smoke_test

        output = io.StringIO()
        with patch("telegram_smoke_test.send_telegram",
                   return_value={"http_status": 200, "server_ack": True}), redirect_stdout(output):
            self.assertEqual(telegram_smoke_test.main(), 0)
        self.assertTrue(json.loads(output.getvalue())["server_ack"])

    def test_specific_configuration_error_does_not_call_network(self):
        transport = Mock()
        env = {"TELEGRAM_BOT_TOKEN": "invalid", "TELEGRAM_CHAT_ID": "-100123456789"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "bot token format"):
                send_telegram("hi", "hello", session=transport)
        transport.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
