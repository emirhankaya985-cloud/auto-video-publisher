import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from actions_secret_names_preflight import assess_names, inspect_repository


class ActionsSecretNamesPreflightTests(unittest.TestCase):
    def test_youtube_names_are_required_and_drive_and_ntfy_are_optional(self):
        report = assess_names({"TOKEN_CHANNEL1_JSON", "TOKEN_CHANNEL2_JSON", "NTFY_TOPIC_URL"})
        self.assertTrue(report["required_names_present"])
        self.assertEqual(report["missing_required"], [])
        self.assertFalse(report["optional"]["drive_dependent_features"])
        self.assertTrue(report["optional"]["ntfy"])
        self.assertFalse(report["secret_values_read"])

    def test_drive_secret_enables_only_optional_drive_features(self):
        report = assess_names({"TOKEN_CHANNEL1_JSON", "TOKEN_CHANNEL2_JSON", "DRIVE_TOKEN_JSON"})
        self.assertEqual(report["missing_required"], [])
        self.assertTrue(report["required_names_present"])
        self.assertTrue(report["optional"]["drive_dependent_features"])
        self.assertNotIn("secret-value-sentinel", str(report))

    def test_ntfy_is_optional(self):
        report = assess_names({"TOKEN_CHANNEL1_JSON", "TOKEN_CHANNEL2_JSON"})
        self.assertTrue(report["required_names_present"])
        self.assertFalse(report["optional"]["ntfy"])

    def test_live_inspection_requires_expected_github_account_and_only_requests_names(self):
        calls = []

        def runner(args, **kwargs):
            calls.append(args)
            output = "emirhankaya985-cloud" if len(calls) == 1 else "TOKEN_CHANNEL1_JSON\nTOKEN_CHANNEL2_JSON"
            return Mock(stdout=output)

        result = inspect_repository(runner)
        self.assertTrue(result["required_names_present"])
        self.assertEqual(calls, [
            ["gh", "api", "user", "--jq", ".login"],
            ["gh", "secret", "list", "--repo", "emirhankaya985-cloud/auto-video-publisher",
             "--json", "name", "--jq", ".[].name"],
        ])

        wrong_identity_calls = []
        def wrong_identity_runner(args, **kwargs):
            wrong_identity_calls.append(args)
            return Mock(stdout="emirhankaya-AFK")
        with self.assertRaises(RuntimeError):
            inspect_repository(wrong_identity_runner)
        # Refuse to inspect the secret inventory unless the expected account is active.
        self.assertEqual(len(wrong_identity_calls), 1)

    def test_inspection_failure_never_prints_provider_error_text(self):
        output = StringIO()
        with patch("actions_secret_names_preflight.inspect_repository",
                   side_effect=RuntimeError("private diagnostic sentinel")), redirect_stdout(output):
            from actions_secret_names_preflight import main
            result = main()
        self.assertEqual(result, 1)
        self.assertIn('"status": "unavailable"', output.getvalue())
        self.assertNotIn("private diagnostic sentinel", output.getvalue())


if __name__ == "__main__":
    unittest.main()
