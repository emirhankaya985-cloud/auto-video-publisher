"""Planner regressions for local failures when only one platform is pending."""
import copy
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from test_public_link_runtime import runtime


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 6, 15, 21, tzinfo=runtime.TR)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class PendingLocalPreparationQuarantine(unittest.TestCase):
    def run_plan(self, *, mutation=None, route='tarladaki', existing_facebook=False,
                 clean_remote_collision=False):
        bad = {'id': 'source278', 'name': '278.mp4'}
        clean = {'id': 'source279', 'name': '279.mp4'}
        if route == 'film':
            bad['name'], clean['name'] = 'Bickin_Part_8.mp4', 'Bickin_Part_9.mp4'
        page_name = 'Film Mağarası' if route == 'film' else 'Tarladaki Fasulye'
        source = 'film' if route == 'film' else 'humor'
        caption = 'Exact caption for failed source'
        row = {'route': route, 'platform': 'instagram', 'file': bad['name'],
               'status': 'ready', 'run_id': '100', 'day': '2026-11-06',
               'caption_hash': runtime.caption_key(caption), 'publish_caption': caption,
               'source_sha256': 'a' * 64,
               'failure': {'reason': 'source_or_cover_preparation_failed',
                           'safe_to_repost': True, 'error_type': 'RuntimeError'}}
        if mutation:
            row.update(mutation)
        state = {'schema': 1, 'entries': {f'{route}:instagram:{bad["id"]}': row},
                 'episode_days': {}}
        facebook_history = [
            {'id': str(1000 + n), 'description': f'Previous Facebook quota {n}',
             'created_time': '2026-11-06T09:00:00+03:00'} for n in range(2)]
        if existing_facebook:
            facebook_history[0]['description'] = caption
            state['entries'][f'{route}:facebook:{bad["id"]}'] = {
                'route': route, 'platform': 'facebook', 'file': bad['name'],
                'status': 'done', 'post_id': '1000', 'run_id': '90',
                'day': '2026-11-06', 'caption_hash': runtime.caption_key(caption),
                'source_sha256': 'a' * 64}
        original = copy.deepcopy(state['entries'])
        files = {item['name']: item for item in (bad, clean)}
        def captions(route, item, files, temp):
            value = caption if item['id'] == bad['id'] else 'Unique clean source caption'
            return {'facebook': value, 'instagram': value}, 'matching-txt'
        def histories(page, platform):
            if page['page_name'] != page_name:
                return []
            if platform == 'facebook':
                return facebook_history
            if clean_remote_collision:
                return [{'id': '987', 'caption': 'Unique clean source caption',
                         'timestamp': '2026-11-05T10:00:00+03:00'}]
            return []
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            stack.enter_context(patch.dict(os.environ, {
                'GITHUB_RUN_ID': '200', 'GITHUB_STEP_SUMMARY': str(root/'summary.md')}, clear=True))
            routes = {route: (source, page_name)}
            pages = [{'page_name': page_name, 'instagram_id': '999'}]
            if route == 'tarladaki':
                routes['penguen'] = ('humor', 'Beyinsiz Penguen')
                pages.append({'page_name': 'Beyinsiz Penguen'})
            for attr, value in {'ROOT': root, 'STATE': root/'state.json', 'PLAN': root/'plan.json',
                                'ROUTES': routes, 'FOLDERS': {source: 'folder'},
                                'datetime': FixedDatetime}.items():
                stack.enter_context(patch.object(runtime, attr, value))
            for attr, value in {'restore': state, 'load_meta_auth': {'pages': pages},
                                'inventory': files, 'target_count': 2,
                                'seed_done': False, 'route_paused': False,
                                'previous_intent_alert_due': False,
                                'verified_film_duplicate': None}.items():
                stack.enter_context(patch.object(runtime, attr, return_value=value))
            stack.enter_context(patch.object(runtime, 'route_enabled', side_effect=lambda r: r == route))
            stack.enter_context(patch.object(runtime, 'graph_rows', side_effect=histories))
            stack.enter_context(patch.object(runtime, 'copies', side_effect=captions))
            stack.enter_context(patch.object(runtime, 'apply_verified_migration'))
            with patch.object(runtime, 'upload_facebook_reel') as facebook, \
                 patch.object(runtime, 'upload_instagram_reel') as instagram:
                runtime.plan()
            facebook.assert_not_called()
            instagram.assert_not_called()
            return (json.loads((root/'plan.json').read_text()),
                    json.loads((root/'state.json').read_text())['entries'], original,
                    (root/'report.md').read_text())

    def test_quota_full_platform_without_source_row_does_not_starve_remaining_feed(self):
        plans, saved, original, report = self.run_plan()
        self.assertEqual([(p['id'], p['platforms']) for p in plans], [('source279', ['instagram'])])
        self.assertEqual(saved['tarladaki:instagram:source278'], original['tarladaki:instagram:source278'])
        self.assertNotIn('tarladaki:facebook:source278', saved)
        self.assertIn('exact pending platforms failed local preparation', report)

    def test_confirmed_other_platform_record_is_preserved_without_republication(self):
        plans, saved, original, _ = self.run_plan(existing_facebook=True)
        self.assertEqual([p['id'] for p in plans], ['source279'])
        for key, row in original.items():
            self.assertEqual(saved[key], row)

    def test_unknown_uncertain_post_stays_blocked_before_pending_quarantine(self):
        plans, saved, original, _ = self.run_plan(mutation={'status': 'uncertain',
            'failure': {'reason': 'upload_failed', 'safe_to_repost': False}})
        self.assertEqual(plans, [])
        self.assertEqual(saved, original)

    def test_next_candidate_still_requires_normal_remote_history_checks(self):
        plans, saved, original, report = self.run_plan(clean_remote_collision=True)
        self.assertEqual(plans, [])
        self.assertEqual(saved, original)
        self.assertIn('remote caption already exists; source unverified', report)

    def test_different_day_or_missing_local_evidence_cannot_skip_failed_source(self):
        for mutation in ({'day': '2026-11-05'}, {'failure': {}},
                         {'failure': {'reason': 'source_or_cover_preparation_failed', 'safe_to_repost': False}}):
            with self.subTest(mutation=mutation):
                plans, _, _, report = self.run_plan(mutation=mutation)
                self.assertEqual([p['id'] for p in plans], ['source278'])
                self.assertNotIn('exact pending platforms failed local preparation', report)

    def test_serial_route_keeps_failed_part_in_sequence(self):
        plans, _, _, report = self.run_plan(route='film')
        self.assertEqual([p['id'] for p in plans], ['source278'])
        self.assertNotIn('exact pending platforms failed local preparation', report)


if __name__ == '__main__':
    unittest.main()
