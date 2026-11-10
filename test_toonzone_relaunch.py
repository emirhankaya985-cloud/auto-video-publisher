"""Regression checks: archive, prior Meta POST or publisher state never reset."""
import unittest
import toonzone_relaunch as rel


class RelaunchSafetyTests(unittest.TestCase):
    def test_approval_only_on_owner_main_first_attempt(self):
        env = {"GITHUB_REPOSITORY": rel.REPO, "GITHUB_REF": "refs/heads/main",
               "GITHUB_RUN_ATTEMPT": "1", "TOONZONE_RELAUNCH_APPROVED": "true"}
        self.assertTrue(rel.allowed_context(env))
        for key in env:
            wrong = dict(env)
            wrong[key] = "false"
            self.assertFalse(rel.allowed_context(wrong))

    def test_order_only_part1_to_4(self):
        rows = [{"episode": episode, "part": part, "id": f"{episode}-{part}",
                 "name": f"S01E{episode:02d}_Name_Part{part}.mp4"}
                for episode in range(4, 13) for part in range(1, 5)]
        self.assertEqual([r["part"] for r in rel.ordered_episode(rows)[:4]], [1, 2, 3, 4])
        self.assertEqual(len(rel.ordered_episode(rows)), 36)
        with self.assertRaises(RuntimeError):
            rel.ordered_episode(rows[:-1])
        with self.assertRaises(RuntimeError):
            rel.ordered_episode(rows + [rows[0]])

    def test_pending_or_unrecognized_posts_never_auto_retry(self):
        for status in ("attempted", "reserved", "held"):
            self.assertTrue(rel.state_for({"status": status, "post_id": ""}, []).startswith("held"))
        self.assertEqual(rel.state_for({"status": "accepted_unverified", "post_id": "11"}, []),
                         "held_remote_id_unverified")
        self.assertEqual(rel.state_for({"status": "accepted_unverified", "post_id": "11"}, [{"id": "11"}]),
                         "verified")

    def test_duplicate_caption_holds_even_if_previous_id_absent(self):
        with self.assertRaises(RuntimeError):
            rel.validate_remote([{"id": "101", "caption": "x"}], "x", None)
        with self.assertRaises(RuntimeError):
            rel.validate_remote([{"id": "101", "caption": "x"}], "x", {"post_id": "102"})
        self.assertEqual(len(rel.validate_remote([{"id": "101", "caption": "x"}], "x",
                                                 {"post_id": "101"})), 1)


if __name__ == "__main__":
    unittest.main()
