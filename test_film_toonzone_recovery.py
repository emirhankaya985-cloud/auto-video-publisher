"""No-publish tests for Film/ToonZone exact-part IG recovery without FB duplicates."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_public_link_runtime import runtime


class FilmToonZoneRecoveryTests(unittest.TestCase):
    def _run(self, route, name, retry_count=0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = "RECOVERY-IG-EXACT"
            original = {"schema": 1, "entries": {
                f"{route}:facebook:clip": {
                    "route": route, "platform": "facebook", "status": "done",
                    "post_id": "2520090981810851", "day": "2026-10-24",
                    "run_id": "40107188749",
                },
                f"{route}:instagram:clip": {
                    "route": route, "platform": "instagram", "status": "uncertain",
                    "caption_hash": runtime.caption_key(caption), "file": name,
                    "day": "2026-10-24", "run_id": "40107188749",
                    "prepublish_retry_count": retry_count,
                    "failure": {
                        "stage": "Instagram ikili video aktarımı",
                        "http_status": 400, "graph_code": None,
                        "reason": "invalid_media_or_graph_request",
                    },
                }
            }, "episode_days": {}}
            folder = "film-source" if route == "film" else "toon-source"
            cover_name = Path(name).stem + ".png"
            covers = {cover_name: {"id": "right-cover"}} if route == "toonzone" else {}
            def inventory(folder_id):
                if folder_id == folder:
                    return {name: {"name": name, "id": "clip"}}
                return covers
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "500",
                                         "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                 patch.object(runtime, "ROOT", root), \
                 patch.object(runtime, "STATE", root / "state.json"), \
                 patch.object(runtime, "PLAN", root / "plan.json"), \
                 patch.object(runtime, "ROUTES", {route: (
                     "film" if route == "film" else "toonzone",
                     "Film Mağarası" if route == "film" else "ToonZone")}), \
                 patch.object(runtime, "FOLDERS", {
                     "film" if route == "film" else "toonzone": folder, "covers": "cover-source"}), \
                 patch.object(runtime, "restore", return_value=original), \
                 patch.object(runtime, "apply_verified_migration"), \
                 patch.object(runtime, "load_meta_auth", return_value={"pages": [{
                     "page_name": "Film Mağarası" if route == "film" else "ToonZone",
                     "instagram_id": "ig-id", "page_token": "test",
                 }]}), \
                 patch.object(runtime, "inventory", side_effect=inventory), \
                 patch.object(runtime, "route_enabled", return_value=True), \
                 patch.object(runtime, "graph_rows", return_value=[]), \
                 patch.object(runtime, "target_count", return_value=4), \
                 patch.object(runtime, "seed_done", return_value=False), \
                 patch.object(runtime, "copies", return_value=(
                     {"facebook": "ALREADY-POSTED-FB", "instagram": caption},
                     "matching-txt")):
                runtime.plan()
            return (json.loads((root / "plan.json").read_text()),
                    json.loads((root / "state.json").read_text())["entries"],
                    (root / "report.md").read_text())

    def test_film_part16_recovery_is_instagram_only(self):
        plans, state, report = self._run("film", "Yoksul_1986_Part_16.mp4")
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["platforms"], ["instagram"])
        self.assertEqual(state["film:facebook:clip"]["post_id"], "2520090981810851")
        self.assertEqual(state["film:facebook:clip"]["status"], "done")
        self.assertEqual(state["film:instagram:clip"]["status"], "intent")
        self.assertEqual(state["film:instagram:clip"]["prepublish_retry_count"], 1)
        self.assertIn("RECOVERY: Yoksul_1986_Part_16.mp4", report)

    def test_toonzone_part3_recovery_is_instagram_only_and_keeps_existing_cover(self):
        plans, state, report = self._run(
            "toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3.mp4")
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["platforms"], ["instagram"])
        self.assertEqual(plans[0]["cover_id"], "right-cover")
        self.assertNotIn("generate_toonzone_cover", plans[0])
        self.assertEqual(state["toonzone:facebook:clip"]["status"], "done")
        self.assertEqual(state["toonzone:instagram:clip"]["prepublish_retry_count"], 1)
        self.assertIn("RECOVERY: S01E03_Caffeinated_Concert_Tickets_Part3.mp4", report)

    def test_second_failed_attempt_never_restarts_film(self):
        plans, state, report = self._run("film", "Yoksul_1986_Part_16.mp4", retry_count=1)
        self.assertEqual(plans, [])
        self.assertEqual(state["film:instagram:clip"]["status"], "uncertain")
        self.assertIn("uncertain previous intent", report)

    def test_second_failed_attempt_never_restarts_toonzone(self):
        plans, state, report = self._run(
            "toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3.mp4", retry_count=1)
        self.assertEqual(plans, [])
        self.assertEqual(state["toonzone:instagram:clip"]["status"], "uncertain")
        self.assertIn("uncertain previous intent", report)


if __name__ == "__main__":
    unittest.main()
