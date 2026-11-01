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


if __name__ == "__main__":
    unittest.main()
