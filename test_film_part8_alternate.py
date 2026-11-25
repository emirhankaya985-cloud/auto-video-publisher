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

    def test_legacy_film_second_history_is_preserved_without_active_route(self):
        self.assertNotIn("film_second", runtime.ROUTES)
        self.assertTrue(runtime.film_part8_local_only_export_hold(
            "film_second", self.files,
            {"film_second:facebook:held-copy-id": deepcopy(self.row)}))
        self.assertEqual(self.row["status"], "held")
        self.assertNotIn("post_id", self.row)


if __name__ == "__main__":
    unittest.main()
