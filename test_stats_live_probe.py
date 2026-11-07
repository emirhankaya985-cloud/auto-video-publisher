"""No network and no notification safety checks for real statistics probe."""
import unittest
from unittest.mock import patch, Mock
import stats_live_probe


class LiveProbeTests(unittest.TestCase):
    def test_partial_coverage_never_claims_complete(self):
        report = Mock(comparison={"measured_at": "2026-11-06T02:00:00+03:00", "accounts": [
            {"platforms": [{"platform": "Threads", "total": None, "daily": {"delta": None}, "weekly": {"delta": None}},
                           {"platform": "Facebook", "total": 200, "daily": {"delta": 5}, "weekly": {"delta": None}}]}],
            "meta_collection": {"status": "partial"}, "collection_errors": ["Threads unavailable"]})
        data = stats_live_probe.summarize(report)
        self.assertEqual(data["counts"]["view_totals_measured"], 1)
        self.assertEqual(data["counts"]["threads_view_totals_measured"], 0)
        self.assertEqual(data["counts"]["daily_changes_measured"], 1)
        self.assertEqual(data["telegram_messages_sent"], 0)
        self.assertEqual(data["publisher_writes"], 0)

    def test_gap_labels_are_bounded_and_never_copy_provider_errors(self):
        known = next(iter(stats_live_probe.stats_reporter.ACCOUNT_TARGETS))
        report = Mock(comparison={"measured_at": "2026-11-06T02:00:00+03:00",
            "accounts": [{"account": known, "platforms": [
                {"platform": "Threads", "total": None},
                {"platform": "Facebook", "total": 3},
            ]}], "collection_errors": [
                "provider said PRIVATE_TOKEN_123 should never appear in telemetry",
            ]})
        result = stats_live_probe.summarize(report)
        self.assertEqual(result["missing_view_counters"],
                         [{"account": known, "platform": "Threads",
                           "reason": "view_counter_unavailable"}])
        self.assertNotIn("PRIVATE_TOKEN_123", str(result))

    def test_owner_seventh_account_is_explicitly_unconfigured_and_unmeasured(self):
        known = list(stats_live_probe.stats_reporter.ACCOUNT_TARGETS)
        report = Mock(comparison={"accounts": [
            {"account": name, "platforms": [{"platform": "Instagram", "total": 0}]}
            for name in known
        ], "meta_collection": {}, "collection_errors": []})
        coverage = stats_live_probe.summarize(report)["owner_account_coverage"]
        self.assertEqual(coverage["expected_accounts"], 7)
        self.assertEqual(coverage["configured_accounts"], 6)
        self.assertEqual(coverage["measured_accounts"], 6)
        self.assertEqual(coverage["unconfigured_accounts"], ["OddFrames"])
        self.assertEqual(coverage["unmeasured_accounts"], ["OddFrames"])

    def test_no_report_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "invalid_comparison"):
            stats_live_probe.summarize(Mock(comparison=None))

    def test_probe_never_invokes_notify_or_publication(self):
        fake = Mock(comparison={"accounts": [{"platforms": [{"platform": "Facebook", "total": 100}]}],
            "meta_collection": {}, "collection_errors": [], "measured_at": "2026-11-06T02:00:00+03:00"})
        with patch.object(stats_live_probe.stats_reporter, "build_report", return_value=fake), \
             patch.object(stats_live_probe.stats_reporter, "notify", side_effect=AssertionError("notification")):
            with __import__("tempfile").TemporaryDirectory() as d:
                with patch.object(stats_live_probe, "OUTPUT", __import__("pathlib").Path(d) / "summary.json"):
                    self.assertEqual(stats_live_probe.main(), 0)


if __name__ == "__main__":
    unittest.main()


def test_engagement_coverage_counts_only_verified_threads_metrics():
    from stats_live_probe import summarize
    from types import SimpleNamespace
    report = SimpleNamespace(comparison={"accounts": [
        {"account": "Film", "platforms": [{"platform": "Threads", "total": 1}]},
        {"account": "Toon", "platforms": [{"platform": "Threads", "total": None}]}],
        "threads_engagement": [
            {"account": "Film", "platform": "Threads", "metric": "likes", "status": "ok", "value": 0},
            {"account": "Film", "platform": "Threads", "metric": "likes", "status": "ok", "value": 0},
            {"account": "Toon", "platform": "Threads", "metric": "likes", "status": "unavailable", "value": None},
            {"account": "Other", "platform": "Instagram", "metric": "likes", "status": "ok", "value": 2}]})
    coverage = summarize(report)["threads_engagement_coverage"]
    assert coverage["likes"] == {"expected_accounts": 2, "measured_accounts": 1}
    assert coverage["shares"] == {"expected_accounts": 2, "measured_accounts": 0}
