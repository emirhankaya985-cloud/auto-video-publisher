import unittest
from unittest.mock import patch

import dashboard_archive_push as sync


class DashboardArchiveSyncTests(unittest.TestCase):
    def test_transient_server_error_is_retried(self):
        class Response:
            def __init__(self, status):
                self.status_code = status
                self.headers = {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise AssertionError("unexpected failure")

        class Session:
            def __init__(self):
                self.calls = 0

            def get(self, *_args, **_kwargs):
                self.calls += 1
                return Response(503 if self.calls == 1 else 200)

        session = Session()
        with patch.object(sync.time, "sleep"):
            response = sync.request_with_retry(session, "get", "https://example.test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.calls, 2)

    def test_recent_window_does_not_add_or_resend_entire_history(self):
        rows = [
            {"period": "2026-11-01", "entity_id": "v1"},
            {"period": "2026-11-07", "entity_id": "v1"},
            {"period": "2026-11-13", "entity_id": "v1"},
            {"period": "2026-11-13", "entity_id": "v2"},
            {"period": "bad-date", "entity_id": "v3"},
        ]
        selected, latest = sync.recent_rows(rows, days=7)
        self.assertEqual(latest, "2026-11-13")
        self.assertEqual([row["entity_id"] for row in selected], ["v1", "v1", "v2"])

    def test_jsonl_parser_preserves_bad_lines_for_review(self):
        rows, invalid = sync._parse_jsonl('{"account":"known"}\nnot-json\n[1,2]\n')
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(invalid), 2)
        self.assertEqual(invalid[0]["_review_reason"], "invalid_json")
        self.assertEqual(invalid[1]["_review_reason"], "row_not_object")

    def test_idempotent_dedup_keeps_latest_measurement_per_entity_period(self):
        earlier = {"period": "2026-11-13", "account": "Account", "platform": "Instagram",
                   "entity_type": "video", "entity_id": "v1", "metric": "view_count",
                   "measured_at": "2026-11-13T10:00:00Z", "value": 10}
        later = dict(earlier, measured_at="2026-11-13T11:00:00Z", value=12)
        other = dict(earlier, entity_id="v2", value=5)
        selected, duplicates = sync.deduplicate_rows([earlier, later, other])
        self.assertEqual(duplicates, 1)
        self.assertEqual(len(selected), 2)
        self.assertIn(12, [row["value"] for row in selected])


if __name__ == "__main__":
    unittest.main()
