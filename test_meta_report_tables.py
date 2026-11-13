import unittest
from meta_report_tables import ntfy_table, publication_telegram

class MetaTableTests(unittest.TestCase):
    def test_both_channels_preserve_missing_and_unknown(self):
        accounts = [{'account': a, 'daily': {'delta': 3}, 'total': 10} for a in ['A & B','Other']]
        data = {'day':'2026-11-02','measured_at':'2026-11-02T13:00:00+03:00',
                'accounts':accounts,'total':20,'daily':{'delta':6},'publication':{
                    'A & B':{'target':5,'expected_posts':10,'platforms':{'fb':{'success':5},'ig':{'success':3}}},'Other':None}}
        text=ntfy_table(data)
        self.assertIn('Eksik',text)
        self.assertIn('N/A',text)
        self.assertLessEqual(len(text.encode()),3800)
        title,html=publication_telegram(data)
        self.assertIn('<pre>',html)
        self.assertIn('A &amp; B',html)
        self.assertIn('2',html)
        self.assertNotIn('YouTube',text)

    def test_error_notification_is_one_plain_digest_per_channel(self):
        from unittest.mock import patch
        import stats_reporter
        from views_comparison import ViewReport
        data = {'accounts': [], 'collection_errors': ['Beyinsiz Penguen / YouTube: HTTP 403']}
        message = ViewReport('report', data)
        with patch.object(stats_reporter, 'telegram_configured', return_value=True), \
             patch.object(stats_reporter, 'send_ntfy', return_value={'http_status': 200}) as ntfy, \
             patch.object(stats_reporter, 'send_telegram', return_value={'server_ack': True}) as telegram:
            stats_reporter.notify(message)
        self.assertEqual(ntfy.call_count, 1)
        self.assertEqual(telegram.call_count, 1)
        self.assertIn('Beyinsiz Penguen / YouTube', ntfy.call_args.args[1])
        self.assertNotIn('reply_markup', telegram.call_args.kwargs)
