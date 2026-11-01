"""Film ambiguous captions: protect real already-published IDs, never infer a new one."""
import unittest
from unittest.mock import patch
from test_public_link_runtime import runtime


class FilmPostedWithSharedCaption(unittest.TestCase):
    def setup(self):
        entry = {
            "route": "film", "platform": "facebook", "status": "done",
            "file": "Avanak_Apti_Part_13 (1).mp4",
            "post_id": "1485238573455436", "day": "2026-11-01",
            "caption_hash": runtime.caption_key("One shared Part 13 caption"),
        }
        history = [
            {"id": "1485238573455436", "description": "One shared Part 13 caption"},
            {"id": "1576719330895885", "description": "One shared Part 13 caption"},
        ]
        return entry, history

    def test_real_post_id_survives_shared_caption_without_post(self):
        entry, history = self.setup()
        with patch.object(runtime, "history_publication_match",
                          return_value=(entry["post_id"], "2026-11-01")):
            self.assertTrue(runtime.confirmed_existing_film_post_amid_caption_reuse(
                entry, "film", "facebook", history))
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["post_id"], "1485238573455436")

    def test_only_exact_source_id_date_caption_and_existing_status(self):
        entry, history = self.setup()
        with patch.object(runtime, "history_publication_match",
                          return_value=(entry["post_id"], "2026-11-01")):
            for field, wrong in (
                ("status", "uncertain"), ("post_id", "no-such-post"),
                ("caption_hash", runtime.caption_key("different")),
                ("reconciliation_proof", "unique_platform_history_caption"),
            ):
                new = dict(entry, **{field: wrong})
                self.assertFalse(runtime.confirmed_existing_film_post_amid_caption_reuse(
                    new, "film", "facebook", history))
            self.assertFalse(runtime.confirmed_existing_film_post_amid_caption_reuse(
                entry, "toonzone", "facebook", history))
        with patch.object(runtime, "history_publication_match",
                          return_value=(entry["post_id"], "2026-10-31")):
            self.assertFalse(runtime.confirmed_existing_film_post_amid_caption_reuse(
                entry, "film", "facebook", history))
        with patch.object(runtime, "history_publication_match",
                          side_effect=RuntimeError("unverified timestamp")):
            self.assertFalse(runtime.confirmed_existing_film_post_amid_caption_reuse(
                entry, "film", "facebook", history))

    def test_ambiguous_caption_is_still_held_for_new_source(self):
        entry, history = self.setup()
        new = dict(entry, status="intent", post_id=None,
                   file="Avanak_Apti_Part_13.mp4")
        self.assertFalse(runtime.confirmed_existing_film_post_amid_caption_reuse(
            new, "film", "facebook", history))


if __name__ == "__main__":
    unittest.main()
