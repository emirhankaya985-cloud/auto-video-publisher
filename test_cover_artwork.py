import os
import struct
import unittest
from unittest.mock import patch

from cover_artwork import (CoverScope, cover_config, match_cover,
                            match_fixed_account_cover, match_toonzone_cover,
                            validate_cover)


class CoverArtworkTests(unittest.TestCase):
    def setUp(self):
        self.scope = CoverScope("cartoon_tr", "video-folder", "cover-subfolder")

    def test_feature_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(cover_config())

    def test_enabled_feature_requires_folder(self):
        with patch.dict(os.environ, {"COVER_FEATURE_ENABLED": "true"}, clear=True):
            with self.assertRaises(RuntimeError):
                cover_config()

    def test_exact_scoped_match(self):
        files = [{"id": "ok", "name": "S01E01_The_Power_Part1.jpg", "parents": ["cover-subfolder"],
                  "appProperties": {"cover_channel_key": "cartoon_tr", "cover_source_folder_id": "video-folder"}},
                 {"id": "wrong", "name": "S01E01_The_Power_Part1.jpg", "parents": ["other"],
                  "appProperties": {"cover_channel_key": "oddframes", "cover_source_folder_id": "video-folder"}}]
        self.assertEqual(match_cover(files, "S01E01_The_Power_Part1", self.scope)["id"], "ok")

    def test_normal_drive_upload_without_custom_properties_matches(self):
        files = [{"id": "ok", "name": "S01E01_The_Power_Part1.jpg", "parents": ["cover-subfolder"]}]
        self.assertEqual(match_cover(files, "S01E01_The_Power_Part1", self.scope)["id"], "ok")

    def test_fixed_account_cover_stays_in_channel_folder(self):
        files = [
            {"id": "ok", "name": "cizgifilm.jpg", "parents": ["cover-subfolder"]},
            {"id": "wrong", "name": "cizgifilm.jpg", "parents": ["other-folder"]},
        ]
        self.assertEqual(match_fixed_account_cover(files, self.scope)["id"], "ok")

    def test_duplicate_is_error(self):
        item = {"name": "clip.jpg", "parents": ["cover-subfolder"],
                "appProperties": {"cover_channel_key": "cartoon_tr", "cover_source_folder_id": "video-folder"}}
        with self.assertRaises(RuntimeError):
            match_cover([{**item, "id": "1"}, {**item, "id": "2"}], "clip", self.scope)

    def test_toonzone_requires_exact_mp4_stem(self):
        video = {"name": "S01E01_The_Power_Part1.mp4"}
        cover = {"id": "cover-1", "name": "S01E01_The_Power_Part1.png",
                 "parents": ["cover-subfolder"]}
        self.assertEqual(match_toonzone_cover(video, [cover], self.scope)["id"], "cover-1")

    def test_toonzone_missing_or_wrong_part_is_blocked(self):
        video = {"name": "S01E01_The_Power_Part1.mp4"}
        wrong = {"id": "cover-2", "name": "S01E01_The_Power_Part2.png",
                 "parents": ["cover-subfolder"]}
        with self.assertRaisesRegex(RuntimeError, "bulunamadı"):
            match_toonzone_cover(video, [wrong], self.scope)

    def test_png_3_by_4_dimensions(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 900, 1200)
        self.assertEqual(validate_cover(png, "image/png"), (900, 1200))

    def test_wrong_ratio_is_rejected(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1080, 1920)
        with self.assertRaises(ValueError):
            validate_cover(png, "image/png")


if __name__ == "__main__":
    unittest.main()
