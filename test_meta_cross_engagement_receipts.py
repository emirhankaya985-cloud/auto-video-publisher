import unittest
from unittest.mock import patch, Mock

from meta_cross_engagement import key
import meta_cross_engagement_receipts as m


class VerifiedReceiptsTests(unittest.TestCase):
    def task(self):
        return {"platform": "facebook", "actor": "222", "owner": "111", "operation": "like",
                "post_id": "333", "source_run_id": "10"}

    def test_only_accepted_matching_ack_not_dryrun(self):
        t = self.task()
        ledger = {"actions": {key(t): {**t, "status": "accepted", "api_ack": True, "run_id": "55"}}}
        names = {("facebook", "222"): "Penguen", ("facebook", "111"): "ToonZone"}
        groups = m.verified_batch(ledger, [t], "55", names)
        self.assertIn("Penguen / facebook: 1 beğeni → ToonZone", m.message(groups, "55"))
        self.assertIn("tüm hesapları", m.message(groups, "55"))
        ledger["actions"][key(t)]["api_ack"] = False
        self.assertFalse(m.verified_batch(ledger, [t], "55", names))
        self.assertIsNone(m.message({}, "55"))

    def test_unsupported_save_cannot_be_announced(self):
        t = self.task()
        t["operation"] = "save"
        ledger = {"actions": {key(t): {**t, "status": "accepted", "api_ack": True, "run_id": "55"}}}
        self.assertFalse(m.verified_batch(ledger, [t], "55", {}))

    def test_wrong_accepted_actor_mapping_fails_closed(self):
        t = self.task()
        ledger = {"actions": {key(t): {**t, "status": "accepted", "api_ack": True, "run_id": "55"}}}
        with self.assertRaisesRegex(RuntimeError, "identity_unverified"):
            m.verified_batch(ledger, [t], "55", {})

    def test_missing_mode_never_sends(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(m, "send_telegram") as send:
            self.assertEqual(m.main(), 0)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
