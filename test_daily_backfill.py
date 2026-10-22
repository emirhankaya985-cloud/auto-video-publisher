from datetime import datetime
from unittest.mock import Mock, patch
import unittest

from daily_backfill import TZ, facebook_posts_today, instagram_posts_today


class DailyBackfillTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 12, 10, 0, tzinfo=TZ)

    @patch("daily_backfill.requests.get")
    def test_counts_facebook_posts_from_today(self, get):
        response = Mock()
        response.json.return_value = {"data": [
            {"created_time": "2026-10-12T06:00:00+0000"},
            {"created_time": "2026-10-11T06:00:00+0000"},
        ]}
        get.return_value = response
        self.assertEqual(
            facebook_posts_today({"page_id": "1", "page_token": "x"}, self.now),
            1,
        )

    @patch("daily_backfill.requests.get")
    def test_counts_only_instagram_video_and_reels(self, get):
        response = Mock()
        response.json.return_value = {"data": [
            {"media_type": "REELS", "timestamp": "2026-10-12T06:00:00+0000"},
            {"media_type": "IMAGE", "timestamp": "2026-10-12T06:00:00+0000"},
        ]}
        get.return_value = response
        page = {"instagram_id": "2", "page_token": "x"}
        self.assertEqual(instagram_posts_today(page, self.now), 1)


if __name__ == "__main__":
    unittest.main()
