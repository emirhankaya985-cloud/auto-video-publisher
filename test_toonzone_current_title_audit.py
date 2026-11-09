"""No-network proof that live ToonZone titles match exact original sources."""
import unittest

import toonzone_current_title_audit as target


def fixture():
    catalog = {}
    state = {"schema": 1, "entries": {}}
    live = {"facebook": [], "instagram": []}
    for episode in range(1, 13):
        for part in range(1, 5):
            name = f"S01E{episode:02d}_Example_Part{part}.mp4"
            source = f"src-{episode}-{part}"
            catalog[name] = {"id": source, "name": name}
            if episode < 4:
                continue
            for platform in live:
                post_id = str(1000000 + episode * 100 + part + (2000000 if platform == "instagram" else 0))
                state["entries"][f"toonzone:{platform}:{source}"] = {
                    "route": "toonzone", "platform": platform, "file": name,
                    "post_id": post_id, "status": "done",
                }
                if (episode, part, platform) in {(4, 1, "facebook"),
                                                  (4, 2, "facebook"),
                                                  (4, 1, "instagram")}:
                    first, second = target.expected_lines(name)
                    caption = first + "\n" + (second if part == 1 else
                                               "📺 Sezon 1 • Bölüm 4 • Part 4/4")
                    live[platform].append({"id": post_id,
                                           "description": caption, "caption": caption})
    return catalog, state, live


class ToonZoneTitleAuditTests(unittest.TestCase):
    def test_correct_identity_title_and_part_are_required(self):
        catalog, state, live = fixture()
        report = target.audit(catalog, state, live)
        self.assertEqual(report["historical_receipts"], 72)
        self.assertEqual(report["verified_canonical_title_and_part"], 2)
        self.assertEqual(report["facebook"]["canonical_title_and_part"], 1)
        self.assertEqual(report["facebook"]["noncanonical_live_title_or_part"], 1)
        self.assertEqual(report["facebook"]["historic_id_not_in_current_list"], 34)
        self.assertEqual(report["instagram"]["canonical_title_and_part"], 1)
        self.assertEqual(report["instagram"]["historic_id_not_in_current_list"], 35)
        self.assertFalse(report["unlisted_post_id_means_deleted"])
        self.assertEqual(report["meta_post_attempts"], 0)
        self.assertFalse(any("token" in str(x) for x in report["entries"]))

    def test_missing_caption_is_not_success(self):
        catalog, state, live = fixture()
        live["instagram"][0].pop("caption")
        report = target.audit(catalog, state, live)
        self.assertEqual(report["instagram"]["live_caption_unavailable"], 1)

    def test_archived_source_conflicts_fail_closed(self):
        catalog, state, live = fixture()
        state["entries"]["toonzone:facebook:src-4-1"]["file"] = "wrong.mp4"
        with self.assertRaisesRegex(ValueError, "missing_original_post_receipt"):
            target.audit(catalog, state, live)

    def test_duplicate_live_id_fails_closed(self):
        catalog, state, live = fixture()
        live["facebook"].append(dict(live["facebook"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate_or_invalid"):
            target.audit(catalog, state, live)

    def test_english_title_is_not_canonical_turkish_title(self):
        file = "S01E04_Death_Punchies_Part1.mp4"
        title, marker = target.expected_lines(file)
        self.assertEqual(title, "🎬 Regular Show | Ölüm Yumrukları")
        self.assertEqual(marker, "📺 Sezon 1 • Bölüm 4 • Part 1/4")


if __name__ == "__main__":
    unittest.main()
