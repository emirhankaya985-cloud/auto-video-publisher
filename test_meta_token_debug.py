import unittest

from test_meta_token import safe_debug_report


class MetaTokenDebugTests(unittest.TestCase):
    def test_safe_report_whitelists_expiry_and_permission_fields(self):
        report = safe_debug_report({
            "is_valid": True,
            "app_id": "12345",
            "type": "USER",
            "expires_at": 1790000000,
            "data_access_expires_at": 1791000000,
            "scopes": ["pages_show_list", "instagram_basic"],
            "access_token": "must-not-appear",
            "app_secret": "must-not-appear-either",
        })
        self.assertTrue(report["is_valid"])
        self.assertEqual(report["app_id"], "12345")
        self.assertEqual(report["permissions"], ["instagram_basic", "pages_show_list"])
        self.assertEqual(report["data_access_expires_at"], 1791000000)
        self.assertEqual(report["data_access_expires_at_utc"], "2026-10-03T04:00:00+00:00")
        self.assertNotIn("must-not-appear", str(report))

    def test_unset_and_zero_expiry_are_reported_without_inventing_dates(self):
        report = safe_debug_report({"is_valid": True, "expires_at": 0})
        self.assertIsNone(report["data_access_expires_at"])
        self.assertIsNone(report["data_access_expires_at_utc"])
        self.assertIsNone(report["expires_at_utc"])


if __name__ == "__main__":
    unittest.main()
