"""No network: recovery-only release must never select unrelated accounts."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from test_public_link_runtime import runtime


class IGTwoFileReleaseTests(unittest.TestCase):
    def test_only_exact_two_instagram_files_ignoring_clock_without_fb_reposts(self):
        film = "Yoksul_1986_Part_16.mp4"
        toon = "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"
        sources = {
            "film": {film: {"name": film, "id": "film-id"}},
            "toonzone": {toon: {"name": toon, "id": "toon-id"}},
            "covers": {Path(toon).stem + ".png": {"id": "toon-cover"}},
            "daily_laugh": {"999.mp4": {"name": "999.mp4", "id": "daily-id"}},
        }
        ledger = {"schema": 1, "episode_days": {}, "entries": {}}
        for route, name, file_id in (
            ("film", film, "film-id"), ("toonzone", toon, "toon-id")
        ):
            ledger["entries"][f"{route}:facebook:{file_id}"] = {
                "route": route, "platform": "facebook", "status": "done",
                "file": name, "post_id": "fb-already-sent", "day": "2026-10-25"
            }
            ledger["entries"][f"{route}:instagram:{file_id}"] = {
                "route": route, "platform": "instagram", "status": "uncertain",
                "file": name, "run_id": "40224351466", "prepublish_retry_count": 1,
                "caption_hash": runtime.caption_key("EXACT-IG-CAPTION"),
                "failure": {"stage": "Instagram ikili video aktarımı",
                            "http_status": 400, "graph_code": None},
            }
        pages = [{"page_name": "Film Mağarası", "instagram_id": "ig-film"},
                 {"page_name": "ToonZone", "instagram_id": "ig-toon"}]
        def catalog(folder):
            return sources.get(folder, {})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {
                "GITHUB_RUN_ID": "999999", "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                "IG_AUDITED_RESCUE_ONLY": "true",
                "TOONZONE_AUTO_COVER_ENABLED": "true",
            }), patch.object(runtime, "ROOT", root), patch.object(
                runtime, "STATE", root / "state.json"
            ), patch.object(runtime, "PLAN", root / "plan.json"), patch.object(
                runtime, "FOLDERS", {name: name for name in sources}
            ), patch.object(runtime, "ROUTES", {
                "film": ("film", "Film Mağarası"),
                "toonzone": ("toonzone", "ToonZone"),
                "daily_laugh": ("daily_laugh", "Daily Laugh Lab"),
            }), patch.object(runtime, "restore", return_value=ledger), patch.object(
                runtime, "apply_verified_migration"
            ), patch.object(runtime, "load_meta_auth", return_value={"pages": pages}), patch.object(
                runtime, "inventory", side_effect=catalog
            ), patch.object(runtime, "graph_rows", return_value=[]), patch.object(
                runtime, "seed_done", return_value=False
            ), patch.object(runtime, "copies", return_value=(
                {"facebook": "FB-CAPTION", "instagram": "EXACT-IG-CAPTION"},
                "matching-txt"
            )), patch.object(runtime, "generate_toonzone_txts", return_value=(0, 0)), patch.object(
                runtime, "toonzone_cover_coverage", return_value=(1, 0)):
                runtime.plan()
            selected = json.loads((root / "plan.json").read_text())
            state = json.loads((root / "state.json").read_text())
        self.assertEqual(len(selected), 2)
        self.assertEqual({v["name"] for v in selected}, {film, toon})
        self.assertTrue(all(v["platforms"] == ["instagram"] for v in selected))
        self.assertTrue(all(v["route"] in {"film", "toonzone"} for v in selected))
        self.assertEqual(state["entries"]["film:facebook:film-id"]["post_id"],
                         "fb-already-sent")
        self.assertEqual(state["entries"]["toonzone:facebook:toon-id"]["post_id"],
                         "fb-already-sent")
        self.assertEqual(state["entries"]["film:instagram:film-id"]["prepublish_retry_count"], 2)
        self.assertEqual(state["entries"]["toonzone:instagram:toon-id"]["prepublish_retry_count"], 2)
        self.assertFalse(any("daily_laugh" in k for k in state["entries"]))

    def test_release_clock_override_is_exact_route_only(self):
        now = datetime(2026, 10, 26, 9, 15, tzinfo=ZoneInfo("Europe/Istanbul"))
        with patch.dict(os.environ, {"IG_AUDITED_RESCUE_ONLY": "true"}):
            self.assertEqual(runtime.target_count("film", now), 1)
            self.assertEqual(runtime.target_count("toonzone", now), 1)
            self.assertEqual(runtime.target_count("tarladaki", now), 1)  # normal 09:00 schedule


if __name__ == "__main__":
    unittest.main()
