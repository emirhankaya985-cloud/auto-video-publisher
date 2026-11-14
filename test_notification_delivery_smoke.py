"""Provider-mocked delivery and dedup; never calls Telegram or ntfy."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import notification_dedup
import notification_delivery_smoke as p


class LiveNotificationSmokeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_ledger = notification_dedup.LEDGER
        notification_dedup.LEDGER = Path(self.tmp.name) / "smoke.json"
        self.addCleanup(lambda: setattr(notification_dedup, "LEDGER", self.old_ledger))
        patcher = patch.dict(os.environ, {"DATABASE_URL": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_trusted_one_shot_main_ref_runs(self):
        good = {"GITHUB_REPOSITORY": "emirhankaya985-cloud/auto-video-publisher",
                "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push",
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "43637600123",
                "NOTIFICATION_SMOKE_COMMIT_TITLE": p.COMMIT_MARKER}
        self.assertTrue(p.trusted_run(good))
        for key, value in (("GITHUB_REF", "refs/heads/pr/42"),
                           ("GITHUB_RUN_ATTEMPT", "2"),
                           ("GITHUB_RUN_ID", "not-a-run"),
                           ("NOTIFICATION_SMOKE_COMMIT_TITLE", "different"),
                           ("GITHUB_REPOSITORY", "other/repository")):
            with self.subTest(key=key):
                x = dict(good, **{key: value})
                self.assertFalse(p.trusted_run(x))
                self.assertEqual(p.smoke(env=x)["provider_writes"], 0)

    def test_real_ACK_receipts_would_send_once_per_channel(self):
        telegram = Mock(return_value={"server_ack": True, "http_status": 200, "message_id": 123})
        ntfy = Mock(return_value={"server_ack": True, "http_status": 200})
        a = p.smoke(strict=False, telegram_sender=telegram, ntfy_sender=ntfy)
        self.assertEqual(a["status"], "both_server_ack")
        self.assertTrue(a["telegram"]["second_same_key_blocked"])
        self.assertTrue(a["ntfy"]["second_same_key_blocked"])
        self.assertFalse(a["phone_delivery_verified"])
        self.assertEqual(a["publisher_post_requests"], 0)
        self.assertEqual(telegram.call_count, 1)
        self.assertEqual(ntfy.call_count, 1)
        b = p.smoke(strict=False, telegram_sender=telegram, ntfy_sender=ntfy)
        self.assertEqual(b["status"], "incomplete")
        self.assertEqual(b["telegram"]["status"], "duplicate_suppressed")
        self.assertEqual(b["ntfy"]["status"], "duplicate_suppressed")
        self.assertEqual(telegram.call_count, 1)
        self.assertEqual(ntfy.call_count, 1)

    def test_missing_or_rejected_provider_never_claims_delivery(self):
        telegram = Mock(side_effect=RuntimeError("PASSWORD_LEAK"))
        ntfy = Mock(return_value={"server_ack": True, "http_status": 200})
        out = p.smoke(strict=False, telegram_sender=telegram, ntfy_sender=ntfy)
        self.assertEqual(out["status"], "incomplete")
        self.assertFalse(out["telegram"]["server_ack"])
        self.assertEqual(out["telegram"]["error_class"], "RuntimeError")
        self.assertNotIn("PASSWORD_LEAK", str(out))
        self.assertTrue(out["ntfy"]["server_ack"])

    def test_http_success_without_proper_ack_is_failure(self):
        t = Mock(return_value={"server_ack": False, "http_status": 200})
        n = Mock(return_value={"server_ack": True, "http_status": 302})
        out = p.smoke(strict=False, telegram_sender=t, ntfy_sender=n)
        self.assertEqual(out["status"], "incomplete")
        self.assertFalse(out["telegram"]["server_ack"])
        self.assertFalse(out["ntfy"]["server_ack"])


if __name__ == "__main__":
    unittest.main()
