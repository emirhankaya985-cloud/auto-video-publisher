import os
import unittest
from unittest.mock import Mock, patch

import connection_audit as audit
import scheduled_multi_publisher as publisher
from publication_safety import platform_allowed, route_paused, batch_exception_allowed


class PreflightTests(unittest.TestCase):
    def test_meta_numeric_error_is_preserved_without_response_text(self):
        response = Mock(ok=False, status_code=401)
        response.json.return_value = {"error": {"code": 190, "error_subcode": 460, "type": "OAuthException", "message": "private-response-text"}}
        with patch.object(audit.requests, "get", return_value=response):
            with self.assertRaises(audit.AuditError) as error:
                audit.graph_get("page-id", "synthetic-test-token")
        safe = audit.safe_error(error.exception)
        self.assertEqual(safe["code"], 190)
        self.assertEqual(safe["subcode"], 460)
        self.assertNotIn("private-response-text", str(safe))

    def run_audit(self, *, wrong_channel=False, wrong_parent=False, uploads=None, properties=None):
        spec = audit.NEW_CHANNELS[0]
        route, secret, channel_id, folder_env, folder_id, file_id, filename = spec
        drive, yt = Mock(), Mock()
        video = {"id": file_id, "name": filename, "parents": ["wrong" if wrong_parent else folder_id], "appProperties": properties or {}}
        drive.files.return_value.get.return_value.execute.return_value = video
        drive.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "txt", "parents": [folder_id]}]}
        scopes = {"https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"}
        with patch.dict(os.environ, {folder_env: folder_id}, clear=True), patch.object(audit, "NEW_CHANNELS", (spec,)), patch.object(audit, "google_client", side_effect=[(drive, set()), (yt, scopes)]), patch.object(audit, "youtube_history", return_value=({"id": "wrong" if wrong_channel else channel_id}, uploads or [])):
            result = audit.new_youtube_preflight()[0]
        drive.files.return_value.update.assert_not_called()
        drive.files.return_value.create.assert_not_called()
        yt.videos.assert_not_called()
        return result

    def test_exact_channel_and_source_pass_without_writes(self):
        self.assertEqual(self.run_audit()["dry_run"], "passed")

    def test_wrong_channel_blocks(self):
        self.assertEqual(self.run_audit(wrong_channel=True)["audit_error"], "channel_identity_mismatch")

    def test_wrong_drive_parent_blocks(self):
        self.assertEqual(self.run_audit(wrong_parent=True)["dry_run"], "blocked")

    def test_existing_uploads_require_reconciliation(self):
        self.assertEqual(self.run_audit(uploads=["prior-video"])["audit_error"], "nonempty_channel_history_requires_reconciliation")

    def test_uncertain_drive_intent_blocks_new_youtube(self):
        self.assertEqual(self.run_audit(properties={"intent_yt_daily_slot": "earlier-slot"})["dry_run"], "blocked")

    def test_original_filename_matching_is_not_title_matching(self):
        # Preflight is fail-closed for every nonempty history, including similarly named uploads.
        self.assertNotEqual(self.run_audit(uploads=["916"])["dry_run"], "passed")


class PublicationGuardTests(unittest.TestCase):
    def test_gonle_instagram_cannot_use_batch_exception(self):
        with patch.dict(os.environ, {"BATCH_ID": "b", "BATCH_API_URL": "https://example.test", "BATCH_API_TOKEN": "test", "BATCH_ALLOWED_ROUTES": "gonle"}, clear=True):
            self.assertTrue(route_paused("gonle_ig"))
            self.assertFalse(batch_exception_allowed("gonle_ig"))
        self.assertTrue(platform_allowed("gonle", "instagram"))
        self.assertTrue(platform_allowed("gonle", "facebook"))

    def test_new_youtube_history_never_recycles_or_crosses_channels(self):
        for prop in ("daily_laugh_youtube_used", "result_yt_daily", "intent_yt_daily_slot", "done_yt_daily_slot", "claimed_route_slot"):
            with self.subTest(prop=prop):
                self.assertFalse(publisher.new_youtube_candidate_unused("daily_laugh_youtube", {"appProperties": {prop: "1"}}))
        self.assertTrue(publisher.new_youtube_candidate_unused("daily_laugh_youtube", {"appProperties": {"result_fb": "existing-facebook-post"}}))

    def test_forced_used_video_returns_before_drive_claim_or_upload(self):
        drive = Mock()
        pair = ("916", {"id": "v", "appProperties": {"result_yt_daily": "prior"}}, {"id": "txt"})
        env = {"GITHUB_ACTIONS": "true", "ENABLE_NEW_YOUTUBE_ROUTES": "true", "DAILY_LAUGH_DRIVE_FOLDER_ID": "folder", "FORCE_STEM": "916"}
        with patch.dict(os.environ, env, clear=True), patch.object(publisher, "list_pairs", return_value=([pair[1]], [pair])), patch.object(publisher, "upload_youtube_shorts") as upload:
            publisher.run(drive=drive, selected=("daily_laugh_youtube", "new-slot"), routing_validated=True)
        drive.files.assert_not_called()
        upload.assert_not_called()

    def test_gonle_combined_route_only_schedules_facebook(self):
        drive = Mock()
        pair = ("141", {"id": "v", "appProperties": {}}, {"id": "txt"})
        downloader = Mock()
        downloader.return_value.next_chunk.return_value = (None, True)
        env = {"GITHUB_ACTIONS": "true", "GONLE_DUSEN_DRIVE_FOLDER_ID": "folder", "ENABLE_GONLE_NORMAL_ROUTES": "true", "ENABLE_GONLE_INSTAGRAM_ROUTES": "true"}
        with patch.dict(os.environ, env, clear=True), patch.object(publisher, "list_pairs", return_value=([pair[1]], [pair])), patch.object(publisher, "select_random_unused", return_value=pair), patch.object(publisher, "verify_file_in_folder"), patch.object(publisher.io, "FileIO"), patch.object(publisher, "MediaIoBaseDownload", downloader), patch.object(publisher.Path, "mkdir"), patch.object(publisher.Path, "read_text", return_value="Caption"), patch.object(publisher, "notify"), patch.object(publisher, "execute_platform_jobs", return_value=({"fb": "confirmed"}, {})) as execute:
            publisher.run(drive=drive, selected=("gonle", "slot"), routing_validated=True)
        self.assertEqual(execute.call_args.args[3], ["fb", "ig"])


if __name__ == "__main__":
    unittest.main()
