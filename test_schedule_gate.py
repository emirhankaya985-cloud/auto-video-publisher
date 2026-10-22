from datetime import datetime, timezone
import unittest

from cloud_omnichannel_publisher import current_publish_slot, slot_already_processed


class ScheduleGateTests(unittest.TestCase):
    def test_scheduled_hour_is_allowed_throughout_the_hour(self):
        self.assertEqual(current_publish_slot(datetime(2026, 10, 11, 9, 9)), "2026-10-11-09")
        self.assertEqual(current_publish_slot(datetime(2026, 10, 11, 9, 50)), "2026-10-11-09")

    def test_other_minutes_and_hours_are_blocked(self):
        self.assertIsNone(current_publish_slot(datetime(2026, 10, 11, 10, 0)))

    def test_aware_time_is_converted_to_turkey_time(self):
        self.assertEqual(
            current_publish_slot(datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)),
            "2026-10-11-09",
        )

    def test_processed_slot_blocks_duplicate(self):
        files = [{"name": "17.mp4", "appProperties": {"scheduled_publish_slot": "2026-10-11-09"}}]
        self.assertTrue(slot_already_processed(files, "2026-10-11-09"))
        self.assertFalse(slot_already_processed(files, "2026-10-11-11"))


if __name__ == "__main__":
    unittest.main()
