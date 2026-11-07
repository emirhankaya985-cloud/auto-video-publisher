import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from publication_operations import (create_backup, restore_backup, series_report,
                                    verify_publications, verify_publications_with_retry,
                                    checked_backup, audit_unresolved_remote)


def entry(part, status='done', post='100', route='film', platform='instagram'):
    name = f'Film_Part_{part}.mp4' if route == 'film' else f'S01E07_Title_Part{part}.mp4'
    return dict(route=route, platform=platform, file=name, status=status,
                post_id=post, run_id='123')


class OperationsTests(unittest.TestCase):
    def test_retry_reads_only_pending_history_and_preserves_evidence(self):
        state = {'schema': 1, 'entries': {
            'ig': entry(1, post='100'),
            'fb': entry(1, post='200', platform='facebook'),
        }}
        attempts, delays = [], []

        def history(route, platform):
            attempts.append(platform)
            if platform == 'facebook':
                return [{'id': '200'}]
            if attempts.count('instagram') == 1:
                raise TimeoutError
            return [{'id': '100'}]

        results = verify_publications_with_retry(state, '123', history, sleep=delays.append)
        self.assertEqual([row['status'] for row in results], ['verified', 'verified'])
        self.assertEqual(attempts, ['instagram', 'facebook', 'instagram'])
        self.assertEqual(delays, [5])

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

    def test_unresolved_remote_audit_never_resolves_by_caption_alone(self):
        from publication_operations import _caption_digest as caption_key
        original = dict(schema=1, entries={
            'a': dict(entry(1, 'uncertain', post=''), caption_hash=caption_key('Exact caption')),
            'b': dict(entry(2, 'held', post=''), failure={'reason': 'visual_duplicate_review'}),
            'c': dict(entry(3, 'uncertain', post=''), caption_hash=caption_key('missing')),
        })
        before = copy.deepcopy(original)
        reads = []
        def history(route, platform):
            reads.append((route, platform))
            return [{'id': '500', 'caption': 'Exact caption'}]
        result = audit_unresolved_remote(original, history)
        self.assertEqual([row['reason'] for row in result],
            ['caption_candidate_requires_source_proof',
             'visual_duplicate_requires_owner_review',
             'not_observed_in_bounded_remote_history'])
        self.assertEqual(result[0]['candidate_post_id'], '500')
        self.assertTrue(all(row['safe_to_repost'] is False for row in result))
        self.assertEqual(reads, [('film', 'instagram')])
        self.assertEqual(original, before)

    def test_unresolved_container_probe_preserves_original_intent(self):
        from publication_operations import _caption_digest
        state = dict(schema=1, entries={'x': dict(entry(1, 'uncertain', post=''),
                      caption_hash=_caption_digest('Original'),
                      failure={'reason': 'invalid_media_or_graph_request',
                               'container_id': '1234567890'})})
        before = copy.deepcopy(state)
        probes = []
        def status(route, container):
            probes.append((route, container))
            return 'IN_PROGRESS'
        result = audit_unresolved_remote(state, lambda *args: [],
                                         read_container=status)
        self.assertEqual(result[0]['existing_container_phase'], 'IN_PROGRESS')
        self.assertEqual(result[0]['reason'], 'not_observed_in_bounded_remote_history')
        self.assertEqual(probes, [('film', '1234567890')])
        self.assertEqual(state, before)
        self.assertFalse(result[0]['safe_to_repost'])

    def test_same_drive_item_other_platform_cross_film_pages_is_not_ig_success(self):
        from publication_operations import _caption_digest
        source = '1Zn8kYmexuUe3z1EKLtCrKFCwj4qVnIa2'
        state = dict(schema=1, entries={
            'film:instagram:'+source: dict(entry(10, 'uncertain', post=''),
                file='Avanak_Apti_Part_10 (1).mp4',
                caption_hash=_caption_digest('caption')),
            'film_second:facebook:'+source: dict(entry(10, 'done', post='999999',
                route='film_second', platform='facebook'),
                file='Avanak_Apti_Part_10 (1).mp4'),
        })
        before = copy.deepcopy(state)
        rows = audit_unresolved_remote(state, lambda *args: [])
        proof = rows[0]['source_evidence']
        self.assertTrue(proof['same_drive_item_other_platform_done'])
        self.assertTrue(proof['same_drive_item_other_route_done'])
        self.assertFalse(proof['source_sha256_present'])
        self.assertFalse(proof['other_platform_exact_sha256_done'])
        self.assertFalse(rows[0]['safe_to_repost'])
        self.assertEqual(state, before)

    def test_changed_file_name_or_corrupt_drive_key_cannot_prove_same_item(self):
        source = '1Zn8kYmexuUe3z1EKLtCrKFCwj4qVnIa2'
        state = dict(schema=1, entries={
            'film:instagram:'+source: dict(entry(1, 'uncertain', post=''),
                file='Original.mp4'),
            'film:facebook:'+source: dict(entry(1, 'done', post='123456',
                platform='facebook'), file='Different.mp4'),
        })
        rows = audit_unresolved_remote(state, lambda *args: [])
        self.assertFalse(rows[0]['source_evidence']['same_drive_item_other_platform_done'])

    def test_source_evidence_separates_verified_cross_platform_bytes_from_ig_post(self):
        from publication_operations import _caption_digest
        sha = 'a' * 64
        state = dict(schema=1, entries={
            'new_ig': dict(entry(1, 'uncertain', post=''),
                           source_sha256=sha, caption_hash=_caption_digest('original')),
            'facebook_done': dict(entry(1, platform='facebook', post='12345'),
                                  source_sha256=sha),
        })
        before = copy.deepcopy(state)
        rows = audit_unresolved_remote(state, lambda *a: [])
        self.assertEqual(len(rows), 1)
        proof = rows[0]['source_evidence']
        self.assertEqual(len(proof['entry_fingerprint']), 16)
        self.assertTrue(proof['other_platform_exact_sha256_done'])
        self.assertTrue(proof['source_sha256_present'])
        self.assertFalse(rows[0]['safe_to_repost'])
        self.assertEqual(rows[0]['reason'], 'not_observed_in_bounded_remote_history')
        self.assertEqual(state, before)

    def test_missing_source_digest_has_filename_clue_not_verified_bytes(self):
        state = dict(schema=1, entries={
            'unresolved': dict(entry(1, 'uncertain', post='')),
            'facebook': entry(1, platform='facebook', post='12345'),
        })
        report = audit_unresolved_remote(state, lambda *a: [])
        proof = report[0]['source_evidence']
        self.assertFalse(proof['source_sha256_present'])
        self.assertFalse(proof['other_platform_exact_sha256_done'])
        self.assertTrue(proof['other_platform_filename_candidate'])
        self.assertFalse(report[0]['safe_to_repost'])

    def test_sibling_film_holds_are_not_misclassified_as_confirmed_posts(self):
        sha = 'b' * 64
        state = dict(schema=1, entries={
            'film_first': dict(entry(1, 'held', post='', platform='facebook'),
                               source_sha256=sha,
                               failure={'reason': 'visual_duplicate_review'}),
            'film_second': dict(entry(1, 'held', post='', route='film_second',
                                    platform='facebook'), source_sha256=sha,
                                failure={'reason': 'visual_duplicate_review'}),
        })
        rows = audit_unresolved_remote(state, lambda *a: [])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['source_evidence']['same_source_held_sibling_pages'] for row in rows))
        self.assertTrue(all(row['reason'] == 'visual_duplicate_requires_owner_review' for row in rows))
        self.assertTrue(all(not row['source_evidence']['other_platform_exact_sha256_done'] for row in rows))

    def test_unresolved_remote_audit_history_failure_never_becomes_absence(self):
        from publication_operations import _caption_digest as caption_key
        state = dict(schema=1, entries={
            'a': dict(entry(1, 'uncertain', post=''), caption_hash=caption_key('caption')),
            'b': dict(entry(2, 'uncertain', post=''), caption_hash=caption_key('caption'))})
        calls = []
        def fails(*args):
            calls.append(1)
            raise RuntimeError('provider token=private')
        result = audit_unresolved_remote(state, fails)
        self.assertEqual(len(calls), 1)
        self.assertEqual([x['reason'] for x in result], ['remote_history_unavailable'] * 2)
        self.assertNotIn('private', str(result))

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
