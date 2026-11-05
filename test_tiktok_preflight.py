"""Zero-network safety tests for the disabled TikTok foundation."""
import unittest
from unittest.mock import Mock

import tiktok_preflight as target


class TikTokPreflightTests(unittest.TestCase):
    def test_no_token_is_not_ready_and_never_leaks_credentials(self):
        row = target.readiness(environ={})
        self.assertEqual(row["mode"], "preflight_only")
        self.assertTrue(row["blocked"])
        self.assertEqual(row["publishes"], 0)
        self.assertFalse(row["authorization_live_verified"])

    def test_requested_publish_without_app_audit_still_blocked(self):
        row = target.readiness(environ={"TIKTOK_PUBLISH_ENABLED": "true", "TIKTOK_ACCESS_TOKEN": "secret",
                                        "TIKTOK_OPEN_ID": "owner"})
        self.assertTrue(row["blocked"])
        self.assertNotIn("secret", str(row))

    def test_probe_requires_explicit_opt_in_no_network(self):
        session = Mock()
        with self.assertRaisesRegex(RuntimeError, "not_enabled"):
            target.probe_creator_info(session=session, environ={"TIKTOK_ACCESS_TOKEN": "secret"})
        session.post.assert_not_called()

    def test_creator_info_probe_is_bounded_single_read_only_query(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {
            "error": {"code": "ok"},
            "data": {"privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 300}}
        result = target.probe_creator_info(session=session, environ={
            "TIKTOK_PREFLIGHT_PROBE_ENABLED": "true", "TIKTOK_ACCESS_TOKEN": "private-token"})
        self.assertEqual(result["publishes"], 0)
        self.assertEqual(result["privacy_options"], ["SELF_ONLY"])
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.post.call_args.args[0], target.CREATOR_INFO_URL)
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
        self.assertNotIn("private-token", str(result))

    def test_provider_failure_sanitizes_credentials(self):
        session = Mock()
        session.post.return_value.status_code = 401
        with self.assertRaises(RuntimeError) as error:
            target.probe_creator_info(session=session, environ={
                "TIKTOK_PREFLIGHT_PROBE_ENABLED": "true", "TIKTOK_ACCESS_TOKEN": "private-token"})
        self.assertNotIn("private-token", str(error.exception))


if __name__ == "__main__":
    unittest.main()
