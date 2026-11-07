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
             patch.object(review, "collect_platforms", return_value=({"instagram": ["https://www.instagram.com/reel/ABCdef_123/"]}, {})), \
             patch.object(review, "send_telegram") as send:
            self.assertEqual(review.main(now), 0)
            send.assert_not_called()


    def test_connected_platforms_and_no_cross_platform_substitution(self):
        pages = [
            {"page_name": "ToonZone", "page_id": "1298191963387372",
             "instagram_id": "178900000000001", "page_token": "fake"},
            {"page_name": "Beyinsiz Penguen", "page_id": "2345678901234",
             "instagram_id": None, "page_token": "fake"},
        ]
        with patch.object(review, "threads_account_config", side_effect=RuntimeError("disabled")):
            self.assertEqual(review.actor_platforms("Beyinsiz Penguen", pages), {"facebook"})
            self.assertEqual(review.actor_platforms("ToonZone", pages), {"facebook", "instagram"})

    def test_toonzone_facebook_video_date_and_owner(self):
        now = datetime(2026, 11, 9, 12, 45, tzinfo=timezone.utc)
        def fake_graph(method, node, token, params):
            self.assertEqual((method, node), ("GET", "1298191963387372/videos"))
            return {"data": [
                {"id": "100000000001", "created_time": "2026-11-09T12:35:00Z",
                 "from": {"id": "1298191963387372"}},
                {"id": "100000000002", "created_time": "2026-11-09T12:32:00Z",
                 "from": {"id": "900000000000000"}},
                {"id": "100000000003", "created_time": "2026-11-08T12:32:00Z",
                 "from": {"id": "1298191963387372"}},
            ]}
        found = review.video_feed_today(now, page={
            "page_id": "1298191963387372", "page_token": "fake"}, get=fake_graph)
        self.assertEqual(found, ["https://www.facebook.com/watch/?v=100000000001"])

    def test_collect_multiplatform_independent_failures(self):
        now = datetime(2026, 11, 9, 12, 45, tzinfo=timezone.utc)
        pages = {"pages": [
            {"page_name": "ToonZone", "page_id": "1298191963387372",
             "instagram_id": "178900000000001", "page_token": "fake"},
        ]}
        with patch.object(review, "actor_platforms", return_value={"instagram", "facebook", "threads"}):
            results, failures = review.collect_platforms(
                now, "ToonZone", loader=lambda token: pages,
                ig=lambda x: ["https://www.instagram.com/reel/abcDEF123/"],
                fb=lambda x, page: (_ for _ in ()).throw(ValueError("bad feed")),
                threads=lambda route, cutoff: ("12345", [
                    ("111", datetime(2026, 11, 9, 12, 20, tzinfo=timezone.utc),
                     "https://www.threads.net/@toonzone.tr/post/abc123")]))
        self.assertEqual(list(results), ["instagram", "threads"])
        self.assertEqual(failures, {"facebook": "Facebook read failed"})
        self.assertIn("Facebook: doğrulama yapılamadı",
                      review.build_platform_message("ToonZone", now.date(), results, failures))

    def test_platform_message_explicitly_read_only(self):
        body = review.build_platform_message("ToonZone",
            datetime(2026, 11, 9).date(), {"facebook": []}, {})
        self.assertIn("Otomatik beğeni/kaydetme yapılmadı.", body)

    def test_message_explicitly_read_only(self):
        body = review.build_message("ToonZone", datetime(2026, 11, 9).date(), [])
        self.assertIn("Otomatik beğeni/kaydetme yapılmadı.", body)


if __name__ == "__main__":
    unittest.main()
