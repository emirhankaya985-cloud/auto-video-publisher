import unittest
from datetime import datetime, timedelta, timezone

from low_view_cleanup import assess


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


if __name__ == "__main__":
    unittest.main()
