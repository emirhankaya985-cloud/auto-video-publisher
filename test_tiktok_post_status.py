"""Mocked TikTok API checks; no provider publishing or network."""
import unittest
from unittest.mock import Mock

from tiktok_post_status import fetch_status, validate_draft, STATUS_FETCH_URL


class TikTokStatusTests(unittest.TestCase):
    ENV = {"TIKTOK_STATUS_PROBE_ENABLED": "true", "TIKTOK_ACCESS_TOKEN": "HIDDEN_TOKEN"}

    def test_no_opt_in_cannot_contact_tiktok(self):
        client = Mock()
        with self.assertRaisesRegex(RuntimeError, "not_enabled"):
            fetch_status("v_pub_file~v2-1.123", session=client, environ={})
        client.post.assert_not_called()

    def test_no_token_and_invalid_publish_id_cannot_contact_tiktok(self):
        client = Mock()
        with self.assertRaises(ValueError):
            fetch_status("https://x/?access_token=HIDDEN_TOKEN", session=client, environ=self.ENV)
        with self.assertRaises(RuntimeError):
            fetch_status("v_pub_file~v2-1.123", session=client,
                         environ={"TIKTOK_STATUS_PROBE_ENABLED": "true"})
        client.post.assert_not_called()

    def test_public_receipt_requires_real_post_id(self):
        client = Mock()
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {
            "error": {"code": "ok"},
            "data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [12345, 12345]}}
        out = fetch_status("v_pub_file~v2-1.123", session=client, environ=self.ENV)
        self.assertEqual(out["public_post_ids"], ["12345"])
        self.assertTrue(out["public_post_id_verified"])
        self.assertEqual(out["provider_writes"], 0)
        self.assertEqual(client.post.call_count, 1)
        self.assertEqual(client.post.call_args.args[0], STATUS_FETCH_URL)
        self.assertFalse(client.post.call_args.kwargs["allow_redirects"])
        self.assertEqual(client.post.call_args.kwargs["json"], {"publish_id": "v_pub_file~v2-1.123"})
        self.assertNotIn("HIDDEN_TOKEN", str(out))

    def test_private_complete_is_not_verified_publication(self):
        client = Mock()
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {
            "error": {"code": "ok"}, "data": {"status": "PUBLISH_COMPLETE",
                                               "publicaly_available_post_id": []}}
        out = fetch_status("receipt-1", session=client, environ=self.ENV)
        self.assertFalse(out["public_post_id_verified"])

    def test_failed_operation_is_sanitized(self):
        client = Mock()
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {
            "error": {"code": "ok", "message": "HIDDEN_TOKEN"},
            "data": {"status": "FAILED", "fail_reason": "HIDDEN_TOKEN"}}
        out = fetch_status("receipt-1", session=client, environ=self.ENV)
        self.assertEqual(out["failure_reason"], "unclassified_failure")
        self.assertNotIn("HIDDEN_TOKEN", str(out))

    def test_status_rejection_sanitizes_error_body(self):
        client = Mock()
        client.post.return_value.status_code = 401
        client.post.return_value.text = "HIDDEN_TOKEN"
        with self.assertRaises(RuntimeError) as error:
            fetch_status("receipt-1", session=client, environ=self.ENV)
        self.assertNotIn("HIDDEN_TOKEN", str(error.exception))

    def test_disallow_nonterminal_status_with_public_receipt(self):
        client = Mock()
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {
            "error": {"code": "ok"}, "data": {"status": "PROCESSING_UPLOAD",
                                               "publicaly_available_post_id": [555]}}
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            fetch_status("receipt-1", session=client, environ=self.ENV)

    def test_creator_specific_privacy_and_duration_and_utf16_length(self):
        creator = {"privacy_options": ["SELF_ONLY"], "max_video_post_duration_sec": 60}
        result = validate_draft(title="caption #tag", privacy_level="SELF_ONLY",
                                creator_info=creator, duration_sec=30)
        self.assertEqual(result["publishes"], 0)
        for value in ("PUBLIC_TO_EVERYONE", None):
            with self.assertRaises(ValueError):
                validate_draft(title="caption", privacy_level=value,
                               creator_info=creator, duration_sec=20)
        with self.assertRaisesRegex(ValueError, "duration"):
            validate_draft(title="caption", privacy_level="SELF_ONLY",
                           creator_info=creator, duration_sec=61)
        with self.assertRaisesRegex(ValueError, "utf16"):
            validate_draft(title="😀" * 1101, privacy_level="SELF_ONLY",
                           creator_info=creator, duration_sec=12)


if __name__ == "__main__":
    unittest.main()
