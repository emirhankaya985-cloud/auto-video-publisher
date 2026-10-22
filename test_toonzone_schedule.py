"""No network, credentials, Drive writes, or platform publishing."""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from toonzone_schedule import TRT, due_toonzone_slots, toonzone_part_eligible


class ToonzoneScheduleTests(unittest.TestCase):
    def slots(self, now, enabled=True, lookback=1440):
        return due_toonzone_slots(now, now - timedelta(minutes=lookback), enabled=enabled)

    def test_four_slots_appear_in_order_only_when_due(self):
        base = datetime(2026, 10, 21, 12, 0, tzinfo=TRT)
        for minute, count in ((0, 1), (9, 1), (10, 2), (19, 2), (20, 3), (29, 3), (30, 4), (45, 4)):
            with self.subTest(minute=minute):
                slots = self.slots(base + timedelta(minutes=minute))
                self.assertEqual(
                    [row[2] for row in slots if row[0].date() == base.date()],
                    [f"2026-10-21-12-toonzone-part{i}" for i in range(1, count + 1)],
                )

    def test_no_premature_or_unauthorized_publications(self):
        now = datetime(2026, 10, 21, 11, 59, tzinfo=TRT)
        self.assertEqual(self.slots(now, lookback=30), [])
        self.assertEqual(self.slots(now + timedelta(minutes=41), enabled=False), [])

    def test_window_filters_expired_slots_and_has_no_duplicate_date(self):
        now = datetime(2026, 10, 21, 12, 20, tzinfo=TRT)
        rows = self.slots(now, lookback=31)
        self.assertEqual([p for _, _, p in rows], [
            "2026-10-21-12-toonzone-part1",
            "2026-10-21-12-toonzone-part2",
            "2026-10-21-12-toonzone-part3",
        ])
        self.assertEqual(len(rows), len(set(row[2] for row in rows)))

    def test_older_day_is_not_replayed_during_todays_catchup(self):
        now = datetime(2026, 10, 21, 12, 25, tzinfo=TRT)
        rows = self.slots(now)
        self.assertTrue(all(row[0].date() == now.date() for row in rows))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows, sorted(rows))

    def test_pending_part_two_can_resume_without_replaying_used_part_one(self):
        ordered = [
            ((1, 1, i), f"Part{i}", {"appProperties": {"used": "1"} if i == 1 else {}}, None)
            for i in range(1, 5)
        ]
        self.assertFalse(toonzone_part_eligible("2026-10-21-12-toonzone-part1", ordered,
                                                 used_key="used", last_slot_key="last"))
        self.assertTrue(toonzone_part_eligible("2026-10-21-12-toonzone-part2", ordered,
                                                used_key="used", last_slot_key="last"))
        self.assertFalse(toonzone_part_eligible("2026-10-21-12-toonzone-part3", ordered,
                                                 used_key="used", last_slot_key="last"))

    def test_next_episode_part_one_is_not_restarted_on_same_date(self):
        ordered = [
            ((1, 1, i), f"E1Part{i}", {"appProperties": {"used": "1", "last": f"2026-10-21-12-toonzone-part{i}"}}, None)
            for i in range(1, 5)
        ] + [((1, 2, 1), "E2Part1", {"appProperties": {}}, None)]
        self.assertFalse(toonzone_part_eligible("2026-10-21-12-toonzone-part1", ordered,
                                                 used_key="used", last_slot_key="last"))
        self.assertTrue(toonzone_part_eligible("2026-10-22-12-toonzone-part1", ordered,
                                                used_key="used", last_slot_key="last"))

    def test_manual_part_four_blocks_new_part_one_that_day(self):
        ordered = [((1, 1, 4), "E1Part4", {"appProperties": {
            "used": "1", "last": "manual-2026-10-21-1300-toonzone-toonzone-part4",
        }}, None), ((1, 2, 1), "E2Part1", {"appProperties": {}}, None)]
        self.assertFalse(toonzone_part_eligible("2026-10-21-12-toonzone-part1", ordered,
                                                 used_key="used", last_slot_key="last"))

    def test_stale_claim_never_skips_required_part_one(self):
        ordered = [((1, 1, 1), "E1Part1", {"appProperties": {"claim": "stale"}}, None)]
        self.assertTrue(toonzone_part_eligible("2026-10-21-12-toonzone-part1", ordered,
                                                used_key="used", last_slot_key="last"))

    def test_utc_input_maps_to_istanbul_no_dst_confusion(self):
        utc = ZoneInfo("UTC")
        now = datetime(2026, 10, 21, 9, 20, tzinfo=utc)
        rows = self.slots(now, lookback=21)
        self.assertEqual([p for _, _, p in rows], [
            "2026-10-21-12-toonzone-part1",
            "2026-10-21-12-toonzone-part2",
            "2026-10-21-12-toonzone-part3",
        ])


if __name__ == "__main__":
    unittest.main()
