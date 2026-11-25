import unittest

from toonzone_asset_matcher import match_cover_assets, normalize_title, parse_asset_name


class ToonZoneAssetMatcherTests(unittest.TestCase):
    def test_parses_numeric_episode_key_and_localized_title(self):
        parsed = parse_asset_name("S02E27_Yenilgi_TR_Part3.mp4")
        self.assertEqual(parsed["key"], (2, 27, 3))
        self.assertEqual(parsed["title"], "Yenilgi_TR")

    def test_normalizes_unicode_without_translating_titles(self):
        self.assertEqual(normalize_title("Örnek_Bölüm-TR"), "ornek bolum")
        self.assertNotEqual(normalize_title("Yenilgi"), normalize_title("Skunked"))

    def test_unique_episode_key_with_localized_title_requires_review(self):
        result = match_cover_assets(
            ["S02E27_Yenilgi_TR_Part3.mp4"],
            ["S02E27_Skunked_Part3-4.jpg"],
        )
        row = result["rows"][0]
        self.assertEqual(row["classification"], "HIGH_CONFIDENCE_REVIEW")
        self.assertEqual(result["summary"]["matched_candidate_count"], 1)
        self.assertFalse(row["publication_eligible"])

    def test_verified_alias_set_is_required_for_localized_verified_match(self):
        result = match_cover_assets(
            ["S02E27_Yenilgi_TR_Part3.mp4"],
            ["S02E27_Skunked_Part3-4.jpg"],
            verified_title_aliases={(2, 27, 3): {"Yenilgi TR", "Skunked"}},
        )
        self.assertEqual(result["rows"][0]["classification"], "VERIFIED_MATCH")
        self.assertEqual(result["summary"]["publication_eligible_count"], 0)

    def test_duplicate_episode_keys_are_ambiguous(self):
        result = match_cover_assets(
            ["S02E27_Yenilgi_Part3.mp4", "S02E27_Other_Part3.mp4"],
            ["S02E27_Skunked_Part3-4.jpg"],
        )
        self.assertEqual(result["rows"][0]["classification"], "AMBIGUOUS")
        self.assertFalse(result["rows"][0]["cover_id"])
        self.assertEqual(len(result["rows"]), 2)

    def test_missing_video_part_leaves_cover_as_unmatched(self):
        result = match_cover_assets(
            ["S02E21_Over_the_Top_Part3.mp4"],
            ["S02E21_Over_the_Top_Part3-4.jpg", "S02E21_Over_the_Top_Part4-4.jpg"],
        )
        self.assertEqual(result["summary"]["matched_candidate_count"], 1)
        self.assertEqual(result["summary"]["unmatched_cover_count"], 1)
        self.assertEqual(result["unmatched_covers"][0]["name"], "S02E21_Over_the_Top_Part4-4.jpg")

    def test_unparseable_assets_are_unmatched_and_never_publishable(self):
        result = match_cover_assets(["clip.mp4"], ["cover.jpg"])
        self.assertEqual(result["rows"][0]["classification"], "UNMATCHED")
        self.assertEqual(result["unmatched_covers"][0]["name"], "cover.jpg")
        self.assertEqual(result["summary"]["publication_eligible_count"], 0)


if __name__ == "__main__":
    unittest.main()
