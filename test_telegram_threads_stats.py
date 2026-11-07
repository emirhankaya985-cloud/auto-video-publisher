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

    def test_old_threads_measurement_is_visible_as_stale(self):
        with patch("telegram_ai_worker.latest_comparison", return_value=(42, {
            "measured_at": "2026-10-20T23:15:00+03:00",
            "accounts": [{"account": "ToonZone", "platforms": [
                {"platform": "Threads", "total": 2, "daily": {"delta": None},
                 "weekly": {"delta": None}}]}]})):
            self.assertIn("36 saatten eski", load_threads_statistics())

    def test_missing_threads_measurements_never_fake_zero(self):
        with patch("telegram_ai_worker.latest_comparison", return_value=(42, {
            "measured_at": "2026-11-05T23:15:00+03:00",
            "accounts": [{"account": "Film", "platforms": [{"platform": "Facebook", "total": 18}]}]})):
            report = load_threads_statistics()
        self.assertIn("N/A", report)
        self.assertNotIn("• Film:", report)

    def test_general_statistics_failure_does_not_break_owner_inbox(self):
        env = {"TELEGRAM_STATUS_ONLY": "true", "TELEGRAM_BOT_TOKEN": "123456:" + "A" * 30,
               "TELEGRAM_CHAT_ID": "123456789", "TELEGRAM_AI_OWNER_ID": "123456789"}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=True):
            send = Mock()
            stats = Mock(side_effect=RuntimeError("Missing analytics artifact"))
            threads = Mock(return_value="Threads ok")
            worker = Worker(str(Path(tmp) / "store.sqlite3"), sender=send,
                            statistics_loader=stats, threads_statistics_loader=threads)
            try:
                for uid, cmd in [(11, "/istatistik"), (12, "/threads")]:
                    worker.handle({"update_id": uid, "message": {
                        "chat": {"id": 123456789}, "from": {"id": 123456789}, "text": cmd}})
                self.assertEqual(stats.call_count, 1)
                self.assertEqual(threads.call_count, 1)
                self.assertEqual(send.call_count, 2)
                self.assertIn("Sayı tahmin edilmedi", send.call_args_list[0].args[1])
                self.assertEqual(send.call_args_list[1].args[1], "Threads ok")
                self.assertEqual(worker.offset(), 13)
            finally:
                worker.db.close()

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


def test_threads_button_displays_engagement_with_explicit_missing_values():
    data = {"measured_at": "2026-11-07T10:00:00+03:00",
            "accounts": [{"account": "Film", "platforms": [{"platform": "Threads", "total": 12}]}],
            "threads_engagement": [
                {"account": "Film", "platform": "Threads", "metric": "likes", "value": 0, "status": "ok"},
                {"account": "Film", "platform": "Threads", "metric": "replies", "value": 8, "status": "unavailable"},
                {"account": "Film", "platform": "Instagram", "metric": "shares", "value": 999, "status": "ok"}]}
    with patch("telegram_ai_worker.latest_comparison", return_value=(42, data)):
        report = load_threads_statistics()
    assert "beğeni 0" in report
    assert "yanıt N/A" in report
    assert "dış paylaşım N/A" in report
    assert "999" not in report
