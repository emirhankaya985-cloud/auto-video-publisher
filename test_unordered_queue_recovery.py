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


    def test_both_humor_accounts_skip_exact_visual_duplicate_and_plan_next(self):
        for route in ("tarladaki", "penguen"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                root = Path(tmp)
                page_name = "Tarladaki Fasulye" if route == "tarladaki" else "Beyinsiz Penguen"
                other = "Beyinsiz Penguen" if route == "tarladaki" else "Tarladaki Fasulye"
                held = {
                    "route": route, "status": "held", "file": "101.mp4",
                    "failure": {"reason": "visual_duplicate_review",
                                "external_post_attempted": False,
                                "safe_to_repost": False,
                                "conflicting_platforms": ["facebook", "instagram"]}}
                state = {"schema": 1,
                         "entries": {f"{route}:{p}:id-101": dict(held, platform=p)
                                     for p in ("facebook", "instagram")},
                         "episode_days": {}}
                original = copy.deepcopy(state["entries"])
                files = {f"{x}.mp4": {"id": f"id-{x}", "name": f"{x}.mp4"}
                         for x in (101, 102)}
                stack.enter_context(patch.dict(os.environ, {
                    "GITHUB_RUN_ID": "888", "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                    "ADAPTIVE_SCHEDULE_ENABLED": "false"}, clear=True))
                route_map = {"tarladaki": ("humor", "Tarladaki Fasulye"),
                             "penguen": ("humor", "Beyinsiz Penguen")}
                for attr, val in {"ROOT": root, "STATE": root / "state.json",
                                  "PLAN": root / "plan.json", "ROUTES": route_map,
                                  "FOLDERS": {"humor": "folder"}}.items():
                    stack.enter_context(patch.object(runtime, attr, val))
                pages = [{"page_name": p, "instagram_id": "444", "page_token": "mock"}
                         for p in (page_name, other)]
                for attr, ret in {"restore": state, "load_meta_auth": {"pages": pages},
                                  "inventory": files, "target_count": 5,
                                  "graph_rows": [], "route_enabled": True}.items():
                    stack.enter_context(patch.object(runtime, attr, return_value=ret))
                stack.enter_context(patch.object(runtime, "apply_verified_migration"))
                stack.enter_context(patch.object(runtime, "route_paused", return_value=False))
                stack.enter_context(patch.object(runtime, "copies",
                    side_effect=lambda *args, **kwargs: ({
                       "facebook": f"Unique {args[1]['id']}",
                       "instagram": f"Unique {args[1]['id']}"}, "matching-txt")))
                runtime.plan()
                plans = json.loads((root / "plan.json").read_text())
                self.assertEqual(len(plans), 1)
                self.assertEqual(plans[0]["id"], "id-102")
                self.assertEqual(set(plans[0]["platforms"]), {"facebook", "instagram"})
                saved = json.loads((root / "state.json").read_text())["entries"]
                for key, old in original.items():
                    self.assertEqual(saved[key], old)
                self.assertNotIn("post_id", saved[f"{route}:facebook:id-102"])
                self.assertIn("proven local-only visual duplicate",
                              (root / "report.md").read_text())

    def test_humor_held_external_post_or_nonvisual_failure_never_skipped(self):
        for failure in (
            {"reason": "visual_duplicate_review", "external_post_attempted": True,
             "safe_to_repost": False},
            {"reason": "visual_duplicate_review", "external_post_attempted": False,
             "safe_to_repost": True},
            {"reason": "post_api_uncertain", "external_post_attempted": False,
             "safe_to_repost": False},
        ):
            self.assertFalse(
                failure.get("reason") == "visual_duplicate_review"
                and failure.get("external_post_attempted") is False
                and failure.get("safe_to_repost") is False,
                failure) if failure.get("reason") != "visual_duplicate_review" or failure.get("external_post_attempted") is not False or failure.get("safe_to_repost") is not False else None


if __name__ == '__main__':
    unittest.main()
