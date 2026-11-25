"""Preserve failed local sources while allowing unrelated unordered clips."""
import copy
import os
import unittest
from unittest.mock import patch
from public_link_runtime import quarantined_unordered_local_failure as held


class LocalPreparationHoldTests(unittest.TestCase):
    def state(self, route):
        return {'entries': {f'{route}:{p}:source195': {
            'route': route, 'platform': p, 'file': '195.mp4',
            'day': '2026-11-05', 'run_id': '42156394826', 'status': 'ready',
            'failure': {'reason': 'source_or_cover_preparation_failed', 'safe_to_repost': True}
        } for p in ('facebook', 'instagram')}}

    def test_exact_prior_local_failure_is_skipped_without_mutation_for_unordered_feeds(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '42160000000'}):
            for route in ('tarladaki', 'penguen', 'gonle', 'daily_laugh'):
                state = self.state(route)
                before = copy.deepcopy(state)
                self.assertTrue(held(route, {'id':'source195','name':'195.mp4'}, state,
                                     ['facebook','instagram'], '2026-11-05'))
                self.assertEqual(state, before)

    def test_confirmed_penguen_342_silent_audio_is_quarantined_across_days(self):
        source_id = '14jz507WmoB-gAsSILcA6WT2LRJgHH1l0'
        source_sha256 = 'c012a06a7207bb73895fbeba8493f8493534be07024227a13fe30499f62ea555'
        state = {'entries': {f'penguen:{p}:{source_id}': {
            'route': 'penguen', 'platform': p, 'file': '342.mp4',
            'day': '2026-11-23', 'run_id': '45171317800', 'status': 'ready',
            'source_sha256': source_sha256,
            'failure': {'reason': 'source_or_cover_preparation_failed',
                        'media_diagnostic': 'silent_audio_samples',
                        'safe_to_repost': True}
        } for p in ('facebook', 'instagram')}}
        before = copy.deepcopy(state)
        item = {'id': source_id, 'name': '342.mp4'}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '45180000000'}):
            self.assertTrue(held('penguen', item, state,
                                 ['facebook', 'instagram'], '2026-11-24'))
        self.assertEqual(state, before)
        changed_bytes = copy.deepcopy(state)
        for row in changed_bytes['entries'].values():
            row['source_sha256'] = 'f' * 64
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '45180000000'}):
            self.assertFalse(held('penguen', item, changed_bytes,
                                  ['facebook', 'instagram'], '2026-11-24'))
            replacement = {'id': 'new-drive-object', 'name': '342.mp4'}
            self.assertFalse(held('penguen', replacement, state,
                                  ['facebook', 'instagram'], '2026-11-24'))

    def test_confirmed_penguen_414_silent_audio_is_quarantined_across_days(self):
        source_id = '1_zCLAJJGTVrZ5h8HReMY3Vj-1q1rylga'
        source_sha256 = '7526fb6ea06e3c4466dbbd7ed7bba8393beaab7a52de404a5cb00edf9919a931'
        state = {'entries': {f'penguen:{p}:{source_id}': {
            'route': 'penguen', 'platform': p, 'file': '414.mp4',
            'day': '2026-11-23', 'run_id': '45240919761', 'status': 'ready',
            'source_sha256': source_sha256,
            'failure': {'reason': 'source_or_cover_preparation_failed',
                        'media_diagnostic': 'silent_audio_samples',
                        'safe_to_repost': True}
        } for p in ('facebook', 'instagram')}}
        before = copy.deepcopy(state)
        item = {'id': source_id, 'name': '414.mp4'}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '45250000000'}):
            self.assertTrue(held('penguen', item, state,
                                 ['facebook', 'instagram'], '2026-11-24'))
        self.assertEqual(state, before)
        changed_bytes = copy.deepcopy(state)
        for row in changed_bytes['entries'].values():
            row['source_sha256'] = 'f' * 64
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '45250000000'}):
            self.assertFalse(held('penguen', item, changed_bytes,
                                  ['facebook', 'instagram'], '2026-11-24'))
            self.assertFalse(held('penguen', {'id': 'replacement', 'name': '414.mp4'},
                                  state, ['facebook', 'instagram'], '2026-11-24'))

    def test_tarladaki_560_fingerprint_frame_failure_is_held_across_days(self):
        source_id = '1Zl7Uf_TgRSU71iGS4xeWH67KYXTxFiuQ'
        source_sha256 = '1b14cb6c20f9be569d1742589e9472fab04bc899aaf28fb1f43061034d751582'
        state = {'entries': {f'tarladaki:{p}:{source_id}': {
            'route': 'tarladaki', 'platform': p, 'file': '560.mp4',
            'day': '2026-11-24', 'run_id': '45449684883', 'status': 'ready',
            'source_sha256': source_sha256,
            'failure': {'reason': 'source_or_cover_preparation_failed',
                        'error_type': 'RuntimeError',
                        'safe_to_repost': True}
        } for p in ('facebook', 'instagram')}}
        before = copy.deepcopy(state)
        item = {'id': source_id, 'name': '560.mp4'}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '45460000000'}):
            self.assertTrue(held('tarladaki', item, state,
                                 ['facebook', 'instagram'], '2026-11-25'))
        self.assertEqual(state, before)
        changed_bytes = copy.deepcopy(state)
        for row in changed_bytes['entries'].values():
            row['source_sha256'] = 'f' * 64
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '45460000000'}):
            self.assertFalse(held('tarladaki', item, changed_bytes,
                                  ['facebook', 'instagram'], '2026-11-25'))
            self.assertFalse(held('tarladaki', {'id': 'replacement', 'name': '560.mp4'},
                                  state, ['facebook', 'instagram'], '2026-11-25'))

    def test_uncertain_missing_mismatched_current_and_serial_records_cannot_be_skipped(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '42160000000'}):
            item = {'id':'source195','name':'195.mp4'}
            for mutation in ('uncertain', 'missing', 'different_file', 'current_run'):
                state = self.state('daily_laugh')
                row = state['entries']['daily_laugh:instagram:source195']
                if mutation == 'uncertain': row['status'] = 'uncertain'
                if mutation == 'missing': del state['entries']['daily_laugh:instagram:source195']
                if mutation == 'different_file': row['file'] = '194.mp4'
                if mutation == 'current_run': row['run_id'] = '42160000000'
                self.assertFalse(held('daily_laugh', item, state, ['facebook','instagram'], '2026-11-05'))
            self.assertFalse(held('daily_laugh', item, self.state('daily_laugh'),
                                  ['facebook','instagram'], '2026-11-06'))
            for route in ('film','film_second','toonzone'):
                self.assertFalse(held(route, item, self.state(route),
                                      ['facebook','instagram'], '2026-11-05'))
