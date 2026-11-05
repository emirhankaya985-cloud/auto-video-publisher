"""S1/S2 ToonZone titles are localized without mutating exact MP4 names."""
import unittest
from ordered_channels import TOONZONE_TITLES_TR, toonzone_metadata


class ToonZoneTranslationTests(unittest.TestCase):
    def test_localized_episode_coverage_and_nonempty_titles(self):
        expected = {(1, episode) for episode in range(1, 13)} | {
            (2, episode) for episode in range(1, 29)}
        self.assertEqual(set(TOONZONE_TITLES_TR), expected)
        self.assertTrue(all(name.strip() for name in TOONZONE_TITLES_TR.values()))

    def test_first_episode_real_title_localized_and_part_retained(self):
        result = toonzone_metadata("S01E01_The_Power_Part_1")
        self.assertEqual(result["title"], "Güç — Part 1")
        self.assertIn("Güç | Sezon 1, Bölüm 1.", result["description"])
        self.assertIn("#S01E01", result["description"])
        self.assertEqual(result["part"], 1)

    def test_second_season_title_and_exact_part_remain_stable(self):
        row = toonzone_metadata("S02E28_Karaoke_Video_Part_4")
        self.assertEqual(row["title"], "Karaoke Videosu — Part 4")
        self.assertEqual(row["minute"], 30)

    def test_invalid_names_still_refuse_publishing(self):
        with self.assertRaises(ValueError):
            toonzone_metadata("bad-source-name")


if __name__ == "__main__":
    unittest.main()
