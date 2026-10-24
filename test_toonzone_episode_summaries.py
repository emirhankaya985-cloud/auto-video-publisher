"""Offline editorial quality and coverage tests for Regular Show S1/S2 captions."""
import re
import unittest

from toonzone_episode_summaries import EPISODE_PLOTS_TR, SOURCE_GUIDES, episode_summary


class ToonZoneEditorialTests(unittest.TestCase):
    def test_all_forty_episodes_have_distinct_original_short_plots(self):
        expected = {f"S01E{i:02d}" for i in range(1, 13)} | {
            f"S02E{i:02d}" for i in range(1, 29)
        }
        self.assertEqual(set(EPISODE_PLOTS_TR), expected)
        self.assertEqual(len(set(EPISODE_PLOTS_TR.values())), 40)

    def test_summaries_are_short_episode_story_hooks_not_generic_templates(self):
        for episode, body in EPISODE_PLOTS_TR.items():
            with self.subTest(episode=episode):
                self.assertGreaterEqual(len(body), 45)
                self.assertLess(len(body), 220)
                self.assertFalse(re.search(r"<[^>]+>|https?://|#\w+|\bPart\s*\d+", body))
                self.assertTrue(body.endswith("."))

    def test_publishing_cannot_invent_unsourced_future_episode_plot(self):
        for season, episode in [(1, 13), (2, 29), (3, 1), (99, 1)]:
            with self.subTest(season=season, episode=episode):
                with self.assertRaises(ValueError):
                    episode_summary(season, episode)

    def test_guide_sources_are_explicit_and_never_network_required(self):
        self.assertEqual(set(SOURCE_GUIDES), {1, 2})
        self.assertIn("imdb.com/title/tt1710308", SOURCE_GUIDES[1])
        self.assertIn("imdb.com/title/tt1710308", SOURCE_GUIDES[2])

    def test_each_part_reuses_true_episode_story(self):
        from toonzone_episode_summaries import episode_summary
        plot1 = episode_summary(1, 1)
        self.assertIn("sihirli bir klavyeye", plot1)
        self.assertEqual(plot1, episode_summary(1, 1))
        self.assertNotEqual(plot1, episode_summary(1, 2))


if __name__ == "__main__":
    unittest.main()
