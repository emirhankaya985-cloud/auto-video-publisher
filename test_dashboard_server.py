import json
import tempfile
import unittest
from pathlib import Path

import dashboard_server as d


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_archive = d.ARCHIVE
        d.ARCHIVE = Path(self.tmp.name) / "history.jsonl"
        rows = []
        for day, views in [("2026-11-01", 100), ("2026-11-07", 140), ("2026-11-13", 190)]:
            rows.append({
                "period": day, "account": "Account", "platform": "Instagram",
                "entity_type": "account", "entity_id": None, "metric": "lifetime_views",
                "value": views, "status": "ok", "measured_at": day + "T22:00:00+03:00",
            })
            rows.append({
                "period": day, "account": "Account", "platform": "Instagram",
                "entity_type": "account", "entity_id": None, "metric": "follower_count",
                "value": 12, "status": "ok",
            })
        d.ARCHIVE.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")

    def tearDown(self):
        d.ARCHIVE = self.old_archive
        self.tmp.cleanup()

    def test_current_and_history_are_real_snapshots(self):
        row = d.build_payload()["accounts"][0]
        self.assertEqual(row["current_views"], 190)
        self.assertEqual(len(row["history"]), 3)
        self.assertEqual(row["followers"], 12)

    def test_missing_baseline_is_not_reported_as_zero(self):
        row = d.build_payload()["accounts"][0]
        self.assertIsNone(row["weekly_delta"])
        self.assertIsNone(row["monthly_delta"])

    def test_failed_measurement_is_not_zero(self):
        d.ARCHIVE.write_text(json.dumps({
            "period": "2026-11-13", "account": "Account", "platform": "Instagram",
            "entity_type": "account", "metric": "lifetime_views", "value": None,
            "status": "error",
        }), encoding="utf-8")
        self.assertIsNone(d.build_payload()["accounts"][0]["current_views"])


if __name__ == "__main__":
    unittest.main()
