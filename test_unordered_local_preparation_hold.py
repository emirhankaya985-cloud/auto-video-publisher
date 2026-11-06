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
