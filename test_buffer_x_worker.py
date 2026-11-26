import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from buffer_x_worker import CHANNEL_CONFIG, configured_channels, plan_artifacts


class BufferWorkerTests(unittest.TestCase):
    def test_configured_channel_mappings_enforce_free_plan_and_uniqueness(self):
        env = {"BUFFER_X_CHANNEL_ID_TARLADAKI": "x1",
               "BUFFER_X_CHANNEL_ID_FILM": "x2",
               "BUFFER_X_CHANNEL_ID_FILM_SAHNELERI": "x3"}
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(len(configured_channels()), 3)
        with patch.dict("os.environ", {**env, "BUFFER_X_CHANNEL_ID_TOONZONE": "x4"}, clear=True):
            with self.assertRaisesRegex(Exception, "free_channel_limit_exceeded"):
                configured_channels()
        with patch.dict("os.environ", {"BUFFER_X_CHANNEL_ID_FILM": "same",
                                       "BUFFER_X_CHANNEL_ID_TOONZONE": "same"}, clear=True):
            with self.assertRaisesRegex(Exception, "duplicate_channel_mapping"):
                configured_channels()

    def test_plan_reader_accepts_only_known_routes(self):
        import json
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "link-state-intent-film"
            folder.mkdir()
            (folder / "plan.json").write_text(json.dumps([
                {"route": "film", "id": "file-1"},
                {"route": "unknown", "id": "file-2"}]), encoding="utf-8")
            rows = plan_artifacts(Path(tmp))
        self.assertEqual([(scope, item["id"]) for scope, item in rows], [("film", "file-1")])

    def test_film_scenes_route_is_separate(self):
        self.assertIn("film_sahneleri", CHANNEL_CONFIG)
        self.assertEqual(CHANNEL_CONFIG["film_sahneleri"][1], "FILM_SAHNELERI")


if __name__ == "__main__":
    unittest.main()
