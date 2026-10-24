"""Recoverability is based on known history and API stages, not wishful retries."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from publisher_recovery import classify_meta_failure, read_with_retry, known_pre_publish_media_rejection


class RecoveryPolicyTests(unittest.TestCase):
    def test_read_429_then_200_with_bounded_backoff(self):
        get = Mock(side_effect=[SimpleNamespace(status_code=429), SimpleNamespace(status_code=200)])
        wait = Mock()
        result = read_with_retry(get, "url", sleep=wait, timeout=5)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(get.call_count, 2)
        wait.assert_called_once_with(1)

    def test_read_500_twice_then_200(self):
        get = Mock(side_effect=[SimpleNamespace(status_code=500), SimpleNamespace(status_code=503),
                                SimpleNamespace(status_code=200)])
        wait = Mock()
        self.assertEqual(read_with_retry(get, "url", sleep=wait).status_code, 200)
        self.assertEqual(wait.call_count, 2)

    def test_read_http_400_is_not_retried(self):
        get = Mock(return_value=SimpleNamespace(status_code=400))
        wait = Mock()
        self.assertEqual(read_with_retry(get, "url", sleep=wait).status_code, 400)
        get.assert_called_once()
        wait.assert_not_called()

    def test_read_http_403_is_not_retried(self):
        get = Mock(return_value=SimpleNamespace(status_code=403))
        self.assertEqual(read_with_retry(get).status_code, 403)
        get.assert_called_once()

    def test_read_transient_connection_error_then_succeeds(self):
        get = Mock(side_effect=[OSError("lost socket"), SimpleNamespace(status_code=200)])
        wait = Mock()
        self.assertEqual(read_with_retry(get, "url", sleep=wait).status_code, 200)
        self.assertEqual(get.call_count, 2)

    def test_read_programming_error_is_never_retried(self):
        get = Mock(side_effect=AssertionError("bad code"))
        with self.assertRaises(AssertionError):
            read_with_retry(get, "url", sleep=Mock())
        get.assert_called_once()

    def test_no_meta_api_error_is_ever_authorized_for_blind_repost(self):
        cases = [(400, 100, "invalid_media_or_graph_request"),
                 (400, 2207009, "invalid_media_or_graph_request"),
                 (401, 190, "credentials_or_permissions"),
                 (403, 200, "credentials_or_permissions"),
                 (429, 4, "rate_limit"),
                 (500, None, "meta_server_or_network")]
        for http, code, expected in cases:
            with self.subTest(http=http, code=code):
                error = SimpleNamespace(http_status=http, code=code,
                                        subcode=2207009, stage="Instagram media_publish")
                result = classify_meta_failure(error)
                self.assertEqual(result["reason"], expected)
                self.assertFalse(result["safe_to_repost"])
                self.assertEqual(result["post_write_action"], "reconcile_with_remote_history_before_any_retry")

    def test_only_known_pre_publish_ig400_gets_one_alternate_encoding(self):
        error = SimpleNamespace(stage="Instagram ikili video aktarımı",
                                http_status=400, code=100)
        self.assertTrue(known_pre_publish_media_rejection(error, "daily_laugh", 0))
        self.assertTrue(known_pre_publish_media_rejection(error, "penguen", 0))
        self.assertFalse(known_pre_publish_media_rejection(error, "daily_laugh", 1))
        self.assertFalse(known_pre_publish_media_rejection(error, "film", 0))
        self.assertFalse(known_pre_publish_media_rejection(error, "toonzone", 0))

    def test_ig_media_publish_or_unknown_transport_is_never_auto_retried(self):
        for stage in ("Instagram media_publish", "Instagram gönderi permalink doğrulama", "unknown"):
            error = SimpleNamespace(stage=stage, http_status=400, code=100)
            self.assertFalse(known_pre_publish_media_rejection(error, "penguen", 0))
        self.assertFalse(known_pre_publish_media_rejection(
            SimpleNamespace(stage="Instagram ikili video aktarımı", http_status=403, code=190),
            "penguen", 0))

    def test_unknown_transport_failure_remains_uncertain(self):
        result = classify_meta_failure(TimeoutError())
        self.assertEqual(result["reason"], "unclassified_upload_result")
        self.assertFalse(result["safe_to_repost"])


if __name__ == "__main__":
    unittest.main()
