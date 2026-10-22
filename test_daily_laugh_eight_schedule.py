"""Daily Laugh eight-video schedule: exact NY calendar-day and DST assertions."""
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from scheduled_multi_publisher import (
    DAILY_LAUGH_CUTOVER_DATE, DAILY_LAUGH_HOURS,
    DAILY_LAUGH_LEGACY_HOURS, daily_laugh_hours_for_date,
    due_slots, is_first_daily_slot, routes_for_time,
)
from stats_reporter import ACCOUNT_TARGETS, publication_progress

NY = ZoneInfo("America/New_York")
TRT = ZoneInfo("Europe/Istanbul")
NEW_HOURS = (8, 10, 12, 14, 16, 18, 20, 22)
OLD_HOURS = (9, 12, 15, 18, 21)


class DailyLaughEightSlotsTests(unittest.TestCase):
    def test_eight_evenly_spaced_slots_begin_next_full_ny_day(self):
        self.assertEqual(DAILY_LAUGH_CUTOVER_DATE, date(2026, 10, 20))
        self.assertEqual(DAILY_LAUGH_HOURS, NEW_HOURS)
        self.assertEqual(DAILY_LAUGH_LEGACY_HOURS, OLD_HOURS)
        self.assertEqual(daily_laugh_hours_for_date(date(2026, 10, 19)), OLD_HOURS)
        self.assertEqual(daily_laugh_hours_for_date(date(2026, 10, 20)), NEW_HOURS)

    def test_all_eight_slots_are_open_on_october_20_in_new_york(self):
        for hour in NEW_HOURS:
            ny = datetime(2026, 10, 20, hour, 0, tzinfo=NY)
            local = ny.astimezone(TRT)
            slot = f"2026-10-20-{hour:02d}-daily_laugh"
            with self.subTest(hour=hour):
                self.assertIn(("daily_laugh", slot), routes_for_time(local))
                self.assertIn(("daily_laugh", slot), routes_for_time(local + timedelta(minutes=29)))
                self.assertNotIn(("daily_laugh", slot), routes_for_time(local + timedelta(minutes=30)))

    def test_eight_slots_survive_us_dstu_transition(self):
        for day in ((2026, 10, 20), (2026, 11, 8), (2027, 3, 14)):
            for hour in NEW_HOURS:
                ny = datetime(*day, hour, tzinfo=NY)
                with self.subTest(day=day, hour=hour):
                    self.assertIn(
                        ("daily_laugh", f"{ny:%Y-%m-%d}-{hour:02d}-daily_laugh"),
                        routes_for_time(ny.astimezone(TRT)),
                    )

    def test_do_not_backfill_nonexistent_october_19_slots(self):
        before = datetime(2026, 10, 19, 23, 30, tzinfo=NY)
        historic = [slot for _, route, slot in due_slots(before.astimezone(TRT))
                    if route == "daily_laugh" and slot.startswith("2026-10-19-")]
        self.assertEqual(len(historic), 5)
        self.assertEqual(set(historic), {f"2026-10-19-{h:02d}-daily_laugh" for h in OLD_HOURS})

    def test_first_daily_notification_moves_to_08_from_cutover(self):
        self.assertTrue(is_first_daily_slot("daily_laugh", "2026-10-19-09-daily_laugh"))
        self.assertFalse(is_first_daily_slot("daily_laugh", "2026-10-20-09-daily_laugh"))
        self.assertTrue(is_first_daily_slot("daily_laugh", "2026-10-20-08-daily_laugh"))
        self.assertFalse(is_first_daily_slot("daily_laugh", "2026-10-20-10-daily_laugh"))

    def test_new_full_ny_day_has_exactly_eight_due_slots(self):
        now = datetime(2026, 10, 20, 23, 55, tzinfo=NY).astimezone(TRT)
        day_slots = [slot for _, route, slot in due_slots(now)
                     if route == "daily_laugh" and slot.startswith("2026-10-20-")]
        self.assertEqual(len(day_slots), 8)
        self.assertEqual(len(set(day_slots)), 8)

    def test_primary_and_backup_cron_cover_midnight_and_three_utc(self):
        root = Path(__file__).parent / ".github" / "workflows"
        main = (root / "omnichannel_schedule.yml").read_text(encoding="utf-8")
        backup = (root / "cloud_schedule_backup.yml").read_text(encoding="utf-8")
        self.assertIn("*/5 0,1,2,3,19,20,21,22,23 * * *", main)
        self.assertIn("35,45,55 0,1,2,3,19,20,21,22,23 * * *", backup)
        self.assertNotIn("*/5 * * * *", main)

    def test_daily_report_target_is_eight_without_historical_inflation(self):
        name = "😂 Daily Laugh Lab"
        self.assertEqual(ACCOUNT_TARGETS[name][0], 8)
        self.assertEqual(8 * len(ACCOUNT_TARGETS[name][3]), 24)
        # No Drive available => report progress unknown, never invent counts.
        self.assertIsNone(publication_progress(None, name, "2026-10-19"))
        self.assertIsNone(publication_progress(None, name, "2026-10-20"))


if __name__ == "__main__":
    unittest.main()
