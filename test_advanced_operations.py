"""Offline no-network regressions for advanced operational safety."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from adaptive_publish_times import recommend_hours
from api_capacity_guard import capacity_from_headers, classify_auth_response, safe_recovery_action
from media_similarity import similar, conflicts, hold_visual_duplicate, visual_fingerprint
from offline_subtitles import build_srt, transcribe_local
from telegram_owner_control import toggle_schedule, stock_summary

A = {"version": 1, "duration_ms": 15000, "frames": ["5555555555555555"] * 3}
B = {"version": 1, "duration_ms": 15100, "frames": ["5555555555555554"] * 3}


class MediaSimilarityTests(unittest.TestCase):
    def test_strict_similarity_and_invalid_or_uninformative(self):
        self.assertTrue(similar(A, B))
        self.assertFalse(similar(A, dict(B, duration_ms=16000)))
        self.assertFalse(similar(A, dict(B, frames=["0" * 16] * 3)))
        self.assertFalse(similar({"version": 1, "duration_ms": 15000,
                                  "frames": ["0" * 16] * 3}, B))
        self.assertFalse(similar(A, {"version": 1, "duration_ms": 15000,
                                     "frames": ["g" * 16] * 3}))

    def test_hold_prevents_repeat_without_touching_original(self):
        original = {"status": "done", "post_id": "456", "visual_fingerprint": A}
        state = {"entries": {"film:facebook:old": original.copy(),
                             "film:facebook:new": {"status": "intent"},
                             "film:instagram:new": {"status": "intent"}}}
        item = {"route": "film", "id": "new", "platforms": ["facebook", "instagram"]}
        self.assertTrue(hold_visual_duplicate(item, state, B))
        self.assertEqual(state["entries"]["film:facebook:old"], original)
        self.assertEqual(state["entries"]["film:facebook:new"]["status"], "held")
        self.assertEqual(state["entries"]["film:instagram:new"]["status"], "held")
        self.assertFalse(state["entries"]["film:facebook:new"]["failure"]["safe_to_repost"])

    def test_distinct_clips_only_register(self):
        state = {"entries": {"toonzone:facebook:one": {"status": "intent"}}}
        item = {"route": "toonzone", "id": "one", "platforms": ["facebook"]}
        self.assertFalse(hold_visual_duplicate(item, state, A))
        self.assertEqual(state["entries"]["toonzone:facebook:one"]["visual_fingerprint"], A)
        self.assertEqual(conflicts(state, route="toonzone", platform="facebook",
                                   source_id="one", fingerprint=A), [])

    def test_sampled_fingerprint_has_three_frames(self):
        pixels = bytes([n * 25 for row in range(8) for n in range(9)])
        def fake_run(argv, **kwargs):
            return SimpleNamespace(returncode=0, stdout=b"15.0\n" if argv[0] == "ffprobe" else pixels)
        result = visual_fingerprint("unused.mp4", runner=fake_run)
        self.assertEqual(result["duration_ms"], 15000)
        self.assertEqual(len(result["frames"]), 3)


class TimeAnalyticsTests(unittest.TestCase):
    def test_requires_distinct_posts_and_days(self):
        now = datetime(2026, 11, 2, 22, tzinfo=timezone.utc)
        observations = []
        for i, day in enumerate([28, 29, 30, 31]):
            row = {"route": "film", "platform": "facebook", "post_id": f"id{i}",
                   "published_at": f"2026-10-{day}T12:00:00+03:00",
                   "measured_at": "2026-11-01T12:00:00+03:00",
                   "views": 1000, "like_count": 50, "comment_count": 5}
            observations.extend([row, row.copy()])
        result = recommend_hours(observations, now=now)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["posts"], 4)
        self.assertEqual(result[0]["hour_tr"], 12)
        self.assertEqual(result[0]["engagement_per_1000_views"], 60)
        self.assertEqual(recommend_hours(observations[:6], now=now), [])

    def test_missing_data_fails_closed(self):
        self.assertEqual(recommend_hours([{"route": "film", "views": 0}]), [])


class SubtitleTests(unittest.TestCase):
    def test_srt_is_from_supplied_actual_segments(self):
        contents = build_srt([(0.0, 1.3, "Merhaba\n dünya"), (1.3, 2, "İkinci bölüm")])
        self.assertIn("00:00:00,000 --> 00:00:01,300", contents)
        self.assertIn("Merhaba dünya", contents)
        with self.assertRaises(ValueError):
            build_srt([(0, 3, "first"), (1, 4, "overlap")])
        with self.assertRaises(ValueError):
            build_srt([])

    def test_offline_generator_never_overwrites_or_publishes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "movie.mp4").write_bytes(b"ftyp")
            (base / "model").mkdir()
            segment = SimpleNamespace(start=0.0, end=1.2, text="Test speech")
            fake_model = Mock()
            fake_model.transcribe.return_value = (iter([segment]), {})
            factory = Mock(return_value=fake_model)
            result = transcribe_local(base / "movie.mp4", base / "out.srt",
                                      base / "model", model_factory=factory)
            self.assertFalse(result["auto_published"])
            self.assertIn("Test speech", (base / "out.srt").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                transcribe_local(base / "movie.mp4", base / "out.srt",
                                 base / "model", model_factory=factory)


class CapacityRecoveryTests(unittest.TestCase):
    def test_observed_usage_thresholds(self):
        self.assertEqual(capacity_from_headers({})["status"], "unavailable")
        self.assertEqual(capacity_from_headers(
            {"X-App-Usage": '{"call_count": 83}'})["status"], "warning")
        self.assertEqual(capacity_from_headers(
            {"X-Page-Usage": '{"total_time": 96}'})["status"], "hold")

    def test_token_and_api_writes_never_auto_retry(self):
        self.assertEqual(classify_auth_response(400, 190, 463)["reason"], "token_expired")
        self.assertFalse(safe_recovery_action("meta_publish")["may_repost"])
        self.assertEqual(safe_recovery_action("read_only_get")["action"],
                         "bounded_read_or_local_retry")
        self.assertEqual(safe_recovery_action("read_only_get", previous_attempt=True)["action"],
                         "hold_and_reconcile")


class TelegramTests(unittest.TestCase):
    def test_schedule_toggle_requires_opt_in_and_verifies(self):
        fake = Mock()
        fake.patch.return_value.status_code = 204
        fake.get.return_value.status_code = 200
        fake.get.return_value.json.return_value = {"value": "false"}
        with patch.dict(os.environ, {"TELEGRAM_CONTROL_ENABLED": "true",
                                     "GITHUB_CONTROL_TOKEN": "example-test-token"}):
            self.assertIn("durduruldu", toggle_schedule(False, session=fake))
        self.assertEqual(fake.patch.call_count, 1)
        with patch.dict(os.environ, {"TELEGRAM_CONTROL_ENABLED": "false",
                                     "GITHUB_CONTROL_TOKEN": "example-test-token"}):
            with self.assertRaises(RuntimeError):
                toggle_schedule(True, session=fake)

    def test_stock_uses_real_artifact_shape_without_api_writes(self):
        fake = Mock()
        responses = []
        def response(code, *, data=None, content=b""):
            return SimpleNamespace(status_code=code, json=lambda: data, content=content)
        zip_bytes = io.BytesIO()
        with zipfile.ZipFile(zip_bytes, "w") as z:
            z.writestr("content-stock.json", json.dumps([
                {"account": "ToonZone", "platform": "facebook", "remaining": 8}]))
        responses = [
            response(200, data={"workflow_runs": [{
                "head_branch": "main", "conclusion": "success", "id": 1,
                "created_at": "2026-11-02T20:00:00Z"}]}),
            response(200, data={"artifacts": [{
                "name": "publication-operations", "expired": False, "id": 2}]}),
            response(200, content=zip_bytes.getvalue()),
        ]
        fake.get.side_effect = responses
        with patch.dict(os.environ, {"GITHUB_TOKEN": "example-test-token"}):
            text = stock_summary(session=fake)
        self.assertIn("ToonZone", text)
        self.assertIn("8 aday", text)
        fake.patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
