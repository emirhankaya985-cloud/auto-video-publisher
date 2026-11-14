import unittest

import dashboard_history_migrate as migration


class HistoryMigrationTests(unittest.TestCase):
    def test_deduplication_key_keeps_video_ids_separate(self):
        base = {"period": "2026-11-13", "account": "Account", "platform": "Instagram",
                "entity_type": "video", "entity_id": "video-1", "metric": "view_count"}
        other_video = dict(base, entity_id="video-2")
        self.assertNotEqual(migration._row_key(base), migration._row_key(other_video))
        self.assertEqual(migration._row_key(base), migration._row_key(dict(base)))


if __name__ == "__main__":
    unittest.main()
