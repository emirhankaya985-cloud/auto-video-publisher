"""No-publish regressions for on-demand ToonZone exact-part cover recovery."""
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from test_public_link_runtime import runtime
from toonzone_cover_fallback import generate_part_cover


def valid_header():
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 900, 1200)


class ToonZoneCoverFallbackTests(unittest.TestCase):
    def test_cover_uses_own_clip_and_part_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "actual.mp4"
            source.write_bytes(b"source")
            filename = "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"
            dest = root / filename.replace(".mp4", ".png")
            with patch("toonzone_cover_fallback.parse_order", return_value=(1, 3, 3, "episode")), \
                 patch("toonzone_cover_fallback.subprocess.run") as ffmpeg:
                ffmpeg.side_effect = lambda command, **kwargs: Path(command[-1]).write_bytes(valid_header())
                self.assertEqual(generate_part_cover(source, filename, dest), dest)
            self.assertEqual(dest.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            command = ffmpeg.call_args.args[0]
            self.assertEqual(command[command.index("-i") + 1], str(source))
            filters = command[command.index("-vf") + 1]
            self.assertIn("S01E03", filters)
            self.assertIn("PART\\ 3\\ OF\\ 4", filters)
            self.assertIn("900:1200", filters)
            self.assertNotIn("http", " ".join(command))

    def test_rejects_wrong_episode_or_png_name_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "clip.mp4"
            source.write_bytes(b"source")
            with patch("toonzone_cover_fallback.parse_order",
                       side_effect=lambda stem, _: (1, 3, 3, "episode")
                       if stem == "S01E03_Caffeinated_Concert_Tickets_Part3" else None), \
                 patch("toonzone_cover_fallback.subprocess.run") as ffmpeg:
                with self.assertRaises(ValueError):
                    generate_part_cover(source, "bad.mp4", root / "bad.png")
                with self.assertRaises(ValueError):
                    generate_part_cover(source, "S01E03_Caffeinated_Concert_Tickets_Part3.mp4",
                                        root / "S01E04_Part3.png")
                ffmpeg.assert_not_called()

    def test_invalid_extracted_image_fails_before_any_meta_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "actual.mp4"
            source.write_bytes(b"source")
            name = "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"
            dest = root / name.replace(".mp4", ".png")
            with patch("toonzone_cover_fallback.parse_order", return_value=(1, 3, 3, "episode")), \
                 patch("toonzone_cover_fallback.subprocess.run") as ffmpeg:
                ffmpeg.side_effect = lambda command, **kwargs: Path(command[-1]).write_bytes(b"bad png")
                with self.assertRaisesRegex(RuntimeError, "hazırlanamadı"):
                    generate_part_cover(source, name, dest)
            self.assertFalse(dest.exists())

    def _plan(self, root, covers, extra_env=None):
        name = "S01E03_Caffeinated_Concert_Tickets_Part3.mp4"
        files = {name: {"id": "video-3", "name": name}}
        state = {"schema": 1, "entries": {}, "episode_days": {}}
        os_env = {"GITHUB_RUN_ID": "111", "GITHUB_STEP_SUMMARY": str(root / "summary.md")}
        os_env.update(extra_env or {})
        with patch.dict(os.environ, os_env), \
             patch.object(runtime, "ROOT", root), \
             patch.object(runtime, "STATE", root / "state.json"), \
             patch.object(runtime, "PLAN", root / "plan.json"), \
             patch.object(runtime, "ROUTES", {"toonzone": ("toonzone", "ToonZone")}), \
             patch.object(runtime, "FOLDERS", {"toonzone": "toon", "covers": "covers"}), \
             patch.object(runtime, "restore", return_value=state), \
             patch.object(runtime, "apply_verified_migration"), \
             patch.object(runtime, "load_meta_auth", return_value={"pages": [
                 {"page_name": "ToonZone", "page_token": "test"}]}), \
             patch.object(runtime, "inventory", side_effect=lambda id: files if id == "toon" else covers), \
             patch.object(runtime, "route_enabled", return_value=True), \
             patch.object(runtime, "target_count", return_value=4), \
             patch.object(runtime, "graph_rows", return_value=[]), \
             patch.object(runtime, "copies", return_value=({"facebook": "part 3", "instagram": "part 3"}, "generated")):
            runtime.plan()
        return json.loads((root / "plan.json").read_text()), (root / "report.md").read_text()

    def test_missing_drive_cover_plans_safe_on_demand_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            plans, report = self._plan(Path(tmp), {}, {"TOONZONE_AUTO_COVER_ENABLED": "true"})
            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0]["name"], "S01E03_Caffeinated_Concert_Tickets_Part3.mp4")
            self.assertTrue(plans[0]["generate_toonzone_cover"])
            self.assertNotIn("cover_id", plans[0])
            self.assertIn("COVER FALLBACK", report)

    def test_existing_part_png_remains_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            covers = {"S01E03_Caffeinated_Concert_Tickets_Part3.png": {"id": "cover-3"}}
            plans, report = self._plan(Path(tmp), covers, {"TOONZONE_AUTO_COVER_ENABLED": "true"})
            self.assertEqual(plans[0]["cover_id"], "cover-3")
            self.assertNotIn("generate_toonzone_cover", plans[0])
            self.assertNotIn("COVER FALLBACK", report)

    def test_owner_can_disable_fallback_without_bypassing_cover_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            plans, report = self._plan(Path(tmp), {}, {"TOONZONE_AUTO_COVER_ENABLED": "false"})
            self.assertEqual(plans, [])
            self.assertIn("fallback disabled", report)

    def test_failed_generation_never_reaches_meta_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            state_file = root / "state.json"
            plan_file = root / "plan.json"
            state_file.write_text(json.dumps({"entries": {"toonzone:facebook:clip": {
                "route": "toonzone", "platform": "facebook", "status": "intent"
            }}}))
            plan_file.write_text(json.dumps([{
                "route": "toonzone", "page": "ToonZone", "id": "clip",
                "name": "S01E03_Caffeinated_Concert_Tickets_Part3.mp4",
                "platforms": ["facebook"], "captions": {"facebook": "caption"},
                "generate_toonzone_cover": True,
            }]))
            def download(_, output):
                Path(output).write_bytes(b"\0\0\0\x20ftyp" + b"placeholder")
                return Path(output)
            with patch.object(runtime, "ROOT", root), \
                 patch.object(runtime, "STATE", state_file), \
                 patch.object(runtime, "PLAN", plan_file), \
                 patch.object(runtime, "load_meta_auth", return_value={"pages": [
                     {"page_name": "ToonZone", "page_token": "test"}]}), \
                 patch.object(runtime, "download", side_effect=download), \
                 patch.object(runtime, "verify_source_video", return_value=True), \
                 patch.object(runtime, "generate_part_cover", side_effect=RuntimeError("bad-frame")), \
                 patch.object(runtime, "upload_facebook_reel") as facebook, \
                 patch.object(runtime, "upload_instagram_reel") as instagram:
                with self.assertRaises(SystemExit):
                    runtime.publish()
                facebook.assert_not_called()
                instagram.assert_not_called()
            state = json.loads(state_file.read_text())
            self.assertEqual(state["entries"]["toonzone:facebook:clip"]["status"], "ready")

    def test_generated_cover_is_composited_before_facebook_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_file, plan_file = root / "state.json", root / "plan.json"
            state_file.write_text(json.dumps({"entries": {"toonzone:facebook:clip": {
                "route": "toonzone", "platform": "facebook", "status": "intent"
            }}}))
            plan_file.write_text(json.dumps([{
                "route": "toonzone", "page": "ToonZone", "id": "clip",
                "name": "S01E03_Caffeinated_Concert_Tickets_Part3.mp4",
                "platforms": ["facebook"], "captions": {"facebook": "caption"},
                "generate_toonzone_cover": True,
            }]))
            def download(_, path):
                Path(path).write_bytes(b"\0\0\0\x20ftyp" + b"placeholder")
                return Path(path)
            with patch.object(runtime, "ROOT", root), \
                 patch.object(runtime, "STATE", state_file), \
                 patch.object(runtime, "PLAN", plan_file), \
                 patch.object(runtime, "load_meta_auth", return_value={"pages": [
                     {"page_name": "ToonZone", "page_token": "test"}]}), \
                 patch.object(runtime, "download", side_effect=download), \
                 patch.object(runtime, "verify_source_video", return_value=True), \
                 patch.object(runtime, "generate_part_cover") as build, \
                 patch.object(runtime, "create_instagram_cover_video") as composite, \
                 patch.object(runtime, "upload_facebook_reel", return_value="123456") as facebook:
                build.return_value = root / "S01E03_Caffeinated_Concert_Tickets_Part3.png"
                composite.side_effect = lambda source, cover, output: Path(output)
                runtime.publish()
                self.assertEqual(build.call_count, 1)
                self.assertEqual(composite.call_count, 1)
                self.assertEqual(facebook.call_count, 1)
                self.assertTrue(facebook.call_args.args[1].endswith("covered.mp4"))
            state = json.loads(state_file.read_text())
            self.assertEqual(state["entries"]["toonzone:facebook:clip"]["status"], "done")
            self.assertEqual(state["entries"]["toonzone:facebook:clip"]["post_id"], "123456")


if __name__ == "__main__":
    unittest.main()
