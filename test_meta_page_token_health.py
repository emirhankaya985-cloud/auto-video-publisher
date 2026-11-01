import json
import unittest
from unittest.mock import Mock

from meta_page_token_health import audit, check_page


class PageHealthTests(unittest.TestCase):
    PAGE = {"page_name": "Tarladaki Fasulye", "page_id": "12345",
            "instagram_id": "99999", "page_token": "TEST-SECRET"}

    def response(self, status=200, **body):
        response = Mock(status_code=status, ok=(status == 200))
        response.json.return_value = body
        return response

    def test_valid_identity_is_not_publish_proof(self):
        getter = Mock(return_value=self.response(id="12345", name="Tarladaki Fasulye",
                    instagram_business_account={"id": "99999"}))
        report = check_page(self.PAGE, get=getter)
        self.assertEqual(report["status"], "identity_verified")
        self.assertFalse(report["publishing_tested"])
        self.assertNotIn("TEST-SECRET", json.dumps(report))
        self.assertEqual(getter.call_args.kwargs["headers"]["Authorization"], "Bearer TEST-SECRET")

    def test_expired_token(self):
        response = self.response(401, error={"code": 190, "error_subcode": 463,
                                            "message": "SECRET-BODY"})
        report = check_page(self.PAGE, get=Mock(return_value=response))
        self.assertEqual(report["reason"], "token_expired")
        self.assertNotIn("SECRET-BODY", json.dumps(report))

    def test_invalid_and_revoked_token(self):
        response = self.response(401, error={"code": 190, "error_subcode": 458})
        self.assertEqual(check_page(self.PAGE, get=Mock(return_value=response))["reason"],
                         "invalid_or_revoked_token")

    def test_instagram_mismatch(self):
        response = self.response(id="12345", name="Tarladaki Fasulye",
                                 instagram_business_account={"id": "8888"})
        self.assertEqual(check_page(self.PAGE, get=Mock(return_value=response))["reason"],
                         "instagram_id_mismatch")

    def test_bad_identifier_does_not_send_request(self):
        get = Mock()
        self.assertEqual(check_page({**self.PAGE, "page_id": "../123"}, get=get)["reason"],
                         "invalid_configuration")
        get.assert_not_called()

    def test_unexpected_error_redacted(self):
        report = check_page(self.PAGE, get=Mock(side_effect=RuntimeError("TEST-SECRET")))
        self.assertEqual(report["reason"], "client_error")
        self.assertNotIn("TEST-SECRET", json.dumps(report))

    def test_historical_film_labels_resolve_by_allowlisted_page_id(self):
        first = {"page_name": "Eski Film Etiketi", "page_id": "1239298989276639", "page_token": "fake"}
        second = {"page_name": "Filmmağrası1", "page_id": "854990964375370", "page_token": "fake"}
        def mocked_get(url, **kwargs):
            pid = url.split("/")[-1]
            return self.response(id=pid, name="arbitrary historical display label")
        from meta_page_token_health import canonical_page_name
        self.assertEqual(canonical_page_name(first), "Film Mağarası")
        self.assertEqual(canonical_page_name(second), "Filmmagrasi")
        result = audit({"pages": [first, second]}, get=mocked_get)
        self.assertEqual([row["status"] for row in result["accounts"]],
                         ["identity_verified", "identity_verified"])
        self.assertNotIn("Film Mağarası", result["missing_page_names"])
        self.assertNotIn("Filmmagrasi", result["missing_page_names"])

    def test_saved_token_whitespace_is_invalid_without_network(self):
        getter = Mock()
        row = check_page({**self.PAGE, "page_token": " TEST-SECRET\\n"}, get=getter)
        self.assertEqual(row["reason"], "invalid_configuration")
        getter.assert_not_called()

    def test_saved_duplicate_id_blocks_second_page(self):
        saved = [self.PAGE,
                 {"page_name": "Beyinsiz Penguen", "page_id": "12345", "page_token": "other"}]
        response = self.response(id="12345", name="Tarladaki Fasulye",
                                 instagram_business_account={"id": "99999"})
        result = audit({"pages": saved}, get=Mock(return_value=response))
        self.assertEqual(result["accounts"][1]["reason"], "duplicate_configuration")

    def test_missing_config(self):
        self.assertEqual(audit(None)["reason"], "missing_or_invalid_META_AUTH_JSON")

    def test_partial_accounts_are_not_all_green(self):
        resp = self.response(id="12345", name="Tarladaki Fasulye",
                             instagram_business_account={"id": "99999"})
        result = audit({"pages": [self.PAGE]}, get=Mock(return_value=resp))
        self.assertEqual(result["status"], "attention_needed")
        self.assertIn("ToonZone", result["missing_page_names"])


class UserTokenOnlyHealthTests(unittest.TestCase):
    def test_main_uses_user_token_when_json_secret_is_absent(self):
        import io
        import os
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from meta_page_token_health import main

        pages = {"pages": [{"page_id": "123", "page_name": "ToonZone", "page_token": "test-only"}]}
        result = {"status": "identity_verified", "publishing_tested": False}
        with patch.dict(os.environ, {"META_ACCESS_TOKEN": "test-user-token", "META_AUTH_JSON": ""}, clear=True), \
             patch("meta_auth_loader.Path.exists", return_value=False), \
             patch("meta_auth_loader.discover_pages", return_value=pages) as discover, \
             patch("meta_page_token_health.audit", return_value=result) as audit, \
             redirect_stdout(io.StringIO()) as stdout:
            code = main()
        self.assertEqual(code, 0)
        discover.assert_called_once_with("test-user-token")
        audit.assert_called_once_with(pages)
        self.assertIn("identity_verified", stdout.getvalue())
        self.assertNotIn("test-user-token", stdout.getvalue())
        self.assertNotIn("test-only", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
