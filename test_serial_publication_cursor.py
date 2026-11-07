import unittest

from serial_publication_cursor import derive_serial_cursor


def entry(route, platform, name, status="done", post_id=None):
    return {"route": route, "platform": platform, "file": name,
            "status": status, "post_id": post_id}


class SerialPublicationCursorTests(unittest.TestCase):
    def test_platform_specific_and_ignores_unordered_daily_laugh(self):
        state = {"entries": {
            "a": entry("toonzone", "facebook", "S01E04_Test_Part1.mp4", post_id="fb1"),
            "b": entry("toonzone", "facebook", "S01E04_Test_Part2.mp4", post_id="fb2"),
            "c": entry("toonzone", "instagram", "S01E04_Test_Part1.mp4", post_id="ig1"),
            "d": entry("toonzone", "instagram", "S01E04_Test_Part2.mp4", "uncertain"),
            "e": entry("daily_laugh", "facebook", "anything_Part1.mp4", post_id="dl"),
        }}
        cursor = derive_serial_cursor(state)
        self.assertEqual(cursor["toonzone:facebook:S01E04"]["last_verified_part"], 2)
        self.assertEqual(cursor["toonzone:instagram:S01E04"]["last_verified_part"], 1)
        self.assertEqual(cursor["toonzone:instagram:S01E04"]["first_unverified_part"], 2)
        self.assertFalse(any("daily_laugh" in name for name in cursor))

    def test_missing_id_does_not_advance_and_gaps_remain_visible(self):
        state = {"entries": {
            "a": entry("film", "instagram", "Avanak_Apti_Part_1.mp4", post_id="p1"),
            "b": entry("film", "instagram", "Avanak_Apti_Part_2.mp4", "done"),
            "c": entry("film", "instagram", "Avanak_Apti_Part_3.mp4", post_id="p3"),
        }}
        record = derive_serial_cursor(state)["film:instagram:avanak apti"]
        self.assertEqual(record["last_verified_part"], 3)
        self.assertEqual(record["first_unverified_part"], 2)
        self.assertEqual(record["held_parts"], [2])

    def test_no_confirmed_post_keeps_cursor_empty(self):
        state = {"entries": {
            "a": entry("film_second", "facebook", "Film_Part_1.mp4", "intent")
        }}
        cursor = derive_serial_cursor(state)["film_second:facebook:film"]
        self.assertIsNone(cursor["last_verified_part"])
        self.assertEqual(cursor["first_unverified_part"], 1)


if __name__ == "__main__":
    unittest.main()
