"""Offline provider receipt acceptance tests."""
import unittest

from verified_post_receipts import require_youtube_video_id


class YoutubeReceiptTests(unittest.TestCase):
    def test_valid_video_id(self):
        self.assertEqual(require_youtube_video_id({"id": "AaBbCcDdEe1"}), "AaBbCcDdEe1")

    def test_missing_or_container_ack_is_not_success(self):
        for payload in (None, {}, {"id": None}, {"id": ""}, {"id": "too-short"},
                        {"id": "aaaaaaaaaaa/"}, {"id": 12345678901},
                        {"uploadStatus": "uploaded"}, {"id": "a" * 12}):
            with self.subTest(payload=payload), self.assertRaisesRegex(RuntimeError, "unverified"):
                require_youtube_video_id(payload)


if __name__ == "__main__":
    unittest.main()
