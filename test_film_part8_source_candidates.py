"""Unit tests for the GET-only Film Part 8 inventory."""
from types import SimpleNamespace
import unittest

from film_part8_source_candidates import matching_sources, summarize


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

    def test_report_never_authorizes_publish(self):
        result = summarize([f("Bickin_Part_8.mp4")])
        self.assertFalse(result["safe_to_publish"])
        self.assertFalse(result["verified_correct_part8"])
        self.assertEqual(result["meta_post_requests"], 0)
        self.assertEqual(result["ledger_writes"], 0)


if __name__ == "__main__":
    unittest.main()
