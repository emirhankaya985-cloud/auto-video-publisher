import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import youtube_main_bridge as bridge


class BridgeTests(unittest.TestCase):
    def test_route_allowlist_and_source_deduplication(self):
        item = {'route': 'tarladaki', 'id': 'file1'}
        self.assertEqual(len(list(bridge.selected([item, item, {'route': 'film'}]))), 1)
        self.assertEqual(list(bridge.selected([dict(item, resume_container_id='123')])), [])

    def test_no_upload_without_archived_intent(self):
        with patch.dict(os.environ, {'YOUTUBE_PUBLISHING_ENABLED': 'true'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'archived'):
                bridge.publish()

    def test_prior_attempt_intent_cannot_upload_on_rerun(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state.json'
            state.write_text(json.dumps({'youtube_entries': {'x': {'status': 'intent', 'run_id': '1', 'attempt': '1'}}}))
            with patch.object(bridge, 'STATE', state), patch.dict(os.environ, {
                'YOUTUBE_PUBLISHING_ENABLED': 'true', 'YOUTUBE_INTENT_ARCHIVED': 'true',
                'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '2'}, clear=True), patch.object(bridge, 'check_channel') as check:
                bridge.publish()
                check.assert_not_called()

    def test_identity_checked_before_new_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            state, plan = Path(temp) / 'state.json', Path(temp) / 'plan.json'
            state.write_text('{}')
            plan.write_text(json.dumps([{'route': 'tarladaki', 'id': 'file1', 'name': 'video.mp4', 'captions': {'facebook': 'caption'}}]))
            with patch.object(bridge, 'STATE', state), patch.object(bridge, 'PLAN', plan), patch.dict(os.environ, {'GITHUB_RUN_ID': '1', 'TOKEN_CHANNEL1_JSON': 'secret'}, clear=True), patch.object(bridge, 'check_channel', return_value={'status': 'verified', 'channel_id': 'WRONG'}):
                with self.assertRaises(RuntimeError):
                    bridge.prepare()
            self.assertEqual(json.loads(state.read_text()), {})

    def test_existing_title_blocks_duplicate_upload(self):
        youtube = Mock()
        youtube.channels().list().execute.return_value = {'items': [{'id': 'expected', 'contentDetails': {'relatedPlaylists': {'uploads': 'pl'}}}]}
        youtube.playlistItems().list().execute.return_value = {'items': [{'snippet': {'title': 'Same title'}}]}
        with self.assertRaisesRegex(RuntimeError, 'reconciliation'):
            bridge.previous_upload(youtube, 'expected', '[source]', 'Same title')


if __name__ == '__main__':
    unittest.main()
