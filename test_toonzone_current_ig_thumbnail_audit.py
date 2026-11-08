"""No network: account/read-only/live-cover acceptance regression tests."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import toonzone_current_ig_thumbnail_audit as target


class ToonZoneCurrentThumbnailTests(unittest.TestCase):
    @staticmethod
    def data():
        catalog = {}
        covers = {}
        ledger = {"schema": 1, "entries": {}}
        live = []
        for e in range(1, 13):
            for p in range(1, 5):
                file = f"S01E{e:02d}_Example_Part{p}.mp4"
                key = f"source-{e}-{p}"
                catalog[file] = {"id": key, "name": file}
                if 4 <= e <= 12:
                    png = f"S01E{e:02d}_Example_Part{p}.png"
                    covers[png] = {"id": f"cover-{e}-{p}"}
                    pid = str(18000000000000000 + e * 10 + p)
                    ledger["entries"][f"toonzone:instagram:{key}"] = {
                        "route": "toonzone", "platform": "instagram",
                        "status": "done", "file": file, "post_id": pid,
                    }
                    if (e, p) in {(4, 1), (10, 4), (12, 4)}:
                        live.append({"id": pid})
        return catalog, covers, ledger, live

    def test_only_exact_current_live_ids_get_thumbnail_checked(self):
        catalog, covers, state, live = self.data()
        selection = target.select_current(catalog, state, live, covers)
        self.assertEqual(selection["archive_count"], 36)
        self.assertEqual(selection["live_id_match_count"], 3)
        self.assertEqual(selection["not_in_live_list"], 33)
        self.assertEqual([(x["episode"], x["part"]) for x in selection["entries"]],
                         [(4, 1), (10, 4), (12, 4)])

    def test_invalid_stored_identity_blocks_even_with_matching_caption(self):
        catalog, covers, state, live = self.data()
        entry = state["entries"]["toonzone:instagram:source-4-1"]
        entry["file"] = "S01E04_Example_Part2.mp4"
        with self.assertRaisesRegex(ValueError, "historical_post_ledger_mismatch"):
            target.select_current(catalog, state, live, covers)

    def test_audit_is_read_only_and_cannot_claim_unlisted_posts(self):
        catalog, covers, state, live = self.data()
        def inventory(folder):
            return catalog if folder == "14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF" else covers
        def download(_id, path):
            Image.new("RGB", (720, 960), (24, 32, 120)).save(path, "PNG")
            return path
        def thumbnail(_page, pid, observed):
            Image.new("RGB", (720, 960), (24, 32, 120)).save(observed, "JPEG")
            return {"id": pid, "media_type": "VIDEO",
                    "permalink": "https://www.instagram.com/reel/aValidReel/"}
        result = target.audit({"page_id": "1298191963387372"},
            inventory=inventory, download=download,
            graph_rows=lambda page, platform: live,
            restore=lambda: state, thumbnail=thumbnail,
            cover_distance=lambda a, b: 0.07)
        self.assertEqual(result["historical_ig_archived"], 36)
        self.assertEqual(result["archived_post_ids_in_current_ig_media_list"], 3)
        self.assertEqual(result["live_thumbnail_match_count"], 3)
        self.assertEqual(result["archived_post_ids_not_in_current_ig_media_list"], 33)
        self.assertEqual(result["remote_unlisted_posts_verified"], 0)
        self.assertTrue(result["no_meta_writes"])

    def test_mismatching_thumbnail_stays_held(self):
        catalog, covers, state, live = self.data()
        def inventory(folder):
            return catalog if folder == "14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF" else covers
        def download(_id, path):
            Image.new("RGB", (720, 960), (24, 32, 120)).save(path, "PNG")
            return path
        def thumbnail(_page, pid, observed):
            Image.new("RGB", (720, 960), (12, 13, 80)).save(observed, "JPEG")
            return {"id": pid, "media_type": "VIDEO",
                    "permalink": "https://www.instagram.com/reel/aValidReel/"}
        result = target.audit({"page_id": "1298191963387372"},
            inventory=inventory, download=download,
            graph_rows=lambda page, platform: live,
            restore=lambda: state, thumbnail=thumbnail,
            cover_distance=lambda a, b: 0.3)
        self.assertEqual(result["live_thumbnail_different_count"], 3)
        self.assertEqual(result["live_thumbnail_match_count"], 0)
        self.assertEqual(result["status"], "held_some_current_thumbnail_mismatch_or_unavailable")
        self.assertTrue(result["no_meta_writes"])


if __name__ == "__main__":
    unittest.main()
