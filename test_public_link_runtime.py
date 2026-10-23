"""No network or production tokens: exercise actual link-runtime safety logic."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo


def load_runtime():
    cloud = types.ModuleType("cloud_omnichannel_publisher")
    cloud.GRAPH_API_VERSION = "v24.0"
    cloud.MetaAPIError = type("MetaAPIError", (RuntimeError,), {})
    for name in ("create_instagram_cover_video", "upload_facebook_reel", "upload_instagram_reel"):
        setattr(cloud, name, Mock(side_effect=AssertionError("No live upload in tests")))
    scheduled = types.ModuleType("scheduled_multi_publisher")
    for name in ("TARLADAKI_HOURS", "PENGUEN_HOURS", "GONLE_HOURS"):
        setattr(scheduled, name, (9, 12, 15, 18, 21))
    scheduled.FILM_HOURS = (10, 12, 14, 16, 18)
    scheduled.daily_laugh_hours_for_date = lambda day: (8, 10, 12, 14, 16, 18, 20, 22)
    scheduled.platform_content_from_txt = Mock(return_value=(None, None, "FB from TXT", "IG from TXT", True))
    auth = types.ModuleType("meta_auth_loader")
    auth.load_meta_auth = Mock(return_value={"pages": []})
    compat = types.ModuleType("instagram_media_compat")
    compat.prepare_instagram_upload = Mock()
    ordered = types.ModuleType("ordered_channels")
    ordered.parse_order = Mock(return_value=(1, 2, 2, "title"))
    ordered.toonzone_metadata = Mock(return_value={"title": "Part 2", "description": "Fallback"})
    safety = types.ModuleType("publication_safety")
    safety.route_paused = Mock(return_value=False)
    stubs = {"requests": types.ModuleType("requests"), "gdown": types.ModuleType("gdown"),
             "cloud_omnichannel_publisher": cloud, "scheduled_multi_publisher": scheduled,
             "meta_auth_loader": auth, "instagram_media_compat": compat,
             "ordered_channels": ordered, "publication_safety": safety}
    spec = importlib.util.spec_from_file_location("tested_public_link_runtime", Path(__file__).with_name("public_link_runtime.py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


runtime = load_runtime()


class LinkRuntimeSafety(unittest.TestCase):
    def test_caption_dedupe_ignores_store_suffix_and_spacing(self):
        self.assertEqual(runtime.caption_key("A  video\nEtsy: https://www.etsy.com/shop/x"), runtime.caption_key("A video"))
        self.assertNotEqual(runtime.caption_key("Part 2"), runtime.caption_key("Part 3"))

    def test_matching_toonzone_txt_is_read_instead_of_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / "caption.txt"
            text.write_text("Actual Drive text", encoding="utf-8")
            with patch.object(runtime, "download", return_value=text):
                result, origin = runtime.copies("toonzone", {"name": "episode.mp4"}, {"episode.txt": {"id": "txt"}}, root)
            self.assertEqual(origin, "matching-txt")
            self.assertEqual(result["instagram"], "IG from TXT")

    def test_non_toonzone_does_not_invent_missing_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "TXT"):
                runtime.copies("gonle", {"name": "1.mp4"}, {}, Path(tmp))

    def test_schedule_remains_five_film_slots_after_catchup_date(self):
        with patch.dict(os.environ, {"COMPLETE_DAY_DATE": "2026-10-23"}):
            self.assertEqual(runtime.target_count("film", datetime(2026, 10, 24, 9, tzinfo=runtime.TR)), 0)
            self.assertEqual(runtime.target_count("film", datetime(2026, 10, 24, 18, tzinfo=runtime.TR)), 5)
            self.assertEqual(runtime.target_count("toonzone", datetime(2026, 10, 24, 12, 20, tzinfo=runtime.TR)), 3)

    def test_catchup_preserves_daily_laugh_eight_target(self):
        with patch.dict(os.environ, {"COMPLETE_DAY_DATE": "2026-10-23"}):
            self.assertEqual(runtime.target_count("daily_laugh", datetime(2026, 10, 23, 9, tzinfo=runtime.TR)), 8)

    def test_newer_intent_beats_older_result_on_crash(self):
        old = {"id": 10, "name": "link-state-result", "workflow_run": {"id": 100}}
        new = {"id": 11, "name": "link-state-intent", "workflow_run": {"id": 101}}
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("state.json", json.dumps({"schema": 1, "entries": {"pending": {"status": "intent"}}}))
        def fake_get(path):
            if "name=link-state-result" in path:
                return Mock(json=lambda: {"artifacts": [old]})
            if "name=link-state-intent" in path:
                return Mock(json=lambda: {"artifacts": [new]})
            self.assertEqual(path, "actions/artifacts/11/zip")
            return Mock(content=memory.getvalue())
        with patch.object(runtime, "github_get", side_effect=fake_get):
            self.assertEqual(runtime.restore()["entries"]["pending"]["status"], "intent")

    def test_missing_or_malformed_state_is_not_reset(self):
        with patch.object(runtime, "github_get", side_effect=RuntimeError("denied")):
            with self.assertRaises(RuntimeError):
                runtime.restore()

    def test_malformed_successful_artifact_response_does_not_reset_state(self):
        with patch.object(runtime, "github_get", return_value=Mock(json=lambda: {})):
            with self.assertRaisesRegex(RuntimeError, "durum listesi"):
                runtime.restore()

    def test_daily_duplicate_names_are_excluded_without_losing_other_files(self):
        rows = [types.SimpleNamespace(id="a", path="1.mp4"),
                types.SimpleNamespace(id="b", path="1.mp4"),
                types.SimpleNamespace(id="c", path="2.mp4")]
        with patch.object(runtime.gdown, "download_folder", create=True, return_value=rows):
            result = runtime.inventory(runtime.FOLDERS["daily_laugh"])
        self.assertEqual(set(result), {"2.mp4"})

    def test_uncertain_toonzone_part_blocks_later_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {"a.mp4": {"name": "a.mp4", "id": "a"}, "b.mp4": {"name": "b.mp4", "id": "b"}}
            initial = {"schema": 1, "episode_days": {}, "entries": {
                "toonzone:facebook:a": {"route": "toonzone", "platform": "facebook", "status": "uncertain", "caption_hash": "old"}}}
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(root / "summary.md"), "GITHUB_RUN_ID": "123"}), patch.object(runtime, "ROOT", root), patch.object(runtime, "STATE", root / "state.json"), patch.object(runtime, "PLAN", root / "plan.json"), patch.object(runtime, "FOLDERS", {"toonzone": "folder", "covers": "coverfolder"}), patch.object(runtime, "ROUTES", {"toonzone": ("toonzone", "ToonZone")}), patch.object(runtime, "restore", return_value=initial), patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "ToonZone"}]}), patch.object(runtime, "inventory", side_effect=lambda folder: source if folder == "folder" else {}), patch.object(runtime, "graph_rows", return_value=[]), patch.object(runtime, "seed_done", return_value=False), patch.object(runtime, "copies", return_value=({"facebook": "caption", "instagram": "caption"}, "matching-txt")) as caption_mock:
                runtime.plan()
                self.assertEqual(json.loads((root / "plan.json").read_text()), [])
                self.assertEqual(caption_mock.call_count, 1)

    def test_source_failure_records_ready_without_calling_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path, plan_path = Path(tmp) / "state.json", Path(tmp) / "plan.json"
            item = {"page": "ToonZone", "route": "toonzone", "id": "v", "name": "ep.mp4", "platforms": ["facebook"], "captions": {"facebook": "copy"}}
            runtime.save(state_path, {"entries": {"toonzone:facebook:v": {"status": "intent"}}})
            runtime.save(plan_path, [item])
            with patch.object(runtime, "STATE", state_path), patch.object(runtime, "PLAN", plan_path), patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "ToonZone"}]}), patch.object(runtime, "download", side_effect=RuntimeError("download failed")):
                with self.assertRaises(SystemExit):
                    runtime.publish()
            self.assertEqual(json.loads(state_path.read_text())["entries"]["toonzone:facebook:v"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
