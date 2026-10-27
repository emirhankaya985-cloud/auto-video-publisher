"""Recoverability is based on known history and API stages, not wishful retries."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from publisher_recovery import classify_meta_failure, read_with_retry, known_pre_publish_media_rejection


class RecoveryPolicyTests(unittest.TestCase):
    def test_graph_400_throttle_retries_only_when_explicitly_opted_in(self):
        for code in (4, 17, 32, 613):
            for enabled in (False, True):
                with self.subTest(code=code, graph_read=enabled):
                    limited = Mock(status_code=400)
                    limited.json.return_value = {"error": {"code": code}}
                    ok = Mock(status_code=200)
                    get = Mock(side_effect=[limited, ok])
                    result = read_with_retry(get, "url", sleep=Mock(), graph_read=enabled)
                    self.assertIs(result, ok if enabled else limited)
                    self.assertEqual(get.call_count, 2 if enabled else 1)
                    self.assertNotIn("graph_read", get.call_args.kwargs)
                    self.assertEqual(limited.close.call_count, int(enabled))
                    ok.close.assert_not_called()

    def test_graph_throttle_exhaustion_returns_last_response_without_extra_sleep(self):
        responses = [Mock(status_code=400) for _ in range(3)]
        for response in responses:
            response.json.return_value = {"error": {"code": 4}}
        get, wait = Mock(side_effect=responses), Mock()
        self.assertIs(read_with_retry(get, sleep=wait, graph_read=True), responses[-1])
        self.assertEqual(get.call_count, 3)
        self.assertEqual([c.args for c in wait.call_args_list], [(1,), (2,)])
        responses[-1].close.assert_not_called()

    def test_graph_permanent_or_malformed_errors_are_not_retried(self):
        for payload in (None, [], "secret-body", {"error": "secret-error"},
                        {"error": {"code": 100}}, {"error": {"code": 190}},
                        {"error": {"code": "4"}}, {"error": {"code": True}}):
            with self.subTest(payload=payload):
                response = Mock(status_code=400)
                response.json.return_value = payload
                get, wait = Mock(return_value=response), Mock()
                self.assertIs(read_with_retry(get, sleep=wait, graph_read=True), response)
                get.assert_called_once()
                wait.assert_not_called()
        response = Mock(status_code=400)
        response.json.side_effect = ValueError("not JSON")
        get = Mock(return_value=response)
        self.assertIs(read_with_retry(get, graph_read=True), response)
        get.assert_called_once()

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

    def test_proven_pre_publish_ig400_gets_bounded_distinct_profiles(self):
        error = SimpleNamespace(stage="Instagram ikili video aktarımı",
                                http_status=400, code=100)
        for route in ("tarladaki", "penguen", "daily_laugh", "gonle"):
            with self.subTest(route=route):
                self.assertTrue(known_pre_publish_media_rejection(error, route, 0))
                self.assertTrue(known_pre_publish_media_rejection(error, route, 1))
                self.assertFalse(known_pre_publish_media_rejection(error, route, 2))
        for route in ("film", "toonzone"):
            self.assertTrue(known_pre_publish_media_rejection(error, route, 0))
            self.assertFalse(known_pre_publish_media_rejection(error, route, 1))
        for counter in (-1, True, "0", None):
            self.assertFalse(known_pre_publish_media_rejection(error, "penguen", counter))

    def test_explicit_pre_publish_transient_meta_subcodes_are_eligible(self):
        transient = SimpleNamespace(stage="Instagram ikili video aktarımı",
                                    http_status=400, code=-1, subcode=2207053)
        self.assertTrue(known_pre_publish_media_rejection(transient, "gonle", 0))
        transient.subcode = 2207051  # platform restriction, not repairable media
        self.assertFalse(known_pre_publish_media_rejection(transient, "gonle", 0))

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
