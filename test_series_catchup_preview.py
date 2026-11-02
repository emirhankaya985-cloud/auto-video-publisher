"""Pure tests. No network, Meta credentials, publishing, or state mutation."""
import unittest
from datetime import date

from series_catchup_preview import plan_toonzone_catchup, film_restart_guard


def clip(episode, part):
    stem = f"S01E{episode:02d}_Demo_Part{part}"
    return {"id": f"e{episode}p{part}", "name": stem + ".mp4"}


def catalog(episodes):
    return [clip(ep, part) for ep in episodes for part in range(1, 5)]


def all_done(episode):
    rows = {}
    for part in range(1, 5):
        video = clip(episode, part)
        for platform in ("facebook", "instagram"):
            rows[f"toonzone:{platform}:{video['id']}"] = {
                "status": "done", "post_id": f"verified-{platform}-{video['id']}",
                "file": video["name"],
            }
    return rows


class PreviewTests(unittest.TestCase):
    def plan(self, videos=None, history=None, **kw):
        return plan_toonzone_catchup(
            videos if videos is not None else catalog([1, 2, 3, 4]),
            history if history is not None else {},
            start_day=date(2026, 11, 3), rejoin_episode=(1, 3), **kw,
        )

    def test_two_episodes_four_ordered_parts_each(self):
        plan = self.plan()
        self.assertEqual(plan["status"], "preview")
        self.assertEqual(plan["preview_parts"], 12)
        self.assertEqual(plan["potential_platform_posts"], 24)
        self.assertEqual([p["time_trt"] for p in plan["posts"][:8]],
                         ["12:00", "12:10", "12:20", "12:30",
                          "18:00", "18:10", "18:20", "18:30"])
        self.assertEqual([p["episode"] for p in plan["posts"][:8]], [(1, 1)]*4+[(1, 2)]*4)
        self.assertEqual(plan["posts"][8]["episode"], (1, 3))
        self.assertEqual(plan["posts"][8]["day"], "2026-11-04")
        self.assertFalse(plan["publishing_enabled"])

    def test_early_complete_episode_not_reposted(self):
        result = self.plan(history=all_done(1))
        self.assertEqual(result["skipped_verified"], [(1, 1)])
        self.assertEqual(result["posts"][0]["episode"], (1, 2))

    def test_partial_or_uncertain_episode_holds_entire_sequence(self):
        for status in ("done", "intent", "uncertain", "held"):
            with self.subTest(status=status):
                history = {"toonzone:facebook:e1p1": {
                    "status": status, "file": clip(1, 1)["name"],
                    "post_id": "123" if status == "done" else None,
                }}
                result = self.plan(history=history)
                self.assertEqual(result["status"], "held")
                self.assertEqual(result["posts"], [])
                self.assertEqual(result["held"]["episode"], (1, 1))

    def test_missing_part_and_duplicate_source_fail(self):
        missing = self.plan(videos=catalog([1])[:-1])
        self.assertEqual(missing["held"]["reason"], "missing_or_invalid_part")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.plan(videos=catalog([1]) + [clip(1, 1)])

    def test_unverified_baseline_fails_and_inputs_untouched(self):
        with self.assertRaises(ValueError):
            plan_toonzone_catchup(catalog([1]), {}, start_day=date(2026, 11, 3),
                                   rejoin_episode=None)
        history = all_done(1)
        saved = {k: v.copy() for k, v in history.items()}
        self.plan(history=history)
        self.assertEqual(history, saved)

    def test_film_requires_reconciliation(self):
        self.assertEqual(film_restart_guard({"film:facebook:a": {
            "route": "film", "status": "done", "post_id": "123"}}),
            "requires_source_and_post_id_reconciliation")
        self.assertEqual(film_restart_guard(None), "held_unknown_history")


if __name__ == "__main__":
    unittest.main()
