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
