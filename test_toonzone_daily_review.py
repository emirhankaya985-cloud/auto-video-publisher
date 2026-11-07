"""Dry-run-only tests. No real provider requests."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import toonzone_daily_review as review


class ToonZoneReviewTests(unittest.TestCase):
    def test_seven_slots_start_next_day(self):
        self.assertIsNone(review.choose_slot(datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)))
        for i, name in enumerate(review.SLOT_NAMES):
            minute = 12 * 60 + 15 * i
            moment = datetime(2026, 11, 9, minute // 60, minute % 60, tzinfo=timezone.utc)
            self.assertEqual(review.choose_slot(moment)[1], name)
        self.assertIsNone(review.choose_slot(datetime(2026, 11, 9, 13, 45, tzinfo=timezone.utc)))

    def test_only_todays_verified_video_links(self):
        now = datetime(2026, 11, 9, 12, 40, tzinfo=timezone.utc)
        pages = lambda token: {"pages": [{"page_name": "ToonZone",
            "page_id": "1298191963387372", "instagram_id": "12345678901234",
            "page_token": "fake-page-token"}]}
        def fake_get(method, path, token, data):
            self.assertEqual(method, "GET")
            return {"data": [
                {"id": "123456789012345", "media_type": "VIDEO",
                 "timestamp": "2026-11-09T12:30:00Z",
                 "permalink": "https://www.instagram.com/reel/ABCdef_123/"},
                {"id": "123456789012346", "media_type": "IMAGE",
                 "timestamp": "2026-11-09T12:30:00Z",
                 "permalink": "https://www.instagram.com/p/ABCdef_456/"},
                {"id": "123456789012347", "media_type": "VIDEO",
                 "timestamp": "2026-11-08T12:30:00Z",
                 "permalink": "https://www.instagram.com/reel/ABCdef_789/"},
                {"id": "123456789012348", "media_type": "VIDEO",
                 "timestamp": "2026-11-09T12:35:00Z",
                 "permalink": "https://evil.example/reel/ABCdef_123/"}
            ]}
        with patch.dict(os.environ, {"META_ACCESS_TOKEN": "fake"}):
            self.assertEqual(review.collect_today(now, loader=pages, get=fake_get),
                ["https://www.instagram.com/reel/ABCdef_123/"])

    def test_manual_runs_never_send(self):
        now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}), \
             patch.object(review, "collect_today", return_value=["https://www.instagram.com/reel/ABCdef_123/"]), \
             patch.object(review, "send_telegram") as send:
            self.assertEqual(review.main(now), 0)
            send.assert_not_called()

    def test_message_explicitly_read_only(self):
        body = review.build_message("ToonZone", datetime(2026, 11, 9).date(), [])
        self.assertIn("Otomatik beğeni/kaydetme yapılmadı.", body)


if __name__ == "__main__":
    unittest.main()
