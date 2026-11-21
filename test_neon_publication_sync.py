import unittest

from neon_publication_sync import SOURCE_KEYS, map_account_rows, receipt_rows


class PublicationReceiptTests(unittest.TestCase):
    def test_only_current_run_timestamped_done_posts_are_returned(self):
        state = {"entries": {
            "ok": {"route": "tarladaki", "platform": "facebook", "status": "done",
                   "post_id": "12345", "publication_run_id": "42",
                   "published_at_utc": "2026-11-21T12:00:00Z", "file": "clip.mp4",
                   "publish_caption": "must never be persisted"},
            "old": {"route": "tarladaki", "platform": "instagram", "status": "done",
                    "post_id": "67890", "publication_run_id": "41",
                    "published_at_utc": "2026-11-20T12:00:00Z"},
            "held": {"route": "tarladaki", "platform": "instagram", "status": "held",
                     "publication_run_id": "42", "post_id": None},
        }}
        rows = receipt_rows(state, route="tarladaki", source_run_id="42",
                            source_run_url="https://github.com/example/run/42")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_key"], SOURCE_KEYS[("tarladaki", "facebook")])
        self.assertEqual(rows[0]["platform_post_id"], "12345")
        self.assertEqual(rows[0]["occurred_at"].isoformat(), "2026-11-21T12:00:00+00:00")
        self.assertNotIn("publish_caption", rows[0]["details"])

    def test_missing_publication_time_fails_closed(self):
        state = {"entries": {"bad": {
            "route": "film_second", "platform": "facebook", "status": "done",
            "post_id": "123", "publication_run_id": "42",
        }}}
        with self.assertRaisesRegex(ValueError, "timestamp_missing"):
            receipt_rows(state, route="film_second", source_run_id="42", source_run_url="")

    def test_film_facebook_routes_are_distinct(self):
        self.assertNotEqual(SOURCE_KEYS[("film", "facebook")],
                            SOURCE_KEYS[("film_second", "facebook")])
        self.assertNotIn(("film_second", "instagram"), SOURCE_KEYS)

    def test_missing_account_mapping_skips_only_that_account(self):
        rows = [
            {"source_key": SOURCE_KEYS[("gonle", "instagram")], "platform_post_id": "11"},
            {"source_key": SOURCE_KEYS[("penguen", "facebook")], "platform_post_id": "22"},
        ]
        mapped, skipped = map_account_rows(rows, [(7, rows[0]["source_key"])])
        self.assertEqual([(account_id, row["platform_post_id"]) for account_id, row in mapped],
                         [(7, "11")])
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
