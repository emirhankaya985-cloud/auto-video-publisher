"""Exact Film Part17 old-container reconciliation, mocked and no writes."""
import copy
import unittest
from unittest.mock import Mock, patch

import expired_ig_container_recovery as recovery


class Film17RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.item = {"id": recovery.FILM17_SOURCE_ID, "name": recovery.FILM17_FILENAME}
        self.entry = {
            "route": "film", "platform": "instagram", "file": recovery.FILM17_FILENAME,
            "run_id": recovery.FILM17_ORIGIN_RUN, "status": "uncertain",
            "post_id": None, "source_sha256": recovery.FILM17_SOURCE_SHA256,
            "caption_hash": recovery.FILM17_CAPTION_HASH,
            "publish_caption": "original-owner-caption-not-logged",
            "prepublish_retry_count": 0,
            "failure": {"reason": "invalid_media_or_graph_request",
                        "stage": "Instagram ikili video aktarımı", "http_status": 400,
                        "container_id": recovery.FILM17_CONTAINER_ID,
                        "container_status": "IN_PROGRESS",
                        "safe_to_repost": False,
                        "post_write_action": "reconcile_with_remote_history_before_any_retry"},
        }
        self.page = {"page_id": "1239298989276639",
                     "instagram_id": "17841477990224124",
                     "page_token": "TEST_PRIVATE_CREDENTIAL"}
        self.enabled = {"FILM_PART17_EXPIRED_RECOVERY_ENABLED": "true"}

    def fetched(self, state):
        res = Mock(status_code=200)
        res.json.return_value = {"id": recovery.FILM17_CONTAINER_ID,
                                 "status_code": state}
        return Mock(return_value=res)

    def recover(self, get, env=None, history=True):
        with patch.object(recovery, "_caption_hash", return_value=recovery.FILM17_CAPTION_HASH):
            return recovery.authorize_film_part17_expired_recovery(
                "film", "instagram", self.item, self.entry, self.page,
                history_reconciled=history, get=get,
                environ=self.enabled if env is None else env)

    def test_disabled_always_fail_closed(self):
        get = Mock()
        self.assertFalse(self.recover(get, env={}))
        get.assert_not_called()

    def test_expired_exact_source_allows_one_new_pre_upload_preparation(self):
        get = self.fetched("EXPIRED")
        self.assertTrue(self.recover(get))
        self.assertEqual(self.entry["status"], "ready")
        self.assertEqual(self.entry["prepublish_retry_count"], 1)
        self.assertTrue(self.entry["expired_container_recovery"]["live_history_checked"])
        self.assertEqual(get.call_count, 1)
        self.assertFalse(self.recover(get))
        self.assertEqual(get.call_count, 1)
        self.assertNotIn("TEST_PRIVATE_CREDENTIAL", str(self.entry))

    def test_no_remote_history_or_wrong_source_is_not_retriable(self):
        for field, bad in (("source_sha256", "bad"),
                           ("caption_hash", "bad"),
                           ("run_id", "different-run"),
                           ("container_publish_attempted", True),
                           ("status", "done"), ("post_id", "18100000000000000"),
                           ("prepublish_retry_count", 1)):
            with self.subTest(field=field):
                get = Mock()
                entry = copy.deepcopy(self.entry)
                self.entry[field] = bad
                self.assertFalse(self.recover(get))
                get.assert_not_called()
                self.entry = entry
        get = Mock()
        self.assertFalse(self.recover(get, history=False))
        get.assert_not_called()

    def test_only_expired_container_allows_recovery(self):
        for status in ("IN_PROGRESS", "FINISHED", "PUBLISHED", "ERROR", "UNKNOWN"):
            with self.subTest(status=status):
                before = copy.deepcopy(self.entry)
                get = self.fetched(status)
                self.assertFalse(self.recover(get))
                self.assertEqual(before, self.entry)


if __name__ == "__main__":
    unittest.main()
