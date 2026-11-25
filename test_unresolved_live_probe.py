"""Live probe transport and identity contract, with no external calls."""
import unittest
from unittest.mock import patch

from unresolved_live_probe import remote_evidence, summarize_film_blockers
from publication_operations import _caption_digest


class UnresolvedRemoteProbeTests(unittest.TestCase):
    def source(self):
        return {"schema": 1, "entries": {"old": {
            "route": "film", "platform": "instagram", "status": "uncertain",
            "caption_hash": _caption_digest("Exact source caption"),
            "failure": {"reason": "invalid_media_or_graph_request",
                        "container_id": "1234567890"}}}}

    def page(self):
        return {"page_id": "123", "page_token": "private-token"}

    def test_only_expected_route_can_supply_remote_evidence(self):
        pages = {"Film Mağarası": self.page()}
        checks = []
        def history(page, platform):
            checks.append(("history", platform))
            self.assertIs(page, pages["Film Mağarası"])
            return [{"id": "999", "caption": "Exact source caption"}]
        def status(page, container):
            checks.append(("container", container))
            self.assertIs(page, pages["Film Mağarası"])
            return "EXPIRED"
        with patch("public_link_runtime.ROUTES", {"film": ("film", "Film Mağarası")}):
            rows = remote_evidence(self.source(), pages,
                history_reader=history, status_reader=status)
        self.assertEqual(rows[0]["candidate_post_id"], "999")
        self.assertEqual(rows[0]["existing_container_phase"], "EXPIRED")
        self.assertFalse(rows[0]["safe_to_repost"])
        self.assertEqual(len(checks), 2)
        self.assertNotIn("private-token", str(rows))

    def test_film_collision_counts_expose_no_identifiers(self):
        rows = [
            {"route": "film", "platform": "instagram",
             "reason": "caption_candidate_requires_source_proof",
             "candidate_post_id": "123456", "file": "private.mp4"},
            {"route": "film", "platform": "facebook",
             "reason": "visual_duplicate_requires_owner_review"},
            {"route": "film_second", "platform": "facebook",
             "reason": "not_observed_in_bounded_remote_history"},
            {"route": "penguen", "platform": "instagram",
             "reason": "caption_candidate_requires_source_proof"},
        ]
        summary = summarize_film_blockers(rows)
        self.assertEqual(summary["film"]["unresolved"], 2)
        self.assertEqual(summary["film"]["source_proof_required"], 1)
        self.assertEqual(summary["film_second"]["unresolved"], 1)
        self.assertFalse(summary["film"]["safe_to_repost"])
        self.assertNotIn("123456", str(summary))
        self.assertNotIn("private.mp4", str(summary))
        self.assertNotIn("penguen", str(summary))

    def test_tarladaki192_and_film17_retained_with_distinct_facebook_evidence(self):
        from unresolved_live_probe import critical_ig_intent_evidence, CRITICAL_IG_INTENTS
        from hashlib import sha256
        import copy
        state = {"entries": {}}
        remote = []
        for route, (filename, origin, container) in CRITICAL_IG_INTENTS.items():
            source = "SOURCE_" + route
            key = f"{route}:instagram:{source}"
            state["entries"][key] = {
                "route": route, "platform": "instagram", "status": "uncertain",
                "file": filename, "run_id": origin, "post_id": None,
                "failure": {"container_id": container},
                "source_sha256": "a" * 64 if route == "film" else None}
            state["entries"][f"{route}:facebook:{source}"] = {
                "route": route, "platform": "facebook", "status": "done",
                "post_id": "123456789", "file": filename}
            remote.append({"route": route, "platform": "instagram",
                           "reason": "caption_candidate_requires_source_proof",
                           "candidate_post_id": "987654321",
                           "existing_container_phase": "EXPIRED",
                           "source_evidence": {"entry_fingerprint": sha256(
                               key.encode()).hexdigest()[:16]}})
        before = copy.deepcopy(state)
        result = critical_ig_intent_evidence(state, remote)
        self.assertEqual(state, before)
        self.assertEqual(set(result), {"tarladaki", "film"})
        for route in result:
            self.assertFalse(result[route]["safe_to_repost"])
            self.assertFalse(result[route]["instagram_post_confirmed"])
            self.assertTrue(result[route]["facebook_sibling_done"])
            self.assertEqual(result[route]["container_phase"], "EXPIRED")
            self.assertEqual(result[route]["status"], "held_requires_exact_ig_source_proof")
            self.assertEqual(result[route]["unverified_caption_candidate_id"], "987654321")
        self.assertFalse(result["tarladaki"]["original_sha256_present"])
        self.assertTrue(result["film"]["original_sha256_present"])
        self.assertNotIn("123456789", str(result))

    def test_ig_missing_or_duplicate_ledger_or_remote_proof_is_never_released(self):
        from unresolved_live_probe import critical_ig_intent_evidence, CRITICAL_IG_INTENTS
        file, run, container = CRITICAL_IG_INTENTS["tarladaki"]
        state = {"entries": {"tarladaki:instagram:SOURCE": {
            "route": "tarladaki", "platform": "instagram", "status": "uncertain",
            "file": file, "run_id": run, "failure": {"container_id": container}}}}
        evidence = critical_ig_intent_evidence(state, [])
        self.assertEqual(evidence["tarladaki"]["status"], "blocked_remote_evidence_unavailable")
        self.assertEqual(evidence["film"]["status"], "blocked_original_ig_ledger_not_unique")
        self.assertFalse(evidence["tarladaki"]["safe_to_repost"])
        state["entries"]["tarladaki:instagram:DUP"] = dict(state["entries"]["tarladaki:instagram:SOURCE"])
        duplicate = critical_ig_intent_evidence(state, [])
        self.assertEqual(duplicate["tarladaki"]["status"], "blocked_original_ig_ledger_not_unique")

    def test_missing_page_is_unavailable_not_permission_to_repost(self):
        with patch("public_link_runtime.ROUTES", {"film": ("film", "Film Mağarası")}):
            rows = remote_evidence(self.source(), {},
                history_reader=lambda *a: self.fail("must not execute"),
                status_reader=lambda *a: self.fail("must not execute"))
        self.assertEqual(rows[0]["reason"], "remote_history_unavailable")
        self.assertEqual(rows[0]["existing_container_phase"], "unverified")
        self.assertFalse(rows[0]["safe_to_repost"])


if __name__ == "__main__":
    unittest.main()
