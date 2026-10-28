"""A film copy can be bypassed only with byte and actual post identity proof."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from test_public_link_runtime import runtime


class FilmDuplicateIdentityTests(unittest.TestCase):
    def fixture(self):
        old = {"id": "old-file", "name": "Avanak_Apti_Part_3 (1).mp4"}
        new = {"id": "copy-file", "name": "Avanak_Apti_Part_3.mp4"}
        text = "Avanak Apti part 3 approved caption"
        entry = {"route": "film_second", "platform": "facebook", "status": "done",
                 "file": old["name"], "post_id": "2174049343505147", "day": "2026-10-27",
                 "caption_hash": runtime.caption_key(text), "run_id": "40494529077"}
        remote = [{"id": entry["post_id"], "description": text,
                   "created_time": "2026-10-27T14:15:00+03:00"}]
        return old, new, text, entry, remote

    def prove(self, *, different=False, mutate=None):
        old, new, text, entry, remote = self.fixture()
        if mutate:
            mutate(entry, remote)
        def download(file_id, path):
            path.write_bytes(b"original" if file_id == old["id"] or not different else b"different")
            return path
        with patch.object(runtime, "download", side_effect=download), \
                patch.object(runtime, "verify_source_video", return_value=True):
            return runtime.verified_film_duplicate(new, "film_second", "facebook",
                {x["name"]: x for x in (old, new)}, {"film_second:facebook:old-file": entry},
                remote, {})

    def test_equal_bytes_and_exact_remote_id_preserve_original_post_day_and_run(self):
        result = self.prove()
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["post_id"], "2174049343505147")
        self.assertEqual(result["day"], "2026-10-27")
        self.assertEqual(result["run_id"], "40494529077")
        self.assertEqual(result["duplicate_of_file_id"], "old-file")
        self.assertEqual(len(result["source_sha256"]), 64)

    def test_same_part_and_caption_with_different_bytes_must_hold(self):
        with self.assertRaisesRegex(RuntimeError, "içerikleri farklı"):
            self.prove(different=True)

    def test_missing_or_changed_remote_identity_never_authorizes_alias(self):
        cases = [lambda e, r: r.clear(),
                 lambda e, r: r[0].update(id="999"),
                 lambda e, r: r[0].update(description="different caption"),
                 lambda e, r: e.update(status="uncertain"),
                 lambda e, r: e.update(day="2026-10-26"),
                 lambda e, r: e.update(route="film"),
                 lambda e, r: e.update(file="Avanak_Apti_Part_4.mp4")]
        for change in cases:
            with self.subTest(change=cases.index(change)):
                self.assertIsNone(self.prove(mutate=change))

    def test_failed_local_media_validation_does_not_create_proof(self):
        with patch.object(runtime, "verify_source_video", side_effect=RuntimeError("invalid MP4")):
            # prove() supplies its own verifier, so directly exercise the boundary.
            old, new, text, entry, remote = self.fixture()
            with patch.object(runtime, "download", return_value=Path("unused")):
                with self.assertRaisesRegex(RuntimeError, "invalid MP4"):
                    runtime.verified_film_duplicate(new, "film_second", "facebook",
                        {x["name"]: x for x in (old, new)}, {"film_second:facebook:old-file": entry}, remote, {})

    def test_verified_copy_unblocks_next_part_without_new_upload_or_duplicate_quota(self):
        old, new, text, entry, remote = self.fixture()
        next_item = {"id": "part4", "name": "Avanak_Apti_Part_4.mp4"}
        original = {"schema": 1, "episode_days": {},
                    "entries": {"film_second:facebook:old-file": entry}}
        def download(file_id, path):
            path.write_bytes(b"identical-video-source")
            return path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "555", "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"film_second": ("film", "Filmmagrasi")}), \
                    patch.object(runtime, "FOLDERS", {"film": "folder"}), \
                    patch.object(runtime, "restore", return_value=original), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "route_enabled", return_value=True), \
                    patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "Filmmagrasi"}]}), \
                    patch.object(runtime, "inventory", return_value={x["name"]: x for x in (old, new, next_item)}), \
                    patch.object(runtime, "graph_rows", return_value=remote), \
                    patch.object(runtime, "target_count", return_value=5), \
                    patch.object(runtime, "seed_done", return_value=False), \
                    patch.object(runtime, "parse_order", side_effect=lambda stem, parser: ("avanak", 3 if "Part_3" in stem else 4)), \
                    patch.object(runtime, "copies", side_effect=lambda route, item, *a: (
                        {"facebook": text + " #Updated" if "Part_3" in item["name"] else "unique part 4", "instagram": "unused"}, "matching-txt")), \
                    patch.object(runtime, "download", side_effect=download), \
                    patch.object(runtime, "verify_source_video", return_value=True), \
                    patch.object(runtime, "upload_facebook_reel") as post:
                runtime.plan()
            planned = json.loads((root / "plan.json").read_text())
            self.assertEqual([x["id"] for x in planned], ["part4"])
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["entries"]["film_second:facebook:copy-file"]["post_id"], entry["post_id"])
            self.assertEqual(runtime.ledger_daily_count(state, "film_second", "facebook", "2026-10-27"), 1)
            self.assertIn("DUPLICATE VERIFIED:", (root / "report.md").read_text())
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
