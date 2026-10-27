"""No-publish regression tests for independent Meta-only nightly reporting."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from analytics_github_history import ARTIFACT_NAME, restore_history
import stats_reporter


class ReportingIndependenceTests(unittest.TestCase):
    def test_stats_read_retries_transient_http_without_any_writes(self):
        limited = Mock(status_code=400)
        limited.json.return_value = {"error": {"code": 4}}
        success = Mock(status_code=200, ok=True)
        success.json.return_value = {"data": [{"id": "123"}]}
        with patch("stats_reporter.requests.get", side_effect=[limited, success]) as get, \
                patch("stats_reporter.time.sleep"), patch("stats_reporter.requests.post") as post:
            result = list(stats_reporter.graph_pages("123/videos", "private-token"))
        self.assertEqual(result, [{"id": "123"}])
        self.assertEqual(get.call_count, 2)
        post.assert_not_called()

    def test_delayed_daily_value_is_not_presented_as_a_permission_or_first_snapshot_error(self):
        self.assertEqual(stats_reporter._daily_delta_text(100, None, {"status": "ok"}, delayed=True),
                         "N/A (gecikmeli ölçüm)")
        self.assertEqual(stats_reporter._daily_delta_text(None, None, None, delayed=True),
                         "⚠️ Veri alınamadı")

    def test_meta_only_uses_no_drive_or_youtube_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "history.jsonl"
            now = datetime(2026, 10, 24, 23, 59, tzinfo=ZoneInfo("Europe/Istanbul"))
            current = {("🌱 Tarladaki Fasulye", "Facebook"): {
                "video-1": {"views": 123, "published_at": "2026-10-23T11:00:00Z"}
            }}
            env = {"META_ONLY_REPORTING": "true",
                   "META_REPORT_ARTIFACT_PATH": str(destination),
                   "GITHUB_EVENT_NAME": "schedule"}
            with patch.dict(os.environ, env), patch(
                "stats_reporter.get_drive_client",
                side_effect=AssertionError("Drive OAuth must not be used")
            ), patch(
                "stats_reporter.get_youtube_client",
                side_effect=AssertionError("YouTube OAuth must not be used")
            ), patch(
                "stats_reporter.restore_history",
                return_value={"status": "first_snapshot", "source_run": None}
            ), patch(
                "stats_reporter._collect_snapshot", return_value=(current, [], [])
            ), patch("stats_reporter.publication_progress",
                     return_value=None):
                report = stats_reporter.build_report(now)
            self.assertIn("YouTube ölçülmedi", report)
            self.assertIn("Facebook: N/A (ilk ölçüm) | Genel 123", report)
            self.assertIn("✅ Tamamlanan: N/A", report)
            self.assertIn("❌ Eksik: N/A", report)
            self.assertTrue(destination.is_file())
            self.assertNotIn("❌ Eksik: 32", report)

    def test_meta_only_collects_no_youtube_stats(self):
        now = datetime(2026, 10, 24, 23, 59, tzinfo=ZoneInfo("Europe/Istanbul"))
        with patch.dict(os.environ, {"META_ONLY_REPORTING": "true"}), patch.object(
            stats_reporter, "META_TARGETS", []
        ), patch.object(
            stats_reporter, "YOUTUBE_TARGETS",
            [("Example", "TOKEN_YOUTUBE", "missing", None, "YouTube")]
        ), patch("stats_reporter.get_youtube_client",
                 side_effect=AssertionError("unexpected YouTube call")):
            snapshot, records, errors = stats_reporter._collect_snapshot(now)
        self.assertEqual(snapshot, {})
        self.assertEqual(records, [])
        self.assertEqual(errors, [])

    def test_meta_http_200_missing_data_does_not_become_zero_views(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {}
        with patch("stats_reporter.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "sayfalama verisi geçersiz"):
                list(stats_reporter.graph_pages("123/videos", "private-token"))

    def test_meta_http_200_invalid_payload_does_not_become_zero_views(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = ["not", "a", "graph", "response"]
        with patch("stats_reporter.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "yanıtı geçersiz"):
                stats_reporter.graph_get("123/insights", "private-token")

    def test_meta_paging_rejects_external_or_replayed_urls(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "data": [], "paging": {"next": "https://evil.example/leak?access_token=secret"}
        }
        with patch("stats_reporter.requests.get", return_value=response) as get:
            with self.assertRaisesRegex(RuntimeError, "bağlantısı reddedildi"):
                list(stats_reporter.graph_pages("123/videos", "private-token"))
        get.assert_called_once()

    def test_initial_github_archive_is_explicit_first_snapshot(self):
        listing = Mock(status_code=200)
        listing.json.return_value = {"total_count": 0, "artifacts": []}
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "history.jsonl"
            actual = restore_history(dest, token="test-token", get=lambda *a, **kw: listing)
            self.assertEqual(actual["status"], "first_snapshot")
            self.assertFalse(dest.exists())

    def test_github_archive_is_restored_without_drive(self):
        raw = '{"period":"2026-10-23","status":"ok"}\n'.encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("daily_video_views.jsonl", raw)
        listing = Mock(status_code=200)
        listing.json.return_value = {
            "total_count": 1,
            "artifacts": [{"name": ARTIFACT_NAME, "id": 100, "expired": False,
                           "created_at": "2026-10-23T20:59:00Z",
                           "workflow_run": {"id": 500, "head_branch": "main"}}]
        }
        download = Mock(status_code=200, content=buffer.getvalue())
        responses = [listing, download]
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "history.jsonl"
            actual = restore_history(dest, token="test-token",
                                     get=lambda *a, **kw: responses.pop(0))
            self.assertEqual(actual["status"], "restored")
            self.assertEqual(actual["source_run"], 500)
            self.assertEqual(dest.read_bytes(), raw)

    def test_inaccessible_archive_does_not_overwrite_prior_history(self):
        listing = Mock(status_code=403)
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "history.jsonl"
            dest.write_text("original snapshot\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as error:
                restore_history(dest, token="top-secret-token",
                                get=lambda *a, **kw: listing)
            self.assertEqual(dest.read_text(encoding="utf-8"), "original snapshot\n")
            self.assertNotIn("top-secret-token", str(error.exception))


    def test_full_report_is_visible_in_actions_summary_without_api_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
                self.assertTrue(stats_reporter.write_step_summary("📈 Bugün: N/A\n👀 Genel: 123"))
            summary = path.read_text(encoding="utf-8")
            self.assertIn("Gün Sonu Sosyal Medya İzlenmeleri", summary)
            self.assertIn("📈 Bugün: N/A", summary)
            self.assertIn("👀 Genel: 123", summary)

    def test_summary_is_optional_and_does_not_send_api_requests(self):
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}):
            self.assertFalse(stats_reporter.write_step_summary("report"))

    def test_disabled_legacy_publishers_and_sheets_have_no_auto_schedule(self):
        for filename in ("omnichannel_schedule.yml",
                         "cloud_schedule_backup.yml", "analytics_sheets_sync.yml"):
            workflow = Path(".github/workflows", filename).read_text(encoding="utf-8")
            self.assertIn("  workflow_dispatch:", workflow)
            self.assertNotIn("\n  schedule:", workflow)
        main = Path(".github/workflows/omnichannel_schedule.yml").read_text(encoding="utf-8")
        self.assertIn("vars.AUTOMATION_ENABLED == 'true'", main)


if __name__ == "__main__":
    unittest.main()
