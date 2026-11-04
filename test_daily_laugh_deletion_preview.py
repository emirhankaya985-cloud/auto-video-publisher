import json
from unittest import TestCase
from unittest.mock import Mock, patch

import daily_laugh_deletion_preview as preview


class DailyLaughDeletionPreviewTests(TestCase):
    def test_cursor_rebuilds_fixed_endpoint_and_deduplicates_ids(self):
        get = Mock(side_effect=[
            {"data": [{"id": "101"}], "paging": {"next": "https://untrusted.invalid/secret",
                                                "cursors": {"after": "cursor"}}},
            {"data": [{"id": "101"}, {"id": "102"}]},
        ])
        rows = preview.graph_edge(get, "123/media", "id")
        self.assertEqual(preview.id_summary([row["id"] for row in rows], str.isdecimal)["count"], 2)
        self.assertEqual(get.call_args.args, ("123/media",))
        self.assertEqual(get.call_args.kwargs["after"], "cursor")

    def test_repeated_cursor_cannot_produce_complete_inventory(self):
        body = {"data": [], "paging": {"next": "url", "cursors": {"after": "repeat"}}}
        fetch = Mock(return_value=body)
        result = preview.checked(lambda: preview.list_all(fetch, graph=True))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["reason"], "inventory_pagination_incomplete")
        self.assertEqual(fetch.call_count, 2)

    def test_facebook_checks_owner_and_keeps_edge_counts_separate(self):
        get = Mock(side_effect=[
            {"data": [{"id": "123_17", "from": {"id": "123"}}]},
            {"data": [{"id": "17", "from": {"id": "123"}}]},
        ])
        result = preview.facebook({"page_id": "123"}, get)
        self.assertTrue(result["edge_counts_may_overlap"])
        self.assertEqual(result["published_posts"]["count"], 1)
        self.assertEqual(result["page_videos"]["count"], 1)
        self.assertNotIn("123_17", json.dumps(result))
        get = Mock(side_effect=[
            {"data": [{"id": "999_17", "from": {"id": "999"}}]},
            {"data": [{"id": "17", "from": {"id": "123"}}]},
        ])
        result = preview.facebook({"page_id": "123"}, get)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["published_posts"]["reason"], "facebook_content_owner_unverified")
        self.assertEqual(result["page_videos"]["count"], 1)

    def test_youtube_hides_nonpublic_ids_and_verifies_ownership(self):
        channel_id = preview.TARGETS["daily_laugh"][2]
        private_id, public_id = "private1234", "public56789"
        api = Mock(side_effect=[
            {"items": [{"id": channel_id, "contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]},
            {"items": [{"contentDetails": {"videoId": identifier}} for identifier in [private_id, public_id]]},
            {"items": [
                {"id": private_id, "snippet": {"channelId": channel_id}, "status": {"privacyStatus": "private"}},
                {"id": public_id, "snippet": {"channelId": channel_id}, "status": {"privacyStatus": "public"}},
            ]},
        ])
        scope = "https://www.googleapis.com/auth/youtube.upload"
        with patch.dict(preview.os.environ, {"TOKEN_DAILY_LAUGH_LAB_JSON": json.dumps({"scopes": [scope]})}), \
             patch.object(preview.Credentials, "from_authorized_user_info"), \
             patch.object(preview, "AuthorizedSession"), patch.object(preview, "read_json", api):
            result = preview.youtube()
        self.assertEqual(result["visibility"], {"public": 1, "unlisted": 0, "private": 1})
        self.assertFalse(result["delete_scope_declared"])
        self.assertNotIn(private_id, json.dumps(result))
        self.assertNotIn(public_id, json.dumps(result))
        self.assertNotIn(scope, json.dumps(result))
