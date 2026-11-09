"""Offline original-cover / provider-ID precedence regression (zero Meta writes)."""
import unittest
from toonzone_season1_gate import season1_receipts, season2_release_allowed


def fixture():
    videos, covers, entries = [], {}, {}
    fb, ig = [], []
    for ep in range(4, 13):
        for part in range(1, 5):
            name = f"S01E{ep:02d}_Owner_Part{part}.mp4"
            fid = f"video-{ep}-{part}"
            videos.append({"id": fid, "name": name})
            covers[name[:-4] + ".png"] = {"id": f"cover-{ep}-{part}"}
            for platform, live in (("facebook", fb), ("instagram", ig)):
                post_id = str(200000 + ep * 100 + part * 10 + int(platform == "instagram"))
                entries[f"toonzone:{platform}:{fid}"] = {
                    "route": "toonzone", "platform": platform, "file": name,
                    "status": "done", "post_id": post_id,
                }
                live.append({"id": post_id})
    return videos, covers, {"entries": entries}, {"facebook": fb, "instagram": ig}


class SeasonOnePriorityTests(unittest.TestCase):
    def test_seventy_two_positive_live_receipts_still_need_owner_release(self):
        args = fixture()
        report = season1_receipts(*args)
        self.assertTrue(report["all_verified"])
        self.assertEqual(report["verified_platform_receipts"], 72)
        self.assertFalse(season2_release_allowed(report))
        self.assertTrue(season2_release_allowed(report, owner_release=True))

    def test_archived_done_but_missing_provider_id_holds_season2(self):
        videos, covers, state, live = fixture()
        removed = live["instagram"].pop()
        report = season1_receipts(videos, covers, state, live)
        self.assertEqual(report["verified_platform_receipts"], 71)
        self.assertFalse(season2_release_allowed(report, owner_release=True))
        held = [x for x in report["rows"] if x["reason"]]
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]["reason"], "archived_id_not_in_live_history")
        self.assertEqual(held[0]["archived_post_id"], removed["id"])

    def test_missing_original_png_blocks_release(self):
        videos, covers, state, live = fixture()
        covers.pop("S01E04_Owner_Part1.png")
        report = season1_receipts(videos, covers, state, live)
        self.assertFalse(report["all_verified"])
        self.assertEqual({r["reason"] for r in report["rows"] if r["reason"]}, {"missing_original_cover"})

    def test_no_ledger_record_is_not_assumed_posted(self):
        videos, covers, state, live = fixture()
        state["entries"].pop("toonzone:facebook:video-4-1")
        report = season1_receipts(videos, covers, state, live)
        self.assertFalse(report["all_verified"])
        self.assertEqual(report["rows"][0]["reason"], "no_exact_done_receipt")

    def test_missing_source_and_duplicate_detected(self):
        videos, covers, state, live = fixture()
        videos.pop()
        report = season1_receipts(videos, covers, state, live)
        self.assertEqual(report["missing_or_unverified_platform_receipts"], 2)
        videos, covers, state, live = fixture()
        videos.append({"id":"alias", "name":"S01E04_Another_Part1.mp4"})
        report = season1_receipts(videos, covers, state, live)
        self.assertFalse(report["all_verified"])
        self.assertEqual(report["duplicate_source_slots"], ["S01E04 Part1"])


if __name__ == "__main__":
    unittest.main()
