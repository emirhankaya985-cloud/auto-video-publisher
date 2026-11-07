"""Offline tests for the Threads and YouTube Telegram notice schedule."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import platform_publication_notifications as notices
from threads_accounts import ThreadsAccount

NOW = datetime(2026, 11, 4, 9, tzinfo=timezone.utc)
THREADS = "https://www.threads.com/@test/post/example"
YOUTUBE = "https://www.youtube.com/watch?v=12345678901"


def blank():
    return {"schema": 1, "records": {}}


class PlatformNotificationTests(unittest.TestCase):
    def test_baseline_does_not_replay_history_and_later_notices_are_reserved_once(self):
        history = blank()
        sources = {("threads", "film"): ("123", [("456", NOW - timedelta(hours=1), THREADS)])}
        self.assertEqual(notices.reserve_notices(history, sources, "100", NOW), ([], 1))
        sources["threads", "film"][1].append(("789", NOW, THREADS))
        messages, seeded = notices.reserve_notices(history, sources, "101", NOW + timedelta(minutes=1))
        self.assertEqual(seeded, 0)
        self.assertEqual(len(messages), 1)
        self.assertIn("Film Mağarası · 1 yeni gönderi", messages[0]["body"])
        self.assertEqual(notices.reserve_notices(history, sources, "102", NOW + timedelta(hours=1)), ([], 0))

    def test_account_change_is_rebaselined_instead_of_replaying_other_account(self):
        history = blank()
        source = ("threads", "film")
        notices.reserve_notices(history, {source: ("123", [])}, "100", NOW)
        self.assertEqual(notices.reserve_notices(
            history, {source: ("456", [("789", NOW, THREADS)])}, "101", NOW), ([], 1))

    def test_old_and_future_posts_cannot_enter_notification_plan(self):
        history = blank()
        source = ("youtube", "gonle")
        notices.reserve_notices(history, {source: ("channel", [])}, "100", NOW)
        posts = [("old", NOW - timedelta(days=3), YOUTUBE),
                 ("future", NOW + timedelta(hours=1), YOUTUBE)]
        self.assertEqual(notices.reserve_notices(history, {source: ("channel", posts)}, "101", NOW), ([], 0))

    def test_partial_threads_failure_preserves_verified_youtube_and_other_routes(self):
        response = Mock(status_code=401)
        bad_route = RuntimeError("private")
        bad_route.response = response

        def threads(route, _cutoff):
            if route == "penguen":
                raise bad_route
            return "123", []

        with patch.object(notices, "load_archived_state", return_value={"youtube_entries": {}}), \
             patch.object(notices, "youtube_posts", return_value=("channel", [])), \
             patch.object(notices, "threads_posts", side_effect=threads):
            sources, failures = notices.collect(NOW - timedelta(days=2))
        self.assertIn(("youtube", "gonle"), sources)
        self.assertIn(("threads", "film"), sources)
        self.assertEqual(failures, {"threads:penguen": "read_failed_http_401"})

    def test_provider_error_codes_are_sanitized_without_retry_or_secrets(self):
        response = Mock(status_code=401)
        response.json.return_value = {"error": {"code": 190,
                                  "message": "access_token=PRIVATE_SECRET"}}
        exc = RuntimeError("private")
        exc.response = response
        self.assertEqual(notices.safe_read_error(exc), "read_failed_http_401_code_190")
        response.status_code = 400
        response.json.return_value = {"error": {"code": 100, "message": "signed url private"}}
        self.assertEqual(notices.safe_read_error(exc), "read_failed_http_400_code_100")
        response.json.return_value = {"error": {"code": 999, "message": "private"}}
        self.assertEqual(notices.safe_read_error(exc), "read_failed_http_400")
        response.json.side_effect = ValueError("private JSON")
        self.assertEqual(notices.safe_read_error(exc), "read_failed_http_400")

    def test_threads_uses_verified_account_and_refuses_injected_permalink(self):
        response = Mock()
        response.json.return_value = {"data": [
            {"id": "456", "timestamp": NOW.isoformat(), "permalink": THREADS + "?tracking=123"},
            {"id": "789", "timestamp": NOW.isoformat(), "permalink": "https://www.threads.com@evil.test/@test/post/code"},
        ]}
        account = ThreadsAccount("film", "test-token", "test", "123", "")
        with patch.object(notices, "threads_account_config", return_value=account), \
             patch.object(notices, "validate_threads_identity", return_value={"id": "123", "username": "test"}), \
             patch.object(notices, "read_with_retry", return_value=response) as get:
            user_id, posts = notices.threads_posts("film", NOW - timedelta(days=2))
        self.assertEqual(user_id, "123")
        self.assertEqual(posts, [("456", NOW, THREADS), ("789", NOW, "")])
        self.assertEqual(get.call_args.args[1], "https://graph.threads.com/v1.0/me/threads")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_youtube_upload_must_be_public_processed_and_bound_to_channel(self):
        route = "gonle"
        _, secret, channel = notices.YOUTUBE_ROUTES[route]
        post = "12345678901"
        ledger = {"entry": {"route": route, "run_id": "100", "post_id": post,
                            "status": "accepted", "channel_id": channel}}
        row = {"id": post, "snippet": {"channelId": channel, "publishedAt": NOW.isoformat()},
               "status": {"privacyStatus": "public", "uploadStatus": "uploaded"}}
        response = Mock()
        response.json.return_value = {"items": [row]}
        with patch.object(notices, "check_channel", return_value={"status": "verified", "channel_id": channel}), \
             patch.object(notices.Credentials, "from_authorized_user_info"), \
             patch.object(notices, "AuthorizedSession"), \
             patch.object(notices, "read_with_retry", return_value=response), \
             patch.dict(os.environ, {secret: "{}"}):
            self.assertEqual(notices.youtube_posts(route, ledger, NOW - timedelta(days=2)), (channel, []))
            row["status"]["uploadStatus"] = "processed"
            self.assertEqual(notices.youtube_posts(route, ledger, NOW - timedelta(days=2)),
                             (channel, [(post, NOW, YOUTUBE)]))
            row["snippet"]["channelId"] = "different"
            with self.assertRaises(ValueError):
                notices.youtube_posts(route, ledger, NOW - timedelta(days=2))

    def test_no_delivery_before_archive_and_no_duplicate_after_ambiguous_delivery(self):
        history = blank()
        account = ("threads", "film")
        notices.reserve_notices(history, {account: ("123", [])}, "100", NOW)
        messages, _ = notices.reserve_notices(history, {account: ("123", [("456", NOW, THREADS)])}, "101", NOW)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(notices, "HISTORY", Path(tmp) / "history.json"), \
             patch.object(notices, "PLAN", Path(tmp) / "plan.json"), \
             patch.object(notices, "send_telegram", side_effect=TimeoutError) as send:
            notices.history_io.save(notices.HISTORY, history)
            notices.history_io.save(notices.PLAN, {"messages": messages, "run_id": "101", "failures": {}})
            with patch.dict(os.environ, {"PLATFORM_NOTICE_INTENT_ARCHIVED": "false"}), self.assertRaises(ValueError):
                notices.send("101")
            send.assert_not_called()
            with patch.dict(os.environ, {"PLATFORM_NOTICE_INTENT_ARCHIVED": "true"}):
                self.assertEqual(notices.send("101"), 1)
                notices.send("101")
            send.assert_called_once()
            recovered = notices.history_io.read(notices.HISTORY)
            self.assertEqual(notices.reserve_notices(recovered, {account: ("123", [("456", NOW, THREADS)])},
                                                     "102", NOW + timedelta(minutes=30)), ([], 0))


if __name__ == "__main__":
    unittest.main()
