import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import toonzone_instagram_season as season


class Tests(unittest.TestCase):
    def test_media_failure_stops_before_uploading_or_processing_later_part(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = 'b' * 64
            history = root / 'alert-history.json'
            plan = root / 'plan.json'
            record = dict(status='reserved', intent_run_id='42', user_id='7',
                          source_id='source', file='part.mp4', caption='caption',
                          last_seen='2026-11-05T12:00:00+00:00')
            item = dict(key=key, id='source', name='part.mp4', text='caption')
            season.archive.save(history, {'schema': 1, 'records': {key: record}})
            season.archive.save(plan, {'run_id': '42', 'user_id': '7', 'plans': [item, item]})
            with patch.object(season, 'HISTORY', history), patch.object(season, 'PLAN', plan), \
                    patch.object(season, 'page_for_toonzone'), \
                    patch.object(season, 'instagram_identity', return_value='7'), \
                    patch('public_link_runtime.download_verified_publication_video', side_effect=RuntimeError('source_unavailable')) as download, \
                    patch('cloud_omnichannel_publisher.upload_instagram_reel') as upload, \
                    patch.dict(os.environ, {'INSTAGRAM_SEASON_INTENT_ARCHIVED': 'true'}):
                with self.assertRaisesRegex(RuntimeError, 'stopped_before_next_part'):
                    season.execute('42')
            self.assertEqual(download.call_count, 1)
            upload.assert_not_called()

    def test_cover_destination_matches_the_exact_part_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = 'c' * 64
            name = 'S01E01_The_Power_Part1.mp4'
            history = root / 'alert-history.json'
            plan = root / 'plan.json'
            source = root / 'source.mp4'
            source.write_bytes(b'test source bytes')
            record = dict(status='reserved', intent_run_id='42', user_id='7',
                          source_id='source', file=name, caption='caption',
                          last_seen='2026-11-05T12:00:00+00:00')
            item = dict(key=key, id='source', name=name, text='caption')
            season.archive.save(history, {'schema': 1, 'records': {key: record}})
            season.archive.save(plan, {'run_id': '42', 'user_id': '7', 'plans': [item]})

            def cover(video, filename, destination):
                self.assertEqual(destination.name, Path(filename).stem + '.png')
                return destination

            with patch.object(season, 'HISTORY', history), patch.object(season, 'PLAN', plan), \
                    patch.object(season, 'page_for_toonzone'), \
                    patch.object(season, 'instagram_identity', return_value='7'), \
                    patch('public_link_runtime.download_verified_publication_video', return_value=source), \
                    patch('public_link_runtime.generate_part_cover', side_effect=cover) as generate, \
                    patch('cloud_omnichannel_publisher.create_instagram_cover_video', return_value=source), \
                    patch('instagram_media_compat.prepare_instagram_upload', return_value=source), \
                    patch('cloud_omnichannel_publisher.upload_instagram_reel', return_value='123') as upload, \
                    patch.object(season, 'graph_get', return_value={
                        'id': '123', 'caption': 'caption', 'media_type': 'VIDEO',
                        'permalink': 'https://www.instagram.com/reel/test/'}), \
                    patch.dict(os.environ, {'INSTAGRAM_SEASON_INTENT_ARCHIVED': 'true'}):
                season.execute('42')
            generate.assert_called_once()
            self.assertFalse(upload.call_args.kwargs['append_store_link'])
            self.assertEqual(season.archive.read(history)['records'][key]['status'], 'verified')

    def test_facebook_check_records_visible_slots_without_posting(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(season, 'ROOT', Path(directory)), \
                patch.object(season, 'page_for_toonzone', return_value={'page_id': '1'}), \
                patch.object(season, 'graph_get', return_value={'id': '1', 'name': 'ToonZone', 'is_published': True}), \
                patch('public_link_runtime.graph_rows', return_value=[
                    {'id': '123', 'description': 'Sezon 1 • Bölüm 3 • Part 3/4 #S01E03'},
                    {'id': '124', 'description': '#S02E03 #Part3'},
                ]), patch('cloud_omnichannel_publisher.upload_facebook_reel') as upload:
            season.audit_facebook()
            data = season.archive.read(Path(directory) / 'facebook-audit.json')
            self.assertEqual(data['first_season_caption_matches'], {'S01E03 Part3': ['123']})
            self.assertEqual(len(data['missing_caption_slots']), 47)
            upload.assert_not_called()

    def test_only_audited_preupload_reservations_are_rebound(self):
        item = {'id': 'source', 'name': 'S01E01_Title_Part1.mp4', 'episode': 1, 'part': 1}
        key = season.archive.identity(season.CAMPAIGN, 'toonzone', 'instagram', 'source')
        prior = {'status': 'reserved', 'intent_run_id': season.AUDITED_PREWRITE_RUN,
                 'user_id': '7', 'source_id': 'source', 'file': item['name']}
        history = {'schema': 1, 'records': {key: prior}}
        with patch.object(season, 'page_for_toonzone'), \
                patch.object(season, 'instagram_identity', return_value='7'), \
                patch.object(season.archive, 'restore', return_value=history), \
                patch('public_link_runtime.graph_rows', return_value=[]), \
                patch('public_link_runtime.inventory', return_value={}), \
                patch.object(season, 'ordered_catalog', return_value=[item]), \
                patch.object(season.archive, 'save'):
            season.prepare('43')
        self.assertEqual(history['records'][key]['intent_run_id'], '43')
        self.assertEqual(history['records'][key]['audited_prewrite_run'], season.AUDITED_PREWRITE_RUN)

    def test_prepare_blocks_unresolved_previous_attempt(self):
        item = {'id': 'source', 'name': 'S01E01_Title_Part1.mp4', 'episode': 1, 'part': 1}
        key = season.archive.identity(season.CAMPAIGN, 'toonzone', 'instagram', 'source')
        with patch.object(season, 'page_for_toonzone'), \
                patch.object(season, 'instagram_identity', return_value='7'), \
                patch.object(season.archive, 'restore', return_value={'schema': 1, 'records': {key: {'status': 'attempted'}}}), \
                patch('public_link_runtime.graph_rows', return_value=[]), \
                patch('public_link_runtime.inventory', return_value={}), \
                patch.object(season, 'ordered_catalog', return_value=[item]), \
                patch.object(season.archive, 'save') as save:
            with self.assertRaisesRegex(RuntimeError, 'previous_intent_unresolved'):
                season.prepare('43')
            save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
