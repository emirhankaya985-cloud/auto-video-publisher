"""Mock-only four-channel authenticated read acceptance; never calls Google."""
import json
import unittest
from unittest.mock import Mock

from youtube_account_inventory import probe_all
from youtube_readonly_connection import TARGETS


class YouTubeInventorySafetyTests(unittest.TestCase):
    def test_all_four_exact_channel_identifiers_required(self):
        called = []
        def check(target):
            called.append(target)
            return {"status": "verified", "channel_id": TARGETS[target][2],
                    "upload_scope_in_file": True}
        outcome = probe_all(checker=check)
        self.assertEqual(outcome["status"], "all_four_verified")
        self.assertEqual(called, list(TARGETS))
        self.assertEqual(outcome["accounts_checked"], 4)
        self.assertEqual(outcome["youtube_upload_requests"], 0)
        self.assertEqual(outcome["provider_writes"], 0)
        self.assertTrue(all(x["expected_channel_id_matched"] for x in outcome["accounts"]))

    def test_same_named_wrong_channel_must_not_be_green(self):
        def check(route):
            return {"status": "verified", "channel_id": "OTHER-ID", "channel_title": "Tarladaki Fasulye"}
        outcome = probe_all(checker=check)
        self.assertEqual(outcome["status"], "auth_or_identity_incomplete")
        self.assertTrue(all(x["status"] == "channel_identity_mismatch"
                            for x in outcome["accounts"]))
        self.assertNotIn("Tarladaki Fasulye", json.dumps(outcome))

    def test_sanitizes_provider_error_and_403_without_token_leaks(self):
        def check(route):
            if route == "channel1":
                return {"status": "youtube_api_rejected", "http_status": 403,
                        "provider_body": "SECRET_TOKEN",
                        "oauth_url": "https://private.invalid?token=SECRET_TOKEN"}
            if route == "channel2":
                raise RuntimeError("SECRET_TOKEN")
            return {"status": "verified", "channel_id": TARGETS[route][2],
                    "channel_title": "SECRET_TOKEN", "upload_scope_in_file": False}
        outcome = probe_all(checker=check)
        self.assertEqual(outcome["status"], "auth_or_identity_incomplete")
        self.assertEqual(outcome["accounts"][0]["http_status"], 403)
        self.assertEqual(outcome["accounts"][0]["upload_scope_in_file"], "N/A")
        self.assertFalse(outcome["accounts"][1]["expected_channel_id_matched"])
        self.assertNotIn("SECRET_TOKEN", json.dumps(outcome))
        self.assertNotIn("private.invalid", json.dumps(outcome))

    def test_partial_or_invalid_result_never_masquerades_as_success(self):
        checker = Mock(return_value={})
        outcome = probe_all(checker=checker)
        self.assertEqual(outcome["status"], "auth_or_identity_incomplete")
        self.assertEqual(checker.call_count, 4)
        self.assertTrue(all(not x["expected_channel_id_matched"]
                            for x in outcome["accounts"]))


if __name__ == "__main__":
    unittest.main()
