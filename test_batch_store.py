import threading, unittest
from batch_store import BatchLedger
class Tests(unittest.TestCase):
 def test_one_claim(self):
  l=BatchLedger(); b=l.create([dict(account='p',platform='fb',drive_file_id='v',drive_folder_id='f')]); out=[]
  ts=[threading.Thread(target=lambda:out.append(l.claim(b,'p','fb'))) for _ in range(2)]
  [t.start() for t in ts]; [t.join() for t in ts]; self.assertEqual(sum(x is not None for x in out),1)
 def test_reuse_blocked(self):
  l=BatchLedger(); l.create([dict(account='p',platform='fb',drive_file_id='v',drive_folder_id='f')])
  with self.assertRaises(Exception): l.create([dict(account='p',platform='fb',drive_file_id='v',drive_folder_id='f')])
 def test_unknown(self):
  l=BatchLedger(); b=l.create([dict(account='g',platform='ig',drive_file_id='v',drive_folder_id='f')]); l.claim(b,'g','ig'); l.finish(b,'g','ig','unknown',error='uncertain'); self.assertEqual(l.rows(b)[0][5],'unknown')
