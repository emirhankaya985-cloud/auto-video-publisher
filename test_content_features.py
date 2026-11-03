import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from analytics_archive import upsert_records
from content_stock import build_stock
from media_quality import inspect_video
from performance_history import collect_engagement, follower_changes


class StockTests(unittest.TestCase):
    def stock(self, files, entries=None, unavailable=()):
        return build_stock({'film': files}, {'entries': entries or {}},
                           {'film': ('film', 'Film')}, {'film': 5},
                           unavailable=unavailable)

    def test_uncertain_and_alias_are_not_stock(self):
        files = {'Movie_Part_1.mp4': {'id': 'a', 'name': 'Movie_Part_1.mp4'},
                 'Movie_Part_1 (1).mp4': {'id': 'b', 'name': 'Movie_Part_1 (1).mp4'},
                 'Movie_Part_2.mp4': {'id': 'c', 'name': 'Movie_Part_2.mp4'},
                 'Movie_Part_2.txt': {}}
        rows = self.stock(files, {'film:instagram:c': {'status': 'uncertain'}})
        self.assertEqual(rows[0]['remaining'], 1)
        self.assertEqual(rows[1]['remaining'], 0)
        self.assertEqual(rows[1]['held'], 1)
        self.assertEqual(rows[0]['ambiguous'], 1)

    def test_missing_catalog_is_na_not_zero(self):
        row = self.stock({}, unavailable={'film'})[0]
        self.assertIsNone(row['remaining'])
        self.assertIsNone(row['estimated_days'])

    def test_visual_duplicate_hold_is_not_available_stock(self):
        files = {'Movie_Part_1.mp4': {'id': 'a', 'name': 'Movie_Part_1.mp4'},
                 'Movie_Part_1.txt': {}}
        row = self.stock(files, {'film:facebook:a': {'status': 'held'}})[0]
        self.assertEqual((row['remaining'], row['held']), (0, 1))

    def test_txt_and_confirmed_id_required(self):
        files = {'Movie_Part_1.mp4': {'id': 'a', 'name': 'Movie_Part_1.mp4'}}
        self.assertEqual(self.stock(files)[0]['missing_txt'], 1)
        row = self.stock(files, {'film:facebook:a': {'status': 'done'}})[0]
        self.assertEqual(row['completed'], 0)
        self.assertEqual(row['held'], 1)

    def test_generated_exact_txt_counts_as_stock_only_for_its_source(self):
        with tempfile.TemporaryDirectory() as folder:
            captions = Path(folder)
            (captions / '1.txt').write_text('Caption', encoding='utf-8')
            (captions / '2 (1).txt').write_text('Other caption', encoding='utf-8')
            files = {f'{i}.mp4': {'id': str(i), 'name': f'{i}.mp4'} for i in (1, 2)}
            rows = build_stock(
                {'daily_laugh': files, 'gonle': files}, {'entries': {}},
                {'daily_laugh': ('daily_laugh', 'Daily Laugh'), 'gonle': ('gonle', 'Gönle')},
                {'daily_laugh': 8, 'gonle': 5}, generated_caption_dirs={'daily_laugh': captions},
            )
            self.assertEqual([(r['remaining'], r['missing_txt']) for r in rows],
                             [(1, 1), (1, 1), (0, 2), (0, 2)])

    def test_toonzone_generated_txt_preserves_serial_and_state_checks(self):
        names = [f'S01E03_Caffeinated_Concert_Tickets_Part{i}' for i in (1, 2, 3)]
        files = {f'{name}.mp4': {'id': str(i), 'name': f'{name}.mp4'}
                 for i, name in enumerate(names)}
        entries = {'toonzone:facebook:0': {'status': 'done', 'post_id': 'confirmed'},
                   'toonzone:facebook:1': {'status': 'uncertain'}}
        with tempfile.TemporaryDirectory() as folder:
            captions = Path(folder)
            for name in names:
                (captions / f'{name}.txt').write_text('Caption', encoding='utf-8')
            facebook, instagram = build_stock(
                {'toonzone': files}, {'entries': entries}, {'toonzone': ('toonzone', 'ToonZone')},
                {'toonzone': 4}, generated_caption_dirs={'toonzone': captions},
            )
        self.assertEqual((facebook['remaining'], facebook['completed'], facebook['held']), (1, 1, 1))
        self.assertEqual(instagram['remaining'], 3)

    def test_missing_source_part_is_detected(self):
        files = {f'Movie_Part_{i}.mp4': {'id': str(i), 'name': f'Movie_Part_{i}.mp4'}
                 for i in (1, 3)}
        self.assertEqual(self.stock(files)[0]['missing_source_parts'], {'movie': [2]})


class EngagementTests(unittest.TestCase):
    def collect(self, get, pages):
        return collect_engagement([('Account', 'Page', 'Instagram')],
            lambda name: {'page_token': 'private', 'instagram_id': '12'},
            get, pages, measured_at='2026-11-02T20:00:00+03:00', period='2026-11-02')

    def test_zero_is_real_but_missing_is_unavailable(self):
        records, errors = self.collect(lambda *a, **k: {'id': '12', 'followers_count': 0},
            lambda *a, **k: [{'id': '30', 'media_type': 'VIDEO', 'like_count': 0}])
        likes = next(r for r in records if r['metric'] == 'like_count')
        comments = next(r for r in records if r['metric'] == 'comment_count')
        self.assertEqual((likes['value'], likes['status']), (0, 'ok'))
        self.assertEqual((comments['value'], comments['status']), (None, 'unavailable'))

    def test_late_pagination_failure_preserves_valid_followers(self):
        def pages(*a, **k):
            yield {'id': '30', 'media_type': 'VIDEO', 'like_count': 8}
            raise RuntimeError('private provider response')
        records, errors = self.collect(lambda *a, **k: {'id': '12', 'followers_count': 20}, pages)
        self.assertEqual(len(records), 1)
        self.assertTrue(errors)
        self.assertNotIn('private', json.dumps(errors))

    def test_history_failure_does_not_overwrite_success_and_delta_can_be_negative(self):
        good, _ = self.collect(lambda *a, **k: {'id': '12', 'followers_count': 20}, lambda *a, **k: [])
        bad, _ = self.collect(lambda *a, **k: {}, lambda *a, **k: [])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.jsonl'
            upsert_records(path, good, preserve_success_on_failure=True)
            upsert_records(path, bad, preserve_success_on_failure=True)
            self.assertEqual(json.loads(path.read_text())['value'], 20)
        row = good[0]
        key = (row['account'], row['platform'], row['entity_type'], row['entity_id'], row['metric'])
        self.assertEqual(follower_changes(good, {key: dict(row, value=22)})[0]['daily_change'], -2)
        self.assertIsNone(follower_changes(bad, {key: row})[0]['daily_change'])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg needed')
class RealMediaQualityTests(unittest.TestCase):
    def make_video(self, path, color, silent=False):
        audio = 'anullsrc=r=44100:cl=mono' if silent else 'sine=frequency=440:sample_rate=44100'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        f'color=c={color}:s=320x240:r=25:d=2', '-f', 'lavfi', '-i', audio,
                        '-t', '2', '-c:v', 'libx264', '-c:a', 'aac', str(path)],
                       check=True, capture_output=True, timeout=30)

    def test_real_visible_clip_passes_black_and_silent_clips_hold(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good, black, silent = [root / (x + '.mp4') for x in ('good', 'black', 'silent')]
            self.make_video(good, 'blue')
            self.make_video(black, 'black')
            self.make_video(silent, 'blue', silent=True)
            self.assertEqual(inspect_video(good)['status'], 'passed_samples')
            for path, reason in ((black, 'black_screen_samples'), (silent, 'silent_audio_samples')):
                with self.assertRaisesRegex(RuntimeError, reason):
                    inspect_video(path)


if __name__ == '__main__':
    unittest.main()
