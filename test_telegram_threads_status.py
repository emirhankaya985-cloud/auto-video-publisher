"""Read-only Threads owner status button: verified artifact identity and no writes."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from telegram_ai_worker import Worker, load_threads_status
from telegram_notifications import (THREADS_STATUS_BUTTON, THREADS_STATUS_CALLBACK_DATA,
                                    THREADS_INLINE_KEYBOARD, STATISTICS_KEYBOARD)


def artifact(records):
    binary = io.BytesIO()
    with zipfile.ZipFile(binary, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("alert-history.json", json.dumps({"schema": 1, "records": records}))
    return binary.getvalue()


class ThreadsOwnerStatusTests(unittest.TestCase):
    def test_recent_main_artifact_only_with_verified_posts_and_pending_intents(self):
        session = Mock()
        session.get.side_effect = [
            Mock(status_code=200, json=Mock(return_value={"artifacts": [
                {"id": 12, "name": "threads-publish-result", "expired": False,
                 "workflow_run": {"head_branch": "other"}},
                {"id": 17, "name": "threads-publish-result", "expired": False,
                 "workflow_run": {"head_branch": "main"}}]})),
            Mock(status_code=200, content=artifact({
                "one": {"route": "daily_laugh", "status": "verified",
                        "post_id": "17939568399127186", "last_seen": "2026-11-07T19:45:55Z"},
                "two": {"route": "penguen", "status": "attempted"},
                "three": {"route": "daily_laugh", "status": "reserved"}})),
        ]
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy"}, clear=True):
            result = load_threads_status(session=session)
        self.assertIn("Daily Laugh Lab: 1 doğrulanmış, son ID 17939568399127186; belirsiz 1", result)
        self.assertIn("Beyinsiz Penguen: doğrulanmış gönderi N/A; belirsiz 1", result)
        self.assertIn("Token güncelliği", result)
        self.assertNotIn("bağlı ve aktif", result)
        self.assertEqual(session.get.call_count, 2)
        self.assertTrue(all(call.kwargs.get("allow_redirects") is not None
                            for call in session.get.call_args_list))

    def test_missing_or_invalid_archive_is_not_a_fake_success(self):
        session = Mock()
        session.get.return_value = Mock(status_code=200,
            json=Mock(return_value={"artifacts": []}))
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy"}, clear=True):
            result = load_threads_status(session=session)
        self.assertIn("doğrulanamadı", result)
        self.assertNotIn("0 gönderi", result)

    def test_separate_status_and_stats_buttons(self):
        texts = [row[0]["text"] for row in THREADS_INLINE_KEYBOARD["inline_keyboard"]]
        self.assertEqual(texts[0], THREADS_STATUS_BUTTON)
        self.assertEqual(len(texts), 2)
        self.assertTrue(any(THREADS_STATUS_BUTTON == button["text"]
                            for row in STATISTICS_KEYBOARD["keyboard"] for button in row))

    def test_callback_and_command_are_owner_only(self):
        env = {"TELEGRAM_STATUS_ONLY": "true",
               "TELEGRAM_BOT_TOKEN": "123456:" + "A" * 30,
               "TELEGRAM_CHAT_ID": "123456789",
               "TELEGRAM_AI_OWNER_ID": "123456789"}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=True):
            sender, status_loader, ack = Mock(), Mock(return_value="Yayın arşivinde son kimlik"), Mock()
            worker = Worker(str(Path(tmp) / "owner.sqlite3"), sender=sender,
                            threads_status_loader=status_loader, callback_ack=ack)
            try:
                def callback(uid, owner):
                    return {"update_id": uid, "callback_query": {
                        "id": "cb" + str(uid), "data": THREADS_STATUS_CALLBACK_DATA,
                        "from": {"id": owner, "is_bot": False},
                        "message": {"chat": {"id": 123456789}}}}
                worker.handle(callback(1, 222))
                worker.handle(callback(2, 123456789))
                worker.handle(callback(2, 123456789))
                worker.handle({"update_id": 3, "message": {
                    "chat": {"id": 123456789},
                    "from": {"id": 123456789}, "text": THREADS_STATUS_BUTTON}})
                self.assertEqual(status_loader.call_count, 2)
                self.assertEqual(sender.call_count, 2)
                sender.assert_any_call(THREADS_STATUS_BUTTON, "Yayın arşivinde son kimlik",
                                       reply_markup=THREADS_INLINE_KEYBOARD)
                ack.assert_called_once_with("cb2")
                self.assertEqual(worker.offset(), 4)
            finally:
                worker.db.close()


if __name__ == "__main__":
    unittest.main()
