import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import threads_live_publish as live


class ThreadsNativeVideoTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 4, 16, tzinfo=timezone.utc)
        self.account = SimpleNamespace(username="film_magrasi", token="test")
        self.history = {"schema": 1, "records": {}}

    def video(self, identifier, offset):
        timestamp = self.now - timedelta(minutes=offset)
        return {"id": identifier, "media_type": "VIDEO", "timestamp": timestamp.isoformat(),
                "caption": "🎞️" * 400,
                "media_url": "https://scontent.example.cdninstagram.com/v/clip.mp4",
                "permalink": f"https://www.instagram.com/reel/clip{identifier}/"}

    def test_first_run_uses_newest_owned_confirmed_video_and_stores_intent(self):
        rows = [self.video("101", 40), self.video("102", 30), self.video("103", 20)]
        state = {"entries": {
            f"film:instagram:drive{n}": {"route": "film", "platform": "instagram",
                                        "status": status, "post_id": n}
            for n, status in (("101", "done"), ("102", "done"), ("103", "intent"))}}
        candidates = live.sources("film", state, rows, self.now)
        with patch.object(live, "ready_media") as check:
            plan = live.choose("film", self.account, "1", candidates, self.history, [], "77", self.now)
        check.assert_called_once()
        intent = self.history["records"][plan["key"]]
        self.assertEqual(intent["instagram_id"], "102")
        self.assertEqual(intent["status"], "reserved")
        self.assertLessEqual(len(plan["text"].encode()), 500)
        self.assertNotIn("media_url", intent)

    def test_attempt_without_owned_receipt_stays_held(self):
        row = self.video("101", 15)
        candidates = [(live.archive.stamp(row["timestamp"]), "101", "drive", row)]
        with patch.object(live, "ready_media"):
            live.choose("film", self.account, "1", candidates, self.history, [], "77", self.now)
        with self.assertRaisesRegex(RuntimeError, "previous_threads_intent_unresolved"):
            live.choose("film", self.account, "1", candidates, self.history, [], "78", self.now)
        remote = {"id": "234", "text": live.caption_for(row), "media_type": "VIDEO",
                  "permalink": "https://www.threads.com/@film_magrasi/post/abc/"}
        self.assertIsNone(live.choose("film", self.account, "1", candidates, self.history, [remote], "79", self.now))
        self.assertEqual(next(iter(self.history["records"].values()))["post_id"], "234")

    def test_native_publish_verifies_returned_post_identity_and_exact_source(self):
        row = self.video("101", 5)
        plan = {"url": row["media_url"], "text": live.caption_for(row)}
        record = {"user_id": "12", "marker": "Instagram: " + row["permalink"]}
        remote = {"id": "44", "text": plan["text"], "media_type": "VIDEO",
                  "permalink": "https://www.threads.com/@film_magrasi/post/abc"}
        with patch.object(live, "profile", return_value="12"), patch.object(live.time, "sleep"), \
             patch.object(live, "graph", side_effect=[{"id": "33"}, {"status": "FINISHED"}, {"id": "44"}, remote]) as api:
            self.assertEqual(live.publish(plan, record, self.account)["post_id"], "44")
        self.assertEqual([c.args[1] for c in api.call_args_list], ["12/threads", "33", "12/threads_publish", "44"])

    def test_media_url_must_be_known_https_cdn(self):
        for value in ("https://cdninstagram.com.evil/a", "https://name@a.fbcdn.net/a", "http://a.fbcdn.net/a"):
            self.assertFalse(live.safe_media_url(value))
