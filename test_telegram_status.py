import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from telegram_status import status_table
from telegram_ai_worker import Worker


class StatusTableTests(unittest.TestCase):
    now = datetime(2026, 11, 3, 1, tzinfo=ZoneInfo('Europe/Istanbul'))

    def test_verified_counts_are_unique_and_unknown_history_is_na(self):
        row = dict(route='film', platform='facebook', status='done', post_id='1234567890', day='2026-11-03')
        table = status_table(now=self.now, state={'entries': {'one': row, 'alias': row.copy()}})
        self.assertIn('1/5', table)
        self.assertIn('12:00 12:10 12:20 12:30', table)
        self.assertIn('06:00', table)  # Standard time: New York 22:00 -> TR 06:00.
        self.assertNotIn('0/5', status_table(now=self.now))
        self.assertLess(len(table.encode('utf-16-le')) // 2, 3600)

    def test_seventh_account_explicitly_unconfigured_without_inventing_posts(self):
        table = status_table(now=self.now, state={'entries': {}}, configured=True)
        self.assertIn('OddFrames', table)
        self.assertIn('Kimlik/hak bekleniyor', table)
        self.assertIn('kota ve yayın sayısı N/A', table)
        self.assertNotIn('OddFrames      0/5', table)

    def test_pending_failed_and_daily_laugh_previous_ny_day_are_visible(self):
        now = datetime(2026, 11, 7, 23, 42, tzinfo=ZoneInfo('Europe/Istanbul'))
        rows = {
            'daily_laugh:facebook:source1': dict(route='daily_laugh', platform='facebook',
                status='done', post_id='2993579024350823', day='2026-11-06'),
            'daily_laugh:facebook:source2': dict(route='daily_laugh', platform='facebook',
                status='held', day='2026-11-06'),
            'tarladaki:instagram:source3': dict(route='tarladaki', platform='instagram',
                status='ready', day='2026-11-07', failure={'reason': 'source_or_cover_preparation_failed'}),
            'tarladaki:instagram:source4': dict(route='tarladaki', platform='instagram',
                status='done', post_id='wrong', day='2026-11-07'),
        }
        message = status_table(now=now, state={'entries': rows})
        self.assertIn('Eks Bek Hata', message)
        self.assertIn('1/8', message)
        self.assertIn('son tamamlanmış New York gününe', message)
        self.assertIn('yerel hazırlık', message)
        self.assertNotIn('1/5', message)
        self.assertLess(len(message.encode('utf-16-le')) // 2, 4096)

    def test_actual_gate_configuration_is_distinct_from_counts(self):
        with patch.dict(os.environ, {'LINK_AUTOMATION_ENABLED': 'true',
                                     'ENABLE_TP_NORMAL_ROUTES': 'true',
                                     'ENABLE_GONLE_INSTAGRAM_ROUTES': 'false'}):
            table = status_table(now=self.now, state={'entries': {}}, configured=True)
        self.assertIn('Açık', table)
        self.assertIn('Kapalı', table)


class StatusOnlyWorkerTests(unittest.TestCase):
    def test_status_uses_no_ai_and_other_commands_never_write(self):
        env = {'TELEGRAM_STATUS_ONLY': 'true', 'TELEGRAM_BOT_TOKEN': '123456:' + 'A'*30,
               'TELEGRAM_CHAT_ID': '123456789', 'TELEGRAM_AI_OWNER_ID': '987654321'}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, env, clear=True):
            send, model, loader = Mock(), Mock(), Mock(return_value='<pre>Plan</pre>')
            worker = Worker(str(Path(temp)/'worker.db'), sender=send, model=model, status_loader=loader)
            self.addCleanup(worker.db.close)
            for uid, text in enumerate(['/stok', '/durdur', '/devam', '/durum', 'durum'], 1):
                worker.handle({'update_id': uid, 'message': {'chat': {'id': 123456789},
                    'from': {'id': 987654321}, 'text': text}})
            model.assert_not_called()
            self.assertEqual(loader.call_count, 2)
            self.assertEqual(send.call_count, 5)
            self.assertEqual(send.call_args.kwargs['parse_mode'], 'HTML')
            self.assertTrue(send.call_args.kwargs['reply_markup']['is_persistent'])
