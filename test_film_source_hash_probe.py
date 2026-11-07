"""Film source identity checks use only in-memory test evidence."""
import hashlib
import unittest
from film_source_hash_probe import compare_film_sources


class FilmSourceProofTests(unittest.TestCase):
    def evidence(self, old_id="OLDIDABCDEFGHIJKLMN", new_id="NEWIDABCDEFGHIJKLMN"):
        entries = {
            "film:instagram:" + old_id: {
                "route": "film", "platform": "instagram", "status": "done",
                "post_id": "123456", "file": "Film_Part_8.mp4"},
            "film:instagram:" + new_id: {
                "route": "film", "platform": "instagram", "status": "uncertain",
                "file": "Film_Part_8 (1).mp4"},
        }
        key = "film:instagram:" + new_id
        rows = [{"route": "film", "platform": "instagram",
                 "reason": "caption_candidate_requires_source_proof",
                 "candidate_post_id": "123456",
                 "source_evidence": {"entry_fingerprint": hashlib.sha256(
                     key.encode()).hexdigest()[:16]}}]
        catalog = {
            "Film_Part_8.mp4": {"id": old_id, "name": "Film_Part_8.mp4"},
            "Film_Part_8 (1).mp4": {"id": new_id, "name": "Film_Part_8 (1).mp4"}}
        return {"entries": entries}, {"rows": rows}, catalog

    def test_identical_source_bytes_still_never_authorize_repost(self):
        state, audit, catalog = self.evidence()
        result = compare_film_sources(state, audit, catalog=catalog, digest=lambda _: "same")
        self.assertEqual(result[0]["finding"], "identical_bytes_to_confirmed_post_no_repost")
        self.assertFalse(result[0]["safe_to_repost"])
        self.assertNotIn("123456", str(result))

    def test_distinct_bytes_cannot_clear_uncertain_intent(self):
        state, audit, catalog = self.evidence()
        result = compare_film_sources(state, audit, catalog=catalog, digest=lambda x: x)
        self.assertEqual(result[0]["finding"], "different_bytes_from_confirmed_post_still_held")
        self.assertEqual(state["entries"][next(reversed(state["entries"]))]["status"], "uncertain")

    def test_saved_exact_hashes_skip_unavailable_drive(self):
        state, audit, catalog = self.evidence()
        entries = list(state["entries"].values())
        entries[0]["source_sha256"] = "a" * 64
        entries[1]["source_sha256"] = "a" * 64
        rows = compare_film_sources(state, audit, catalog=catalog,
                                    digest=lambda _: self.fail("no network"))
        self.assertEqual(rows[0]["finding"], "identical_recorded_sha256_no_repost")
        self.assertFalse(rows[0]["safe_to_repost"])

    def test_failed_source_read_is_sanitized_and_still_held(self):
        state, audit, catalog = self.evidence()
        def bad(_):
            raise RuntimeError("sensitive external media URL")
        rows = compare_film_sources(state, audit, catalog=catalog, digest=bad)
        self.assertEqual(rows[0]["finding"], "source_download_or_digest_unavailable")
        self.assertEqual(rows[0]["failure_type"], "RuntimeError")
        self.assertNotIn("sensitive", str(rows))
        self.assertFalse(rows[0]["safe_to_repost"])

    def test_film_visual_collision_names_prior_published_part_without_post(self):
        state, audit, catalog = self.evidence()
        entries = state["entries"]
        old_id, new_id = list(entries)
        old = entries[old_id]
        new = entries[new_id]
        old["file"] = "Bickin_Part_3.mp4"
        new["file"] = "Bickin_Part_8 (1).mp4"
        frame = {"version": 1, "duration_ms": 180118,
                 "frames": ["00008f2763320000", "00001f4783b62300",
                            "0000177706060000"]}
        old["visual_fingerprint"] = frame
        new["visual_fingerprint"] = frame
        audit["rows"][0]["reason"] = "visual_duplicate_requires_owner_review"
        rows = compare_film_sources(state, audit, catalog=catalog,
                                    digest=lambda _: self.fail("must not fetch"))
        self.assertEqual(rows[0]["matching_confirmed_files"], ["Bickin_Part_3.mp4"])
        self.assertEqual(rows[0]["finding"], "visual_similarity_to_confirmed_other_source_still_held")
        self.assertFalse(rows[0]["safe_to_repost"])
        self.assertEqual(new["status"], "uncertain")

    def test_no_confirmed_post_does_not_download_media(self):
        state, audit, catalog = self.evidence()
        audit["rows"][0]["candidate_post_id"] = "999"
        result = compare_film_sources(state, audit, catalog=catalog,
                                      digest=lambda _: self.fail("must not download"))
        self.assertEqual(result[0]["finding"], "candidate_has_no_unique_confirmed_source")

    def test_identity_mismatch_fails_closed(self):
        state, audit, catalog = self.evidence()
        audit["rows"][0]["source_evidence"]["entry_fingerprint"] = "bad"
        with self.assertRaisesRegex(ValueError, "probe_identity_drift"):
            compare_film_sources(state, audit, catalog=catalog, digest=lambda _: "sha")


if __name__ == "__main__":
    unittest.main()
