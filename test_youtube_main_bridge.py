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

    def test_gonle_selected_for_same_source_and_id_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            state, plan = Path(temp) / 'state.json', Path(temp) / 'plan.json'
            state.write_text('{}')
            plan.write_text(json.dumps([{
                'route': 'gonle', 'id': 'file-1', 'name': 'sample.mp4',
                'captions': {'facebook': 'Owner-approved caption'},
            }]))
            expected = 'UCvSvo5WghuXqsjwLRmIz22g'
            with patch.object(bridge, 'STATE', state), patch.object(bridge, 'PLAN', plan), \
                 patch.dict(os.environ, {'GITHUB_RUN_ID': '721', 'TOKEN_GONLE_DUSEN_JSON': 'test-only'}, clear=True), \
                 patch.object(bridge, 'check_channel', return_value={'status': 'verified', 'channel_id': expected}) as check:
                bridge.prepare()
            check.assert_called_once_with('gonle_dusen')
            entry = json.loads(state.read_text())['youtube_entries']['gonle:file-1']
            self.assertEqual(entry['channel_id'], expected)
            self.assertEqual(entry['status'], 'intent')
            self.assertEqual(entry['source_id'], 'file-1')

    def test_missing_gonle_secret_held_no_intent_or_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            state, plan = Path(temp) / 'state.json', Path(temp) / 'plan.json'
            state.write_text('{}')
            plan.write_text(json.dumps([{
                'route': 'gonle', 'id': 'file-1', 'name': 'sample.mp4',
                'captions': {'facebook': 'caption'},
            }]))
            with patch.object(bridge, 'STATE', state), patch.object(bridge, 'PLAN', plan), \
                 patch.dict(os.environ, {'GITHUB_RUN_ID': '721'}, clear=True), \
                 patch.object(bridge, 'check_channel') as check, \
                 patch.object(bridge, 'record_error') as record:
                bridge.prepare()
            saved = json.loads(state.read_text())
            self.assertFalse(saved['youtube_entries'])
            self.assertEqual(saved['youtube_prepare_errors'], ['gonle: missing_secret'])
            check.assert_not_called()
            record.assert_called_once_with('youtube_prepare', 'missing_secret', route='gonle', platform='youtube')

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

    def test_accepted_id_saved_before_verification_and_never_reuploaded(self):
        expected = bridge.ROUTES['tarladaki'][2]
        post = 'abcdefghijk'
        entry = {'status': 'intent', 'run_id': '1', 'attempt': '1', 'route': 'tarladaki',
                 'source_id': 'source', 'channel_id': expected, 'title': 'title', 'caption': 'caption'}
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state.json'
            state.write_text(json.dumps({'youtube_entries': {'tarladaki:source': entry}}))
            youtube = Mock()
            def fail_read(**kwargs):
                saved = json.loads(state.read_text())['youtube_entries']['tarladaki:source']
                self.assertEqual((saved['status'], saved['post_id']), ('accepted', post))
                raise RuntimeError('temporary GET failure')
            youtube.videos().list().execute.side_effect = fail_read
            with patch.object(bridge, 'STATE', state), patch.dict(os.environ, {
                'YOUTUBE_PUBLISHING_ENABLED':'true','YOUTUBE_INTENT_ARCHIVED':'true',
                'GITHUB_RUN_ID':'1','TOKEN_CHANNEL1_JSON':'{}'}, clear=True), \
                patch.object(bridge, 'check_channel', return_value={'status':'verified','channel_id':expected}), \
                patch.object(bridge.Credentials, 'from_authorized_user_info'), \
                patch.object(bridge, 'build', return_value=youtube), \
                patch.object(bridge, 'previous_upload', return_value=None), \
                patch.object(bridge, 'download', return_value=Path(tmp)/'video.mp4'), \
                patch.object(bridge, 'verify_source_video'), \
                patch.object(bridge, 'record_error'), \
                patch.object(bridge, 'upload_video', return_value=post) as upload:
                with self.assertRaises(SystemExit):
                    bridge.publish()
                with self.assertRaises(SystemExit):
                    bridge.publish()
                upload.assert_called_once()

    def test_normal_processing_is_pending_and_wrong_identity_is_failure(self):
        youtube = Mock()
        entry = {'post_id':'abcdefghijk','route':'tarladaki','status':'accepted'}
        youtube.videos().list().execute.return_value = {'items':[{'id':'abcdefghijk',
            'snippet':{'channelId':'expected'},'status':{'privacyStatus':'public','uploadStatus':'uploaded'}}]}
        bridge.verify_saved_upload(youtube, entry, 'expected')
        self.assertEqual(entry['status'], 'accepted')
        youtube.videos().list().execute.return_value['items'][0]['id'] = 'wrong-video'
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            bridge.verify_saved_upload(youtube, entry, 'expected')

    def test_terminal_provider_result_keeps_id_and_holds_without_reupload(self):
        for status in ('failed', 'rejected', 'deleted'):
            youtube = Mock()
            entry = {'post_id': 'abcdefghijk', 'route': 'tarladaki', 'status': 'accepted'}
            youtube.videos().list().execute.return_value = {'items': [{
                'id': entry['post_id'], 'snippet': {'channelId': 'expected'},
                'status': {'privacyStatus': 'public', 'uploadStatus': status}}]}
            with self.assertRaisesRegex(RuntimeError, 'terminal'):
                bridge.verify_saved_upload(youtube, entry, 'expected')
            self.assertEqual(entry['status'], 'held')
            self.assertEqual(entry['post_id'], 'abcdefghijk')
            self.assertEqual(entry['verification_status'], 'upload_' + status)
            youtube.videos().insert.assert_not_called()

    def test_missing_saved_video_is_neither_done_nor_permission_to_reupload(self):
        youtube = Mock()
        youtube.videos().list().execute.return_value = {'items': []}
        entry = {'post_id': 'abcdefghijk', 'route': 'tarladaki', 'status': 'accepted'}
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            bridge.verify_saved_upload(youtube, entry, 'expected')
        self.assertEqual(entry['status'], 'held')
        self.assertEqual(entry['verification_status'], 'video_unavailable')
        youtube.videos().insert.assert_not_called()

    def test_malformed_saved_video_response_remains_a_failure_without_reclassification(self):
        youtube = Mock()
        youtube.videos().list().execute.return_value = {}
        entry = {'post_id': 'abcdefghijk', 'route': 'tarladaki', 'status': 'accepted'}
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            bridge.verify_saved_upload(youtube, entry, 'expected')
        self.assertEqual(entry['status'], 'accepted')

    def test_unavailable_id_rechecked_without_reupload_or_repeated_error_and_can_recover(self):
        expected = bridge.ROUTES['tarladaki'][2]
        entry = {'status': 'accepted', 'route': 'tarladaki', 'post_id': 'abcdefghijk',
                 'channel_id': expected}
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)/'state.json'
            state.write_text(json.dumps({'youtube_entries': {'tarladaki:source': entry}}))
            youtube = Mock()
            youtube.videos().list().execute.return_value = {'items': []}
            with patch.object(bridge, 'STATE', state), patch.dict(os.environ, {
                'YOUTUBE_PUBLISHING_ENABLED': 'true', 'YOUTUBE_INTENT_ARCHIVED': 'true',
                'GITHUB_RUN_ID': '1', 'TOKEN_CHANNEL1_JSON': '{}'}, clear=True), \
                patch.object(bridge, 'check_channel', return_value={'status':'verified','channel_id':expected}), \
                patch.object(bridge.Credentials, 'from_authorized_user_info'), \
                patch.object(bridge, 'build', return_value=youtube), \
                patch.object(bridge, 'record_error') as journal, \
                patch.object(bridge, 'upload_video') as upload:
                with self.assertRaises(SystemExit):
                    bridge.publish()
                bridge.publish()
                journal.assert_called_once()
                youtube.videos().list().execute.return_value = {'items': [{
                    'id':'abcdefghijk', 'snippet':{'channelId':expected},
                    'status':{'privacyStatus':'public','uploadStatus':'uploaded'}}]}
                bridge.publish()
                self.assertEqual(json.loads(state.read_text())['youtube_entries']['tarladaki:source']['status'], 'accepted')
                youtube.videos().list().execute.return_value = {'items': [{
                    'id':'abcdefghijk', 'snippet':{'channelId':expected},
                    'status':{'privacyStatus':'public','uploadStatus':'processed'}}]}
                bridge.publish()
                self.assertEqual(json.loads(state.read_text())['youtube_entries']['tarladaki:source']['status'], 'done')
                upload.assert_not_called()



class LocalPreparationGateTests(unittest.TestCase):
    def fixture(self, platforms=('instagram',)):
        route, source, filename, run = 'tarladaki', 'source278', '278.mp4', '42207238768'
        entry = {'status': 'intent', 'run_id': run, 'attempt': '1', 'route': route,
                 'source_id': source, 'file': filename, 'channel_id': bridge.ROUTES[route][2],
                 'title': '278', 'caption': 'approved caption'}
        item = {'route': route, 'id': source, 'name': filename, 'platforms': list(platforms)}
        state = {'entries': {f'{route}:{p}:{source}': {
            'route': route, 'platform': p, 'file': filename, 'run_id': run, 'status': 'ready',
            'failure': {'reason': 'source_or_cover_preparation_failed', 'safe_to_repost': True},
        } for p in platforms}, 'youtube_entries': {f'{route}:{source}': entry}}
        return state, item, entry, run

    def test_new_fanout_stays_held_before_google_or_upload_and_preserves_meta_and_old_uncertain(self):
        state, item, entry, run = self.fixture()
        state['youtube_entries']['tarladaki:old'] = {'status': 'uncertain', 'run_id': '10'}
        before = json.loads(json.dumps(state))
        with tempfile.TemporaryDirectory() as tmp:
            path, plan = Path(tmp)/'state.json', Path(tmp)/'plan.json'
            path.write_text(json.dumps(state)); plan.write_text(json.dumps([item]))
            with patch.object(bridge, 'STATE', path), patch.object(bridge, 'PLAN', plan), \
                 patch.dict(os.environ, {'YOUTUBE_PUBLISHING_ENABLED': 'true',
                     'YOUTUBE_INTENT_ARCHIVED': 'true', 'GITHUB_RUN_ID': run}, clear=True), \
                 patch.object(bridge, 'check_channel') as check, \
                 patch.object(bridge, 'build') as build, \
                 patch.object(bridge, 'download') as download, \
                 patch.object(bridge, 'upload_video') as upload:
                bridge.publish()
            saved = json.loads(path.read_text())
        result = saved['youtube_entries']['tarladaki:source278']
        self.assertEqual(result['status'], 'held')
        self.assertEqual(result['verification_status'], 'source_local_preparation_failed')
        self.assertIs(result['external_post_attempted'], False)
        self.assertEqual(result['source_local_preparation_proof'], {
            'run_id': run, 'route': 'tarladaki', 'source_id': 'source278',
            'file': '278.mp4', 'platforms': ['instagram']})
        self.assertNotIn('post_id', result)
        self.assertEqual(saved['entries'], before['entries'])
        self.assertEqual(saved['youtube_entries']['tarladaki:old'], before['youtube_entries']['tarladaki:old'])
        for mock in (check, build, download, upload): mock.assert_not_called()

    def test_all_active_platforms_must_have_exact_current_local_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp)/'plan.json'
            for change in ({'status': 'uncertain'}, {'status': 'done'}, {'run_id': 'old'},
                           {'file': '279.mp4'}, {'route': 'penguen'}, {'platform': 'instagram'},
                           {'post_id': '123'}, {'failure': {'reason': 'upload_failed', 'safe_to_repost': True}},
                           {'failure': {'reason': 'source_or_cover_preparation_failed', 'safe_to_repost': False}}):
                state, item, entry, run = self.fixture(('facebook', 'instagram'))
                plan.write_text(json.dumps([item]))
                state['entries']['tarladaki:facebook:source278'].update(change)
                before = json.loads(json.dumps(state))
                with patch.object(bridge, 'PLAN', plan):
                    self.assertIsNone(bridge.current_local_preparation_failure(
                        'tarladaki:source278', entry, state, run), change)
                self.assertEqual(state, before)

    def test_mismatched_youtube_binding_or_old_local_failure_does_not_create_hold(self):
        for change in ({'run_id': 'old'}, {'file': '279.mp4'}, {'source_id': 'other'},
                       {'channel_id': 'other'}, {'post_id': 'abcdefghijk'}, {'status': 'uncertain'}):
            state, item, entry, run = self.fixture()
            entry.update(change)
            with patch.object(bridge.PLAN.__class__, 'read_text') as read:
                self.assertIsNone(bridge.current_local_preparation_failure('tarladaki:source278', entry, state, run))
                read.assert_not_called()

    def test_positive_local_failure_with_unverified_plan_fails_closed(self):
        state, item, entry, run = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp)/'plan.json'
            for value in ({}, [], [dict(item, name='other.mp4')], [item, item],
                          [dict(item, platforms=[])], [dict(item, platforms=['youtube'])],
                          [dict(item, platforms=['instagram', 'instagram'])],
                          [dict(item, resume_container_id='123')]):
                plan.write_text(json.dumps(value))
                with patch.object(bridge, 'PLAN', plan), self.assertRaisesRegex(RuntimeError, 'plan unverified'):
                    bridge.current_local_preparation_failure('tarladaki:source278', entry, state, run)

    def test_saved_id_reconciliation_remains_get_only_without_needing_current_plan(self):
        state, item, entry, run = self.fixture()
        entry.update(status='accepted', post_id='abcdefghijk')
        youtube = Mock()
        youtube.videos().list().execute.return_value = {'items': [{
            'id': 'abcdefghijk', 'snippet': {'channelId': entry['channel_id']},
            'status': {'privacyStatus': 'public', 'uploadStatus': 'processed'}}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'; path.write_text(json.dumps(state))
            with patch.object(bridge, 'STATE', path), patch.object(bridge, 'PLAN', Path(tmp)/'absent'), \
                 patch.dict(os.environ, {'YOUTUBE_PUBLISHING_ENABLED': 'true', 'YOUTUBE_INTENT_ARCHIVED': 'true',
                     'GITHUB_RUN_ID': run, 'TOKEN_CHANNEL1_JSON': '{}'}, clear=True), \
                 patch.object(bridge, 'check_channel', return_value={'status': 'verified', 'channel_id': entry['channel_id']}), \
                 patch.object(bridge.Credentials, 'from_authorized_user_info'), \
                 patch.object(bridge, 'build', return_value=youtube), \
                 patch.object(bridge, 'upload_video') as upload:
                bridge.publish()
            self.assertEqual(json.loads(path.read_text())['youtube_entries']['tarladaki:source278']['status'], 'done')
        upload.assert_not_called()
        youtube.videos().insert.assert_not_called()


if __name__ == '__main__':
    unittest.main()
