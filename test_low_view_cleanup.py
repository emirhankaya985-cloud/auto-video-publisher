import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

from low_view_cleanup import (assess, collect_instagram_snapshot,
                              delete_review_candidates)


NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


class LowViewAssessmentTests(unittest.TestCase):
    def report(self, snapshot):
        return assess(snapshot, NOW.isoformat(), now=NOW, excluded_accounts=set())

    def test_under_48_hours_is_held_even_with_zero_views(self):
        row = {"acct": {"views": 0, "published_at": (NOW - timedelta(hours=47)).isoformat()}}
        result = self.report({("A", "Instagram"): row})
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["held"][0]["reason"], "younger_than_48h")

    def test_48_hours_zero_and_nine_are_review_candidates(self):
        published = (NOW - timedelta(hours=48)).isoformat()
        result = self.report({("A", "Instagram"): {
            "zero": {"views": 0, "published_at": published},
            "nine": {"views": 9, "published_at": published},
        }})
        self.assertEqual({x["content_id"] for x in result["candidates"]}, {"zero", "nine"})
        self.assertTrue(all(x["action"] == "review_only_no_delete" for x in result["candidates"]))
        self.assertFalse(result["deletion_enabled"])

    def test_missing_expected_platform_makes_whole_scan_incomplete_and_holds_rows(self):
        old = (NOW - timedelta(days=3)).isoformat()
        result = assess({("A", "Instagram"): {
            "private-id": {"views": 0, "published_at": old},
        }}, NOW.isoformat(), now=NOW, excluded_accounts=set(),
            expected_sources={("A", "Instagram"), ("B", "Threads")})
        self.assertFalse(result["collection_complete"])
        self.assertEqual(result["candidates"], [])
        self.assertIn(["B", "Threads"], result["missing_sources"])
        self.assertEqual(result["held"][0]["reason"], "collection_incomplete")

    def test_collection_error_and_none_snapshot_never_create_candidate(self):
        old = (NOW - timedelta(days=3)).isoformat()
        result = assess({("A", "Instagram"): {
            "private-id": {"views": 0, "published_at": old},
        }, ("B", "Threads"): None}, NOW.isoformat(), now=NOW,
            excluded_accounts=set(), collection_errors=["B / Threads: identity missing"])
        self.assertFalse(result["collection_complete"])
        self.assertEqual(result["candidates"], [])
        self.assertTrue(any(row["reason"] == "platform_collection_unavailable"
                            for row in result["held"]))

    def test_complete_inventory_still_applies_review_only_threshold(self):
        old = (NOW - timedelta(hours=48)).isoformat()
        result = assess({("A", "Instagram"): {
            "private-id": {"views": 9, "published_at": old},
        }}, NOW.isoformat(), now=NOW, excluded_accounts=set(),
            expected_sources={("A", "Instagram")})
        self.assertTrue(result["collection_complete"])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["action"], "review_only_no_delete")

    def test_ten_views_are_kept(self):
        row = {"id": {"views": 10, "published_at": (NOW - timedelta(hours=72)).isoformat()}}
        result = self.report({("A", "Facebook"): row})
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["held"][0]["reason"], "threshold_met")

    def test_missing_bad_or_negative_view_data_is_held(self):
        old = (NOW - timedelta(days=3)).isoformat()
        result = self.report({("A", "Facebook"): {
            "missing": {"published_at": old},
            "negative": {"views": -1, "published_at": old},
            "bool": {"views": True, "published_at": old},
            "bad": {"views": 0, "published_at": "yesterday"},
        }})
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(result["held"]), 4)
        self.assertEqual({x["reason"] for x in result["held"]},
                         {"view_count_unavailable", "publication_time_unverified"})

    def test_ordered_series_are_always_held(self):
        old = (NOW - timedelta(days=10)).isoformat()
        result = assess({("🎬 Film Mağarası", "Instagram"):
                         {"ep": {"views": 0, "published_at": old}}},
                        NOW.isoformat(), now=NOW)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["held"][0]["reason"], "ordered_series_protected")

    def test_snapshot_time_must_be_timezone_aware_and_not_future(self):
        with self.assertRaises(ValueError):
            assess({}, "2026-11-26T12:00:00", now=NOW)
        with self.assertRaises(ValueError):
            assess({}, (NOW + timedelta(hours=1)).isoformat(), now=NOW)

    def test_live_collector_queries_only_instagram_routes(self):
        targets = [("A", "Page A", "Facebook"), ("A", "Page A", "Instagram"),
                   ("B", "Page B", "YouTube"), ("C", "Page C", "Instagram")]
        page_lookup = mock.Mock(side_effect=lambda name: {"page": name,
                                "instagram_id": "9", "page_token": "test"})
        snapshot_loader = mock.Mock(side_effect=lambda page: {page["page"]: {
            "views": 4, "published_at": (NOW - timedelta(days=3)).isoformat()}})

        snapshot, errors = collect_instagram_snapshot(
            targets=targets, get_page_info=page_lookup, snapshot_loader=snapshot_loader)

        self.assertEqual(set(snapshot), {("A", "Instagram"), ("C", "Instagram")})
        self.assertEqual(page_lookup.call_args_list, [mock.call("Page A"),
                                                     mock.call("Page C")])
        self.assertEqual(snapshot_loader.call_count, 2)
        self.assertEqual(errors, [])

    def test_one_failed_instagram_account_suppresses_all_preview_candidates(self):
        targets = [("A", "Page A", "Instagram"), ("B", "Page B", "Instagram")]
        page_lookup = mock.Mock(side_effect=lambda name: {"page": name,
                                "instagram_id": "9", "page_token": "test"})
        def loader(page):
            if page["page"] == "Page B":
                raise RuntimeError("provider detail is intentionally not returned")
            return {"private-id": {"views": 1,
                    "published_at": (NOW - timedelta(days=3)).isoformat()}}

        snapshot, errors = collect_instagram_snapshot(
            targets=targets, get_page_info=page_lookup, snapshot_loader=loader)
        result = assess(snapshot, NOW.isoformat(), now=NOW,
                        expected_sources={("A", "Instagram"), ("B", "Instagram")},
                        collection_errors=errors)

        self.assertFalse(result["collection_complete"])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(errors, ["B / Instagram: instagram_metrics_read_failed (RuntimeError)"])
        self.assertNotIn("provider detail", str(result))

    def test_identity_lookup_failure_is_reported_without_exception_message(self):
        targets = [("A", "Page A", "Instagram")]
        def lookup(_name):
            raise RuntimeError("sensitive token-like error details")

        snapshot, errors = collect_instagram_snapshot(
            targets=targets, get_page_info=lookup,
            snapshot_loader=mock.Mock())

        self.assertIsNone(snapshot[("A", "Instagram")])
        self.assertEqual(errors, ["A / Instagram: identity_lookup_failed (RuntimeError)"])
        self.assertNotIn("sensitive", str(errors))

    def test_automatic_delete_requires_complete_scan(self):
        report = {"collection_complete": False, "candidates": [
            {"account": "A", "content_id": "123", "views": 1,
             "published_at": (NOW - timedelta(days=3)).isoformat()},
        ]}
        delete_call = mock.Mock(return_value=True)
        result = delete_review_candidates(report, {"A": {"page_token": "x", "user_access_token": "u",
                                                         "instagram_id": "9"}},
            delete_call, delete_start_at=(NOW - timedelta(hours=1)).isoformat(), now=NOW)
        self.assertEqual(result["status"], "blocked_incomplete_collection")
        delete_call.assert_not_called()

    def test_auto_delete_skips_pre_activation_content_and_caps_per_account(self):
        start = NOW - timedelta(hours=72)
        old = (start - timedelta(hours=1)).isoformat()
        hours_old_by_id = {"0": 49, "1": 52, "2": 50, "3": 51}
        report = {"collection_complete": True, "candidates": [
            {"account": "A", "content_id": "old", "views": 1, "published_at": old},
            *[{"account": "A", "content_id": str(i), "views": 2,
               "published_at": (NOW - timedelta(hours=hours_old_by_id[str(i)])).isoformat()}
              for i in range(4)],
        ]}
        page = {"page_token": "test-token", "user_access_token": "test-user-token",
                "instagram_id": "9"}
        deleted_ids = []
        result = delete_review_candidates(report, {"A": page},
            lambda _page, media_id: deleted_ids.append(media_id) or True,
            delete_start_at=start.isoformat(), now=NOW, max_per_account=3)
        self.assertEqual(deleted_ids, ["1", "3", "2"])
        self.assertEqual(len(result["deleted"]), 3)
        self.assertEqual(result["skipped_before_start"], 1)
        self.assertEqual(result["held"], 1)

    def test_invalid_or_future_activation_timestamp_never_deletes(self):
        result = delete_review_candidates({"collection_complete": True, "candidates": []}, {},
            mock.Mock(), delete_start_at=(NOW + timedelta(minutes=1)).isoformat(), now=NOW)
        self.assertEqual(result["status"], "blocked_invalid_delete_start")

    def test_auto_delete_requires_verified_account_token(self):
        report = {"collection_complete": True, "candidates": [
            {"account": "A", "content_id": "123", "views": 1,
             "published_at": (NOW - timedelta(hours=50)).isoformat()},
        ]}
        call = mock.Mock(return_value=True)
        result = delete_review_candidates(report, {"A": {"page_token": "test-token",
                                                           "instagram_id": "9"}}, call,
            delete_start_at=(NOW - timedelta(hours=72)).isoformat(), now=NOW)
        self.assertEqual(result["status"], "halted_on_error")
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
