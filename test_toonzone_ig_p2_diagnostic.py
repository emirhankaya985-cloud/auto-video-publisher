"""Fail-closed tests: ToonZone ambiguity probe makes no write requests."""
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock

import toonzone_ig_p2_diagnostic as m
from publisher_alert_history import identity

NOW = datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc)
PAGE = {"page_id": "1298191963387372", "instagram_id": m.EXPECTED_IG}


def state():
    a = {"schema": 1, "records": {}}
    for platform in ("facebook", "instagram"):
        key = identity(m.CAMPAIGN, "toonzone", platform, m.TARGET_SOURCE)
        row = {"source_id": m.TARGET_SOURCE, "route": "toonzone",
               "platform": platform, "file": m.TARGET_FILE,
               "intent_run_id": m.TARGET_RUN, "caption": "Exact pinned caption",
               "status": "accepted_unverified" if platform == "facebook" else "attempted",
               "last_seen": "2026-11-10T18:25:48+00:00"}
        if platform == "facebook":
            row["post_id"] = m.TARGET_FACEBOOK_ID
        a["records"][key] = row
    return a


def rows(page, platform):
    if platform == "facebook":
        return [{"id": m.TARGET_FACEBOOK_ID, "description": "Exact pinned caption",
                 "created_time": "2026-11-10T18:22:21+00:00"}]
    return []


class ReadOnlyTest(unittest.TestCase):
    def test_finished_container_reports_resumable_without_posts(self):
        get = Mock(return_value={"id": m.TARGET_CONTAINER, "status_code": "FINISHED"})
        result = m.inspect(state(), PAGE, rows, get, now=NOW)
        self.assertEqual(result["posts_created"], 0)
        self.assertTrue(result["facebook"]["archived_id_matches"])
        self.assertEqual(result["instagram"]["remote_exact_caption_matches"], 0)
        self.assertTrue(result["container"]["existing_container_ready_for_guarded_resumption"])
        get.assert_called_once_with(PAGE, m.TARGET_CONTAINER)

    def test_processing_container_never_allows_resumption(self):
        for status in ("ERROR", "EXPIRED", "IN_PROGRESS"):
            with self.subTest(status=status):
                result = m.inspect(state(), PAGE, rows,
                    Mock(return_value={"id": m.TARGET_CONTAINER, "status_code": status}), now=NOW)
                self.assertFalse(result["container"]["existing_container_ready_for_guarded_resumption"])

    def test_existing_instagram_media_is_not_ready_to_repost(self):
        def with_ig(page, platform):
            if platform == "facebook":
                return rows(page, platform)
            return [{"id": "18010000000000000", "caption": "Exact pinned caption",
                     "timestamp": "2026-11-10T18:25:12+00:00"}]
        result = m.inspect(state(), PAGE, with_ig,
            Mock(return_value={"status_code": "FINISHED"}), now=NOW)
        self.assertFalse(result["container"]["existing_container_ready_for_guarded_resumption"])
        self.assertEqual(result["instagram"]["remote_exact_caption_matches"], 1)

    def test_wrong_campaign_or_page_fails_closed(self):
        for changed in ({"page_id": "3", "instagram_id": m.EXPECTED_IG},
                        {"page_id": PAGE["page_id"], "instagram_id": "999"}):
            with self.assertRaisesRegex(RuntimeError, "identity_unverified"):
                m.inspect(state(), changed, rows, Mock(), now=NOW)
        state2 = state()
        state2["records"].pop(next(iter(state2["records"])))
        with self.assertRaisesRegex(RuntimeError, "exact_original_intent_not_found"):
            m.inspect(state2, PAGE, rows, Mock(), now=NOW)

    def test_no_synthetic_post_from_mismatched_caption_or_old_media(self):
        def wrong_caption(page, platform):
            return [{"id": m.TARGET_FACEBOOK_ID, "description": "Other caption",
                     "created_time": "2026-11-10T18:23:00+00:00"}] if platform == "facebook" else []
        result = m.inspect(state(), PAGE, wrong_caption,
                           Mock(return_value={"status_code": "IN_PROGRESS"}), now=NOW)
        self.assertIsNone(result["facebook"]["provider_post_id_verified"])
        def old(page, platform):
            return [{"id": m.TARGET_FACEBOOK_ID, "description": "Exact pinned caption",
                     "created_time": "2026-11-09T18:23:00+00:00"}] if platform == "facebook" else []
        with self.assertRaisesRegex(RuntimeError, "outside_original_attempt"):
            m.inspect(state(), PAGE, old, Mock(), now=NOW)


if __name__ == "__main__":
    unittest.main()
