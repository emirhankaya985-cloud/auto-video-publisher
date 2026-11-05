"""Owner-only Threads button and read-only archive coverage."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from telegram_ai_worker import Worker, load_threads_statistics
from telegram_notifications import THREADS_STATISTICS_BUTTON, STATISTICS_KEYBOARD


class ThreadsStatusTests(unittest.TestCase):
    def test_threads_report_does_not_contaminate_facebook_counts(self):
        data = {"measured_at": "2026-11-05T23:15:00+03:00",
                "accounts": [{"account": "ToonZone", "platforms": [
                    {"platform": "Facebook", "total": 987, "daily": {"delta": 40}, "weekly": {"delta": 80}},
                    {"platform": "Threads", "total": 125, "daily": {"delta": None}, "weekly": {"delta": 9}}]}],
                "followers": [{"account": "ToonZone", "platform": "Threads", "followers": 0}]}
        with patch("telegram_ai_worker.latest_comparison", return_value=(42, data)):
            report = load_threads_statistics()
        self.assertIn("ToonZone: 125 / N/A / 9 · 0 takipçi", report)
        self.assertNotIn("987", report)
        self.assertIn("/actions/runs/42", report)

    def test_missing_threads_measurements_never_fake_zero(self):
        with patch("telegram_ai_worker.latest_comparison", return_value=(42, {
            "measured_at": "2026-11-05T23:15:00+03:00",
            "accounts": [{"account": "Film", "platforms": [{"platform": "Facebook", "total": 18}]}]})):
            report = load_threads_statistics()
        self.assertIn("N/A", report)
        self.assertNotIn("• Film:", report)

    def test_owner_only_threads_command_and_separate_button(self):
        env = {"TELEGRAM_STATUS_ONLY": "true", "TELEGRAM_BOT_TOKEN": "123456:" + "A" * 30,
               "TELEGRAM_CHAT_ID": "123456789", "TELEGRAM_AI_OWNER_ID": "123456789"}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=True):
            send, stats, threads = Mock(), Mock(), Mock(return_value="Threads ölçümü")
            worker = Worker(str(Path(tmp) / "store.sqlite3"), sender=send,
                            statistics_loader=stats, threads_statistics_loader=threads)
            try:
                for uid, owner, command in [(1, 999, THREADS_STATISTICS_BUTTON),
                                            (2, 123456789, THREADS_STATISTICS_BUTTON),
                                            (3, 123456789, "/threads")]:
                    worker.handle({"update_id": uid, "message": {
                        "chat": {"id": 123456789}, "from": {"id": owner}, "text": command}})
                self.assertEqual(send.call_count, 2)
                self.assertEqual(threads.call_count, 2)
                stats.assert_not_called()
                self.assertEqual(send.call_args.kwargs["reply_markup"], STATISTICS_KEYBOARD)
            finally:
                worker.db.close()


if __name__ == "__main__":
    unittest.main()
