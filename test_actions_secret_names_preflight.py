import unittest
from unittest.mock import Mock

from actions_secret_names_preflight import assess_names, inspect_repository


class ActionsSecretNamesPreflightTests(unittest.TestCase):
    def test_required_secret_names_and_optional_ntfy(self):
        report = assess_names({"DRIVE_TOKEN_JSON", "TOKEN_CHANNEL1_JSON", "TOKEN_CHANNEL2_JSON",
                               "NTFY_TOPIC_URL"})
        self.assertTrue(report["ready_by_name_only"])
        self.assertEqual(report["missing_required"], [])
        self.assertTrue(report["optional"]["ntfy"])
        self.assertFalse(report["secret_values_read"])

    def test_missing_drive_secret_is_named_without_values(self):
        report = assess_names({"TOKEN_CHANNEL1_JSON", "TOKEN_CHANNEL2_JSON", "NTFY_TOPIC_URL"})
        self.assertEqual(report["missing_required"], ["DRIVE_TOKEN_JSON"])
        self.assertFalse(report["ready_by_name_only"])
        self.assertNotIn("secret-value-sentinel", str(report))

    def test_ntfy_is_optional(self):
        report = assess_names({"DRIVE_TOKEN_JSON", "TOKEN_CHANNEL1_JSON", "TOKEN_CHANNEL2_JSON"})
        self.assertTrue(report["ready_by_name_only"])
        self.assertFalse(report["optional"]["ntfy"])

    def test_live_inspection_requires_expected_github_account_and_only_requests_names(self):
        calls = []

        def runner(args, **kwargs):
            calls.append(args)
            output = "emirhankaya985-cloud" if len(calls) == 1 else "DRIVE_TOKEN_JSON\nTOKEN_CHANNEL1_JSON\nTOKEN_CHANNEL2_JSON"
            return Mock(stdout=output)

        result = inspect_repository(runner)
        self.assertTrue(result["ready_by_name_only"])
        self.assertEqual(calls[1][0:3], ["gh", "secret", "list"])
        self.assertIn("--json", calls[1])
        self.assertIn("name", calls[1])
        self.assertNotIn("value", calls[1])

        with self.assertRaises(RuntimeError):
            inspect_repository(lambda *_args, **_kwargs: Mock(stdout="emirhankaya-AFK"))


if __name__ == "__main__":
    unittest.main()
