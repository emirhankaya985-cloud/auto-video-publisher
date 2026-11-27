"""Fresh Instagram container status reads are GET-only and fail closed."""
import copy
import unittest
from unittest.mock import Mock

from instagram_container_reconcile import refresh_pre_publish_container_status
from publisher_recovery import known_pre_publish_media_rejection


class ContainerReconcileTests(unittest.TestCase):
    def setUp(self):
        self.entry = {
            "route": "film", "platform": "instagram", "file": "episode.mp4",
            "status": "uncertain", "container_publish_attempted": False,
            "failure": {
                "container_id": "17908115514599675",
                "stage": "Instagram ikili video aktarımı", "http_status": 400,
                "graph_code": None, "container_status": "IN_PROGRESS",
            },
        }
        self.page = {
            "page_id": "123456789012345", "instagram_id": "17841412345678901",
            "page_token": "TEST_PRIVATE_TOKEN",
        }

    @staticmethod
    def response(status, *, response_id="17908115514599675", http=200, error=None):
        result = Mock(status_code=http)
        result.json.return_value = {
            "id": response_id, "status_code": status,
            **({"error": error} if error else {}),
        }
        return result

    def test_expired_refreshes_failure_and_makes_only_pre_publish_error_retryable(self):
        get = Mock(return_value=self.response("EXPIRED"))
        self.assertEqual(refresh_pre_publish_container_status(
            "film", self.entry, self.page, history_reconciled=True, get=get), "EXPIRED")
        get.assert_called_once()
        args, kwargs = get.call_args
        self.assertIn("/17908115514599675", args[0])
        self.assertEqual(kwargs["params"]["fields"], "id,status_code,status")
        self.assertEqual(self.entry["failure"]["container_status"], "EXPIRED")
        self.assertNotIn("TEST_PRIVATE_TOKEN", str(self.entry))
        prior = Mock(stage=self.entry["failure"]["stage"], http_status=400,
                     code=None, subcode=None, container_status="EXPIRED")
        self.assertTrue(known_pre_publish_media_rejection(prior, "film", 0))

    def test_in_progress_refresh_does_not_authorize_retry(self):
        get = Mock(return_value=self.response("IN_PROGRESS"))
        self.assertEqual(refresh_pre_publish_container_status(
            "film", self.entry, self.page, history_reconciled=True, get=get), "IN_PROGRESS")
        prior = Mock(stage=self.entry["failure"]["stage"], http_status=400,
                     code=None, subcode=None,
                     container_status=self.entry["failure"]["container_status"])
        self.assertFalse(known_pre_publish_media_rejection(prior, "film", 0))

    def test_publish_attempt_and_binding_mismatch_skip_status_get(self):
        get = Mock()
        self.entry["container_publish_attempted"] = True
        self.assertIsNone(refresh_pre_publish_container_status(
            "film", self.entry, self.page, history_reconciled=True, get=get))
        self.entry["container_publish_attempted"] = False
        self.entry["container_resume"] = {"container_id": "17900000000000000"}
        self.assertIsNone(refresh_pre_publish_container_status(
            "film", self.entry, self.page, history_reconciled=True, get=get))
        get.assert_not_called()

    def test_history_must_be_reconciled_before_container_get(self):
        get = Mock()
        self.assertIsNone(refresh_pre_publish_container_status("film", self.entry, self.page, get=get))
        get.assert_not_called()

    def test_route_mismatch_skips_status_get(self):
        get = Mock()
        self.assertIsNone(refresh_pre_publish_container_status(
            "tarladaki", self.entry, self.page, history_reconciled=True, get=get))
        get.assert_not_called()

    def test_terminal_cached_status_does_not_make_extra_meta_request(self):
        get = Mock()
        self.entry["failure"]["container_status"] = "EXPIRED"
        self.assertIsNone(refresh_pre_publish_container_status(
            "film", self.entry, self.page, history_reconciled=True, get=get))
        get.assert_not_called()

    def test_bad_response_does_not_replace_prior_status(self):
        for response in (self.response("EXPIRED", response_id="17900000000000000"),
                         self.response("EXPIRED", http=400),
                         self.response("UNKNOWN")):
            with self.subTest(response=response):
                entry = copy.deepcopy(self.entry)
                get = Mock(return_value=response)
                self.assertIsNone(refresh_pre_publish_container_status(
                    "film", entry, self.page, history_reconciled=True, get=get))
                self.assertEqual(entry["failure"]["container_status"], "IN_PROGRESS")


if __name__ == "__main__":
    unittest.main()
