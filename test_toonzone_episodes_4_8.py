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

    def test_live_reservation_writes_archive_compatible_with_restore_schema(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock

        import publisher_alert_history as history
        from public_link_runtime import FOLDERS

        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cover_files = {
                Path(row["name"]).stem + ".png": {"id": "cover-" + row["id"]}
                for row in self.catalog() if 4 <= row["episode"] <= 8
            }
            def download_cover(file_id, output):
                path = Path(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("cover=" + file_id).encode("utf-8"))
                return path

            with patch.dict(os.environ, {"TOONZONE_RIGHTS_APPROVED": "true",
                                         "TOONZONE_RELEASE_4_8": "true"}, clear=True), \
                 patch.object(target, "ROOT", folder), \
                 patch.object(target, "HISTORY", folder / "alert-history.json"), \
                 patch.object(target, "PLAN", folder / "plan.json"), \
                 patch.object(target, "REPORT", folder / "audit.json"), \
                 patch.object(target, "page_for_toonzone", return_value={"page_id": "123"}), \
                 patch.object(target, "instagram_identity", return_value=target.ACCOUNT_ID), \
                 patch.object(target, "ordered_catalog", return_value=self.catalog()), \
                 patch.object(target, "text_for", side_effect=lambda x: f"S01E{x['episode']:02d} Part{x['part']}"), \
                 patch.object(history, "restore", return_value={"schema": 1, "records": {}}), \
                 patch("public_link_runtime.inventory", side_effect=lambda x: cover_files if x == FOLDERS["covers"] else {}), \
                 patch("public_link_runtime.graph_rows", return_value=[]), \
                 patch("public_link_runtime.download", side_effect=download_cover), \
                 patch("public_link_runtime.probe", return_value={"streams": [{"codec_type": "video", "width": 720}]}):
                result = target.audit("20261106", reserve=True)
            validated = history.validate(json.loads((folder / "alert-history.json").read_text()))
            self.assertEqual(result["prepared_parts"], 20)
            self.assertEqual(len(validated["records"]), 20)
            self.assertTrue(all(record["last_seen"].endswith("+00:00")
                                for record in validated["records"].values()))
            self.assertEqual(len(json.loads((folder / "plan.json").read_text())["plans"]), 20)

    def test_artifact_contract_persists_exact_history_member_separately(self):
        from pathlib import Path
        content = Path(".github/workflows/toonzone_episodes_4_8.yml").read_text()
        self.assertIn("name: toonzone-4-8-intent", content)
        self.assertIn("name: toonzone-4-8-result", content)
        self.assertIn("name: toonzone-4-8-summary", content)
        self.assertEqual(content.count("path: toonzone-4-8-runtime/alert-history.json"), 2)
        self.assertNotIn("toonzone-4-8-runtime/history.json", content)

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
