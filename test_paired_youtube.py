import copy
import os
import unittest
from unittest.mock import patch, Mock
import paired_youtube as yt

class PairedYouTubeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'YOUTUBE_PUBLISHING_ENABLED':'true','GITHUB_RUN_ID':'run'}, clear=True)
        journal = patch('paired_youtube.record_error')
        journal.start()
        self.addCleanup(journal.stop)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.item = {'route':'penguen','id':'file','name':'video.mp4','platforms':['facebook'], 'captions':{'facebook':'Caption'}}
        self.state = {'entries':{'penguen:facebook:file':{'day':'2026-11-01'}}}

    @patch('paired_youtube.client_for')
    def test_pairs_same_source_and_persists_intent(self, client):
        plans=yt.plan_paired_youtube([self.item], self.state)
        self.assertEqual(plans[0]['platforms'], ['facebook','youtube'])
        self.assertEqual(self.state['entries']['penguen:youtube:file']['source_id'], 'file')
        client.assert_called_once_with('penguen')

    @patch('paired_youtube.client_for')
    def test_disabled_and_audit_never_connect(self, client):
        yt.plan_paired_youtube([self.item],self.state,audit=True)
        with patch.dict(os.environ, {'YOUTUBE_PUBLISHING_ENABLED':'false'}):
            yt.plan_paired_youtube([self.item],self.state)
        client.assert_not_called()

    @patch('paired_youtube.client_for', side_effect=RuntimeError('secret'))
    def test_bad_credential_leaves_meta_intact(self, client):
        yt.plan_paired_youtube([self.item], self.state)
        self.assertEqual(self.item['platforms'], ['facebook'])
        self.assertNotIn('penguen:youtube:file',self.state['entries'])

    @patch('paired_youtube.client_for')
    def test_uncertain_prior_upload_holds_route(self, client):
        self.state['entries']['old']={'route':'penguen','platform':'youtube','status':'uncertain','run_id':'older'}
        yt.plan_paired_youtube([self.item],self.state)
        client.assert_not_called()

    @patch('paired_youtube.client_for')
    def test_completed_source_not_uploaded_again(self, client):
        self.state['entries']['penguen:youtube:file']={'status':'done'}
        yt.plan_paired_youtube([self.item],self.state)
        client.assert_not_called()

    @patch('paired_youtube.client_for')
    def test_upload_requires_reserved_matching_intent(self, client):
        yt.plan_paired_youtube([self.item],self.state)
        with self.assertRaises(RuntimeError):
            yt.publish_paired_youtube(self.item,'video.mp4',self.state)

if __name__=='__main__': unittest.main()
