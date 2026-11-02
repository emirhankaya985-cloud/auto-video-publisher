import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from adaptive_schedule import build_schedule, slots_for_route, restore_schedule, freeze_schedule


class AdaptiveScheduleTests(unittest.TestCase):
    generated = datetime(2026, 11, 2, 20, 15, tzinfo=timezone.utc)
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    original = [(h, 30) for h in (9, 12, 15, 18, 21)]

    def evidence(self):
        return [dict(route='penguen', platform=p, hour_tr=h, posts=4, days=3,
                     engagement_per_1000_views=20) for p in ('facebook', 'instagram')
                for h in (10, 13, 16, 19, 22)]

    def test_preserves_five_slots_and_minutes_only_on_next_day(self):
        plan = build_schedule(self.evidence(), generated_at=self.generated)
        self.assertEqual(slots_for_route(plan, 'penguen', self.now, self.original),
                         [(h, 30) for h in (10, 13, 16, 19, 22)])
        self.assertEqual(slots_for_route(plan, 'penguen', self.generated, self.original), self.original)
        self.assertEqual(slots_for_route(plan, 'film', self.now, self.original), self.original)
        self.assertEqual(slots_for_route(plan, 'toonzone', self.now, self.original), self.original)

    def test_missing_platform_or_hour_never_changes_slots(self):
        for rows in ([], self.evidence()[:-1], self.evidence()[:5]):
            plan = build_schedule(rows, generated_at=self.generated)
            self.assertEqual(slots_for_route(plan, 'penguen', self.now, self.original), self.original)

    def test_duplicate_hours_and_malformed_evidence_rejected(self):
        plan = build_schedule(self.evidence(), generated_at=self.generated)
        plan['slots']['penguen'] = [10, 10, 13, 16, 19]
        self.assertEqual(slots_for_route(plan, 'penguen', self.now, self.original), self.original)
        self.assertEqual(slots_for_route({}, 'penguen', self.now, self.original), self.original)

    def test_late_report_cannot_change_first_policy_or_fallback(self):
        for first in ({}, {'slots': {'penguen': [10, 13, 16, 19, 22]}}):
            with self.subTest(first=first), tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / 'policy.json'
                state = {'entries': {}}
                target.write_text(json.dumps(first))
                freeze_schedule(state, '2026-11-03', target)
                target.write_text(json.dumps({'slots': {'penguen': [8, 11, 14, 17, 20]}}))
                freeze_schedule(state, '2026-11-03', target)
                self.assertEqual(json.loads(target.read_text()), first)
                self.assertEqual(state['entries'], {})

    def test_restore_uses_only_successful_main_artifact(self):
        document = build_schedule(self.evidence(), generated_at=self.generated)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('time-recommendations.json', json.dumps({'schedule': document}))
        def response(payload=None, content=b''):
            return SimpleNamespace(json=lambda: payload, content=content, raise_for_status=lambda: None)
        get = Mock(side_effect=[
            response({'workflow_runs': [{'id': 1, 'head_branch': 'main', 'conclusion': 'success'}]}),
            response({'artifacts': [{'id': 2, 'name': 'publish-time-recommendations', 'expired': False}]}),
            response(content=data.getvalue()),
        ])
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'policy.json'
            receipt = restore_schedule(target, token='offline-test', now=self.now, get=get)
            self.assertEqual(receipt['status'], 'restored')
            self.assertEqual(json.loads(target.read_text()), document)
            # Missing evidence removes any stale local plan and falls back.
            receipt = restore_schedule(target, token='', now=self.now, get=get)
            self.assertEqual(receipt['status'], 'fallback')
            self.assertFalse(target.exists())
