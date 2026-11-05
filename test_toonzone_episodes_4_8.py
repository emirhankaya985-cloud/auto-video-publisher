"""Strict mock-only ToonZone 4-8 safety checks; no real provider requests."""
import os
import unittest
from unittest.mock import patch

import toonzone_episodes_4_8 as target


class ToonZoneBatchTests(unittest.TestCase):
    def catalog(self):
        return [dict(episode=e, part=p, id=f"source-{e}-{p}",
                     name=f"S01E{e:02d}_Episode_Part{p}.mp4")
                for e in range(1, 13) for p in range(1, 5)]

    def test_exact_twenty_part_order(self):
        rows = target.selected(self.catalog())
        self.assertEqual(len(rows), 20)
        self.assertEqual([(x["episode"], x["part"]) for x in rows], target.EXPECTED)

    def test_missing_part_and_duplicate_source_fail_before_writes(self):
        with self.assertRaisesRegex(RuntimeError, "catalog"):
            target.selected([r for r in self.catalog() if (r["episode"], r["part"]) != (6, 2)])
        rows = self.catalog()
        rows[18]["id"] = rows[17]["id"]
        with self.assertRaisesRegex(RuntimeError, "source"):
            target.selected(rows)

    def test_old_and_new_caption_variants_are_detected(self):
        cases = ["ToonZone · S01E04 · Part 1/4", "Sezon 1 • Bölüm 8 • Part 4/4",
                 "Regular Show #S01E07 #Part2"]
        self.assertEqual([target.published_slot(x) for x in cases],
                         [(4, 1), (8, 4), (7, 2)])
        self.assertIsNone(target.published_slot("Sezon 1 • Bölüm 2 • Part 1/4"))

    def test_old_unaudited_post_blocks_every_new_upload(self):
        posts = [{"id": "123", "caption": "ToonZone · S01E04 · Part 1/4"}]
        with self.assertRaisesRegex(RuntimeError, "already_live"):
            target.conflicts(posts, {})

    def test_unresolved_previous_attempt_and_missing_live_post_are_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            target.conflicts([], {"key": {"status": "attempted"}})
        row = {"status": "verified", "post_id": "123", "caption": "ToonZone · S01E04 · Part 1/4"}
        with self.assertRaisesRegex(RuntimeError, "missing_from_live"):
            target.conflicts([], {"key": row})

    def test_release_needs_archived_intent_before_any_api_write(self):
        with patch.dict(os.environ, {"TOONZONE_INTENT_ARCHIVED": "false"}, clear=True), \
             self.assertRaisesRegex(RuntimeError, "not_archived"):
            target.publish("42")

    def test_no_unapproved_rights_or_release_flag(self):
        with patch.dict(os.environ, {"TOONZONE_INTENT_ARCHIVED": "true"}, clear=True), \
             self.assertRaisesRegex(RuntimeError, "release_gate_closed"):
            target.publish("42")


if __name__ == "__main__":
    unittest.main()
