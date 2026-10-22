import unittest
from unittest.mock import Mock

from ordered_channels import (
    CHANNELS,
    analyze_files,
    assert_publish_ready,
    next_ready_pair,
    parse_order,
    toonzone_publication_state,
    toonzone_metadata,
)


def pair(stem, properties=None, with_txt=True):
    files = [{"id": stem, "name": stem + ".mp4", "appProperties": properties or {}}]
    if with_txt:
        files.append({"id": stem + "-txt", "name": stem + ".txt"})
    return files


class OrderedChannelTests(unittest.TestCase):
    def test_toonzone_metadata_uses_ten_minute_part_slots(self):
        self.assertEqual(toonzone_metadata("S01E01_The_Power_Part1"), {
            "season": 1, "episode": 1, "part": 1,
            "title": "The Power — Part 1",
            "description": "The Power | Sezon 1, Bölüm 1. Bu bölümde neler olduğunu yorumlarda paylaş!\n\n#RegularShow #ToonZone #ÇizgiFilm #Cartoon #S01E01\n\nEtsy: https://www.etsy.com/shop/MiroviaStudio?ref=dashboard-header",
            "minute": 0,
        })
        self.assertEqual(toonzone_metadata("S01E01_The_Power_Part4")["minute"], 30)
        self.assertEqual(
            toonzone_metadata("S01E01_The_Power_Part1")["description"],
            toonzone_metadata("S01E01_The_Power_Part4")["description"],
        )

    def test_toonzone_rejects_parts_outside_one_to_four(self):
        with self.assertRaises(ValueError):
            toonzone_metadata("S01E01_The_Power_Part5")

    def test_toonzone_publication_state_exposes_only_nonempty_safe_markers(self):
        history_key = CHANNELS["cartoon_tr"].history_key
        video = {"appProperties": {
            history_key: "1", "claimed_route_slot": "manual-test",
            "claimed_at": "2026-10-19T00:00:00+03:00", "secret": "never report",
            "done_ig_slot": "", "result_fb": "public-post-id",
        }}
        self.assertEqual(toonzone_publication_state(video), {
            history_key: "1", "claimed_route_slot": "manual-test",
            "claimed_at": "2026-10-19T00:00:00+03:00", "result_fb": "public-post-id",
        })

    def test_film_orders_by_title_then_numeric_part(self):
        stems = ["Avanak_Apti_Part_10", "Avanak_Apti_Part_2", "Avanak_Apti_Part_1"]
        files = sum((pair(stem) for stem in stems), [])
        ordered = analyze_files(files, CHANNELS["film_primary"])["ordered"]
        self.assertEqual([row[1] for row in ordered], [stems[2], stems[1], stems[0]])

    def test_cartoon_orders_season_episode_part(self):
        stems = [
            "S02E01_New_Show_Part1", "S01E02_Just_Set_Up_The_Chairs_Part1",
            "S01E01_The_Power_Part2", "S01E01_The_Power_Part1",
        ]
        files = sum((pair(stem) for stem in stems), [])
        ordered = analyze_files(files, CHANNELS["cartoon_tr"])["ordered"]
        self.assertEqual([row[1] for row in ordered], [stems[3], stems[2], stems[1], stems[0]])

    def test_missing_txt_is_reported_and_never_selected(self):
        files = pair("Avanak_Apti_Part_1", with_txt=False) + pair("Avanak_Apti_Part_2")
        report = analyze_files(files, CHANNELS["film_primary"])
        self.assertEqual(report["missing_txt"], ["Avanak_Apti_Part_1"])
        self.assertEqual(next_ready_pair(files, "film_primary")[1], "Avanak_Apti_Part_2")

    def test_film_with_missing_middle_part_is_blocked(self):
        files = pair("Avanak_Apti_Part_1") + pair("Avanak_Apti_Part_3")
        report = analyze_files(files, CHANNELS["film_primary"])
        self.assertEqual(report["blocked_series"], ["avanak apti"])
        self.assertIsNone(next_ready_pair(files, "film_primary"))

    def test_duplicate_drive_names_are_reported(self):
        files = pair("Avanak_Apti_Part_1") + [{"id":"copy", "name":"Avanak_Apti_Part_1.mp4", "appProperties":{}}]
        report = analyze_files(files, CHANNELS["film_primary"])
        self.assertEqual(report["duplicate_names"], ["Avanak_Apti_Part_1"])

    def test_part_suffix_variant_is_duplicate_only_with_matching_checksum(self):
        files = [
            {"id":"a", "name":"Movie_Part_1.mp4", "md5Checksum":"same", "appProperties":{}},
            {"id":"b", "name":"Movie_Part_1_2.mp4", "md5Checksum":"same", "appProperties":{}},
            {"id":"c", "name":"Movie_Part_2_2.mp4", "md5Checksum":"different", "appProperties":{}},
            {"id":"t", "name":"Movie_Part_1.txt"},
        ]
        report = analyze_files(files, CHANNELS["film_primary"])
        self.assertEqual(report["duplicate_variants"], ["Movie_Part_1_2"])
        self.assertEqual(report["invalid_names"], ["Movie_Part_2_2"])

    def test_shared_cartoon_folder_has_independent_history(self):
        tr_key = CHANNELS["cartoon_tr"].history_key
        files = pair("S01E01_The_Power_Part1", {tr_key: "1", "oddframes_language_verified": "1"})
        self.assertIsNone(next_ready_pair(files, "cartoon_tr"))
        self.assertIsNotNone(next_ready_pair(files, "oddframes"))
        self.assertNotEqual(CHANNELS["cartoon_tr"].history_key, CHANNELS["oddframes"].history_key)

    def test_oddframes_blocks_unverified_language(self):
        files = pair("S01E01_The_Power_Part1")
        self.assertIsNone(next_ready_pair(files, "oddframes"))
        files[0]["appProperties"]["oddframes_language_verified"] = "1"
        self.assertIsNotNone(next_ready_pair(files, "oddframes"))

    def test_real_publish_is_disabled_without_complete_account_config(self):
        for config in (None, {}, {"enabled": False}, {"enabled": True, "platform": "facebook"}):
            with self.subTest(config=config), self.assertRaisesRegex(RuntimeError, "devre dışı|tamamlanmadı"):
                assert_publish_ready("film_primary", config)

    def test_oddframes_requires_explicit_english_policy(self):
        config = {"enabled": True, "platform": "instagram", "account_id": "id", "account_name": "OddFrames"}
        with self.assertRaisesRegex(RuntimeError, "İngilizce"):
            assert_publish_ready("oddframes", config)

    def test_expected_name_patterns(self):
        self.assertEqual(parse_order("Avanak_Apti_Part_3", "film"), ("avanak apti", 3))
        self.assertEqual(parse_order("S01E01_The_Power_Part4", "cartoon"), (1, 1, 4, "the power"))
        self.assertIsNone(parse_order("random.mp4", "cartoon"))


if __name__ == "__main__":
    unittest.main()
