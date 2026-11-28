import json
import unittest
from unittest.mock import Mock

from buffer_connection_audit import (
    ACCOUNT_QUERY,
    API_URL,
    BufferConnectionError,
    audit,
    validate_channel_mapping,
    X_ACCOUNT_KEYS,
)


class BufferConnectionAuditTests(unittest.TestCase):
    @staticmethod
    def _channels(count=6):
        return [
            {"channel_id": f"mock-channel-{index}", "name": f"Mock X {index}",
             "connected": True, "queue_paused": False}
            for index in range(count)
        ]

    def test_complete_mapping_resolves_six_connected_x_channels_offline(self):
        channels = self._channels()
        mapping = {key: channels[index]["channel_id"] for index, key in enumerate(X_ACCOUNT_KEYS)}
        result = validate_channel_mapping(json.dumps(mapping), channels)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["accounts"]), 6)

    def test_partial_mapping_reports_missing_accounts_without_inventing_ids(self):
        result = validate_channel_mapping('{"tarladaki":"mock-known-id"}', self._channels(0))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["accounts"]["tarladaki"]["status"], "channel_not_found")
        self.assertEqual(result["missing_accounts"], list(X_ACCOUNT_KEYS[1:]))

    def test_missing_mapping_is_not_reported_as_zero_or_connected(self):
        result = validate_channel_mapping("", self._channels())
        self.assertEqual(result["status"], "not_configured")
        self.assertEqual(result["missing_accounts"], list(X_ACCOUNT_KEYS))

    def test_bad_json_and_unknown_accounts_fail_closed(self):
        self.assertEqual(validate_channel_mapping("not-json", [])["reason"], "invalid_json")
        result = validate_channel_mapping('{"other":"mock-id"}', [])
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["reason"], "unknown_account_key")

    def test_duplicate_ids_and_disconnected_channels_fail_closed(self):
        channels = self._channels()
        duplicate = {key: "same-id" for key in X_ACCOUNT_KEYS}
        self.assertEqual(validate_channel_mapping(json.dumps(duplicate), channels)["reason"],
                         "duplicate_configured_channel_id")
        mapping = {key: channels[index]["channel_id"] for index, key in enumerate(X_ACCOUNT_KEYS)}
        channels[0]["connected"] = False
        result = validate_channel_mapping(json.dumps(mapping), channels)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["accounts"]["tarladaki"]["status"], "disconnected")

    def test_lists_only_x_channels_without_writing_posts(self):
        key = "buffer-secret-test-value"
        responses = [
            Mock(status_code=200, ok=True, json=lambda: {
                "data": {"account": {"organizations": [{"id": "org-1"}]}}
            }),
            Mock(status_code=200, ok=True, json=lambda: {
                "data": {"channels": [
                    {"id": "channel-x", "name": "TarladaFasulye", "displayName": None,
                     "service": "twitter", "isDisconnected": False, "isQueuePaused": False},
                    {"id": "channel-ig", "name": "not-in-scope", "service": "instagram",
                     "isDisconnected": False, "isQueuePaused": False},
                ]}
            }),
        ]
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return responses.pop(0)

        result = audit(key, post=post)

        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["x_channel_count"], 1)
        self.assertEqual(result["x_channels"][0]["name"], "TarladaFasulye")
        self.assertFalse(result["posting_performed"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[0] == API_URL for call in calls))
        self.assertNotIn(key, str(result))
        self.assertIn("account", calls[0][1]["json"]["query"])
        self.assertNotIn("mutation", str([c[1]["json"] for c in calls]).casefold())
        self.assertTrue(all(c[1]["headers"]["Authorization"] == f"Bearer {key}" for c in calls))

    def test_missing_key_fails_before_network(self):
        post = Mock()
        with self.assertRaisesRegex(BufferConnectionError, "api_key_missing"):
            audit("", post=post)
        post.assert_not_called()

    def test_401_error_does_not_expose_key_or_response(self):
        key = "private-buffer-key"
        response = Mock(status_code=401, ok=False, json=Mock(side_effect=AssertionError))
        with self.assertRaises(BufferConnectionError) as caught:
            audit(key, post=Mock(return_value=response))
        self.assertEqual(str(caught.exception), "unauthorized")
        self.assertNotIn(key, str(caught.exception))

    def test_graphql_error_only_reports_safe_code(self):
        response = Mock(status_code=200, ok=True, json=lambda: {
            "errors": [{"message": "private provider detail", "extensions": {"code": "FORBIDDEN"}}]
        })
        with self.assertRaises(BufferConnectionError) as caught:
            audit("key", post=Mock(return_value=response))
        self.assertEqual(str(caught.exception), "graphql_error:FORBIDDEN")
        self.assertNotIn("private provider detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
