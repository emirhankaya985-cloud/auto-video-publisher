"""No-write regression tests for previous local-only MP4 source quarantine."""
import copy
import os
import unittest
from unittest.mock import patch

from test_public_link_runtime import runtime


class ProvenLocalSourceQuarantine(unittest.TestCase):
    def video(self):
        return {"id": "drive-195", "name": "195.mp4"}

    def state(self):
        return {"entries": {
            f"tarladaki:{platform}:drive-195": {
                "route": "tarladaki", "platform": platform, "file": "195.mp4",
                "day": "2026-11-01", "status": "ready",
                "run_id": "41334846816",
                "failure": {
                    "reason": "source_or_cover_preparation_failed",
                    "safe_to_repost": True, "error_type": "RuntimeError"
                }
            } for platform in ("facebook", "instagram")
        }}

    def test_repeated_preupload_failure_can_skip_exact_clip(self):
        state = self.state()
        old = copy.deepcopy(state)
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "41340000000"}):
            self.assertTrue(runtime.quarantined_unordered_local_failure(
                "tarladaki", self.video(), state,
                ["facebook", "instagram"], "2026-11-01"))
        self.assertEqual(state, old)  # No claim, intent or history mutation.

    def test_unknown_source_status_or_date_never_quarantines(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "41340000000"}):
            for change in (
                {"status": "uncertain"}, {"status": "done"},
                {"file": "another.mp4"}, {"day": "2026-10-31"},
                {"run_id": "41340000000"}, {"run_id": ""},
                {"failure": {"reason": "upload_failed", "safe_to_repost": True}},
                {"failure": {"reason": "source_or_cover_preparation_failed",
                             "safe_to_repost": False}},
            ):
                state = self.state()
                state["entries"]["tarladaki:instagram:drive-195"].update(change)
                self.assertFalse(runtime.quarantined_unordered_local_failure(
                    "tarladaki", self.video(), state,
                    ["facebook", "instagram"], "2026-11-01"), change)
            self.assertFalse(runtime.quarantined_unordered_local_failure(
                "film", self.video(), self.state(),
                ["facebook", "instagram"], "2026-11-01"))
            self.assertFalse(runtime.quarantined_unordered_local_failure(
                "tarladaki", {"id": "new", "name": "195.mp4"},
                self.state(), ["facebook", "instagram"], "2026-11-01"))
            self.assertFalse(runtime.quarantined_unordered_local_failure(
                "tarladaki", self.video(), self.state(),
                ["facebook", "instagram"], "2026-11-02"))

    def test_independently_verified_corrupt_source_stays_held_next_day(self):
        source = {"id": "1hArLxDecYFwPs9lWQasXaNHK4f0dQ20W", "name": "195.mp4"}
        state = self.state()
        state["entries"] = {
            key.replace("drive-195", source["id"]): dict(entry, day="2026-11-04", run_id="41790686639")
            for key, entry in state["entries"].items()
        }
        platforms = ["facebook", "instagram"]
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "41799999999"}):
            self.assertTrue(runtime.quarantined_unordered_local_failure(
                "tarladaki", source, state, platforms, "2026-11-05"))
            self.assertFalse(runtime.quarantined_unordered_local_failure(
                "tarladaki", dict(source, id="replacement"), state, platforms, "2026-11-05"))
            state["entries"][f"tarladaki:instagram:{source['id']}"]["status"] = "uncertain"
            self.assertFalse(runtime.quarantined_unordered_local_failure(
                "tarladaki", source, state, platforms, "2026-11-05"))

    def penguen_timeline_fixture(self):
        source = {"id": "1lBoXFmmxvlfL6lUhxk4Qc_eZ6WHANb2I", "name": "250.mp4"}
        state = {"entries": {
            f"penguen:{platform}:{source['id']}": {
                "route": "penguen", "platform": platform, "file": "250.mp4",
                "day": "2026-11-06", "run_id": "42175366213", "status": "ready",
                "source_sha256": "513d67961759f96a7e64196bf2adbe4d8ce01f0acb3b0257a5acce71a27ea1b0",
                "failure": {"reason": "source_or_cover_preparation_failed",
                            "safe_to_repost": True, "error_type": "RuntimeError"},
            } for platform in ("facebook", "instagram")
        }}
        return source, state

    def test_audited_video_timeline_failure_stays_held_without_mutation(self):
        source, state = self.penguen_timeline_fixture()
        old = copy.deepcopy(state)
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "42199999999"}):
            self.assertTrue(runtime.quarantined_unordered_local_failure(
                "penguen", source, state, ["facebook", "instagram"], "2026-11-07"))
        self.assertEqual(state, old)

    def test_timeline_hold_requires_exact_hash_run_and_all_local_only_records(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "42199999999"}):
            for change in (
                {"source_sha256": "different"}, {"source_sha256": None},
                {"run_id": "42175366214"}, {"status": "uncertain"},
                {"status": "done"}, {"file": "251.mp4"},
                {"failure": {"reason": "upload_failed", "safe_to_repost": True}},
                {"failure": {"reason": "source_or_cover_preparation_failed",
                             "safe_to_repost": False}},
            ):
                source, state = self.penguen_timeline_fixture()
                state["entries"][f"penguen:instagram:{source['id']}"].update(change)
                self.assertFalse(runtime.quarantined_unordered_local_failure(
                    "penguen", source, state, ["facebook", "instagram"], "2026-11-07"), change)
            source, state = self.penguen_timeline_fixture()
            self.assertFalse(runtime.quarantined_unordered_local_failure(
                "penguen", dict(source, id="replacement"), state,
                ["facebook", "instagram"], "2026-11-07"))
            del state["entries"][f"penguen:instagram:{source['id']}"]
            self.assertFalse(runtime.quarantined_unordered_local_failure(
                "penguen", source, state, ["facebook", "instagram"], "2026-11-07"))


if __name__ == "__main__":
    unittest.main()
