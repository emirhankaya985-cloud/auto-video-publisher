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
