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

    def test_future_ig_transcoded_video_first_frame_is_exact_original_cover(self):
        from PIL import ImageOps
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cover = root / "S01E12_Demo_Part1.png"
            video = root / "final-instagram.mp4"
            Image.new("RGB", (720, 960), (83, 119, 201)).save(cover, "PNG")
            video.write_bytes(b"test-only-no-Meta-POST")
            def ffmpeg_mock(_cmd, **kwargs):
                with Image.open(cover) as image:
                    expected = ImageOps.pad(image.convert("RGB"), (720, 1280),
                                            color=(0, 0, 0))
                    expected.save(Path(_cmd[-1]), "PNG")
            actual = audit.verify_prepared_instagram_first_frame(
                cover, video, runner=ffmpeg_mock)
            self.assertTrue(actual["first_frame_matches_cover"])
            self.assertLessEqual(actual["comparison_distance"], 0.12)
            self.assertEqual(actual["first_frame_width"], 720)
            self.assertEqual(actual["first_frame_height"], 1280)

    def test_future_ig_wrong_first_frame_blocks_before_any_meta_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cover = root / "S01E12_Demo_Part1.png"
            video = root / "final-instagram.mp4"
            Image.new("RGB", (720, 960), (83, 119, 201)).save(cover, "PNG")
            video.write_bytes(b"test-only-no-Meta-POST")
            def wrong_frame(_cmd, **kwargs):
                Image.new("RGB", (720, 1280), (10, 10, 10)).save(_cmd[-1], "PNG")
            with self.assertRaisesRegex(RuntimeError, "cover_held"):
                audit.verify_prepared_instagram_first_frame(
                    cover, video, runner=wrong_frame)

    def test_future_ig_missing_frame_also_blocks_before_meta(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cover = root / "S01E12_Demo_Part1.png"
            video = root / "final-instagram.mp4"
            Image.new("RGB", (720, 960), (83, 119, 201)).save(cover, "PNG")
            video.write_bytes(b"test-only-no-Meta-POST")
            with self.assertRaisesRegex(RuntimeError, "cover_held"):
                audit.verify_prepared_instagram_first_frame(
                    cover, video, runner=lambda _cmd, **kwargs: None)

    def test_main_publisher_wires_future_toonzone_cover_gate_and_offset(self):
        publisher = (Path(__file__).parent / "public_link_runtime.py").read_text()
        self.assertIn('preserve_full_cover=(item["route"] == "toonzone")', publisher)
        self.assertIn("verify_prepared_instagram_first_frame(cover, prepared_ig)", publisher)
        self.assertIn('tag_options["thumb_offset"] = 0', publisher)

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
