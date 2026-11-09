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

    def test_four_live_auth_failures_distinguish_refresh_from_network_safely(self):
        results = {
            "channel1": {"status": "authorization_or_connection_failed",
                         "error_type": "RefreshError", "unsafe": "PRIVATE_SECRET"},
            "channel2": {"status": "authorization_or_connection_failed",
                         "error_type": "ReadTimeout"},
            "daily_laugh": {"status": "authorization_or_connection_failed",
                            "error_type": "RefreshError"},
            "gonle_dusen": {"status": "authorization_or_connection_failed",
                            "error_type": "SECRET_PRIVATE_EXCEPTION"},
        }
        report = probe_all(checker=lambda target: results[target])
        self.assertEqual(report["status"], "auth_or_identity_incomplete")
        self.assertEqual(report["accounts_checked"], 4)
        self.assertEqual(report["safe_failure_kind_counts"], {
            "network_timeout": 1,
            "oauth_refresh_rejected": 2,
            "other_authorization_or_transport_error": 1,
        })
        self.assertFalse(any(x["expected_channel_id_matched"] for x in report["accounts"]))
        self.assertEqual(report["youtube_upload_requests"], 0)
        self.assertEqual(report["provider_writes"], 0)
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertNotIn("ReadTimeout", json.dumps(report))

    def test_success_does_not_invent_a_failure_kind(self):
        report = probe_all(checker=lambda target: {
            "status": "verified", "channel_id": TARGETS[target][2],
            "error_type": "RefreshError",
        })
        self.assertEqual(report["status"], "all_four_verified")
        self.assertEqual(report["safe_failure_kind_counts"], {})
        self.assertTrue(all("failure_kind" not in x for x in report["accounts"]))

    def test_partial_or_invalid_result_never_masquerades_as_success(self):
        checker = Mock(return_value={})
        outcome = probe_all(checker=checker)
        self.assertEqual(outcome["status"], "auth_or_identity_incomplete")
        self.assertEqual(checker.call_count, 4)
        self.assertTrue(all(not x["expected_channel_id_matched"]
                            for x in outcome["accounts"]))


if __name__ == "__main__":
    unittest.main()
