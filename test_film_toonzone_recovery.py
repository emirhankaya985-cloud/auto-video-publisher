"""No-publish tests for Film/ToonZone exact-part IG recovery without FB duplicates."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_public_link_runtime import runtime


class FilmToonZoneRecoveryTests(unittest.TestCase):
    def _run(self, route, name, retry_count=0, run_id="40107188749"):
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
                    "day": "2026-10-24", "run_id": run_id,
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

    def test_one_last_ig_720p_attempt_for_two_verified_pre_publish_400(self):
        for route, filename in (
            ("film", "Yoksul_1986_Part_16.mp4"),
            ("toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"),
        ):
            with self.subTest(route=route):
                plans, state, report = self._run(
                    route, filename, retry_count=1, run_id="40224351466")
                self.assertEqual(len(plans), 1)
                self.assertEqual(plans[0]["platforms"], ["instagram"])
                self.assertEqual(state[f"{route}:instagram:clip"]["status"], "intent")
                self.assertEqual(state[f"{route}:instagram:clip"]["prepublish_retry_count"], 2)
                self.assertEqual(state[f"{route}:facebook:clip"]["status"], "done")
                self.assertIn("RECOVERY V3", report)

    def test_no_fourth_try_and_no_non_audited_video_override(self):
        for route, filename in (
            ("film", "Yoksul_1986_Part_16.mp4"),
            ("toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"),
        ):
            plans, state, report = self._run(
                route, filename, retry_count=2, run_id="40224351466")
            self.assertEqual(plans, [])
            self.assertEqual(state[f"{route}:instagram:clip"]["status"], "uncertain")
        wrong = {"status": "uncertain", "run_id": "40224351466",
                 "prepublish_retry_count": 1,
                 "failure": {"stage": "Instagram media_publish", "http_status": 400}}
        self.assertFalse(runtime.audited_ig_v3_eligible(
            "film", "instagram", "Yoksul_1986_Part_16.mp4", wrong))
        wrong["failure"]["stage"] = "Instagram ikili video aktarımı"
        self.assertFalse(runtime.audited_ig_v3_eligible(
            "film", "instagram", "Yoksul_1986_Part_17.mp4", wrong))

    def test_confirmed_full_180s_compact_v4_release_is_exact_ig_only(self):
        for route, filename in (
            ("film", "Yoksul_1986_Part_16.mp4"),
            ("toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"),
        ):
            with self.subTest(route=route):
                planned, state, text = self._run(
                    route, filename, retry_count=2, run_id="40281812561")
                self.assertEqual(len(planned), 1)
                self.assertEqual(planned[0]["platforms"], ["instagram"])
                self.assertEqual(state[f"{route}:instagram:clip"]["status"], "intent")
                self.assertEqual(state[f"{route}:instagram:clip"]["prepublish_retry_count"], 3)
                self.assertEqual(state[f"{route}:facebook:clip"]["status"], "done")
                self.assertIn("RECOVERY V4", text)

    def test_fourth_failure_does_not_auto_repost_compact_v4(self):
        for route, filename in (
            ("film", "Yoksul_1986_Part_16.mp4"),
            ("toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"),
        ):
            planned, state, text = self._run(
                route, filename, retry_count=3, run_id="40281812561")
            self.assertEqual(planned, [])
            self.assertEqual(state[f"{route}:instagram:clip"]["status"], "uncertain")
        prior = {"status": "uncertain", "prepublish_retry_count": 2,
                 "run_id": "40281812561",
                 "failure": {"stage": "Instagram media_publish", "http_status": 400}}
        self.assertFalse(runtime.audited_ig_v4_eligible(
            "film", "instagram", "Yoksul_1986_Part_16.mp4", prior))
        prior["failure"]["stage"] = "Instagram ikili video aktarımı"
        self.assertFalse(runtime.audited_ig_v4_eligible(
            "film", "instagram", "Yoksul_1986_Part_17.mp4", prior))

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
