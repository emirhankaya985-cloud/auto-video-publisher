import tempfile
import unittest
from pathlib import Path

import platform_like_switches as switches


class PlatformLikeSwitchTests(unittest.TestCase):
    def test_default_and_explicit_false_are_separate_and_disabled(self):
        result = switches.status({key: "false" for key in switches.FLAGS.values()})
        self.assertEqual(set(result["platforms"]), {"x", "youtube", "instagram"})
        self.assertEqual(result["like_writes_performed"], 0)
        self.assertTrue(all(not item["enabled"] for item in result["platforms"].values()))

    def test_true_does_not_unlock_unsupported_writes(self):
        result = switches.status({key: "true" for key in switches.FLAGS.values()})
        self.assertTrue(all(not item["enabled"] for item in result["platforms"].values()))
        self.assertTrue(all(item["reason"] == switches.REASONS[name]
                            for name, item in result["platforms"].items()))

    def test_status_artifact_contains_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "platform-like-status.json"
            switches.write_status(target, {"X_AUTO_LIKE_ENABLED": "false", "SECRET": "private"})
            self.assertTrue(target.exists())
            self.assertNotIn("private", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
