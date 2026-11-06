"""No-network acceptance tests for independent YouTube accepted-upload checks."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import youtube_accepted_audit as audit


def entry(**kwargs):
    return {
        "status": "accepted",
        "route": "gonle",
        "post_id": "lH7bsyAdI5A",
        "channel_id": "UCvSvo5WghuXqsjwLRmIz22g",
        **kwargs,
    }


class AcceptedReadOnlyTests(unittest.TestCase):
    def test_held_unavailable_id_remains_in_independent_audit(self):
        state = {'schema': 1, 'youtube_entries': {'tarladaki:source': entry(
            status='held', verification_status='video_unavailable')}}
        before = json.dumps(state)
        result = audit.audit(state, verifier=lambda _: 'youtube_video_unavailable')
        self.assertEqual(result['held_checked'], 1)
        self.assertEqual(result['unverified'], 1)
        self.assertEqual(result['status'], 'pending_confirmation')
        self.assertEqual(json.dumps(state), before)

    def test_exact_public_processed_id_and_channel_are_required(self):
        youtube = Mock()
        youtube.videos().list().execute.return_value = {
            "items": [{"id": "lH7bsyAdI5A",
                       "snippet": {"channelId": "UCvSvo5WghuXqsjwLRmIz22g"},
                       "status": {"privacyStatus": "public", "uploadStatus": "processed"}}]}
        factory = Mock(return_value=youtube)
        checker = Mock(return_value={
            "status": "verified", "channel_id": "UCvSvo5WghuXqsjwLRmIz22g"})
        with patch.dict("os.environ", {"TOKEN_GONLE_DUSEN_JSON": '{"test":"mock"}'}), \
             patch.object(audit.Credentials, "from_authorized_user_info", return_value=Mock()):
            result = audit.verify_accepted(entry(), channel_check=checker, youtube_build=factory)
        self.assertEqual(result, "public_processed_verified")
        youtube.videos().insert.assert_not_called()
        youtube.videos().update.assert_not_called()
        youtube.videos().delete.assert_not_called()
        self.assertEqual(youtube.videos().list.call_args.kwargs["id"], "lH7bsyAdI5A")

    def test_wrong_binding_never_calls_google(self):
        checker, builder = Mock(), Mock()
        bad = entry()
        bad["channel_id"] = "wrong"
        result = audit.verify_accepted(bad, channel_check=checker, youtube_build=builder)
        self.assertEqual(result, "channel_binding_mismatch")
        checker.assert_not_called()
        builder.assert_not_called()

    def test_uploading_not_claimed_public(self):
        youtube = Mock()
        youtube.videos().list().execute.return_value = {
            "items": [{"id": "lH7bsyAdI5A",
                       "snippet": {"channelId": "UCvSvo5WghuXqsjwLRmIz22g"},
                       "status": {"privacyStatus": "public", "uploadStatus": "uploaded"}}]}
        with patch.dict("os.environ", {"TOKEN_GONLE_DUSEN_JSON": '{"test":"mock"}'}), \
             patch.object(audit.Credentials, "from_authorized_user_info", return_value=Mock()):
            reason = audit.verify_accepted(
                entry(), channel_check=lambda _: {
                    "status": "verified", "channel_id": "UCvSvo5WghuXqsjwLRmIz22g"},
                youtube_build=lambda *args, **kwargs: youtube)
        self.assertEqual(reason, "youtube_processing_or_visibility_pending")
        youtube.videos().insert.assert_not_called()

    def test_audit_does_not_mark_accepted_entry_done(self):
        state = {"schema": 1, "youtube_entries": {
            "gonle:source": entry(),
            "penguen:old": {"status": "done", "post_id": "IlhxRG1QnjU"}}}
        copy = json.loads(json.dumps(state))
        result = audit.audit(state, verifier=lambda _: "public_processed_verified")
        self.assertEqual(result["accepted_checked"], 1)
        self.assertEqual(result["public_processed_verified"], 1)
        self.assertEqual(result["uploads_attempted"], 0)
        self.assertFalse(result["publication_state_modified"])
        self.assertEqual(state, copy)

    def test_unavailable_state_fails_closed_without_leaking_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(audit, "REPORT", Path(tmp) / "report.json"), \
             patch.dict("os.environ", {"GITHUB_REPOSITORY": audit.REPO}), \
             patch.object(audit, "load_archived_state",
                          side_effect=RuntimeError("secret-bearing provider data")):
            self.assertEqual(audit.main(), 1)
            receipt = (Path(tmp) / "report.json").read_text()
        self.assertIn("archived_state_unavailable", receipt)
        self.assertNotIn("secret-bearing", receipt)

    def test_unknown_route_and_missing_video_id_never_contact_google(self):
        builder = Mock()
        self.assertEqual(audit.verify_accepted({"route": "bad", "post_id": "lH7bsyAdI5A"},
                                               youtube_build=builder), "invalid_archived_identity")
        self.assertEqual(audit.verify_accepted({"route": "gonle", "post_id": None},
                                               youtube_build=builder), "invalid_archived_identity")
        builder.assert_not_called()


class UncertainSourceReadOnlyTests(unittest.TestCase):
    key = "gonle:source_275"
    marker = "[avp-source:gonle:source_275]"

    def uncertain(self, **changes):
        row = entry(status="uncertain", source_id="source_275")
        del row["post_id"]
        return dict(row, **changes)

    def playlist_row(self, post_id="lH7bsyAdI5A", description=None):
        return {"snippet": {"title": "275", "description": self.marker if description is None else description,
                            "resourceId": {"videoId": post_id}}}

    def youtube(self, pages=None):
        youtube = Mock()
        youtube.channels().list().execute.return_value = {"items": [{
            "id": "UCvSvo5WghuXqsjwLRmIz22g",
            "contentDetails": {"relatedPlaylists": {"uploads": "uploads-playlist"}}}]}
        youtube.playlistItems().list().execute.side_effect = pages or [
            {"items": [self.playlist_row()]}]
        youtube.videos().list().execute.return_value = {"items": [{
            "id": "lH7bsyAdI5A",
            "snippet": {"channelId": "UCvSvo5WghuXqsjwLRmIz22g", "description": self.marker},
            "status": {"privacyStatus": "public", "uploadStatus": "processed"}}]}
        return youtube

    def run_probe(self, youtube, row=None, key=None):
        with patch.dict("os.environ", {"TOKEN_GONLE_DUSEN_JSON": '{"test":"mock"}'}), \
             patch.object(audit.Credentials, "from_authorized_user_info", return_value=Mock()):
            result = audit.verify_uncertain(
                self.key if key is None else key,
                self.uncertain() if row is None else row,
                channel_check=lambda _: {"status": "verified", "channel_id": "UCvSvo5WghuXqsjwLRmIz22g"},
                youtube_build=lambda *args, **kwargs: youtube)
        for resource in (youtube.channels(), youtube.playlistItems(), youtube.videos()):
            resource.insert.assert_not_called()
            resource.update.assert_not_called()
            resource.delete.assert_not_called()
        return result

    def test_unique_exact_marker_is_reported_after_complete_history_and_video_get(self):
        youtube = self.youtube([
            {"items": [self.playlist_row()], "nextPageToken": "next"},
            {"items": []}])
        result = self.run_probe(youtube)
        self.assertEqual(result["status"], "uncertain_marker_public_processed_verified")
        self.assertEqual(result["video_id"], "lH7bsyAdI5A")
        self.assertTrue(result["requires_reconciliation"])
        self.assertEqual(youtube.playlistItems().list.call_args.kwargs["pageToken"], "next")
        self.assertEqual(youtube.videos().list.call_args.kwargs["id"], "lH7bsyAdI5A")
        self.assertEqual(youtube.channels().list.call_args.kwargs, {"part": "contentDetails", "mine": True})

    def test_duplicate_markers_across_pages_remain_ambiguous(self):
        youtube = self.youtube([
            {"items": [self.playlist_row()], "nextPageToken": "next"},
            {"items": [self.playlist_row("abcdefghijk")]}])
        result = self.run_probe(youtube)
        self.assertEqual(result["status"], "uncertain_marker_ambiguous")
        self.assertIsNone(result["video_id"])
        youtube.videos().list().execute.assert_not_called()

    def test_title_and_partial_markers_never_prove_source(self):
        for description in ("same title only", self.marker + "suffix",
                            "prefix" + self.marker, "[avp-source:gonle:source_275_extra]"):
            youtube = self.youtube([{"items": [self.playlist_row(description=description)]}])
            result = self.run_probe(youtube)
            self.assertEqual(result["status"], "uncertain_marker_not_found")
            youtube.videos().list().execute.assert_not_called()

    def test_incomplete_or_malformed_history_never_confirms_found_marker(self):
        cases = [
            ([{"items": [self.playlist_row()], "nextPageToken": "same"},
              {"items": [], "nextPageToken": "same"}], "youtube_upload_history_incomplete"),
            ([{"items": [self.playlist_row()], "nextPageToken": {"bad": "token"}}],
             "youtube_upload_history_incomplete"),
            ([{"items": [self.playlist_row()], "nextPageToken": "more"},
              {"items": [], "nextPageToken": "still-more"}], "youtube_upload_history_incomplete"),
            ([{"unexpected": []}], "youtube_upload_history_invalid"),
            ([{"items": [None]}], "youtube_upload_history_invalid"),
        ]
        for pages, expected in cases:
            with self.subTest(pages=pages), patch.object(audit, "MAX_UPLOAD_PAGES", 2):
                youtube = self.youtube(pages)
                self.assertEqual(self.run_probe(youtube)["status"], expected)
                youtube.videos().list().execute.assert_not_called()

    def test_video_identity_marker_and_visibility_are_checked_independently(self):
        cases = [
            ({"id": "abcdefghijk"}, None, "youtube_source_identity_mismatch"),
            (None, {"channelId": "other", "description": self.marker}, "youtube_source_identity_mismatch"),
            (None, {"channelId": "UCvSvo5WghuXqsjwLRmIz22g", "description": "no marker"},
             "youtube_source_identity_mismatch"),
        ]
        for change, snippet, expected in cases:
            youtube = self.youtube()
            payload = youtube.videos().list().execute.return_value
            if change:
                payload["items"][0].update(change)
            if snippet:
                payload["items"][0]["snippet"] = snippet
            self.assertEqual(self.run_probe(youtube)["status"], expected)
        for status, expected in [
            ({"privacyStatus": "private", "uploadStatus": "processed"},
             "uncertain_marker_processing_or_visibility_pending"),
            ({"privacyStatus": "public", "uploadStatus": "uploaded"},
             "uncertain_marker_processing_or_visibility_pending"),
            ({"privacyStatus": "public", "uploadStatus": "rejected"}, "youtube_upload_rejected"),
        ]:
            youtube = self.youtube()
            youtube.videos().list().execute.return_value["items"][0]["status"] = status
            self.assertEqual(self.run_probe(youtube)["status"], expected)

    def test_bad_source_binding_never_contacts_google(self):
        for key, changes in [
            ("gonle:other", {}), (self.key, {"source_id": "other"}),
            (self.key, {"channel_id": "other"}), (self.key, {"status": "done"}),
            (self.key, {"post_id": "lH7bsyAdI5A"}),
        ]:
            checker, builder = Mock(), Mock()
            audit.verify_uncertain(key, self.uncertain(**changes), channel_check=checker, youtube_build=builder)
            checker.assert_not_called()
            builder.assert_not_called()

    def test_read_errors_are_redacted_and_leave_source_unresolved(self):
        youtube = self.youtube([RuntimeError("private OAuth provider payload")])
        result = self.run_probe(youtube)
        self.assertEqual(result["status"], "youtube_read_or_auth_failed")
        self.assertNotIn("private OAuth", json.dumps(result))

    def test_corrupt_ledger_key_is_not_echoed_or_sent_to_google(self):
        builder = Mock()
        row = self.uncertain(source_id="secret-bearing invalid source")
        state = {"schema": 1, "youtube_entries": {"secret-bearing corrupt key": row}}
        result = audit.audit(state, uncertain_verifier=lambda key, entry: audit.verify_uncertain(
            key, entry, youtube_build=builder))
        builder.assert_not_called()
        self.assertIsNone(result["posts"][0]["ledger_key"])
        self.assertIsNone(result["posts"][0]["source_id"])
        self.assertNotIn("secret-bearing", json.dumps(result))

    def test_audit_exposes_uncertain_source_binding_without_releasing_or_hiding_it(self):
        state = {"schema": 1, "youtube_entries": {self.key: self.uncertain()}}
        before = json.loads(json.dumps(state))
        result = audit.audit(state, uncertain_verifier=lambda key, entry: {
            "status": "uncertain_marker_public_processed_verified", "video_id": "lH7bsyAdI5A",
            "requires_reconciliation": True})
        self.assertEqual(state, before)
        self.assertEqual(result["status"], "pending_confirmation")
        self.assertEqual(result["accepted_checked"], 0)
        self.assertEqual(result["held_checked"], 0)
        self.assertEqual(result["uncertain_checked"], 1)
        self.assertEqual(result["uncertain_marker_public_processed_verified"], 1)
        self.assertEqual(result["public_processed_verified"], 0)
        self.assertEqual(result["unverified"], 1)
        self.assertEqual(result["posts"][0]["ledger_key"], self.key)
        self.assertEqual(result["posts"][0]["source_id"], "source_275")
        self.assertEqual(result["uploads_attempted"], 0)
        self.assertFalse(result["publication_state_modified"])


if __name__ == "__main__":
    unittest.main()
