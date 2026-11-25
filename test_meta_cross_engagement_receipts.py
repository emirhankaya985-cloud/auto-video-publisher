import unittest
import json
import os
import tempfile
from pathlib import Path
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
        self.assertIn("Penguen / facebook: 1 beğeni → ToonZone", m.message(groups, "55", names))
        self.assertIn("tüm hesapları", m.message(groups, "55", names))
        ledger["actions"][key(t)]["api_ack"] = False
        self.assertFalse(m.verified_batch(ledger, [t], "55", names))
        self.assertIsNone(m.message({}, "55", names))


    def test_accepted_like_report_includes_other_verified_accounts_with_zero(self):
        t = self.task()
        ledger = {"actions": {key(t): {**t, "status": "accepted", "api_ack": True, "run_id": "55"}}}
        names = {("facebook", "222"): "Penguen",
                 ("facebook", "111"): "ToonZone",
                 ("instagram", "444"): "Gönle Düşen"}
        groups = m.verified_batch(ledger, [t], "55", names)
        body = m.message(groups, "55", names)
        self.assertIn("Gönle Düşen", body)
        self.assertIn("Henüz doğrulanmış beğeni yok", body)
        self.assertIn("Toplam: 1 beğeni", body)
        self.assertEqual(body.count("Toplam:"), 1)

    def test_owner_likes_count_only_when_acknowledged(self):
        t = self.task()
        t["actor"] = t["owner"]
        names = {("facebook", "111"): "ToonZone"}
        ledger = {"actions": {key(t): {**t, "status": "accepted",
                                      "api_ack": True, "run_id": "55"}}}
        groups = m.verified_batch(ledger, [t], "55", names)
        self.assertIn("ToonZone / facebook: 1 beğeni → ToonZone (kendi gönderisi: 1)",
                      m.message(groups, "55", names))
        ledger["actions"][key(t)]["api_ack"] = False
        self.assertFalse(m.verified_batch(ledger, [t], "55", names))

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

    def test_zero_plan_alert_says_no_attempt_and_is_daily(self):
        name, body, category = m.no_like_alert({"planned": 0}, {"actions": {}}, [], "55")
        self.assertEqual(category, "no_plan")
        self.assertIn("beğeni denemesi yapılmadı", body)
        self.assertIn("cross-engagement-no-like-", name)

    def test_unconfirmed_plan_alert_does_not_claim_rejection_of_uncertain_post(self):
        t = self.task()
        ledger = {"actions": {key(t): {**t, "run_id": "55", "status": "uncertain"}}}
        name, body, category = m.no_like_alert({"planned": 1}, ledger, [t], "55")
        self.assertEqual(category, "unconfirmed")
        self.assertIn("sonucu belirsiz", body)
        self.assertNotIn("denemesi yapılmadı", body)

    def test_accepted_action_never_gets_zero_like_alert(self):
        t = self.task()
        ledger = {"actions": {key(t): {**t, "run_id": "55", "status": "accepted", "api_ack": True}}}
        self.assertIsNone(m.no_like_alert({"planned": 1}, ledger, [t], "55"))

    def test_accepted_label_without_ack_still_gets_unconfirmed_alert(self):
        t = self.task()
        ledger = {"actions": {key(t): {**t, "run_id": "55", "status": "accepted",
                                       "api_ack": False}}}
        alert = m.no_like_alert({"planned": 1}, ledger, [t], "55")
        self.assertEqual(alert[2], "unconfirmed")
        self.assertIn("hiçbiri", alert[1])
        ledger["actions"][key(t)]["api_ack"] = True
        ledger["actions"][key(t)]["owner"] = "999"
        self.assertEqual(m.no_like_alert({"planned": 1}, ledger, [t], "55")[2], "unconfirmed")

    def test_alert_archive_lookup_fails_closed_on_partial_inventory(self):
        with patch("meta_cross_engagement.github", return_value=Mock(
            json=Mock(return_value={"total_count": 2, "artifacts": []}))):
            with self.assertRaisesRegex(RuntimeError, "history_unavailable"):
                m.alert_already_archived("cross-engagement-no-like-test")

    def test_main_sends_zero_like_once_after_archived_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "report.json").write_text(json.dumps({"mode": "apply", "planned": 0}))
            (root / "plan.json").write_text("[]")
            (root / "engagement.json").write_text('{"actions": {}}')
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "55", "ENGAGEMENT_MODE": "account_batch",
                                      "ENGAGEMENT_RESULT_ARCHIVED": "true"}), \
                 patch.object(m, "REPORT", root / "report.json"), \
                 patch.object(m, "PLAN", root / "plan.json"), \
                 patch.object(m, "LEDGER", root / "engagement.json"), \
                 patch.object(m, "ALERT", root / "no-like-alert.json"), \
                 patch("meta_auth_loader.load_meta_auth", return_value={"pages": []}), \
                 patch.object(m, "alert_already_archived", return_value=False), \
                 patch.object(m, "send_telegram", return_value={"server_ack": True}) as send:
                self.assertEqual(m.main(), 0)
                self.assertTrue((root / "no-like-alert.json").exists())
                self.assertIn("beğeni atılmadı", send.call_args.args[0])

            with patch.dict(os.environ, {"GITHUB_RUN_ID": "55", "ENGAGEMENT_MODE": "account_batch",
                                      "ENGAGEMENT_RESULT_ARCHIVED": "true"}), \
                 patch.object(m, "REPORT", root / "report.json"), \
                 patch.object(m, "PLAN", root / "plan.json"), \
                 patch.object(m, "LEDGER", root / "engagement.json"), \
                 patch("meta_auth_loader.load_meta_auth", return_value={"pages": []}), \
                 patch.object(m, "alert_already_archived", return_value=True), \
                 patch.object(m, "send_telegram") as send:
                self.assertEqual(m.main(), 0)
                send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
