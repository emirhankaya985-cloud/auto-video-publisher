"""Fail-closed Film Mağarası byte-identity and in-run part guard."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_public_link_runtime import runtime


class FilmAliasSafety(unittest.TestCase):
    def fixture(self):
        item = {"id": "old-copy", "name": "Avanak_Apti_Part_10 (1).mp4"}
        caption = "real published caption"
        old = {
            "route": "film", "platform": "instagram", "status": "uncertain",
            "file": item["name"],
            "source_collision_post_id": "18130409657501240",
            "reconciliation_conflict": "post_id_belongs_to_other_source",
            "resume_no_publish_confirmed": True,
            "container_resume": {"container_id": "expired"},
        }
        real = {
            "route": "film", "platform": "instagram", "status": "done",
            "file": "Avanak_Apti_Part_10.mp4", "day": "2026-11-01",
            "post_id": "18130409657501240",
            "caption_hash": runtime.caption_key(caption),
        }
        files = {
            item["name"]: dict(item),
            real["file"]: {"id": "real-owner", "name": real["file"]},
        }
        entries = {
            "film:instagram:old-copy": old,
            "film:instagram:real-owner": real,
        }
        return item, old, files, entries, [{"id": "18130409657501240", "caption": caption}]

    def test_exact_source_bytes_skip_alias_without_reassignment(self):
        item, old, files, entries, history = self.fixture()
        previous = copy.deepcopy(entries)
        with tempfile.TemporaryDirectory() as tmp:
            def download(source_id, requested_path):
                path = Path(tmp) / source_id
                path.write_bytes(b"same original video bytes")
                return path
            with patch.object(runtime, "download", side_effect=download), \
                 patch.object(runtime, "verify_source_video"), \
                 patch.object(runtime, "history_publication_match",
                              return_value=("18130409657501240", "2026-11-01")):
                self.assertTrue(runtime.proven_film_ig_source_alias(
                    item, old, "film", "instagram", files, entries, history, {}))
        self.assertEqual(entries, previous)
        self.assertEqual(old["status"], "uncertain")
        self.assertNotIn("post_id", old)

    def test_different_bytes_block_alias_bypass(self):
        item, old, files, entries, history = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            def download(source_id, requested_path):
                path = Path(tmp) / source_id
                path.write_bytes(source_id.encode())
                return path
            with patch.object(runtime, "download", side_effect=download), \
                 patch.object(runtime, "verify_source_video"), \
                 patch.object(runtime, "history_publication_match",
                              return_value=("18130409657501240", "2026-11-01")):
                with self.assertRaisesRegex(RuntimeError, "içerikleri farklı"):
                    runtime.proven_film_ig_source_alias(
                        item, old, "film", "instagram", files, entries, history, {})

    def test_unproven_container_or_wrong_post_stays_held(self):
        item, old, files, entries, history = self.fixture()
        for changed in ({"resume_no_publish_confirmed": False},
                        {"container_publish_attempted": True},
                        {"source_collision_post_id": "another"},
                        {"reconciliation_conflict": None}, {"status": "done"}):
            trial = dict(old, **changed)
            with patch.object(runtime, "verified_film_duplicate",
                              return_value=dict(entries["film:instagram:real-owner"],
                                                reconciliation_proof="identical_source_bytes_and_exact_remote_post",
                                                duplicate_of_file_id="real-owner")):
                result = runtime.proven_film_ig_source_alias(
                    item, trial, "film", "instagram", files, entries, history, {})
            self.assertFalse(result, changed)
        self.assertFalse(runtime.proven_film_ig_source_alias(
            item, old, "film", "facebook", files, entries, history, {}))

    def test_same_part_legacy_drive_copies_share_batch_key(self):
        self.assertEqual(
            runtime.film_canonical_part("Avanak_Apti_Part_15 (1).mp4"),
            runtime.film_canonical_part("Avanak_Apti_Part_15.mp4"))
        self.assertNotEqual(
            runtime.film_canonical_part("Avanak_Apti_Part_15.mp4"),
            runtime.film_canonical_part("Avanak_Apti_Part_16.mp4"))


if __name__ == "__main__":
    unittest.main()
