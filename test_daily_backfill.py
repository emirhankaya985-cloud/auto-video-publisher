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


    def test_failed_post_attempt_never_gets_blindly_retried(self):
        import os
        import daily_backfill as backfill
        from unittest.mock import patch, Mock
        route = "tarladaki"
        page = {"page_id": "123", "page_token": "opaque", "instagram_id": "456"}
        with patch.dict(os.environ, {"BACKFILL_ROUTE": route, "BACKFILL_AUDIT_ONLY": "false",
                                     "TARGET_PER_DAY": "3"}, clear=False), \
             patch.object(backfill, "TARGET_PER_DAY", 3), \
             patch.object(backfill, "meta_page", return_value=page), \
             patch.object(backfill, "facebook_posts_today", return_value=0), \
             patch.object(backfill, "instagram_posts_today", return_value=0), \
             patch.object(backfill, "route_paused", return_value=False), \
             patch.object(backfill, "run", side_effect=TimeoutError("ambiguous POST")) as publisher, \
             patch.object(backfill.time, "sleep") as sleep, \
             self.assertRaisesRegex(RuntimeError, "Tamamlanamayan"):
            backfill.main()
        publisher.assert_called_once()
        sleep.assert_not_called()

    def test_audit_only_cannot_post(self):
        import os
        import daily_backfill as backfill
        with patch.dict(os.environ, {"BACKFILL_ROUTE": "tarladaki", "BACKFILL_AUDIT_ONLY": "true"}), \
             patch.object(backfill, "meta_page", return_value={}), \
             patch.object(backfill, "facebook_posts_today", return_value=0), \
             patch.object(backfill, "instagram_posts_today", return_value=0), \
             patch.object(backfill, "run") as publisher:
            backfill.main()
        publisher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
