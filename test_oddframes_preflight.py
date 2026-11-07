"""OddFrames must not inherit another account's Drive, Page or rights."""
import unittest
from oddframes_preflight import readiness


class OddFramesReadinessTests(unittest.TestCase):
    def all_fields(self):
        return {"ODDFRAMES_DRIVE_FOLDER_ID": "12345678901234567890",
                "ODDFRAMES_PAGE_ID": "1234567890",
                "ODDFRAMES_INSTAGRAM_ID": "1234567891",
                "ENABLE_ODDFRAMES_ROUTES": "true",
                "ODDFRAMES_RIGHTS_APPROVED": "true"}

    def page(self):
        return {"page_name": "OddFrames", "page_id": "1234567890",
                "instagram_id": "1234567891", "page_token": "not-shared"}

    def test_missing_rights_and_credentials_block_without_meta_reads(self):
        result = readiness(environ={})
        self.assertEqual(result["status"], "blocked_configuration_or_rights")
        self.assertIn("ODDFRAMES_RIGHTS_APPROVED", result["missing"])
        self.assertFalse(result["authorized_to_publish"])

    def test_wrong_page_never_reuses_other_account_identity(self):
        env = self.all_fields()
        self.assertEqual(readiness(environ=env)["status"], "meta_identity_unverified")
        wrong = dict(self.page(), page_name="ToonZone")
        self.assertEqual(readiness(environ=env, pages=[wrong])["status"], "meta_identity_mismatch")
        self.assertEqual(readiness(environ=env, pages=[self.page(), self.page()])["status"], "meta_identity_mismatch")

    def test_matching_values_are_preflight_only_not_publish_authorization(self):
        response = readiness(environ=self.all_fields(), pages=[self.page()])
        self.assertEqual(response["status"], "preflight_ready_no_publication")
        self.assertFalse(response["authorized_to_publish"])
        self.assertTrue(response["requires_publisher_integration"])
        self.assertNotIn("not-shared", str(response))

    def test_invalid_or_reused_ids_block(self):
        env = self.all_fields()
        env["ODDFRAMES_DRIVE_FOLDER_ID"] = "../bad"
        self.assertEqual(readiness(environ=env, pages=[self.page()])["status"],
                         "invalid_identity_settings")


if __name__ == "__main__":
    unittest.main()
