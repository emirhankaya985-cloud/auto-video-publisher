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
