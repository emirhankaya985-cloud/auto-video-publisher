"""Protect old 1 November Film intent from a different source's post ID."""
import copy
import unittest
from test_public_link_runtime import runtime


class SourceIdentityReconciliationTests(unittest.TestCase):
    def sample(self):
        return {
            "film:instagram:old-source": {
                "route": "film", "platform": "instagram", "status": "done",
                "file": "Avanak_Apti_Part_10 (1).mp4", "post_id": "1234",
                "reconciliation_proof": "unique_platform_history_caption",
                "container_resume": {"container_id": "expired"},
                "resume_no_publish_confirmed": True,
            },
            "film:instagram:actual-source": {
                "route": "film", "platform": "instagram", "status": "done",
                "file": "Avanak_Apti_Part_10.mp4", "post_id": "1234",
                "run_id": "real-publication-run",
            },
            "film_second:facebook:other-page": {
                "route": "film_second", "platform": "facebook", "status": "done",
                "post_id": "1234",
            },
        }

    def test_weak_alias_is_held_and_real_owner_is_untouched(self):
        state = {"entries": self.sample()}
        original_owner = copy.deepcopy(state["entries"]["film:instagram:actual-source"])
        runtime.quarantine_weak_caption_aliases(state)
        old = state["entries"]["film:instagram:old-source"]
        self.assertEqual(old["status"], "uncertain")
        self.assertNotIn("post_id", old)
        self.assertEqual(old["source_collision_post_id"], "1234")
        self.assertEqual(old["container_resume"], {"container_id": "expired"})
        self.assertEqual(state["entries"]["film:instagram:actual-source"], original_owner)
        self.assertTrue(runtime.conflicting_done_post_source(
            state["entries"], "film:instagram:old-source", "film", "instagram", "1234"))
        self.assertFalse(runtime.conflicting_done_post_source(
            state["entries"], "film:instagram:old-source", "film", "facebook", "1234"))

    def test_proven_exact_content_alias_remains_done(self):
        state = {"entries": self.sample()}
        state["entries"]["film:instagram:old-source"][
            "reconciliation_proof"] = "exact_video_content_identity"
        runtime.quarantine_weak_caption_aliases(state)
        self.assertEqual(state["entries"]["film:instagram:old-source"]["status"], "done")
        self.assertEqual(state["entries"]["film:instagram:old-source"]["post_id"], "1234")

    def test_unrelated_platform_and_empty_post_never_alias(self):
        state = {"entries": self.sample()}
        self.assertFalse(runtime.conflicting_done_post_source(
            state["entries"], "film:instagram:unknown", "film", "instagram", ""))
        self.assertFalse(runtime.conflicting_done_post_source(
            state["entries"], "film_second:facebook:other-page", "film_second", "facebook", "1234"))
        self.assertFalse(runtime.conflicting_done_post_source(
            state["entries"], "film:facebook:new", "film", "facebook", "1234"))


if __name__ == "__main__":
    unittest.main()
