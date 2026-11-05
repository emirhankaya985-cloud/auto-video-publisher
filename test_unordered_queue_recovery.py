"""Reproduce partial old records blocking unrelated unordered source videos."""
import copy
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import public_link_runtime as runtime


class UnorderedQueueTests(unittest.TestCase):
    def test_old_ambiguous_or_uncertain_candidate_preserves_evidence_and_selects_next(self):
        for route in ('gonle', 'daily_laugh'):
            for status in ('done', 'uncertain', 'held'):
                with self.subTest(route=route, status=status), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                    root = Path(tmp)
                    name = 'Gönle Düşen' if route == 'gonle' else 'Daily Laugh Lab'
                    row = {'route': route, 'platform': 'instagram', 'file': '101.mp4',
                           'status': status, 'caption_hash': runtime.caption_key('old caption')}
                    if status == 'done':
                        row.update(post_id='111', day='2026-10-20')
                    elif status == 'uncertain':
                        row['failure'] = {'stage': 'Instagram ikili video aktarımı', 'http_status': 400,
                                          'container_status': 'IN_PROGRESS'}
                        row['prepublish_retry_count'] = 1
                    else:
                        row['failure'] = {'external_post_attempted': False}
                    state = {'schema': 1, 'entries': {f'{route}:instagram:id-101': row}, 'episode_days': {}}
                    original = copy.deepcopy(row)
                    files = {f'{n}.mp4': {'id': f'id-{n}', 'name': f'{n}.mp4'} for n in (101, 102)}
                    def captions(route, item, files, temp):
                        value = 'old caption' if item['id'] == 'id-101' else 'new unique caption'
                        return {'facebook': value, 'instagram': value}, 'matching-txt'
                    remote = [{'id': str(n), 'caption': 'old caption',
                               'timestamp': '2026-10-20T10:00:00Z'} for n in (111, 222)] if status == 'done' else []
                    stack.enter_context(patch.dict(os.environ, {'GITHUB_RUN_ID': '456',
                                                               'GITHUB_STEP_SUMMARY': str(root / 'summary.md')}))
                    for attr, value in {'ROOT': root, 'STATE': root/'state.json', 'PLAN': root/'plan.json',
                                        'ROUTES': {route: (route, name)}, 'FOLDERS': {route: 'folder'}}.items():
                        stack.enter_context(patch.object(runtime, attr, value))
                    for attr, value in {'restore': state, 'load_meta_auth': {'pages': [{'page_name': name,
                                         'instagram_id': '999', 'page_token': 'test'}]}, 'inventory': files,
                                        'target_count': 5, 'graph_rows': remote, 'route_enabled': True}.items():
                        stack.enter_context(patch.object(runtime, attr, return_value=value))
                    stack.enter_context(patch.object(runtime, 'apply_verified_migration'))
                    stack.enter_context(patch.object(runtime, 'route_paused', return_value=False))
                    stack.enter_context(patch.object(runtime, 'previous_intent_alert_due', return_value=False))
                    stack.enter_context(patch.object(runtime, 'copies', side_effect=captions))
                    runtime.plan()
                    plans = json.loads((root/'plan.json').read_text())
                    self.assertEqual([p['id'] for p in plans], ['id-102'])
                    saved = json.loads((root/'state.json').read_text())['entries']
                    self.assertEqual(saved[f'{route}:instagram:id-101'], original)
                    self.assertNotIn(f'{route}:facebook:id-101', saved)


if __name__ == '__main__':
    unittest.main()
