"""Offline safety tests for optional operations; never call remote APIs."""
from datetime import datetime
from pathlib import Path
import copy
import tempfile
import unittest

from operational_enhancements import (
    bind_source_integrity, bounded_catchup_limit, rank_complete_engagement,
)


class CatchupTests(unittest.TestCase):
    def test_two_only_for_real_backlog_after_local_18_and_explicit_enable(self):
        now = datetime(2026, 11, 3, 20, 10)
        self.assertEqual(bounded_catchup_limit("film", 5,
                         {"facebook": 3, "instagram": 2}, now, enabled=True), 2)
        self.assertEqual(bounded_catchup_limit("film", 5,
                         {"facebook": 4}, now, enabled=True), 1)
        self.assertEqual(bounded_catchup_limit("film", 5,
                         {"facebook": 1}, now, enabled=False), 1)
        self.assertEqual(bounded_catchup_limit("film", 5,
                         {"facebook": 1}, datetime(2026, 11, 3, 17), enabled=True), 1)
        self.assertEqual(bounded_catchup_limit("toonzone", 4,
                         {"instagram": 0}, now, enabled=True), 1)
        self.assertEqual(bounded_catchup_limit("film", 0,
                         {"facebook": 0}, now, enabled=True), 1)
        self.assertEqual(bounded_catchup_limit("film", 5,
                         {"facebook": -1}, now, enabled=True), 1)


class SourceIntegrityTests(unittest.TestCase):
    def entries(self):
        return {"entries": {
            "film:facebook:id1": {"route": "film", "platform": "facebook", "status": "intent",
                                  "file": "Film_Part_1.mp4"},
            "film:instagram:id1": {"route": "film", "platform": "instagram", "status": "intent",
                                   "file": "Film_Part_1.mp4"},
            "film:facebook:old": {"status": "done", "post_id": "999"},
        }}

    def item(self):
        return {"route": "film", "id": "id1", "name": "Film_Part_1.mp4",
                "platforms": ["facebook", "instagram"]}

    def test_first_source_is_baselined_for_both_platforms(self):
        state = self.entries()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "source.mp4"
            path.write_bytes(b"initial-source")
            self.assertTrue(bind_source_integrity(self.item(), state, path))
        self.assertEqual(state["entries"]["film:facebook:id1"]["source_sha256"],
                         state["entries"]["film:instagram:id1"]["source_sha256"])

    def test_replaced_source_holds_both_and_preserves_old_posts(self):
        state = self.entries()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "source.mp4"
            path.write_bytes(b"original")
            bind_source_integrity(self.item(), state, path)
            old = copy.deepcopy(state["entries"]["film:facebook:old"])
            for platform in ("facebook", "instagram"):
                state["entries"][f"film:{platform}:id1"]["status"] = "intent"
            path.write_bytes(b"CHANGED")
            self.assertFalse(bind_source_integrity(self.item(), state, path))
        self.assertEqual(state["entries"]["film:facebook:old"], old)
        for platform in ("facebook", "instagram"):
            held = state["entries"][f"film:{platform}:id1"]
            self.assertEqual(held["status"], "held")
            self.assertFalse(held["failure"]["safe_to_repost"])

    def test_wrong_intent_never_baselines(self):
        state = self.entries()
        state["entries"]["film:facebook:id1"]["file"] = "wrong.mp4"
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "source.mp4"
            path.write_bytes(b"content")
            with self.assertRaises(RuntimeError):
                bind_source_integrity(self.item(), state, path)


class RankingTests(unittest.TestCase):
    def record(self, id, metric, value, status="ok", platform="instagram"):
        return dict(entity_type="video", entity_id=id, account="Film",
                    platform=platform, metric=metric, value=value, status=status)

    def test_only_complete_posts_ranked_and_true_zero_is_eligible(self):
        data = [self.record("1", "like_count", 5),
                self.record("1", "comment_count", 2),
                self.record("2", "like_count", 0),
                self.record("2", "comment_count", 0),
                self.record("3", "like_count", 999),
                self.record("3", "comment_count", None, "unavailable")]
        result = rank_complete_engagement(data)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["excluded_incomplete_posts"], 1)
        self.assertEqual([r["post_id"] for r in result["ranking"][0]["top_posts"]], ["1", "2"])

    def test_duplicate_metric_cannot_inflate_score_or_cross_platform(self):
        data = [self.record("1", "like_count", 5), self.record("1", "like_count", 5),
                self.record("1", "comment_count", 2),
                self.record("1", "like_count", 1, platform="facebook"),
                self.record("1", "comment_count", 1, platform="facebook")]
        result = rank_complete_engagement(data)
        self.assertEqual(result["excluded_incomplete_posts"], 1)
        self.assertEqual(result["ranking"][0]["platform"], "facebook")
        self.assertEqual(result["ranking"][0]["top_posts"][0]["interactions"], 2)



class LiveIntegrationContractTests(unittest.TestCase):
    def test_source_digest_gate_is_before_any_meta_upload(self):
        import ast
        tree = ast.parse((Path(__file__).parent / "public_link_runtime.py").read_text())
        publisher = next(node for node in tree.body
                         if isinstance(node, ast.FunctionDef) and node.name == "publish")
        calls = [(n.func.id, n.lineno) for n in ast.walk(publisher)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        digest_line = min(l for name, l in calls if name == "bind_source_integrity")
        meta_lines = [l for name, l in calls
                      if name in {"upload_facebook_reel", "upload_instagram_reel"}]
        self.assertTrue(meta_lines)
        self.assertTrue(all(digest_line < l for l in meta_lines))

    def test_backfill_is_opt_in_in_production_workflow(self):
        yml = (Path(__file__).parent / ".github" / "workflows" /
               "public_link_schedule.yml").read_text()
        self.assertIn("vars.AUTO_BACKFILL_ENABLED == 'true'", yml)
        self.assertIn("bounded_catchup_limit", (Path(__file__).parent /
                                              "public_link_runtime.py").read_text())


if __name__ == "__main__":
    unittest.main()
