import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import threads_toonzone_season as season


class Tests(unittest.TestCase):
    def catalog(self):
        return {f'S01E{episode:02d}_Title_Part{part}.mp4':
                {'id': f'file-{episode}-{part}', 'name': f'S01E{episode:02d}_Title_Part{part}.mp4'}
                for episode in reversed(range(1, 13)) for part in reversed(range(1, 5))}

    def test_catalog_is_complete_and_numerically_ordered(self):
        rows = season.ordered_catalog(self.catalog())
        self.assertEqual([(r['episode'], r['part']) for r in rows],
                         [(e, p) for e in range(1, 13) for p in range(1, 5)])
        broken = self.catalog()
        broken.pop('S01E03_Title_Part3.mp4')
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            season.ordered_catalog(broken)

    def test_captions_fit_and_have_no_store_link(self):
        for episode in range(1, 13):
            for part in range(1, 5):
                text, marker = season.caption(episode, part)
                self.assertLessEqual(len(text.encode('utf-8')), 500)
                self.assertIn(marker, text.splitlines())
                self.assertNotIn('etsy', text.lower())
                self.assertIn('#SürekliDizi', text)

    def test_media_failure_stops_before_any_post_or_later_part(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = dict(status='reserved', intent_run_id='42', user_id='7',
                          source_id='source', file='part.mp4', marker='marker',
                          last_seen='2026-11-05T12:00:00+00:00')
            key = 'a' * 64
            plan = dict(key=key, id='source', name='part.mp4', text='marker')
            history = root / 'alert-history.json'
            intent = root / 'plan.json'
            season.archive.save(history, {'schema': 1, 'records': {key: record}})
            season.archive.save(intent, {'run_id': '42', 'plans': [plan, plan]})
            with patch.object(season, 'HISTORY', history), patch.object(season, 'PLAN', intent), \
                    patch.object(season, 'account_config'), patch.object(season, 'profile', return_value='7'), \
                    patch('public_link_runtime.download_verified_publication_video', side_effect=RuntimeError('source_unavailable')) as download, \
                    patch.object(season, 'publish') as publish, \
                    patch.dict(os.environ, {'THREADS_INTENT_ARCHIVED': 'true'}):
                with self.assertRaisesRegex(RuntimeError, 'stopped_before_next_part'):
                    season.execute('42')
            self.assertEqual(download.call_count, 1)
            publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
