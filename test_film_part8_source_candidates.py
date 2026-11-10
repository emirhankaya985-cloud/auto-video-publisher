"""Unit tests for the GET-only Film Part 8 inventory."""
from types import SimpleNamespace
import unittest

from film_part8_source_candidates import matching_sources, summarize, inventory_film_series


def f(name, file_id="1ABCDEFGHIJKLMNOPQRSTUVWXYZabcde"):
    return SimpleNamespace(path=name, id=file_id)


class FilmPart8SourceTests(unittest.TestCase):
    def test_lists_both_canonical_and_export_copy(self):
        rows = matching_sources([
            f("Bickin_Part_3.mp4"),
            f("Bickin_Part_8.mp4"),
            f("Bickin_Part_8 (1).mp4"),
            f("Bickin_Part_8.txt"),
        ])
        self.assertEqual([r["filename"] for r in rows],
                         ["Bickin_Part_3.mp4", "Bickin_Part_8 (1).mp4",
                          "Bickin_Part_8.mp4"])
        self.assertEqual(summarize([f("Bickin_Part_8.mp4")])
                         ["part8_candidate_count"], 1)

    def test_excludes_nested_unrelated_and_unknown(self):
        rows = matching_sources([
            f("nested/Bickin_Part_8.mp4"),
            f("Bickin_Part_18.mp4"),
            f("Bickin_Part_8.mp4"),
            f("Bickin_Part_8.mp4"),
        ])
        self.assertEqual(len(rows), 1)

    def test_conflicting_names_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "ambiguous_duplicate_filename"):
            matching_sources([f("Bickin_Part_8.mp4"),
                              f("Bickin_Part_8.mp4",
                                "1ABCDEFGHIJKLMNOPQRSTUVWXYZzyxwv")])

    def test_new_film_candidate_requires_contiguous_parts_txt_and_no_ledger_posts(self):
        items = [f(f"Yeni_Film_Part_{i}.mp4") for i in range(1, 5)]
        items += [f(f"Yeni_Film_Part_{i}.txt") for i in range(1, 5)]
        data = {"schema": 1, "entries": {}}
        [first] = inventory_film_series(items, data)
        self.assertEqual(first["series"], "Yeni Film")
        self.assertTrue(first["candidate_new_film"])
        self.assertEqual(first["missing_parts"], [])
        self.assertEqual(first["missing_txt_parts"], [])
        already_posted = {"schema": 1, "entries": {
            "film:facebook:source": {"route": "film", "platform": "facebook",
                                      "file": "Yeni_Film_Part_1.mp4", "status": "done",
                                      "post_id": "198763211"}}}
        [historical] = inventory_film_series(items, already_posted)
        self.assertFalse(historical["candidate_new_film"])
        self.assertEqual(historical["confirmed_existing_ledger_parts"], [1])
        [missing_text] = inventory_film_series(items[:-1], data)
        self.assertFalse(missing_text["candidate_new_film"])
        self.assertEqual(missing_text["missing_txt_parts"], [4])
        with_gap = [f(f"Yeni_Film_Part_{i}.mp4") for i in [1, 2, 4, 5]]
        with_gap += [f(f"Yeni_Film_Part_{i}.txt") for i in [1, 2, 4, 5]]
        [gapped] = inventory_film_series(with_gap, data)
        self.assertFalse(gapped["candidate_new_film"])
        self.assertEqual(gapped["missing_parts"], [3])

    def test_bickin_is_excluded_even_if_file_inventory_looks_complete(self):
        items = [f(f"Bickin_Part_{i}.mp4") for i in range(1, 5)]
        items += [f(f"Bickin_Part_{i}.txt") for i in range(1, 5)]
        [series] = inventory_film_series(items, {"entries": {}})
        self.assertFalse(series["candidate_new_film"])
        with self.assertRaisesRegex(ValueError, "film_ledger_unavailable"):
            inventory_film_series(items, {})

    def test_report_never_authorizes_publish(self):
        result = summarize([f("Bickin_Part_8.mp4")])
        self.assertFalse(result["safe_to_publish"])
        self.assertFalse(result["verified_correct_part8"])
        self.assertEqual(result["meta_post_requests"], 0)
        self.assertEqual(result["ledger_writes"], 0)


if __name__ == "__main__":
    unittest.main()
