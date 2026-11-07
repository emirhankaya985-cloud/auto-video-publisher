import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import sequential_toonzone_review as seq


def mock_discovery(now, actor):
    return {"instagram": ["https://www.instagram.com/reel/abcDEF123/"]}, {}


class SequenceTests(unittest.TestCase):
    def test_order_and_ack_required(self):
        state = {"schema": 1, "records": {}}
        now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        for index, name in enumerate(seq.ORDER):
            plan = seq.prepare(state, now + timedelta(minutes=index * 15), str(index + 10), discover=mock_discovery)
            self.assertEqual((plan["status"], plan["actor"]), ("reserved", name))
            blocked = seq.prepare(state, now + timedelta(minutes=index * 15), "999", discover=mock_discovery)
            self.assertEqual(blocked["status"], "blocked_unresolved_intent")
            self.assertTrue(seq.apply_ack(state, plan, str(index + 10), delivered=True))
        self.assertEqual(seq.prepare(state, now + timedelta(hours=2), "20", discover=mock_discovery)["status"],
                         "day_completed")
        self.assertEqual(state["toonzone_sequence"]["cursor"], len(seq.ORDER))

    def test_does_not_advance_on_failed_read(self):
        history = {"schema": 1, "records": {}}
        now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        out = seq.prepare(history, now, "10", discover=lambda n, a: ({}, {"threads": "read failed"}))
        self.assertEqual(out["status"], "platform_read_failed")
        self.assertEqual(history["toonzone_sequence"]["cursor"], 0)

    def test_ambiguous_delivery_halts_current_and_next_day(self):
        state = {"schema": 1, "records": {}}
        now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        plan = seq.prepare(state, now, "10", discover=mock_discovery)
        seq.apply_ack(state, plan, "10", delivered=False)
        self.assertEqual(seq.prepare(state, now + timedelta(minutes=15), "11", discover=mock_discovery)["status"],
                         "blocked_unresolved_intent")
        with self.assertRaises(ValueError):
            seq.prepare(state, now + timedelta(days=1), "12", discover=mock_discovery)

    def test_guard_and_time_window(self):
        now = datetime(2026, 11, 9, 11, 59, tzinfo=timezone.utc)
        self.assertIsNone(seq.active_day(now))
        self.assertEqual(seq.active_day(now + timedelta(minutes=1)), "2026-11-09")
        self.assertIsNone(seq.active_day(now + timedelta(hours=6)))
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}):
            self.assertFalse(seq.check_runner())

    def test_no_platform_writes_and_unconfirmed_ack(self):
        state = {"schema": 1, "records": {}}
        now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        plan = seq.prepare(state, now, "10", discover=mock_discovery)
        self.assertIn("Otomatik beğeni/kaydetme yapılmadı.", plan["message"])
        self.assertFalse(seq.apply_ack(state, plan, "10", delivered=False))


if __name__ == "__main__":
    unittest.main()
