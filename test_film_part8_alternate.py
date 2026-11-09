"""Bickin Part 8 may use its original source only when an export was held pre-POST.

No test sends Meta API writes or changes any historic post ID.
"""
import json
import os
import tempfile
import unittest
from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import public_link_runtime as runtime


class FilmPart8AlternateTests(unittest.TestCase):
    def setUp(self):
        self.copy = {"id": "held-copy-id", "name": "Bickin_Part_8 (1).mp4"}
        self.original = {"id": "original-file-id", "name": "Bickin_Part_8.mp4"}
        self.files = {x["name"]: x for x in (self.copy, self.original)}
        self.row = {
            "route": "film_second", "platform": "facebook", "status": "held",
            "file": self.copy["name"], "caption_hash": "historic-hash",
            "failure": {
                "reason": "visual_duplicate_review",
                "external_post_attempted": False,
                "safe_to_repost": False,
                "conflicting_platforms": ["facebook"],
            },
        }

    def test_exact_nonposted_export_hold_preserved(self):
        original = deepcopy(self.row)
        state = {"film_second:facebook:held-copy-id": self.row}
        self.assertTrue(runtime.film_part8_local_only_export_hold(
            "film_second", self.files, state))
        self.assertEqual(self.row, original)

    def test_requires_original_distinct_source_and_exact_proof(self):
        base = deepcopy(self.row)
        for change in (
            {"status": "uncertain"},
            {"status": "done", "post_id": "1234"},
            {"route": "film"},
            {"file": "Bickin_Part_3.mp4"},
            {"failure": dict(base["failure"], external_post_attempted=True)},
            {"failure": dict(base["failure"], safe_to_repost=True)},
            {"failure": dict(base["failure"], reason="video_upload_failed")},
            {"failure": dict(base["failure"], conflicting_platforms=[])},
        ):
            with self.subTest(change=change):
                state = {"film_second:facebook:held-copy-id":
                         dict(deepcopy(base), **change)}
                self.assertFalse(runtime.film_part8_local_only_export_hold(
                    "film_second", self.files, state))
        self.assertFalse(runtime.film_part8_local_only_export_hold(
            "toonzone", self.files, {"film_second:facebook:held-copy-id": base}))
        self.assertFalse(runtime.film_part8_local_only_export_hold(
            "film_second", {self.copy["name"]: self.copy},
            {"film_second:facebook:held-copy-id": base}))
        same_id = dict(self.original, id=self.copy["id"])
        self.assertFalse(runtime.film_part8_local_only_export_hold(
            "film_second", dict(self.files, **{same_id["name"]: same_id}),
            {"film_second:facebook:held-copy-id": base}))

    def test_plan_keeps_hold_and_reserves_only_original_no_post(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            start = {"schema": 1, "episode_days": {}, "entries": {
                "film_second:facebook:held-copy-id": deepcopy(self.row)
            }}
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {
                    "GITHUB_RUN_ID": "12345",
                    "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                    "ADAPTIVE_SCHEDULE_ENABLED": "false",
                    "AUTO_BACKFILL_ENABLED": "false",
                    "CATCHUP_BATCH_DATE": "not-today",
                    "META_PREFLIGHT_PARTIAL_OK": "false",
                    "PUBLISH_ACCOUNT_SCOPE": "film_second",
                }))
                for name, value in (
                    ("ROOT", root),
                    ("STATE", root / "state.json"),
                    ("PLAN", root / "plan.json"),
                    ("FOLDERS", {"film": "shared-folder"}),
                    ("ROUTES", {"film_second": ("film", "Filmmagrasi")}),
                ):
                    stack.enter_context(patch.object(runtime, name, value))
                stack.enter_context(patch.object(runtime, "restore", return_value=start))
                stack.enter_context(patch.object(runtime, "apply_verified_migration"))
                stack.enter_context(patch.object(runtime, "quarantine_weak_caption_aliases"))
                stack.enter_context(patch.object(runtime, "load_meta_auth", return_value={
                    "pages": [{"page_name": "Filmmagrasi"}]}))
                stack.enter_context(patch.object(runtime, "inventory", return_value=self.files))
                stack.enter_context(patch.object(runtime, "graph_rows", return_value=[]))
                stack.enter_context(patch.object(runtime, "route_enabled", return_value=True))
                stack.enter_context(patch.object(runtime, "target_count", return_value=1))
                stack.enter_context(patch.object(runtime, "seed_done", return_value=False))
                stack.enter_context(patch.object(runtime, "verified_film_duplicate", return_value=None))
                stack.enter_context(patch.object(runtime, "copies", return_value=({
                    "facebook": "Owner checked caption", "instagram": "Owner checked caption"
                }, "matching-txt")))
                stack.enter_context(patch.object(
                    runtime, "prepare_caption", side_effect=lambda text, *_: text))
                stack.enter_context(patch("content_stock.build_stock", return_value={}))
                stack.enter_context(patch("content_stock.stock_markdown", return_value=""))
                post = stack.enter_context(patch.object(runtime, "upload_facebook_reel"))
                runtime.plan()
                post.assert_not_called()
            plans = json.loads((root / "plan.json").read_text())
            state = json.loads((root / "state.json").read_text())
            self.assertEqual([item["name"] for item in plans],
                             ["Bickin_Part_8.mp4"])
            self.assertEqual(plans[0]["platforms"], ["facebook"])
            self.assertEqual(state["entries"]["film_second:facebook:held-copy-id"],
                             self.row)
            self.assertEqual(state["entries"]["film_second:facebook:original-file-id"]["status"],
                             "intent")
            self.assertIn("QUARANTINE: Bickin Part 8 export",
                          (root / "report.md").read_text())


if __name__ == "__main__":
    unittest.main()
