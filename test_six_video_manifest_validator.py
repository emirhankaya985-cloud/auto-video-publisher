import unittest

from six_video_manifest_validator import validate_manifest


def target(index, platform="facebook", account="tarladaki"):
    return {
        "account": account,
        "platform": platform,
        "drive_file_id": f"mock-drive-{index}",
        "video": f"mock-video-{index}.mp4",
    }


class SixVideoManifestValidatorTests(unittest.TestCase):
    def test_six_distinct_sources_pass_even_when_one_has_two_platform_routes(self):
        targets = [target(index) for index in range(6)]
        targets.append(target(0, platform="instagram"))
        result = validate_manifest({"targets": targets, "publishing_enabled": False})
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["unique_source_videos"], 6)
        self.assertEqual(result["target_rows"], 7)
        self.assertFalse(result["publishing_performed"])

    def test_five_sources_do_not_pass_as_six(self):
        result = validate_manifest({"targets": [target(index) for index in range(5)]})
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["unique_source_videos"], 5)
        self.assertEqual(result["missing_source_videos"], 1)

    def test_more_than_six_sources_are_invalid(self):
        result = validate_manifest({"targets": [target(index) for index in range(7)]})
        self.assertEqual(result["status"], "invalid")
        self.assertIn("source_video_count_exceeds_six", result["errors"])

    def test_same_source_on_multiple_platforms_counts_once(self):
        targets = [target(0, platform="facebook"), target(0, platform="instagram")]
        result = validate_manifest({"targets": targets})
        self.assertEqual(result["unique_source_videos"], 1)
        self.assertEqual(result["status"], "incomplete")

    def test_conflicting_name_and_duplicate_route_fail_closed(self):
        targets = [target(index) for index in range(6)]
        targets.append(dict(targets[0]))
        targets[-1]["video"] = "different.mp4"
        result = validate_manifest({"targets": targets})
        self.assertEqual(result["status"], "invalid")
        self.assertIn("source_id_filename_conflict", result["errors"])
        self.assertIn("duplicate_account_platform_route", result["errors"])

    def test_unknown_account_and_missing_source_identity_are_rejected(self):
        targets = [target(index) for index in range(6)]
        targets[0]["account"] = "film_second"
        targets[1].pop("drive_file_id")
        result = validate_manifest({"targets": targets})
        self.assertEqual(result["status"], "invalid")
        self.assertIn("account_invalid", result["errors"])
        self.assertIn("source_id_missing", result["errors"])

    def test_invalid_manifest_shape_fails_closed(self):
        self.assertEqual(validate_manifest([])["status"], "invalid")
        self.assertIn("targets_missing_or_invalid", validate_manifest({})["errors"])


if __name__ == "__main__":
    unittest.main()
