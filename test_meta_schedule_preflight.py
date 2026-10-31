import json
import unittest
from unittest.mock import Mock

from meta_schedule_preflight import check_auth


class PreflightTests(unittest.TestCase):
    def test_verified_page_is_read_only_and_no_secrets_leak(self):
        report = check_auth(lambda: {"pages": [
            {"page_id": "12345", "page_token": "SECRET-META", "page_name": "ToonZone"}]})
        self.assertEqual(report["status"], "identity_discovered")
        self.assertEqual(report["page_count"], 1)
        self.assertFalse(report["publishing_tested"])
        self.assertNotIn("SECRET-META", json.dumps(report))

    def test_expired_graph_token_short_circuits_and_redacts_secret(self):
        def expired():
            raise RuntimeError("Meta hesap erişimi reddedildi (HTTP 401, kod 190, alt_kod 463)")
        report = check_auth(expired)
        self.assertEqual(report["reason"], "meta_auth_rejected")
        self.assertEqual((report["graph_code"], report["graph_subcode"]), (190, 463))
        self.assertFalse(report["publishing_tested"])

    def test_untrusted_provider_exception_never_appears_in_report(self):
        def fail():
            raise RuntimeError("SECRET-RAW-META-URL")
        report = check_auth(fail)
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertEqual(report["status"], "blocked")

    def test_empty_or_invalid_config_fails_closed(self):
        self.assertEqual(check_auth(lambda: {"pages": []})["status"], "blocked")
        self.assertEqual(check_auth(lambda: {"pages": [{"page_id": "1", "page_token": ""}]})["status"], "blocked")
        self.assertEqual(check_auth(lambda: None)["status"], "blocked")

    def test_workflow_checks_credentials_before_installing_media_dependencies(self):
        from pathlib import Path
        yml = (Path(__file__).with_name(".github") / "workflows" / "public_link_schedule.yml").read_text()
        self.assertIn('if [ -n "$META_AUTH_JSON" ]; then', yml)
        self.assertIn("python meta_schedule_preflight.py", yml)
        self.assertIn("python meta_page_token_health.py", yml)
        self.assertLess(yml.index("python meta_schedule_preflight.py"),
                        yml.index("pip install gdown==6.4.2"))
        self.assertLess(yml.index("python meta_schedule_preflight.py"),
                        yml.index("run: python public_link_runtime.py publish"))


if __name__ == "__main__":
    unittest.main()
