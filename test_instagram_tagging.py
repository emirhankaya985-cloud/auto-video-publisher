"""Offline safety tests for Instagram @mentions, hashtags and true Reel tags."""
import json
import tempfile
import unittest
from pathlib import Path

from instagram_tagging import (
    _parse_rules, enhance_instagram_caption, load_rules,
    reels_user_tags_payload,
)


class InstagramTaggingTests(unittest.TestCase):
    @staticmethod
    def approved():
        return _parse_rules({"schema": 1, "rules": [
            {"route": "film", "stem": "ronaldo_goal_01",
             "usernames": ["@cristiano"], "hashtags": ["#Ronaldo", "#CR7"]}
        ]})

    def test_no_rules_never_mutate_any_live_caption(self):
        for route in ("film", "daily_laugh", "toonzone", "tarladaki"):
            text = "Episode description\n\n#Reels"
            self.assertEqual(enhance_instagram_caption(text, route, "101", rules={}),
                             (text, []))

    def test_only_explicit_video_is_tagged(self):
        rules = self.approved()
        caption = "Cristiano Ronaldo's goal"
        changed, tags = enhance_instagram_caption(caption, "film", "ronaldo_goal_01", rules=rules)
        self.assertEqual(tags, ["cristiano"])
        self.assertIn("@cristiano", changed)
        self.assertIn("#Ronaldo", changed)
        self.assertIn("#CR7", changed)
        self.assertEqual(enhance_instagram_caption(caption, "film", "ronaldo_goal_02", rules=rules),
                         (caption, []))
        self.assertEqual(enhance_instagram_caption(caption, "toonzone", "ronaldo_goal_01", rules=rules),
                         (caption, []))

    def test_duplicate_mentions_and_tags_are_not_added(self):
        rules = self.approved()
        before = "About @Cristiano and #Ronaldo #CR7"
        after, tags = enhance_instagram_caption(before, "film", "ronaldo_goal_01", rules=rules)
        self.assertEqual(before, after)
        self.assertEqual(tags, ["cristiano"])

    def test_tagging_refuses_overlength_caption_not_silent_truncation(self):
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            enhance_instagram_caption("x" * 2200, "film", "ronaldo_goal_01", rules=self.approved())

    def test_duplicates_and_unknown_files_fail_closed(self):
        with self.assertRaises(ValueError):
            _parse_rules({"schema": 1, "rules": [
                {"route": "film", "stem": "a", "usernames": []},
                {"route": "film", "stem": "a", "usernames": ["cristiano"]},
            ]})
        with self.assertRaises(ValueError):
            _parse_rules({"schema": 1, "rules": [
                {"route": "film", "stem": "*", "usernames": ["cristiano"]}
            ]})

    def test_invalid_usernames_rejected_not_injected_to_meta(self):
        for username in ("x y", '";drop table', "@" * 30, "../secret"):
            with self.subTest(username=username):
                with self.assertRaises(ValueError):
                    reels_user_tags_payload([username])

    def test_user_tags_is_username_only_json_for_reels(self):
        payload = reels_user_tags_payload(["cristiano", "Cristiano"])
        self.assertEqual(json.loads(payload), [{"username": "cristiano"}])
        self.assertNotIn("x", json.loads(payload)[0])
        self.assertNotIn("y", json.loads(payload)[0])

    def test_empty_manifest_and_disk_config_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text('{"schema":1,"rules":[]}', encoding="utf-8")
            self.assertEqual(load_rules(path), {})
            self.assertEqual(enhance_instagram_caption("original", "film", "101", rules={}),
                             ("original", []))


if __name__ == "__main__":
    unittest.main()
