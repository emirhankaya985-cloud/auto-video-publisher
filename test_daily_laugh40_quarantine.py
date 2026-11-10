"""No Meta writes: quarantine exact already-failed Daily Laugh 40 source."""
import os
import unittest
from unittest.mock import patch
from public_link_runtime import quarantined_unordered_local_failure


class DailyLaugh40QuarantineTests(unittest.TestCase):
    SOURCE = "1i0pA26ewaAOlqxTbIxva_nsxZ_K_OrUW"
    SHA = "579051bc54e3466977fec7656b1eb15b03bd1e2c339c9dfa3acd889086e2f45c"

    def state(self):
        return {"entries": {
            f"daily_laugh:{platform}:{self.SOURCE}": {
                "route": "daily_laugh", "platform": platform,
                "file": "40.mp4", "day": "2026-11-10",
                "run_id": "42888833591", "status": "ready",
                "source_sha256": self.SHA,
                "failure": {"reason": "source_or_cover_preparation_failed",
                            "safe_to_repost": True},
            } for platform in ("facebook", "instagram")
        }}

    def skip(self, data, file_id=None, name="40.mp4"):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "42889999999"}):
            return quarantined_unordered_local_failure(
                "daily_laugh", {"id": file_id or self.SOURCE, "name": name},
                data, ["facebook", "instagram"], "2026-11-11")

    def test_exact_local_failure_skipped_both_platforms_after_midnight(self):
        self.assertTrue(self.skip(self.state()))

    def test_modified_or_unknown_source_may_not_inherit_quarantine(self):
        state = self.state()
        state["entries"][f"daily_laugh:instagram:{self.SOURCE}"]["source_sha256"] = "0" * 64
        self.assertFalse(self.skip(state))
        self.assertFalse(self.skip(self.state(), file_id="replacement-drive-id"))
        self.assertFalse(self.skip(self.state(), name="40-fixed.mp4"))

    def test_uncertain_or_published_action_cannot_be_silently_skipped(self):
        for status in ("uncertain", "intent", "done"):
            state = self.state()
            state["entries"][f"daily_laugh:facebook:{self.SOURCE}"]["status"] = status
            self.assertFalse(self.skip(state))

    def test_missing_local_only_evidence_cannot_be_skipped(self):
        state = self.state()
        state["entries"][f"daily_laugh:instagram:{self.SOURCE}"]["failure"] = {
            "reason": "provider_uncertain", "safe_to_repost": False}
        self.assertFalse(self.skip(state))


if __name__ == "__main__":
    unittest.main()
