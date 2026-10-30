"""Offline multi-account Threads checks; no API requests are made."""
import os
import unittest
from unittest.mock import patch
from threads_accounts import THREADS_ROUTE_PREFIXES, threads_account_config, threads_result_key, threads_route_enabled


class ThreadsAccountsTests(unittest.TestCase):
    def test_routes_are_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(len(THREADS_ROUTE_PREFIXES), 6)
            for route in THREADS_ROUTE_PREFIXES:
                self.assertFalse(threads_route_enabled(route))

    def test_readonly_needs_identity_not_media_host(self):
        with patch.dict(os.environ, {
            "FILM_THREADS_ACCESS_TOKEN": "film-token",
            "FILM_THREADS_USERNAME": "@film_magrasi",
            "FILM_THREADS_USER_ID": "12345",
        }, clear=True):
            account = threads_account_config("film", require_enabled=False, require_media=False)
            self.assertEqual((account.username, account.expected_user_id), ("film_magrasi", "12345"))
            with self.assertRaisesRegex(RuntimeError, "FILM_THREADS_VIDEO_URL_TEMPLATE"):
                threads_account_config("film", require_enabled=False)

    def test_each_route_has_separate_credentials(self):
        for route, prefix in THREADS_ROUTE_PREFIXES.items():
            with self.subTest(route=route), patch.dict(os.environ, {
                f"ENABLE_{prefix}_THREADS": "true",
                f"{prefix}_THREADS_ACCESS_TOKEN": f"token-{route}",
                f"{prefix}_THREADS_USERNAME": route,
                f"{prefix}_THREADS_VIDEO_URL_TEMPLATE": "https://cdn.example/{file_id}",
            }, clear=True):
                self.assertTrue(threads_route_enabled(route))
                self.assertEqual(threads_account_config(route).token, f"token-{route}")

    def test_penguen_legacy_token_is_not_shared(self):
        with patch.dict(os.environ, {
            "THREADS_ACCESS_TOKEN": "penguen-only", "PENGUEN_THREADS_USERNAME": "penguen",
        }, clear=True):
            self.assertEqual(threads_account_config("penguen", require_enabled=False, require_media=False).token, "penguen-only")
            with self.assertRaisesRegex(RuntimeError, "GONLE_THREADS_ACCESS_TOKEN"):
                threads_account_config("gonle", require_enabled=False, require_media=False)

    def test_invalid_token_and_route_fail_closed(self):
        with self.assertRaises(ValueError):
            threads_account_config("invalid", require_enabled=False)
        with patch.dict(os.environ, {
            "TOONZONE_THREADS_ACCESS_TOKEN": "bad token",
            "TOONZONE_THREADS_USERNAME": "toonzone",
        }, clear=True):
            with self.assertRaisesRegex(RuntimeError, "biçimi"):
                threads_account_config("toonzone", require_enabled=False, require_media=False)

    def test_result_keys_are_unique(self):
        self.assertEqual(len({threads_result_key(route) for route in THREADS_ROUTE_PREFIXES}), 6)
        self.assertEqual(threads_result_key("penguen"), "threads")

    @patch("check_threads_connection.validate_threads_identity", return_value={"id": "123", "username": "film_magrasi"})
    def test_readonly_check_ensures_expected_id(self, validate):
        from check_threads_connection import main
        env = {"THREADS_CHECK_ROUTE": "film", "FILM_THREADS_ACCESS_TOKEN": "film-token",
               "FILM_THREADS_USERNAME": "film_magrasi", "FILM_THREADS_USER_ID": "123"}
        with patch.dict(os.environ, env, clear=True):
            main()
        validate.assert_called_once_with(token="film-token", expected_username="film_magrasi")
        with patch.dict(os.environ, {**env, "FILM_THREADS_USER_ID": "different"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ID"):
                main()


if __name__ == "__main__":
    unittest.main()
