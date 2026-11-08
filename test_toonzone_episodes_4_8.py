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

    def test_historical_72_receipts_do_not_imply_current_visibility(self):
        catalog = self.catalog()
        state = {"schema": 1, "entries": {}}
        for item in catalog:
            if not (4 <= item["episode"] <= 12):
                continue
            for platform in ("facebook", "instagram"):
                pid = str(1000000000000000
                          + item["episode"] * 1000 + item["part"] * 10
                          + (1 if platform == "facebook" else 2))
                state["entries"][f"toonzone:{platform}:{item['id']}"] = {
                    "route": "toonzone", "platform": platform,
                    "status": "done", "file": item["name"],
                    "run_id": "40000123456", "post_id": pid,
                }
        count = target.historical_season_receipts(catalog, state)
        self.assertEqual(count["historical_facebook_done_with_id"], 36)
        self.assertEqual(count["historical_instagram_done_with_id"], 36)
        self.assertEqual(count["historical_total_done_with_id"], 72)
        self.assertTrue(count["historical_complete_72"])
        self.assertFalse(count["historical_means_currently_visible"])
        self.assertEqual(count["historical_missing_receipts"], [])
        first = next(item for item in catalog if item["episode"] == 4 and item["part"] == 1)
        ig = state["entries"][f"toonzone:instagram:{first['id']}"]["post_id"]
        fb = state["entries"][f"toonzone:facebook:{first['id']}"]["post_id"]
        instagram = target.current_provider_receipt_visibility(
            catalog, state, [{"id": ig}], "instagram")
        facebook = target.current_provider_receipt_visibility(
            catalog, state, [{"id": fb}], "facebook")
        self.assertEqual(instagram["instagram_historical_ids_present_in_live_list"], 1)
        self.assertEqual(instagram["instagram_historical_ids_absent_from_live_list"], 35)
        self.assertEqual(facebook["facebook_historical_ids_present_in_live_list"], 1)
        self.assertFalse(instagram["instagram_absent_proves_deleted"])
        self.assertFalse(facebook["facebook_absent_proves_deleted"])

    def test_missing_receipt_and_duplicate_history_are_not_accepted(self):
        catalog = self.catalog()
        state = {"schema": 1, "entries": {}}
        for item in catalog:
            if not 4 <= item["episode"] <= 12:
                continue
            for platform in ("facebook", "instagram"):
                state["entries"][f"toonzone:{platform}:{item['id']}"] = {
                    "route": "toonzone", "platform": platform,
                    "status": "done", "file": item["name"],
                    "run_id": "40000123456",
                    "post_id": str(item["episode"] * 1000 + item["part"] * 10 +
                                   (1 if platform == "facebook" else 2)),
                }
        first = next(row for row in catalog if row["episode"] == 4 and row["part"] == 1)
        state["entries"].pop(f"toonzone:facebook:{first['id']}")
        report = target.historical_season_receipts(catalog, state)
        self.assertEqual(report["historical_total_done_with_id"], 71)
        self.assertFalse(report["historical_complete_72"])
        self.assertEqual(report["historical_missing_receipts"],
                         ["S01E04 Part1 facebook"])
        state["entries"][f"toonzone:facebook:{first['id']}"] = {
            "route": "toonzone", "platform": "facebook", "status": "done",
            "file": first["name"], "run_id": "40000123456", "post_id": "4011",
        }
        another = next(row for row in catalog if row["episode"] == 4 and row["part"] == 2)
        state["entries"][f"toonzone:facebook:{another['id']}"]["post_id"] = "4011"
        with self.assertRaisesRegex(RuntimeError, "duplicate_post_id"):
            target.historical_season_receipts(catalog, state)

    def test_owner_4_12_inventory_has_thirty_six_exact_cover_names(self):
        from pathlib import Path
        catalog = self.catalog()
        covers = {Path(item["name"]).stem + ".png": {"id": "cover-" + item["id"]}
                  for item in catalog if 4 <= item["episode"] <= 12}
        report = target.season_inventory_coverage(catalog, covers)
        self.assertEqual(report["requested_4_12_parts"], 36)
        self.assertEqual(report["source_names_found_4_12"], 36)
        self.assertEqual(report["cover_names_found_4_12"], 36)
        self.assertFalse(report["cover_bytes_verified_4_12"])
        self.assertEqual(report["missing_cover_names_4_12"], [])
        del covers["S01E09_Episode_Part2.png"]
        missing = target.season_inventory_coverage(catalog, covers)
        self.assertEqual(missing["cover_names_found_4_12"], 35)
        self.assertEqual(missing["missing_cover_names_4_12"], ["S01E09_Episode_Part2.png"])

    def test_facebook_caption_candidate_cannot_prove_publication(self):
        rows = [{"id": "1", "description": "ToonZone · S01E04 · Part 1/4"},
                {"id": "2", "description": "ToonZone · S01E12 · Part 4/4"},
                {"id": "3", "description": "S01E13 Part1"},
                {"id": "4", "description": "S01E12 Part4"}]
        result = target.facebook_caption_candidates(rows)
        self.assertEqual(result["facebook_caption_candidate_count_4_12"], 2)
        self.assertFalse(result["facebook_source_identity_verified"])
        self.assertEqual(result["facebook_caption_candidate_slots_4_12"],
                         ["S01E04 Part1", "S01E12 Part4"])

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
                 patch("public_link_runtime.restore", return_value={"schema": 1, "entries": {}}), \
                 patch("public_link_runtime.download", side_effect=download_cover), \
                 patch("public_link_runtime.download_verified_publication_video", side_effect=download_cover), \
                 patch("public_link_runtime.probe", return_value={"streams": [{"codec_type": "video", "width": 720}]}):
                result = target.audit("20261106", reserve=True)
            validated = history.validate(json.loads((folder / "alert-history.json").read_text()))
            self.assertEqual(result["prepared_parts"], 20)
            self.assertEqual(len(validated["records"]), 20)
            self.assertEqual(result["source_files_verified"], 20)
            self.assertTrue(all(len(row["source_sha256"]) == 64 for row in validated["records"].values()))
            self.assertTrue(all(record["last_seen"].endswith("+00:00")
                                for record in validated["records"].values()))
            self.assertEqual(len(json.loads((folder / "plan.json").read_text())["plans"]), 20)

    def test_last_source_failure_stops_full_preflight_without_mutating_catalog(self):
        from pathlib import Path
        rows = target.selected(self.catalog())
        calls = []
        def source_read(identity, path):
            calls.append(identity)
            if len(calls) == 20:
                raise RuntimeError("source_unreadable")
            Path(path).write_bytes(identity.encode())
            return Path(path)
        with patch("public_link_runtime.download_verified_publication_video", side_effect=source_read), \
             self.assertRaisesRegex(RuntimeError, "source_unreadable"):
            target.preflight_sources(rows)
        self.assertEqual(len(calls), 20)
        self.assertTrue(all("source_sha256" not in row for row in rows))

    def test_replaced_source_or_missing_reserved_hash_cannot_reach_upload(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"approved source")
            expected = target.digest(source)
            item, record = {"source_sha256": expected}, {"source_sha256": expected}
            target.verify_reserved_source(source, item, record)
            source.write_bytes(b"replaced under same Drive ID")
            with self.assertRaisesRegex(RuntimeError, "source_changed"):
                target.verify_reserved_source(source, item, record)
            with self.assertRaisesRegex(RuntimeError, "source_changed"):
                target.verify_reserved_source(source, item, {})
            self.assertEqual(record["source_sha256"], expected)

    def test_artifact_contract_persists_exact_history_member_separately(self):
        from pathlib import Path
        content = Path(".github/workflows/toonzone_episodes_4_8.yml").read_text()
        self.assertIn("name: toonzone-4-8-intent", content)
        self.assertIn("name: toonzone-4-8-result", content)
        self.assertIn("name: toonzone-4-8-summary", content)
        self.assertEqual(content.count("path: toonzone-4-8-runtime/alert-history.json"), 2)
        self.assertNotIn("toonzone-4-8-runtime/history.json", content)

    def test_release_shares_normal_publisher_lock_and_keeps_rights_gates(self):
        from pathlib import Path
        import yaml
        release = yaml.safe_load(Path(".github/workflows/toonzone_episodes_4_8.yml").read_text())
        normal = yaml.safe_load(Path(".github/workflows/public_link_schedule.yml").read_text())
        job = release["jobs"]["publish"]
        self.assertEqual(job["concurrency"]["group"], normal["concurrency"]["group"])
        self.assertIs(job["concurrency"]["cancel-in-progress"], False)
        self.assertIn("vars.TOONZONE_RIGHTS_APPROVED == 'true'", job["if"])
        self.assertIn("github.run_attempt == 1", job["if"])

    def test_audit_authorization_only_after_both_release_gates(self):
        for reserve, env, expected in (
            (False, {"TOONZONE_RIGHTS_APPROVED": "true",
                     "TOONZONE_RELEASE_4_8": "true"}, False),
            (True, {}, False),
            (True, {"TOONZONE_RIGHTS_APPROVED": "true"}, False),
            (True, {"TOONZONE_RELEASE_4_8": "true"}, False),
            (True, {"TOONZONE_RIGHTS_APPROVED": "true",
                    "TOONZONE_RELEASE_4_8": "true"}, True),
        ):
            with self.subTest(reserve=reserve, env=env):
                self.assertIs(target.release_authorized(reserve, environ=env), expected)

    def test_release_needs_archived_intent_before_any_api_write(self):
        with patch.dict(os.environ, {"TOONZONE_INTENT_ARCHIVED": "false"}, clear=True), \
             self.assertRaisesRegex(RuntimeError, "not_archived"):
            target.publish("42")

    def test_no_unapproved_rights_or_release_flag(self):
        with patch.dict(os.environ, {"TOONZONE_INTENT_ARCHIVED": "true"}, clear=True), \
             self.assertRaisesRegex(RuntimeError, "release_gate_closed"):
            target.publish("42")


    def test_main_publisher_ledger_recognizes_live_id_even_with_old_caption(self):
        items = target.selected(self.catalog())
        first = items[0]
        state = {"schema": 1, "entries": {
            f"toonzone:instagram:{first['id']}": {
                "route": "toonzone", "platform": "instagram", "file": first["name"],
                "status": "done", "post_id": "18100507712530539"
            }
        }}
        # Older regular-publisher captions need not carry this campaign's S01E marker.
        live = [{"id": "18100507712530539", "caption": "Older original caption"}]
        main = target.main_publisher_posts(items, live, state)
        self.assertEqual(main, {(4, 1): "18100507712530539"})
        self.assertEqual(target.conflicts(live, {}, main), {(4, 1)})
        # Original caption carries no campaign slot marker: old campaign
        # alone incorrectly sees zero posts. The main-ledger proof closes it.
        self.assertEqual(target.conflicts(live, {}), set())
        with self.assertRaisesRegex(RuntimeError, "already_live"):
            target.conflicts(
                [{"id": "18100507712530539", "caption": "S01E04 Part 1"}], {})

    def test_main_publisher_record_cannot_be_reposted_if_unresolved_or_not_live(self):
        items = target.selected(self.catalog())
        first = items[0]
        original = {"route": "toonzone", "platform": "instagram",
                    "file": first["name"], "status": "done", "post_id": "123"}
        key = f"toonzone:instagram:{first['id']}"
        live = [{"id": "123", "caption": "Original regular publisher text"}]
        for change, expected in (
            ({"status": "uncertain"}, "prior_intent_unresolved"),
            ({"file": "Wrong_Part1.mp4"}, "source_identity_conflict"),
            ({"post_id": None}, "prior_intent_unresolved"),
            ({"platform": "facebook"}, "source_identity_conflict"),
        ):
            with self.subTest(change=change):
                entry = dict(original, **change)
                with self.assertRaisesRegex(RuntimeError, expected):
                    target.main_publisher_posts(
                        items, live, {"schema": 1, "entries": {key: entry}})
        with self.assertRaisesRegex(RuntimeError, "post_missing_from_live"):
            target.main_publisher_posts(
                items, [], {"schema": 1, "entries": {key: original}})
        with self.assertRaisesRegex(RuntimeError, "ledger_unavailable"):
            target.main_publisher_posts(items, live, {"entries": {}})
        with self.assertRaisesRegex(RuntimeError, "caption_slot_mismatch"):
            target.main_publisher_posts(
                items, [{"id": "123", "caption": "S01E05 Part 2"}],
                {"schema": 1, "entries": {key: original}})

    def test_existing_twenty_regular_posts_mean_zero_new_reservations(self):
        import json
        import tempfile
        from pathlib import Path
        import publisher_alert_history as history

        selected = target.selected(self.catalog())
        live = []
        entries = {}
        for i, item in enumerate(selected):
            pid = str(18000000000000000 + i)
            live.append({"id": pid, "caption": "Older text without campaign marker"})
            entries[f"toonzone:instagram:{item['id']}"] = {
                "route": "toonzone", "platform": "instagram", "status": "done",
                "file": item["name"], "post_id": pid,
            }
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.dict(os.environ, {"TOONZONE_RIGHTS_APPROVED": "true",
                                         "TOONZONE_RELEASE_4_8": "true"}, clear=True), \
                 patch.object(target, "ROOT", root), \
                 patch.object(target, "HISTORY", root / "alert-history.json"), \
                 patch.object(target, "PLAN", root / "plan.json"), \
                 patch.object(target, "REPORT", root / "audit.json"), \
                 patch.object(target, "page_for_toonzone", return_value={"page_id": "123"}), \
                 patch.object(target, "instagram_identity", return_value=target.ACCOUNT_ID), \
                 patch.object(target, "ordered_catalog", return_value=self.catalog()), \
                 patch.object(history, "restore", return_value={"schema": 1, "records": {}}), \
                 patch("public_link_runtime.inventory", return_value={}), \
                 patch("public_link_runtime.graph_rows", return_value=live), \
                 patch("public_link_runtime.restore",
                       return_value={"schema": 1, "entries": entries}), \
                 patch("public_link_runtime.download_verified_publication_video",
                       side_effect=AssertionError("source should not be downloaded")):
                report = target.audit("987654", reserve=True)
            self.assertEqual(report["previously_verified"], 20)
            self.assertEqual(report["regular_publisher_live_id_matches"], 20)
            self.assertEqual(report["prepared_parts"], 0)
            self.assertEqual(report["posts_created"], 0)
            self.assertEqual(json.loads((root / "plan.json").read_text())["plans"], [])
            self.assertEqual(history.validate(
                json.loads((root / "alert-history.json").read_text()))["records"], {})


    def test_missing_live_ids_are_collected_without_releasing_either_part(self):
        items = target.selected(self.catalog())
        entries = {}
        for item in items[:2]:
            entries[f"toonzone:instagram:{item['id']}"] = {
                "route": "toonzone", "platform": "instagram",
                "file": item["name"], "status": "done",
                "post_id": str(18100000000000000 + item["part"]),
            }
        with self.assertRaises(target.MainPublisherLiveMissing) as raised:
            target.main_publisher_posts(
                items, [], {"schema": 1, "entries": entries})
        self.assertEqual(
            [(x["episode"], x["part"]) for x in raised.exception.records],
            [(4, 1), (4, 2)],
        )
        self.assertEqual(raised.exception.records[0]["file"], items[0]["name"])

    def test_live_mismatch_writes_nonpublish_evidence_artifact(self):
        import json
        import tempfile
        from pathlib import Path
        import publisher_alert_history as history

        items = target.selected(self.catalog())
        first = items[0]
        entries = {f"toonzone:instagram:{first['id']}": {
            "route": "toonzone", "platform": "instagram",
            "file": first["name"], "status": "done",
            "post_id": "18100507712530539",
        }}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(target, "ROOT", root), \
                 patch.object(target, "REPORT", root / "audit.json"), \
                 patch.object(target, "page_for_toonzone", return_value={"page_id": "123"}), \
                 patch.object(target, "instagram_identity", return_value=target.ACCOUNT_ID), \
                 patch.object(target, "ordered_catalog", return_value=self.catalog()), \
                 patch.object(history, "restore", return_value={"schema": 1, "records": {}}), \
                 patch("public_link_runtime.inventory", return_value={}), \
                 patch("public_link_runtime.graph_rows", return_value=[]), \
                 patch("public_link_runtime.restore",
                       return_value={"schema": 1, "entries": entries}), \
                 patch.object(target, "direct_probe_missing_main_posts",
                              return_value=[{"status": "ambiguous", "reason": "test_only"}]), \
                 patch("public_link_runtime.download_verified_publication_video",
                       side_effect=AssertionError("not allowed to upload")):
                result = target.audit("987654", reserve=False)
            report = json.loads((root / "audit.json").read_text())
            self.assertEqual(result, report)
            self.assertEqual(report["status"], "held_live_history_mismatch")
            self.assertFalse(report["publication_authorized"])
            self.assertFalse(report["safe_to_reserve"])
            self.assertEqual(report["unverified_archive_count"], 1)
            self.assertEqual(report["posts_created"], 0)
            self.assertFalse((root / "plan.json").exists())
            self.assertFalse((root / "alert-history.json").exists())
            self.assertEqual(len(report["archived_ids_absent_from_list"]), 1)
            self.assertEqual(report["archived_ids_absent_from_list"][0]["archived_post_id"],
                             "18100507712530539")



    def test_individual_post_get_confirms_only_exact_owner_and_caption(self):
        from unittest.mock import Mock
        from public_link_runtime import caption_key
        item = target.selected(self.catalog())[0]
        post = "18100507712530539"
        account = target.ACCOUNT_ID
        record = {"episode": item["episode"], "part": item["part"],
                  "file": item["name"], "source_id": item["id"],
                  "archived_post_id": post}
        state = {"entries": {f"toonzone:instagram:{item['id']}": {
            "status": "done", "route": "toonzone", "platform": "instagram",
            "file": item["name"], "post_id": post,
            "caption_hash": caption_key("S01E04 Part 1/4"),
        }}}
        page = {"page_id": "1298191963387372", "page_token": "TEST-SECRET"}
        body = {"id": post, "owner": {"id": account}, "media_type": "VIDEO",
                "caption": "S01E04 Part 1/4",
                "timestamp": "2026-10-27T13:00:00+00:00",
                "permalink": "https://www.instagram.com/reel/Example/"}
        for change, expected_status, reason in (
            ({}, "verified", "exact_id_account_video_caption"),
            ({"owner": {"id": "17840000000000000"}}, "ambiguous", "wrong_instagram_account"),
            ({"owner": None}, "ambiguous", "owner_id_unavailable"),
            ({"media_type": "IMAGE"}, "ambiguous", "not_video"),
            ({"caption": "DIFFERENT PART"}, "ambiguous", "archived_caption_hash"),
            ({"id": "99999"}, "ambiguous", "returned_id_mismatch"),
        ):
            with self.subTest(change=change):
                response = Mock(status_code=200)
                response.json.return_value = dict(body, **change)
                get = Mock(return_value=response)
                result = target.direct_probe_missing_main_posts(
                    [record], page, account, state, get=get)[0]
                self.assertEqual(result["status"], expected_status)
                self.assertIn(reason, result["reason"])
                self.assertEqual(get.call_count, 1)
                self.assertEqual(get.call_args.kwargs["params"]["fields"],
                                 "id,caption,media_type,permalink,timestamp,owner")
                self.assertEqual(get.call_args.kwargs["headers"]["Authorization"],
                                 "Bearer TEST-SECRET")
                self.assertNotIn("TEST-SECRET", repr(result))
                response.close.assert_called_once()

    def test_owner_free_read_accepts_only_canonical_username_and_archived_caption(self):
        from unittest.mock import Mock
        from public_link_runtime import caption_key
        item = target.selected(self.catalog())[0]
        pid = "18100507712530539"
        row = {"episode": 4, "part": 1, "file": item["name"],
               "source_id": item["id"], "archived_post_id": pid,
               "status": "ambiguous", "graph_error_code": 100}
        state = {"entries": {f"toonzone:instagram:{item['id']}": {
            "status": "done", "post_id": pid,
            "caption_hash": caption_key("S01E04 Part 1/4"),
        }}}
        page = {"page_id": "1298191963387372", "page_token": "PRIVATE-CREDENTIAL"}
        body = {"id": pid, "username": "toonzone.tr",
                "caption": "S01E04 Part 1/4", "media_type": "VIDEO",
                "timestamp": "2026-11-08T21:00:00+00:00",
                "permalink": "https://www.instagram.com/reel/VerifiedExample/"}
        response = Mock(status_code=200)
        response.json.return_value = body
        with patch("toonzone_instagram_season.graph_get",
                   return_value={"id": target.ACCOUNT_ID, "username": "toonzone.tr"}):
            get = Mock(return_value=response)
            report = target.probe_ig_without_owner(
                [row], page, target.ACCOUNT_ID, state, get=get)[0]
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["reason"], "exact_id_canonical_username_video_caption")
        self.assertEqual(report["basic_read_status"], "verified")
        self.assertEqual(report["_verified_caption"], "S01E04 Part 1/4")
        self.assertEqual(get.call_count, 1)
        self.assertNotIn("owner", get.call_args.kwargs["params"]["fields"])
        self.assertIn("username", get.call_args.kwargs["params"]["fields"])
        self.assertNotIn("PRIVATE-CREDENTIAL", repr(report))

    def test_owner_free_read_never_accepts_wrong_username_or_basic_only(self):
        from unittest.mock import Mock
        from public_link_runtime import caption_key
        item = target.selected(self.catalog())[0]
        pid = "18100507712530539"
        state = {"entries": {f"toonzone:instagram:{item['id']}": {
            "status": "done", "post_id": pid,
            "caption_hash": caption_key("S01E04 Part 1/4"),
        }}}
        page = {"page_id": "1298191963387372", "page_token": "PRIVATE-CREDENTIAL"}
        body = {"id": pid, "caption": "S01E04 Part 1/4",
                "media_type": "VIDEO", "timestamp": "2026-11-08T21:00:00Z",
                "permalink": "https://www.instagram.com/reel/Example/"}
        def row():
            return {"episode": 4, "part": 1, "file": item["name"],
                    "source_id": item["id"], "archived_post_id": pid,
                    "status": "ambiguous", "graph_error_code": 100}
        with patch("toonzone_instagram_season.graph_get",
                   return_value={"id": target.ACCOUNT_ID, "username": "toonzone.tr"}):
            wrong = Mock(status_code=200)
            wrong.json.return_value = dict(body, username="someone.else")
            result = target.probe_ig_without_owner(
                [row()], page, target.ACCOUNT_ID, state,
                get=Mock(return_value=wrong))[0]
            self.assertEqual(result["status"], "ambiguous")
            self.assertEqual(result["basic_read_status"], "username_mismatch_or_missing")

            denied = Mock(status_code=400)
            denied.json.return_value = {"error": {"code": 100, "error_subcode": 33,
                                                    "message": "private-token-must-not-leak"}}
            basic = Mock(status_code=200)
            basic.json.return_value = body  # Has no username or ownership proof.
            get = Mock(side_effect=[denied, basic])
            outcome = target.probe_ig_without_owner(
                [row()], page, target.ACCOUNT_ID, state, get=get)[0]
            self.assertEqual(outcome["status"], "ambiguous")
            self.assertEqual(outcome["basic_read_status"], "readable_but_owner_unconfirmed")
            self.assertEqual(get.call_count, 2)
            self.assertNotIn("private-token-must-not-leak", repr(outcome))
            denied.close.assert_called_once()
            basic.close.assert_called_once()

    def test_individual_get_errors_never_prove_deletion_or_authorize_repost(self):
        from unittest.mock import Mock
        item = target.selected(self.catalog())[0]
        row = {"episode": 4, "part": 1, "file": item["name"],
               "source_id": item["id"], "archived_post_id": "123"}
        state = {"entries": {f"toonzone:instagram:{item['id']}": {
            "status": "done", "route": "toonzone",
            "platform": "instagram", "file": item["name"], "post_id": "123",
        }}}
        page = {"page_id": "1298191963387372", "page_token": "NOT-A-REAL-TOKEN"}
        for http, code, expected in (
            (403, 200, "access_blocked"),
            (401, 190, "access_blocked"),
            (404, 100, "not_found"),
            (400, 100, "ambiguous"),
        ):
            with self.subTest(http=http, code=code):
                response = Mock(status_code=http)
                response.json.return_value = {"error": {"code": code,
                    "message": "SECRET NEVER APPEARS IN REPORT"}}
                result = target.direct_probe_missing_main_posts(
                    [row], page, target.ACCOUNT_ID, state,
                    get=Mock(return_value=response))[0]
                self.assertEqual(result["status"], expected)
                self.assertNotIn("SECRET", repr(result))
                self.assertNotEqual(result["status"], "verified")
                response.close.assert_called_once()
        result = target.direct_probe_missing_main_posts(
            [row], page, target.ACCOUNT_ID, state,
            get=Mock(side_effect=OSError("SECRET TIMEOUT")))[0]
        self.assertEqual(result["status"], "ambiguous")
        self.assertNotIn("SECRET", repr(result))

    def test_probe_refuses_to_reclassify_changed_source_or_ledger(self):
        from unittest.mock import Mock
        item = target.selected(self.catalog())[0]
        row = {"episode": 4, "part": 1, "file": item["name"],
               "source_id": item["id"], "archived_post_id": "123"}
        state = {"entries": {f"toonzone:instagram:{item['id']}": {
            "status": "uncertain", "route": "toonzone",
            "platform": "instagram", "file": item["name"], "post_id": "123",
        }}}
        get = Mock()
        with self.assertRaisesRegex(RuntimeError, "record_changed"):
            target.direct_probe_missing_main_posts(
                [row], {"page_id": "123", "page_token": "TOKEN"},
                target.ACCOUNT_ID, state, get=get)
        get.assert_not_called()



    def test_positive_control_differentiates_unsupported_owner_from_id_failure(self):
        from unittest.mock import Mock
        with_owner = Mock(status_code=400)
        with_owner.json.return_value = {
            "error": {"code": 100, "message": "secret detailed error"}}
        basic = Mock(status_code=200)
        basic.json.return_value = {"id": "18000000000000001",
                                   "media_type": "VIDEO"}
        get = Mock(side_effect=[with_owner, basic])
        result = target.individual_get_positive_control(
            [{"id": "18000000000000001", "media_type": "VIDEO"}],
            {"page_id": "1298191963387372", "page_token": "SECRET-TOKEN"},
            get=get,
        )
        self.assertEqual(result["with_owner"]["status"], "read_rejected")
        self.assertEqual(result["with_owner"]["graph_error_code"], 100)
        self.assertEqual(result["basic"]["status"], "exact_id_readable")
        self.assertEqual(get.call_count, 2)
        self.assertIn("owner", get.call_args_list[0].kwargs["params"]["fields"])
        self.assertNotIn("owner", get.call_args_list[1].kwargs["params"]["fields"])
        self.assertNotIn("SECRET", repr(result))
        with_owner.close.assert_called_once()
        basic.close.assert_called_once()

    def test_positive_control_rejects_wrong_id_and_handles_empty_list(self):
        from unittest.mock import Mock
        self.assertEqual(
            target.individual_get_positive_control([], {"page_token": "SECRET"}),
            {"status": "no_listed_media_for_control"})
        response = Mock(status_code=200)
        response.json.return_value = {"id": "999"}
        get = Mock(return_value=response)
        result = target.individual_get_positive_control(
            [{"id": "181"}], {"page_token": "SECRET"}, get=get)
        self.assertEqual(result["with_owner"]["status"], "returned_identity_mismatch")
        self.assertEqual(result["basic"]["status"], "returned_identity_mismatch")
        self.assertEqual(get.call_count, 2)



    def test_mismatch_is_still_fatal_for_reservation_and_never_uploads(self):
        import json
        import tempfile
        from pathlib import Path
        import publisher_alert_history as history

        row = target.selected(self.catalog())[0]
        entries = {f"toonzone:instagram:{row['id']}": {
            "route": "toonzone", "platform": "instagram",
            "file": row["name"], "status": "done",
            "post_id": "18100507712530539",
        }}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(os.environ, {
                    "TOONZONE_RIGHTS_APPROVED": "true",
                    "TOONZONE_RELEASE_4_8": "true",
            }, clear=True), \
                 patch.object(target, "ROOT", root), \
                 patch.object(target, "REPORT", root / "audit.json"), \
                 patch.object(target, "PLAN", root / "plan.json"), \
                 patch.object(target, "HISTORY", root / "alert-history.json"), \
                 patch.object(target, "page_for_toonzone",
                              return_value={"page_id": "123"}), \
                 patch.object(target, "instagram_identity",
                              return_value=target.ACCOUNT_ID), \
                 patch.object(target, "ordered_catalog",
                              return_value=self.catalog()), \
                 patch.object(history, "restore",
                              return_value={"schema": 1, "records": {}}), \
                 patch("public_link_runtime.inventory", return_value={}), \
                 patch("public_link_runtime.graph_rows", return_value=[]), \
                 patch("public_link_runtime.restore",
                       return_value={"schema": 1, "entries": entries}), \
                 patch.object(target, "direct_probe_missing_main_posts",
                              return_value=[{"status": "ambiguous",
                                            "reason": "graph_code_100"}]), \
                 patch("public_link_runtime.download_verified_publication_video") as download:
                with self.assertRaises(target.MainPublisherLiveMissing):
                    target.audit("987654", reserve=True)
            report = json.loads((root / "audit.json").read_text())
            self.assertFalse(report["safe_to_reserve"])
            self.assertFalse(report["publication_authorized"])
            self.assertFalse((root / "plan.json").exists())
            self.assertFalse((root / "alert-history.json").exists())
            download.assert_not_called()

    def test_workflow_requires_positive_audit_to_release_any_part(self):
        from pathlib import Path
        workflow = (Path(__file__).parent / ".github" / "workflows"
                    / "toonzone_episodes_4_8.yml").read_text(encoding="utf-8")
        self.assertIn("release_ready: ${{ steps.eligibility.outputs.release_ready }}", workflow)
        self.assertIn("needs.live-audit.outputs.release_ready == 'true'", workflow)
        self.assertIn('verdict.get("safe_to_reserve") is True', workflow)
        self.assertIn("and verdict.get(\"previously_verified\", 0) + verdict.get(\"prepared_parts\", 0) == 20", workflow)
        self.assertIn("and verdict.get(\"posts_created\") == 0", workflow)
        self.assertIn("vars.TOONZONE_RIGHTS_APPROVED == 'true'", workflow)
        self.assertIn("vars.TOONZONE_RELEASE_4_8 == 'true'", workflow)


    def test_twenty_original_meta_receipts_match_original_ledger_not_current_live(self):
        import json
        from pathlib import Path

        registry = Path(__file__).parent / "docs" / (
            "toonzone-4-8-original-instagram-publish-receipts.json"
        )
        payload = json.loads(registry.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"],
                         "historical_publish_confirmation_only_not_current_live_verification")
        self.assertEqual(len(payload["records"]), 20)
        selected = target.selected(self.catalog())
        records = []
        entries = {}
        by_slot = {(x["episode"], x["part"]): x for x in payload["records"]}
        for item in selected:
            proof = by_slot[item["episode"], item["part"]]
            item["name"] = proof["source_file"]
            self.assertEqual(item["name"], proof["source_file"])
            records.append({
                "episode": item["episode"], "part": item["part"],
                "file": item["name"], "source_id": item["id"],
                "archived_post_id": proof["post_id"],
            })
            entries[f"toonzone:instagram:{item['id']}"] = {
                "route": "toonzone", "platform": "instagram",
                "file": item["name"], "status": "done",
                "post_id": proof["post_id"], "run_id": proof["source_run_id"],
            }
        actual = target.historical_publish_receipts(
            records, {"schema": 1, "entries": entries}
        )
        self.assertEqual(actual["historical_publish_receipts_matching_ledger"], 20)
        self.assertEqual(actual["historical_publish_receipts_checked"], 20)
        self.assertEqual(actual["historical_publish_reel_urls_available"], 20)
        self.assertEqual(actual["current_live_verified_by_historical_receipts"], 0)
        self.assertTrue(actual["historical_only"])
        # Tampered source-run identity must not be counted as proof.
        entries[f"toonzone:instagram:{selected[0]['id']}"]["run_id"] = "99999"
        amended = target.historical_publish_receipts(
            records, {"schema": 1, "entries": entries}
        )
        self.assertEqual(amended["historical_publish_receipts_matching_ledger"], 19)
        self.assertEqual(amended["current_live_verified_by_historical_receipts"], 0)

    def test_corrupted_historical_registry_is_not_accepted_as_evidence(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old-posts.json"
            path.write_text(json.dumps({"schema": 1, "records": []}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "receipts_invalid"):
                target.historical_publish_receipts([], {"entries": {}}, registry_path=path)
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "receipts_unavailable"):
                target.historical_publish_receipts([], {"entries": {}}, registry_path=path)


if __name__ == "__main__":
    unittest.main()
