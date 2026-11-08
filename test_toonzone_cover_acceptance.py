"""Mock-only cover validation: no Google Drive or Meta network requests."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import toonzone_cover_acceptance as audit


class CoverAcceptanceTests(unittest.TestCase):
    @staticmethod
    def catalog():
        return {
            f"S01E{e:02d}_Unit_Test_Part{p}.mp4":
            {"id": f"original-source-{e}-{p}", "name": f"S01E{e:02d}_Unit_Test_Part{p}.mp4"}
            for e in range(1, 13) for p in range(1, 5)
        }

    @staticmethod
    def fake_covers():
        return {
            f"S01E{e:02d}_Unit_Test_Part{p}.png":
            {"id": f"approved-cover-{e}-{p}"}
            for e in range(4, 13) for p in range(1, 5)
        }

    @staticmethod
    def download(cover_id, dest):
        _, _, episode, part = cover_id.split("-")
        episode, part = int(episode), int(part)
        Image.new("RGB", (720, 960),
                  color=(episode * 17 % 255, part * 47 % 255,
                         (episode + part) * 19 % 255)).save(dest, format="PNG")
        return dest

    def test_exact_all_36_png_bytes_verified_with_zero_meta_writes(self):
        result = audit.assess(self.catalog(), self.fake_covers(), download=self.download)
        self.assertEqual(result["requested_parts"], 36)
        self.assertEqual(result["exact_cover_names_matched"], 36)
        self.assertEqual(result["verified_png_bytes"], 36)
        self.assertTrue(result["all_exact_png_bytes_accepted"])
        self.assertEqual(result["duplicate_png_sha256_groups"], [])
        self.assertEqual(result["meta_writes"], 0)
        self.assertFalse(result["remote_instagram_thumbnail_verified"])
        self.assertFalse(result["source_mp4_content_verified"])

    def test_missing_cover_is_held(self):
        covers = self.fake_covers()
        covers.pop("S01E09_Unit_Test_Part2.png")
        result = audit.assess(self.catalog(), covers, download=self.download)
        self.assertEqual(result["verified_png_bytes"], 35)
        self.assertFalse(result["all_exact_png_bytes_accepted"])
        self.assertEqual(result["exact_cover_names_matched"], 35)

    def test_invalid_image_payload_blocks_acceptance(self):
        def bad_download(cover_id, dest):
            if cover_id == "approved-cover-4-1":
                Path(dest).write_bytes(b"not-a-PNG" * 100)
                return dest
            return self.download(cover_id, dest)
        result = audit.assess(self.catalog(), self.fake_covers(), download=bad_download)
        self.assertEqual(result["verified_png_bytes"], 35)
        self.assertFalse(result["all_exact_png_bytes_accepted"])
        bad = next(x for x in result["parts"] if x["episode"] == 4 and x["part"] == 1)
        self.assertEqual(bad["reason"], "cover_download_or_image_validation_failed")

    def test_identical_cover_bytes_for_different_parts_are_not_accepted(self):
        def duplicate_download(cover_id, dest):
            if cover_id == "approved-cover-4-2":
                return self.download("approved-cover-4-1", dest)
            return self.download(cover_id, dest)
        result = audit.assess(self.catalog(), self.fake_covers(), download=duplicate_download)
        self.assertEqual(result["verified_png_bytes"], 36)
        self.assertFalse(result["all_exact_png_bytes_accepted"])
        self.assertEqual(result["duplicate_png_sha256_groups"],
                         [["S01E04-Part1", "S01E04-Part2"]])

    def test_wrong_file_name_is_not_assumed_matched(self):
        covers = self.fake_covers()
        covers["S01E04_Unit_Test_Part1.png"] = {"id": ""}
        result = audit.assess(self.catalog(), covers, download=self.download)
        self.assertEqual(result["verified_png_bytes"], 35)
        self.assertEqual(result["exact_cover_names_matched"], 35)


if __name__ == "__main__":
    unittest.main()
