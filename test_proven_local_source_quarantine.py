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


if __name__ == "__main__":
    unittest.main()
