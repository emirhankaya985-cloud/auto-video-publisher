"""Offline fail-closed tests for existing Gönle Facebook & Instagram receipts."""
import copy
import unittest
import meta_receipt_readonly as m


class ExistingReceiptTests(unittest.TestCase):
    def ledger(self):
        caption = "Original 181 Gönle caption"
        return {"schema": 1, "entries": {
            f"{m.ROUTE}:{p}:{m.SOURCE}": {
                "route": m.ROUTE, "platform": p, "status": "done",
                "file": "181.mp4", "source_sha256": m.SOURCE_SHA,
                "run_id": m.RUN_ID, "post_id": post_id,
                "publish_caption": caption
            } for p, post_id in (("facebook", m.FACEBOOK_ID), ("instagram", m.INSTAGRAM_ID))
        }}

    def video(self):
        return {
            "id": m.FACEBOOK_ID, "description": "Original 181 Gönle caption",
            "from": {"id": "321"}, "length": 180,
            "created_time": "2026-11-10T19:31:42+00:00",
        }

    def test_direct_provider_proof_requires_id_owner_caption_video_date(self):
        base = self.video()
        self.assertTrue(m.exact_facebook_video_proof(
            base, post_id=m.FACEBOOK_ID, page_id="321", caption=base["description"]))
        for key, value in (
            ("id", "unrelated"), ("from", {"id": "other"}), ("description", "wrong"),
            ("length", None), ("length", 0), ("length", -1),
            ("created_time", "2026-11-09T12:00:00Z"), ("created_time", "no-date")
        ):
            wrong = copy.deepcopy(base)
            wrong[key] = value
            with self.subTest(field=key, value=value):
                self.assertFalse(m.exact_facebook_video_proof(
                    wrong, post_id=m.FACEBOOK_ID, page_id="321", caption=base["description"]))

    def test_missing_bounded_facebook_history_does_not_authorize_repost(self):
        state = self.ledger()
        old = copy.deepcopy(state)
        report = m.assess(state, page_id="321", facebook_rows=[], instagram_rows=[])
        self.assertEqual(report["facebook"]["status"], "held_provider_visibility_or_object_unverified")
        self.assertEqual(report["instagram"]["status"], "held_provider_visibility_unverified")
        self.assertEqual(report["posts_created"], 0)
        self.assertEqual(report["state_mutations"], 0)
        self.assertEqual(state, old)

    def test_exact_video_id_proves_original_without_any_write(self):
        state = self.ledger()
        report = m.assess(state, page_id="321", facebook_rows=[], instagram_rows=[
            {"id": m.INSTAGRAM_ID, "caption": "Original 181 Gönle caption",
             "media_type": "VIDEO"}
        ], direct_payload=self.video())
        self.assertEqual(report["facebook"]["status"], "verified")
        self.assertEqual(report["facebook"]["proof"],
                         "exact_provider_video_id_owner_caption_length_date")
        self.assertEqual(report["instagram"]["status"], "verified")

    def test_other_video_or_changed_caption_never_resolves_original(self):
        state = self.ledger()
        record = state["entries"][f"gonle:facebook:{m.SOURCE}"]
        for key, value in (("source_sha256", "0"*64), ("status", "uncertain"),
                           ("post_id", "222"), ("run_id", "1234")):
            trial = copy.deepcopy(state)
            trial["entries"][f"gonle:facebook:{m.SOURCE}"][key] = value
            with self.subTest(field=key), self.assertRaises(RuntimeError):
                m.verified_original(trial)

if __name__ == "__main__":
    unittest.main()
