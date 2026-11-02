import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from publication_operations import (create_backup, restore_backup, series_report,
                                    verify_publications, checked_backup)


def entry(part, status='done', post='100', route='film', platform='instagram'):
    name = f'Film_Part_{part}.mp4' if route == 'film' else f'S01E07_Title_Part{part}.mp4'
    return dict(route=route, platform=platform, file=name, status=status,
                post_id=post, run_id='123')


class OperationsTests(unittest.TestCase):
    def test_platform_isolation_and_gap(self):
        state = dict(schema=1, entries={'a': entry(1), 'b': entry(3),
                     'c': entry(2, platform='facebook')})
        groups = {r['platform']: r for r in series_report(state)['series']}
        self.assertEqual(groups['instagram']['missing_parts'], [2])
        self.assertEqual(groups['facebook']['missing_parts'], [1])

    def test_alias_does_not_create_second_success(self):
        a = entry(1)
        alias = dict(a, file='Film_Part_1 (1).mp4', status='uncertain', post_id='')
        report = series_report(dict(schema=1, entries={'a': a, 'b': alias}))['series'][0]
        self.assertEqual(report['confirmed_parts'], [1])
        self.assertEqual(report['conflicting_parts'], [])
        alias.update(status='done', post_id='200')
        report = series_report(dict(schema=1, entries={'a': a, 'b': alias}))['series'][0]
        self.assertEqual(report['conflicting_parts'], [1])

    def test_toonzone_expects_four_parts_and_id_required(self):
        report = series_report(dict(schema=1, entries={'a': entry(1, route='toonzone'),
                     'b': entry(2, route='toonzone', post='')}))['series'][0]
        self.assertEqual(report['missing_parts'], [2, 3, 4])
        self.assertEqual(report['held_parts'], [2])

    def test_lossless_backup_restore_and_overwrite_refusal(self):
        state = dict(schema=1, entries={'a': entry(1)}, youtube_entries={'y': {'status': 'accepted'}},
                     unknown_future_field={'preserve': True})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, backup, dest = [root / p for p in ('state.json', 'backup.zip', 'restored.json')]
            source.write_text(json.dumps(state))
            create_backup(source, backup)
            restore_backup(backup, dest)
            self.assertEqual(source.read_bytes(), dest.read_bytes())
            with self.assertRaises(FileExistsError):
                restore_backup(backup, dest)
            with self.assertRaises(FileExistsError):
                create_backup(source, backup)

    def test_corruption_rejected_before_restore(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('state.json', '{"schema":1,"entries":{}}')
            z.writestr('manifest.json', '{"schema":1,"bytes":25,"sha256":"bad"}')
        with self.assertRaises(ValueError):
            checked_backup(data.getvalue())

    def test_get_only_verification_never_mutates_uncertain_or_done(self):
        state = dict(schema=1, entries={'a': entry(1), 'b': entry(2, 'uncertain'),
                     'c': dict(entry(3), run_id='old')})
        original = copy.deepcopy(state)
        calls = []
        def history(route, platform):
            calls.append((route, platform))
            return [{'id': '100'}]
        report = verify_publications(state, '123', history)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]['status'], 'verified')
        self.assertEqual(state, original)
        self.assertEqual(calls, [('film', 'instagram')])

    def test_history_failure_and_missing_never_grant_repost(self):
        state = dict(schema=1, entries={'a': entry(1), 'b': entry(2, post='200')})
        def fail(*args):
            raise RuntimeError('sensitive provider body')
        for read in (fail, lambda *a: [], lambda *a: {}):
            report = verify_publications(state, '123', read)
            self.assertTrue(all(r['status'] == 'unverified' for r in report))
            self.assertNotIn('sensitive', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
