"""Offline Film Mağarası alternative-series handoff safeguards."""
import unittest

from film_series_transition import EXPECTED_PARTS, SERIES_PREFIX, switch_film_source


def fixture():
    videos = [{"id": f"verified-drive-{i}", "name": f"{SERIES_PREFIX}_Part_{i}.mp4"}
              for i in range(1, EXPECTED_PARTS + 1)]
    catalog = {row["name"]: row for row in videos}
    for i in range(1, EXPECTED_PARTS + 1):
        catalog[f"{SERIES_PREFIX}_Part_{i}.txt"] = {"id": f"txt-{i}"}
    return videos, catalog


class FilmSeriesTransitionTests(unittest.TestCase):
    def test_only_complete_original_series_is_selected(self):
        videos, catalog = fixture()
        videos += [
            {"id": "stale-bickin", "name": "Bickin_Part_8.mp4"},
            {"id": "duplicate-export", "name": f"{SERIES_PREFIX}_Part_1 (1).mp4"},
            {"id": "already-posted-yoksul", "name": "Yoksul_1986_Part_1.mp4"},
        ]
        before = list(videos)
        for route in ("film", "film_second"):
            selected = switch_film_source(route, videos, catalog)
            self.assertEqual(len(selected), EXPECTED_PARTS)
            self.assertEqual([row["name"] for row in selected],
                             [f"{SERIES_PREFIX}_Part_{i}.mp4"
                              for i in range(1, EXPECTED_PARTS + 1)])
            self.assertEqual(videos, before)

    def test_missing_part_or_txt_fails_closed(self):
        videos, catalog = fixture()
        del catalog[f"{SERIES_PREFIX}_Part_9.txt"]
        with self.assertRaisesRegex(RuntimeError, "new_film_source_or_txt_incomplete"):
            switch_film_source("film", videos, catalog)
        videos, catalog = fixture()
        videos.pop()
        with self.assertRaisesRegex(RuntimeError, "new_film_source_selection_incomplete"):
            switch_film_source("film", videos, catalog)

    def test_other_accounts_are_not_affected(self):
        videos, catalog = fixture()
        self.assertEqual(switch_film_source("toonzone", videos, {}), videos)
        self.assertEqual(switch_film_source("penguen", videos, {}), videos)


if __name__ == "__main__":
    unittest.main()
