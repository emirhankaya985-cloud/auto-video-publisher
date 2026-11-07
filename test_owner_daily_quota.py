"""No-provider-write safety and actual ledger-day contract for all seven accounts."""
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from owner_daily_quota import quota_evidence


class QuotaReadOnlyTests(unittest.TestCase):
    NOW = datetime(2026, 11, 7, 23, 42, tzinfo=ZoneInfo("Europe/Istanbul"))

    def test_four_platforms_not_silently_counted_from_meta_ledger(self):
        state = {"schema": 1, "entries": {
            "tarladaki:instagram:1abcdefghijklmno": {
                "route": "tarladaki", "platform": "instagram",
                "day": "2026-11-07", "status": "done", "post_id": "18131994541885064"},
            "tarladaki:instagram:2abcdefghijklmno": {
                "route": "tarladaki", "platform": "instagram",
                "day": "2026-11-07", "status": "uncertain", "post_id": None},
            "gonle:facebook:3abcdefghijklmno": {
                "route": "gonle", "platform": "facebook",
                "day": "2026-11-07", "status": "done", "post_id": "1234567890"},
        }}
        before = json.dumps(state, sort_keys=True)
        report = quota_evidence(state, now=self.NOW)
        self.assertEqual(report["accounts_expected"], 7)
        self.assertEqual(len(report["accounts"]), 7)
        self.assertEqual(report["new_provider_posts"], 0)
        self.assertEqual(report["provider_writes"], 0)
        first = report["accounts"][0]
        instagram = next(r for r in first["platforms"] if r["platform"] == "instagram")
        self.assertEqual(instagram["ledger_post_ids_count"], 1)
        self.assertEqual(instagram["unresolved_sources"], 1)
        self.assertEqual(instagram["not_recorded_against_target"], 4)
        self.assertEqual(instagram["live_provider_history_confirmation"], "N/A")
        self.assertFalse(instagram["safe_to_auto_repost"])
        self.assertEqual(first["threads_daily_posts"], "N/A")
        self.assertEqual(first["youtube_daily_posts"], "N/A")
        odd = report["accounts"][6]
        self.assertEqual(odd["status"], "not_configured")
        self.assertEqual(odd["platforms"], [])
        self.assertEqual(json.dumps(state, sort_keys=True), before)

    def test_daily_laugh_previous_new_york_day_not_today_tr(self):
        state = {"schema": 1, "entries": {
            "daily_laugh:facebook:1abcdefghijklmno": {
                "route": "daily_laugh", "platform": "facebook", "day": "2026-11-06",
                "status": "done", "post_id": "1234567899"},
            "daily_laugh:facebook:2abcdefghijklmno": {
                "route": "daily_laugh", "platform": "facebook", "day": "2026-11-07",
                "status": "done", "post_id": "1234567891"}}}
        result = quota_evidence(state, now=self.NOW)
        daily = next(row for row in result["accounts"] if row["account"] == "Daily Laugh Lab")
        self.assertEqual(daily["day"], "2026-11-06")
        self.assertEqual(daily["platforms"][0]["ledger_post_ids_count"], 1)

    def test_bad_or_unverified_done_id_cannot_increment_success(self):
        state = {"schema": 1, "entries": {
            "tarladaki:facebook:1234567890abcdef": {
                "route": "tarladaki", "platform": "facebook", "day": "2026-11-07",
                "status": "done", "post_id": "invalid-private-text"}}}
        fb = quota_evidence(state, now=self.NOW)["accounts"][0]["platforms"][0]
        self.assertEqual(fb["ledger_post_ids_count"], 0)
        self.assertEqual(fb["invalid_done_rows"], 1)

    def test_invalid_or_missing_ledger_must_not_become_zero(self):
        with self.assertRaises(ValueError):
            quota_evidence({}, now=self.NOW)
        with self.assertRaises(ValueError):
            quota_evidence({"schema": 1, "entries": {"bad": None}}, now=self.NOW)


if __name__ == "__main__":
    unittest.main()
