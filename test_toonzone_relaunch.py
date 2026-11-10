"""Regression checks: archive, prior Meta POST or publisher state never reset."""
import unittest
import copy
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import toonzone_relaunch as rel


class RelaunchSafetyTests(unittest.TestCase):
    def test_approval_only_on_owner_main_first_attempt(self):
        env = {"GITHUB_REPOSITORY": rel.REPO, "GITHUB_REF": "refs/heads/main",
               "GITHUB_RUN_ATTEMPT": "1", "TOONZONE_RELAUNCH_APPROVED": "true"}
        self.assertTrue(rel.allowed_context(env))
        for key in env:
            wrong = dict(env)
            wrong[key] = "false"
            self.assertFalse(rel.allowed_context(wrong))

    def test_order_only_part1_to_4(self):
        rows = [{"episode": episode, "part": part, "id": f"{episode}-{part}",
                 "name": f"S01E{episode:02d}_Name_Part{part}.mp4"}
                for episode in range(4, 13) for part in range(1, 5)]
        self.assertEqual([r["part"] for r in rel.ordered_episode(rows)[:4]], [1, 2, 3, 4])
        self.assertEqual(len(rel.ordered_episode(rows)), 36)
        with self.assertRaises(RuntimeError):
            rel.ordered_episode(rows[:-1])
        with self.assertRaises(RuntimeError):
            rel.ordered_episode(rows + [rows[0]])

    def test_pending_or_unrecognized_posts_never_auto_retry(self):
        for status in ("attempted", "reserved", "held"):
            self.assertTrue(rel.state_for({"status": status, "post_id": ""}, []).startswith("held"))
        self.assertEqual(rel.state_for({"status": "accepted_unverified", "post_id": "11"}, []),
                         "held_remote_id_unverified")
        self.assertEqual(rel.state_for({"status": "accepted_unverified", "post_id": "11"}, [{"id": "11"}]),
                         "verified")

    def recovery_ledger(self):
        item = {"episode": 6, "part": 2, "id": rel.RECOVERY_SOURCE, "name": rel.RECOVERY_FILE}
        facebook = {
            "status": "verified", "platform": "facebook", "route": "toonzone",
            "file": rel.RECOVERY_FILE, "source_id": rel.RECOVERY_SOURCE,
            "post_id": rel.RECOVERY_FB_ID, "caption": "exact caption",
            "last_seen": "2026-11-10T18:22:12+00:00",
        }
        instagram = {
            "status": "resume_reserved", "platform": "instagram", "route": "toonzone",
            "file": rel.RECOVERY_FILE, "source_id": rel.RECOVERY_SOURCE,
            "cover_id": rel.RECOVERY_COVER,
            "source_sha256": rel.RECOVERY_SOURCE_SHA,
            "cover_sha256": rel.RECOVERY_COVER_SHA,
            "intent_run_id": rel.RECOVERY_RUN, "caption": "exact caption",
            "resume_container_id": rel.RECOVERY_CONTAINER,
            "resume_run_id": "500", "last_seen": "2026-11-10T18:25:48+00:00",
        }
        return item, {"schema": 1, "records": {
            rel.record_key(item, "facebook"): facebook,
            rel.record_key(item, "instagram"): instagram
        }}, instagram

    def test_pinned_incident_checks_exact_identity_before_any_resume(self):
        item, ledger, rec = self.recovery_ledger()
        self.assertTrue(rel.known_ig_incident(item, rec))
        for field, wrong in (("source_sha256", "bad"), ("intent_run_id", "other"),
                             ("cover_id", "other")):
            invalid = dict(rec, **{field: wrong})
            self.assertFalse(rel.known_ig_incident(item, invalid))

    def test_recovered_media_requires_original_attempt_timestamp_and_unique_id(self):
        with patch.object(rel.history, "now_utc",
                          return_value=datetime(2026, 11, 10, 19, tzinfo=timezone.utc)):
            valid = [{"id": "18000000000000001", "caption": "x",
                      "timestamp": "2026-11-10T18:24:00+00:00"}]
            self.assertEqual(rel.verified_incident_media(valid, "x"), valid)
            with self.assertRaisesRegex(RuntimeError, "outside_original_attempt"):
                rel.verified_incident_media([dict(valid[0],
                    timestamp="2026-11-09T18:24:00+00:00")], "x")
            with self.assertRaisesRegex(RuntimeError, "ambiguous_original_caption"):
                rel.verified_incident_media(valid + valid, "x")

    def test_existing_finished_container_publishes_only_once_with_durable_intent(self):
        item, ledger, ig = self.recovery_ledger()
        snapshots = []
        def rows(page, platform):
            if platform == "facebook":
                return [{"id": rel.RECOVERY_FB_ID, "description": "exact caption"}]
            return []
        def resume(page, container, before_publish):
            self.assertEqual(container, rel.RECOVERY_CONTAINER)
            self.assertEqual(ig["status"], "resume_reserved")
            before_publish()
            self.assertEqual(ig["status"], "resume_publish_attempted")
            self.assertEqual(snapshots[-1]["records"][rel.record_key(item, "instagram")]["status"],
                             "resume_publish_attempted")
            return "18033333333333333"
        plan = {"platforms": ["instagram"]}
        with patch.object(rel, "pinned_container_status", return_value="FINISHED"), \
             patch.object(rel.history, "save", side_effect=lambda path, data: snapshots.append(copy.deepcopy(data))), \
             patch.object(rel.history, "now_utc",
                          return_value=datetime(2026, 11, 10, 19, tzinfo=timezone.utc)):
            rel.finish_existing_container({"page_id": "1298191963387372"}, item,
                   plan, ledger, "500", resume_fn=resume, rows_fn=rows, verify_fn=Mock(return_value=True))
        self.assertEqual(ig["status"], "verified")
        self.assertEqual(ig["post_id"], "18033333333333333")
        self.assertEqual(ig["resume_publish_run_id"], "500")

    def test_unfinished_original_container_never_invokes_publish(self):
        item, ledger, ig = self.recovery_ledger()
        with patch.object(rel, "pinned_container_status", return_value="IN_PROGRESS"), \
             patch.object(rel.history, "save", Mock()):
            writer = Mock()
            rel.finish_existing_container({"page_id": "1298191963387372"},
                   item, {"platforms": ["instagram"]}, ledger, "500",
                   resume_fn=writer,
                   rows_fn=lambda page, platform: [{"id": rel.RECOVERY_FB_ID,
                       "description": "exact caption"}] if platform == "facebook" else [],
                   verify_fn=Mock())
            writer.assert_not_called()
            self.assertEqual(ig["status"], "attempted")

    def test_duplicate_caption_holds_even_if_previous_id_absent(self):
        with self.assertRaises(RuntimeError):
            rel.validate_remote([{"id": "101", "caption": "x"}], "x", None)
        with self.assertRaises(RuntimeError):
            rel.validate_remote([{"id": "101", "caption": "x"}], "x", {"post_id": "102"})
        self.assertEqual(len(rel.validate_remote([{"id": "101", "caption": "x"}], "x",
                                                 {"post_id": "101"})), 1)


if __name__ == "__main__":
    unittest.main()
