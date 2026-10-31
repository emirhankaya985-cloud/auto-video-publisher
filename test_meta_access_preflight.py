"""No-network regression tests for redacted Meta credential preflight."""
import json
import unittest
from unittest.mock import Mock
from meta_access_preflight import probe_user_token, probe_page_inventory


def response(code, body):
    return Mock(status_code=code, json=Mock(return_value=body))


class PreflightSafety(unittest.TestCase):
    def test_user_token_success_never_claims_publish(self):
        get = Mock(return_value=response(200, {"data": [{"id": "123"}]}))
        result = probe_user_token("fake-user-secret", get=get)
        self.assertEqual(result["status"], "read_verified")
        self.assertFalse(result["publishing_tested"])
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer fake-user-secret")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertNotIn("fake-user-secret", json.dumps(result))

    def test_expired_190_463_disclosed_without_secret_or_error_body(self):
        body = {"error": {"code": 190, "error_subcode": 463,
                           "message": "fake-user-secret and confidential URL"}}
        result = probe_user_token("fake-user-secret", get=Mock(return_value=response(401, body)))
        self.assertEqual(result["reason"], "expired_user_token")
        self.assertEqual(result["graph_subcode"], 463)
        self.assertNotIn("fake-user-secret", json.dumps(result))
        self.assertNotIn("confidential", json.dumps(result))

    def test_190_without_subcode_not_assumed_expired(self):
        result = probe_user_token("token", get=Mock(return_value=response(401, {"error": {"code": 190}})))
        self.assertEqual(result["reason"], "user_token_rejected")
        self.assertIsNone(result["graph_subcode"])

    def test_session_invalid(self):
        result = probe_user_token("token", get=Mock(return_value=response(
            401, {"error": {"code": 190, "error_subcode": 458}})))
        self.assertEqual(result["reason"], "app_or_session_invalid")

    def test_broken_response_fails_closed_and_never_shows_raw_exception(self):
        r = probe_user_token("secret", get=Mock(side_effect=RuntimeError("secret")))
        self.assertEqual(r["reason"], "read_failure")
        self.assertNotIn("secret", json.dumps(r))

    def test_missing_or_empty_managed_accounts_fail_closed(self):
        self.assertEqual(probe_user_token("")["reason"], "missing_user_token")
        self.assertEqual(probe_user_token("token", get=Mock(return_value=response(
            200, {"data": []})))["reason"], "no_managed_pages_returned")

    def test_independent_page_fallback_and_secret_redaction(self):
        config = '{"pages":[{"page_token":"SECRET-PAGE"}]}'
        r = probe_page_inventory(config, check=lambda data: {
            "status": "identity_verified", "accounts": [
                {"status": "identity_verified"} for _ in range(7)]})
        self.assertEqual(r["verified_count"], 7)
        self.assertEqual(r["status"], "identity_verified")
        self.assertNotIn("SECRET-PAGE", json.dumps(r))

    def test_invalid_saved_json_sanitized(self):
        self.assertEqual(probe_page_inventory("")["status"], "not_configured")
        self.assertEqual(probe_page_inventory("{invalid")["reason"],
                         "invalid_saved_page_configuration")


if __name__ == "__main__":
    unittest.main()
