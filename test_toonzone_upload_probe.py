import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import toonzone_first_three_upload_probe as probe


class ProbeSafetyTests(unittest.TestCase):
    def test_probe_never_publishes_and_persists_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);video=root/'instagram.mp4';video.write_bytes(b'prepared')
            history=root/'alert-history.json'
            probe.archive.save(history,{'schema':1,'records':{'0'*64:{'status':'reserved','intent_run_id':'test','last_seen':probe.archive.now_utc().isoformat(),'candidate_upload_sha256':probe.batch.digest(video),'caption':'original'}}})
            with patch.object(probe,'ROOT',root),patch.object(probe,'HISTORY',history),patch.dict(os.environ,{'GITHUB_RUN_ID':'test','UPLOAD_PROBE_INTENT_ARCHIVED':'true'}),patch.object(probe.batch,'page_for_toonzone',return_value={'page_token':'test'}),patch.object(probe.batch,'instagram_identity',return_value=probe.batch.EXPECTED_INSTAGRAM_ID),patch('cloud_omnichannel_publisher.upload_instagram_reel',return_value={'container_id':'123','published':False,'status':'FINISHED'}) as upload:
                probe.upload()
                self.assertFalse(upload.call_args.kwargs['publish'])
                self.assertFalse(upload.call_args.kwargs['append_store_link'])
                self.assertEqual(probe.archive.read(history)['records']['0'*64]['candidate_container_id'],'123')

    def test_missing_archived_intent_prevents_any_upload(self):
        with patch.dict(os.environ,{'UPLOAD_PROBE_INTENT_ARCHIVED':'false'}),patch('cloud_omnichannel_publisher.upload_instagram_reel') as upload:
            with self.assertRaisesRegex(RuntimeError,'probe_not_archived'): probe.upload()
            upload.assert_not_called()
