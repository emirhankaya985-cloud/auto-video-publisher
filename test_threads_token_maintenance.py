"""No live requests or credential writes in token rotation safety tests."""
import os
import unittest
from unittest.mock import Mock, patch

from threads_token_maintenance import rotate, github_secret_store, SECRET_NAMES


class ThreadsRotationTests(unittest.TestCase):
    def env(self):
        return {"PENGUEN_THREADS_ACCESS_TOKEN": "existing-valid-token",
                "PENGUEN_THREADS_USERNAME": "beyinsiz.penguen",
                "PENGUEN_THREADS_USER_ID": "123"}

    def identity(self, *, token, expected_username, session):
        return {"id": "123", "username": "beyinsiz.penguen"}

    @patch("threads_token_maintenance.validate_threads_identity")
    def test_valid_rotation_stored_only_after_second_identity_check(self, check):
        check.side_effect = self.identity
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "new-token", "expires_in": 5184000}
        session = Mock(get=Mock(return_value=response))
        store = Mock()
        with patch.dict(os.environ, self.env(), clear=True):
            result = rotate("penguen", session=session, persist=store)
        self.assertEqual(result["days_valid"], 60)
        self.assertEqual(check.call_count, 2)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(session.get.call_args.args, ("https://graph.threads.net/refresh_access_token",))
        self.assertEqual(session.get.call_args.kwargs["params"], {"grant_type": "th_refresh_token"})
        store.assert_called_once_with(SECRET_NAMES["penguen"], "new-token")
        self.assertNotIn("new-token", str(result))

    @patch("threads_token_maintenance.validate_threads_identity")
    def test_401_existing_token_is_never_refreshed_or_stored(self, check):
        check.side_effect = RuntimeError("private provider response")
        session, store = Mock(), Mock()
        with patch.dict(os.environ, self.env(), clear=True):
            with self.assertRaisesRegex(RuntimeError, "reauthorization_required"):
                rotate("penguen", session=session, persist=store)
        session.get.assert_not_called()
        store.assert_not_called()

    @patch("threads_token_maintenance.validate_threads_identity")
    def test_changed_identity_never_persists_secrets(self, check):
        check.side_effect = [self.identity(token="old", expected_username="", session=None),
                             {"id": "999", "username": "beyinsiz.penguen"}]
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "new-token", "expires_in": 5184000}
        store = Mock()
        with patch.dict(os.environ, self.env(), clear=True):
            with self.assertRaisesRegex(RuntimeError, "identity_changed"):
                rotate("penguen", session=Mock(get=Mock(return_value=response)), persist=store)
        store.assert_not_called()

    def test_secret_store_refuses_non_owner_or_missing_pat(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "untrusted/repo",
                                     "GITHUB_REF": "refs/heads/main",
                                     "GITHUB_RUN_ATTEMPT": "1"}, clear=True), \
             patch("threads_token_maintenance.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "not_authorized"):
                github_secret_store(SECRET_NAMES["penguen"], "new-token")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
