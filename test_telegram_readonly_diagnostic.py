"""Verify Telegram diagnostics without making network calls or sending messages."""
import unittest
from unittest.mock import Mock

from telegram_readonly_diagnostic import diagnose


class TelegramReadonlyDiagnosticTests(unittest.TestCase):
    TOKEN = "123456:" + "A" * 30
    CHAT = "-1001234567890"

    def test_safe_success_only_reads_bot_and_chat(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"id": 1234}}
        get = Mock(return_value=response)
        actual = diagnose(token=self.TOKEN, chat_id=self.CHAT, get=get)
        self.assertEqual(actual, {"status": "healthy", "code": "bot_and_chat_readable", "message_sent": False})
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all(call.args[0].endswith(("/getMe", "/getChat")) for call in get.call_args_list))
        self.assertEqual(get.call_args_list[0].kwargs["params"], {})
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"chat_id": self.CHAT})
        self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in get.call_args_list))

    def test_chat_http_400_classified_without_leaking_chat(self):
        good = Mock(status_code=200)
        good.json.return_value = {"ok": True, "result": {"id": 1234}}
        bad = Mock(status_code=400)
        get = Mock(side_effect=[good, bad])
        result = diagnose(token=self.TOKEN, chat_id=self.CHAT, get=get)
        self.assertEqual(result["code"], "telegram_getchat_http_400")
        self.assertNotIn(self.CHAT, str(result))
        self.assertNotIn(self.TOKEN, str(result))

    def test_invalid_token_cannot_leave_process(self):
        get = Mock()
        actual = diagnose(token="123", chat_id=self.CHAT, get=get)
        self.assertEqual(actual["code"], "telegram_bot_token_format")
        get.assert_not_called()

    def test_bot_token_http_401_classified(self):
        get = Mock(return_value=Mock(status_code=401))
        actual = diagnose(token=self.TOKEN, chat_id=self.CHAT, get=get)
        self.assertEqual(actual["code"], "telegram_getme_http_401")

    def test_missing_secret_no_network(self):
        get = Mock()
        actual = diagnose(token="", chat_id=self.CHAT, get=get)
        self.assertEqual(actual["code"], "telegram_secrets_missing")
        get.assert_not_called()

    def test_no_raw_server_response_in_logs_or_errors(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": False, "description": "secret-bot-token"}
        get = Mock(return_value=response)
        result = diagnose(token=self.TOKEN, chat_id=self.CHAT, get=get)
        self.assertEqual(result["code"], "telegram_getme_receipt_invalid")
        self.assertNotIn("secret-bot-token", str(result))


if __name__ == "__main__":
    unittest.main()
