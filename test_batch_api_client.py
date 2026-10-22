import os, unittest
from unittest.mock import patch, Mock
from batch_api_client import BatchGate
class Tests(unittest.TestCase):
 def test_unconfigured_gate_is_inert(self): self.assertFalse(BatchGate('a','fb','v','f').claim())
 @patch('batch_api_client.requests.post')
 def test_claim_and_finish(self, post):
  post.return_value=Mock(status_code=200,json=lambda:{'claimed':True},raise_for_status=lambda:None)
  with patch.dict(os.environ,{'BATCH_ID':'b','BATCH_API_URL':'https://x','BATCH_API_TOKEN':'secret'}):
   post.side_effect=[Mock(status_code=200,json=lambda:{'claimed':True,'claim_token':'claim'},raise_for_status=lambda:None),Mock(status_code=200,raise_for_status=lambda:None)]
   g=BatchGate('a','fb','v','f'); self.assertTrue(g.claim()); g.finish('confirmed','id','url'); self.assertEqual(post.call_count,2)
   self.assertEqual(post.call_args_list[0].kwargs['json']['drive_file_id'],'v')
   self.assertEqual(post.call_args_list[0].kwargs['json']['drive_folder_id'],'f')
   self.assertEqual(post.call_args_list[1].kwargs['json']['claim_token'],'claim')
