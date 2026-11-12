"""Regression checks: archive, prior Meta POST or publisher state never reset."""
import unittest
import copy
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import toonzone_relaunch as rel


class RelaunchSafetyTests(unittest.TestCase):
    def test_manual_dispatch_required_while_sequence_conflicts_with_verified_history(self):
        from pathlib import Path
        workflow = Path(".github/workflows/toonzone_relaunch.yml").read_text(encoding="utf-8")
        self.assertIn("Automatic relaunch is paused while the owner-provided sequence conflicts with live Meta history.", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotRegex(workflow, r"(?m)^\\s+schedule:")
        self.assertIn("group: toonzone-relaunch-s01e04", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("github.run_attempt == 1", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("Verify exact owner relaunch marker and Meta identity; reserve only next part", workflow)
        self.assertIn("Persist intent BEFORE any external Meta write", workflow)
        self.assertIn("Publish only reserved next part on Facebook and Instagram", workflow)

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

    def test_readonly_exact_facebook_receipt_never_reposts(self):
        from datetime import datetime, timezone
        page = {"page_id": "1298191963387372", "page_token": "unit-test-only"}
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "id": "1234567", "description": "original caption",
            "from": {"id": page["page_id"]}, "length": 175,
            "created_time": datetime.now(timezone.utc).isoformat()}
        with patch("publisher_recovery.read_with_retry", return_value=response) as read, \
             patch("requests.post") as post:
            self.assertTrue(rel.exact_original_facebook_video(
                page, "1234567", "original caption"))
            self.assertEqual(read.call_count, 1)
            post.assert_not_called()
        for changed in (
            dict(response.json.return_value, id="7654321"),
            dict(response.json.return_value, description="other caption"),
            dict(response.json.return_value, **{"from": {"id": "different"}}),
            dict(response.json.return_value, length=0),
        ):
            rejected = Mock()
            rejected.status_code = 200
            rejected.json.return_value = changed
            with patch("publisher_recovery.read_with_retry", return_value=rejected):
                self.assertFalse(rel.exact_original_facebook_video(
                    page, "1234567", "original caption"))

    def test_unlisted_facebook_is_held_until_exact_id_owner_proven(self):
        row = {"status": "accepted_unverified", "post_id": "1234567"}
        self.assertEqual(rel.state_for(row, []), "held_remote_id_unverified")
        self.assertEqual(rel.state_for(row, [], exact_provider_verified=True), "verified")
        self.assertEqual(rel.state_for({"status": "attempted"}, [],
                       exact_provider_verified=True), "held_previous_attempt_or_reservation")
        with patch("public_link_runtime.graph_rows", return_value=[]), \
             patch.object(rel.time, "sleep"), \
             patch.object(rel, "exact_original_facebook_video", return_value=True) as get:
            self.assertTrue(rel.verify_post({"page_id": "1298191963387372"},
                            "facebook", "1234567", "original caption"))
            get.assert_called_once()
        with patch("public_link_runtime.graph_rows", return_value=[]), \
             patch.object(rel.time, "sleep"), \
             patch.object(rel, "exact_original_facebook_video", return_value=False):
            self.assertFalse(rel.verify_post({"page_id": "1298191963387372"},
                             "facebook", "1234567", "original caption"))

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

    def test_replacement_guard_requires_age_exact_original_and_owner_marker(self):
        item, ledger, ig = self.recovery_ledger()
        ig["status"] = "attempted"
        marker = rel.RECOVERY_REPLACEMENT_MARKER
        now = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)
        self.assertTrue(rel.replacement_allowed(item, ig, "IN_PROGRESS",
                                                now=now, marker_text=marker))
        self.assertFalse(rel.replacement_allowed(item, ig, "IN_PROGRESS",
            now=datetime(2026, 11, 10, 19, tzinfo=timezone.utc), marker_text=marker))
        self.assertFalse(rel.replacement_allowed(item, ig, "FINISHED", now=now, marker_text=marker))
        self.assertFalse(rel.replacement_allowed(item, ig, "IN_PROGRESS", now=now, marker_text=""))
        for field, value in (("replacement_run_id", "old"), ("post_id", "123")):
            changed = dict(ig, **{field: value})
            self.assertFalse(rel.replacement_allowed(item, changed, "IN_PROGRESS",
                now=now, marker_text=marker))
        ig["status"] = "replacement_upload_attempted"
        self.assertFalse(rel.replacement_allowed(item, ig, "IN_PROGRESS",
            now=now, marker_text=marker))

    def replacement_case(self):
        item, ledger, ig = self.recovery_ledger()
        ig.update(status="replacement_reserved", replacement_run_id="500",
                  replacement_original_container_id=rel.RECOVERY_CONTAINER)
        plan = {"mode": "replace_stalled_container", "platforms": ["instagram"],
                "text": "exact caption", "cover_id": rel.RECOVERY_COVER,
                "source_sha256": rel.RECOVERY_SOURCE_SHA,
                "cover_sha256": rel.RECOVERY_COVER_SHA}
        def rows(page, platform):
            return ([{"id": rel.RECOVERY_FB_ID, "description": "exact caption"}]
                    if platform == "facebook" else [])
        def digest(p):
            return (rel.RECOVERY_SOURCE_SHA if p.name == "source.mp4"
                    else rel.RECOVERY_COVER_SHA)
        dependencies = {
            "rows_fn": rows, "status_fn": Mock(return_value="IN_PROGRESS"),
            "source_fn": lambda _id, p: p,
            "cover_fn": lambda _id, p: p,
            "cover_video_fn": lambda src, cover, p, **kw: p,
            "prepare_fn": lambda inp, out, **kw: out,
            "cover_check_fn": Mock(return_value=True), "png_check_fn": Mock(),
            "digest_fn": digest, "verifier": Mock(return_value=True)
        }
        return item, ledger, ig, plan, dependencies

    def test_replacement_upload_once_only_after_persisted_intent(self):
        item, ledger, ig, plan, dependencies = self.replacement_case()
        snapshots = []
        def uploader(page, video_path, caption, **kw):
            self.assertEqual(ig["status"], "replacement_upload_attempted")
            self.assertEqual(snapshots[-1]["records"][rel.record_key(item, "instagram")]["status"],
                             "replacement_upload_attempted")
            self.assertEqual(kw["forbidden_container_ids"], {rel.RECOVERY_CONTAINER})
            self.assertFalse(kw["append_store_link"])
            self.assertEqual(kw["thumb_offset"], 0)
            return "18012345678998765"
        dependencies["uploader"] = Mock(side_effect=uploader)
        with patch.object(rel.history, "save",
                          side_effect=lambda p, data: snapshots.append(copy.deepcopy(data))), \
             patch.object(rel.history, "now_utc",
                          return_value=datetime(2026, 11, 10, 20, tzinfo=timezone.utc)):
            rel.finish_stalled_replacement({"page_id": "1298191963387372"}, item,
                plan, ledger, "500", **dependencies)
        dependencies["uploader"].assert_called_once()
        self.assertEqual(ig["status"], "verified")
        self.assertEqual(ig["post_id"], "18012345678998765")
        self.assertEqual(ig["replacement_run_id"], "500")

    def test_replacement_cancelled_if_old_container_finished_no_upload(self):
        item, ledger, ig, plan, dependencies = self.replacement_case()
        dependencies["status_fn"] = Mock(return_value="FINISHED")
        dependencies["uploader"] = Mock()
        with patch.object(rel.history, "save", Mock()):
            rel.finish_stalled_replacement({"page_id": "1298191963387372"}, item,
                plan, ledger, "500", **dependencies)
        dependencies["uploader"].assert_not_called()
        self.assertEqual(ig["status"], "attempted")

    def test_replacement_ambiguous_failure_never_gets_second_write(self):
        item, ledger, ig, plan, dependencies = self.replacement_case()
        class Rejected(Exception):
            container_id = "17922222222222222"
        dependencies["uploader"] = Mock(side_effect=Rejected())
        with patch.object(rel.history, "save", Mock()):
            with self.assertRaisesRegex(RuntimeError, "no_automatic_retry"):
                rel.finish_stalled_replacement({"page_id": "1298191963387372"}, item,
                    plan, ledger, "500", **dependencies)
        self.assertEqual(ig["status"], "replacement_failed_held")
        self.assertEqual(ig["replacement_container_id"], "17922222222222222")
        self.assertFalse(rel.replacement_allowed(item, ig, "IN_PROGRESS",
            now=datetime(2026, 11, 10, 21, tzinfo=timezone.utc),
            marker_text=rel.RECOVERY_REPLACEMENT_MARKER))
        dependencies["uploader"].assert_called_once()

    def e09_case(self):
        item = {"episode": 9, "part": 1, "id": rel.E09_SOURCE, "name": rel.E09_FILE}
        facebook = {"status": "verified", "platform": "facebook",
                    "post_id": rel.E09_FB_ID, "caption": "e09 caption",
                    "last_seen": "2026-11-11T00:09:13+00:00"}
        ig = {"status": "attempted", "platform": "instagram",
              "source_id": rel.E09_SOURCE, "file": rel.E09_FILE,
              "cover_id": rel.E09_COVER, "source_sha256": rel.E09_SOURCE_SHA,
              "cover_sha256": rel.E09_COVER_SHA, "intent_run_id": rel.E09_RUN,
              "error_type": "MetaAPIError", "caption": "e09 caption",
              "last_seen": "2026-11-11T00:12:24+00:00"}
        ledger = {"schema": 1, "records": {
            rel.record_key(item, "facebook"): facebook,
            rel.record_key(item, "instagram"): ig
        }}
        return item, ledger, ig

    def test_e09_replacement_requires_exact_original_and_no_prior_new_write(self):
        item, ledger, ig = self.e09_case()
        self.assertTrue(rel.e09_replacement_allowed(item, ig, rel.E09_MARKER))
        self.assertFalse(rel.e09_replacement_allowed(item, ig, ""))
        self.assertFalse(rel.e09_replacement_allowed(item, dict(ig, post_id="123"), rel.E09_MARKER))
        self.assertFalse(rel.e09_replacement_allowed(item, dict(ig, source_sha256="bad"), rel.E09_MARKER))
        self.assertFalse(rel.e09_replacement_allowed(item, dict(ig, status="replacement_failed_held"), rel.E09_MARKER))
        self.assertFalse(rel.e09_replacement_allowed(item, dict(ig, replacement_run_id="old"), rel.E09_MARKER))

    def test_e09_one_shot_persists_pre_post_intent_and_never_touches_facebook(self):
        item, ledger, ig = self.e09_case()
        ig.update(status="replacement_reserved", replacement_run_id="777",
                  replacement_original_container_id=rel.E09_CONTAINER)
        plan = {"mode": "replace_expired_e09", "platforms": ["instagram"],
                "text": "e09 caption", "cover_id": rel.E09_COVER,
                "source_sha256": rel.E09_SOURCE_SHA,
                "cover_sha256": rel.E09_COVER_SHA}
        snapshots = []
        def rows(page, platform):
            return ([{"id": rel.E09_FB_ID, "description": "e09 caption"}]
                    if platform == "facebook" else [])
        def digest(path):
            return rel.E09_SOURCE_SHA if path.name == "source.mp4" else rel.E09_COVER_SHA
        def uploader(page, video_path, caption, **kwargs):
            self.assertEqual(ig["status"], "replacement_upload_attempted")
            self.assertEqual(snapshots[-1]["records"][rel.record_key(item, "instagram")]["status"],
                             "replacement_upload_attempted")
            self.assertEqual(kwargs["forbidden_container_ids"], {rel.E09_CONTAINER})
            self.assertEqual(kwargs["thumb_offset"], 0)
            return "18055555555555555"
        with patch.object(rel.history, "save", side_effect=lambda p, d: snapshots.append(copy.deepcopy(d))), \
             patch.object(rel.history, "now_utc",
                          return_value=datetime(2026, 11, 12, 15, tzinfo=timezone.utc)):
            rel.finish_expired_e09_replacement(
                {"page_id": "1298191963387372"}, item, plan, ledger, "777",
                rows_fn=rows, status_fn=Mock(return_value="EXPIRED"),
                uploader=Mock(side_effect=uploader), verifier=Mock(return_value=True),
                source_fn=lambda _id, p: p, cover_fn=lambda _id, p: p,
                cover_video_fn=lambda src, cover, p, **kw: p,
                prepare_fn=lambda src, p, **kw: p,
                png_check_fn=Mock(), cover_check_fn=Mock(), digest_fn=digest)
        self.assertEqual(ig["status"], "verified")
        self.assertEqual(ig["post_id"], "18055555555555555")
        self.assertEqual(ledger["records"][rel.record_key(item, "facebook")]["post_id"], rel.E09_FB_ID)

    def test_e09_original_not_expired_never_uploads(self):
        item, ledger, ig = self.e09_case()
        ig.update(status="replacement_reserved", replacement_run_id="777",
                  replacement_original_container_id=rel.E09_CONTAINER)
        plan = {"mode": "replace_expired_e09", "platforms": ["instagram"],
                "text": "e09 caption", "cover_id": rel.E09_COVER,
                "source_sha256": rel.E09_SOURCE_SHA,
                "cover_sha256": rel.E09_COVER_SHA}
        upload = Mock()
        with self.assertRaisesRegex(RuntimeError, "original_not_expired"):
            rel.finish_expired_e09_replacement(
                {"page_id": "1298191963387372"}, item, plan, ledger, "777",
                rows_fn=lambda page, platform: [
                    {"id": rel.E09_FB_ID, "description": "e09 caption"}
                ] if platform == "facebook" else [],
                status_fn=Mock(return_value="IN_PROGRESS"), uploader=upload)
        upload.assert_not_called()

    def test_duplicate_caption_holds_even_if_previous_id_absent(self):
        with self.assertRaises(RuntimeError):
            rel.validate_remote([{"id": "101", "caption": "x"}], "x", None)
        with self.assertRaises(RuntimeError):
            rel.validate_remote([{"id": "101", "caption": "x"}], "x", {"post_id": "102"})
        self.assertEqual(len(rel.validate_remote([{"id": "101", "caption": "x"}], "x",
                                                 {"post_id": "101"})), 1)


if __name__ == "__main__":
    unittest.main()
