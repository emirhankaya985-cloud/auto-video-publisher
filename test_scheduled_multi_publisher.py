import os
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch
from pathlib import Path
import unittest
import requests
import yaml
import scheduled_multi_publisher as publisher

from scheduled_multi_publisher import (
    content_from_txt,
    platform_content_from_txt,
    due_slots,
    execute_platform_jobs,
    FAILED_SLOT,
    is_first_daily_slot,
    is_ambiguous_publish_error,
    is_permanent_publish_error,
    next_due_route,
    notify,
    route_for_time,
    routes_for_time,
    slot_is_done,
    safe_temp_path,
    select_random_unused,
    shared_folder_for_slot,
    quarantine_legacy_shared_claims,
    list_pairs,
    validate_drive_routing,
    verify_file_in_folder,
    _normalized_name,
    run_due,
    configured_max_due_slots,
    youtube_safe_description,
    audit_routing_only,
    apply_youtube_fixed_cover,
    select_next_film_part,
    clear_exact_film_claim_for_publish,
    parse_film_upload_test_ids,
    _film_upload_only_batch,
    _toonzone_ig_upload_only_test,
    select_next_toonzone_part,
    TOONZONE_USED,
    TOONZONE_COVER_FOLDER_ID,
    TOONZONE_IG_FAILED_TEST_FILE_ID,
    validate_toonzone_starting_episode,
    run as run_publisher,
)


class RouteTests(unittest.TestCase):
    def test_only_exact_reconciled_film_claim_is_cleared_and_published_state_blocks_it(self):
        claim = "manual-2026-10-17-0819-film"
        item = {
            "id": "1dhKwAI9LPpUEniIfqNuWKrY8EQuM67xZ",
            "name": "Yoksul_1986_Part_2.mp4",
            "appProperties": {"claimed_route_slot": claim},
        }
        drive = Mock()
        drive.files.return_value.list.return_value.execute.side_effect = [
            {"files": [item], "nextPageToken": "next"},
            {"files": []},
        ]
        result = clear_exact_film_claim_for_publish(drive, "film-folder", claim)
        self.assertEqual(result, item["id"])
        drive.files.return_value.update.assert_called_once_with(
            fileId=item["id"],
            body={"appProperties": {"claimed_route_slot": None, "claimed_at": None}},
        )

        item["appProperties"]["result_ig"] = "existing-media"
        drive.files.return_value.list.return_value.execute.side_effect = [{"files": [item]}]
        with self.assertRaisesRegex(RuntimeError, "yayın/işlem kaydı"):
            clear_exact_film_claim_for_publish(drive, "film-folder", claim)
        self.assertEqual(drive.files.return_value.update.call_count, 1)

    def test_dedicated_film_upload_only_workflow_is_fixed_and_fails_closed(self):
        workflow_path = Path(__file__).parent / ".github" / "workflows" / "film_ig_upload_only_test.yml"
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(workflow_text)
        events = workflow.get("on", workflow.get(True, {}))
        inputs = events["workflow_dispatch"]["inputs"]
        job = workflow["jobs"]["upload-only-batch"]
        upload_step = next(step for step in job["steps"] if step.get("name") == "Run fixed Film Instagram upload-only batch")
        step_names = [step.get("name", "") for step in job["steps"]]

        self.assertTrue(inputs["file_ids"]["required"])
        self.assertLess(
            step_names.index("Reject missing or duplicate test IDs before external API access"),
            step_names.index("Run fixed Film Instagram upload-only batch"),
        )
        self.assertEqual(upload_step["env"]["FORCE_ROUTE"], "film")
        self.assertEqual(upload_step["env"]["FORCE_PLATFORM"], "instagram")
        self.assertEqual(upload_step["env"]["FILM_IG_UPLOAD_ONLY"], "true")
        self.assertEqual(upload_step["env"]["FILM_IG_TEST_BATCH"], "true")
        self.assertEqual(upload_step["env"]["FILM_IG_TEST_START_INDEX"], "2")
        self.assertEqual(upload_step["env"]["FILM_IG_TEST_BATCH_COUNT"], "13")
        self.assertEqual(upload_step["run"], "python scheduled_multi_publisher.py")
        self.assertIn("len(file_ids) != 15 or len(set(file_ids)) != 15", workflow_text)
        self.assertNotIn("media_publish", workflow_text)

    def test_workflow_wires_gonle_controlled_test_with_fail_closed_guard(self):
        workflow_path = Path(__file__).parent / ".github" / "workflows" / "omnichannel_schedule.yml"
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(workflow_text)
        events = workflow.get("on", workflow.get(True, {}))
        self.assertIn("controlled_gonle_ig_test", events["workflow_dispatch"]["inputs"])
        job = workflow["jobs"]["omnichannel-upload"]
        upload_step = next(step for step in job["steps"] if step.get("name") == "Drive'dan Siradaki Videoyu 4 Kanala Birden Bas")
        self.assertEqual(upload_step["env"]["GONLE_IG_CONTROLLED_TEST"], "${{ inputs.controlled_gonle_ig_test }}")
        self.assertIn('GONLE_IG_CONTROLLED_TEST" = "true"', upload_step["run"])

    def test_workflow_exposes_ordered_toonzone_parts_and_narrow_part1_recovery(self):
        workflow_path = Path(__file__).parent / ".github" / "workflows" / "omnichannel_schedule.yml"
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(workflow_text)
        events = workflow.get("on", workflow.get(True, {}))
        inputs = events["workflow_dispatch"]["inputs"]
        job = workflow["jobs"]["omnichannel-upload"]
        upload_step = next(step for step in job["steps"] if step.get("name") == "Drive'dan Siradaki Videoyu 4 Kanala Birden Bas")
        self.assertEqual(inputs["toonzone_part"]["options"], ["", "1", "2", "3", "4", "resume_part1_ig"])
        self.assertEqual(upload_step["env"]["TOONZONE_PART"], "${{ inputs.toonzone_part }}")
        self.assertEqual(upload_step["env"]["TOONZONE_RESUME_PART1_IG"], "false")
        self.assertIn("TOONZONE_RESUME_PART1_IG", upload_step["run"])
        self.assertIn("FORCE_PLATFORM\" != \"instagram\"", upload_step["run"])

    def test_film_upload_test_ids_require_exactly_fifteen_unique_ids(self):
        self.assertEqual(parse_film_upload_test_ids("\n".join(f"drive-{i}" for i in range(15))),
                         [f"drive-{i}" for i in range(15)])
        with self.assertRaisesRegex(RuntimeError, "tam olarak 15"):
            parse_film_upload_test_ids("drive-1,drive-1")

    def test_empty_explicit_film_batch_fails_closed_without_normal_selector(self):
        env = {
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "instagram",
            "FILM_IG_UPLOAD_ONLY": "true", "FILM_IG_TEST_BATCH": "true",
            "FILM_DRIVE_FOLDER_ID": "film-folder",
            "FILM_IG_TEST_FILE_IDS": "   ", "FILM_IG_TEST_START_INDEX": "0",
            "FILM_IG_TEST_BATCH_COUNT": "2",
        }
        with patch.dict(os.environ, env, clear=True), \
             patch("scheduled_multi_publisher.require_route_enabled"), \
             patch("scheduled_multi_publisher.batch_exception_allowed", return_value=True), \
             patch("scheduled_multi_publisher.select_next_film_part") as selector, \
             patch("scheduled_multi_publisher._film_upload_only_batch") as batch:
            with self.assertRaisesRegex(RuntimeError, "15 benzersiz"):
                run_publisher(drive=Mock(), routing_validated=True)
        selector.assert_not_called()
        batch.assert_not_called()

    def test_explicit_film_upload_batch_never_publishes_or_mutates_drive(self):
        file_ids = [f"drive-{i}" for i in range(15)]
        inventory = [
            {"id": file_id, "name": f"Film_{i}_Part_1.mp4", "parents": ["film-folder"],
             "mimeType": "video/mp4", "md5Checksum": f"md5-{i}"}
            for i, file_id in enumerate(file_ids)
        ]
        page = {"instagram_id": "ig-id", "page_token": "never-logged"}

        class Downloader:
            def __init__(self, target, request, chunksize):
                self.target = target
                self.payload = request
                self.done = False
            def next_chunk(self):
                if not self.done:
                    self.target.write(self.payload)
                    self.done = True
                return None, True

        drive = Mock()
        drive.files.return_value.get_media.side_effect = [f"payload-{i}".encode() for i in range(15)]
        with patch("scheduled_multi_publisher.list_film_mp4s_for_test", return_value=inventory), \
             patch("scheduled_multi_publisher.meta_page", return_value=page), \
             patch("scheduled_multi_publisher.verify_file_in_folder"), \
             patch("scheduled_multi_publisher.MediaIoBaseDownload", Downloader), \
             patch("scheduled_multi_publisher.log_media_diagnostics"), \
             patch("scheduled_multi_publisher.check_full_decode"), \
             patch("instagram_media_compat.probe", return_value={}), \
             patch("instagram_media_compat.mp4_atom_structure", return_value={
                 "valid": True, "moov_front": True, "edit_list": False,
             }), \
             patch("instagram_media_compat.compatibility_issues", return_value=[]), \
             patch("scheduled_multi_publisher.prepare_instagram_upload", side_effect=lambda source, *_a, **_kw: (source, "direct")) as prepare, \
             patch("scheduled_multi_publisher.upload_instagram_reel", side_effect=[
                 {"container_id": "container-a", "status": "FINISHED", "published": False},
                 {"container_id": "container-b", "status": "FINISHED", "published": False},
             ]) as upload:
            result = _film_upload_only_batch(drive, "film-folder", file_ids, start_index=0, count=2)
        self.assertEqual([row["status"] for row in result], ["FINISHED", "FINISHED"])
        self.assertEqual(len({row["container_id"] for row in result}), 2)
        self.assertEqual(upload.call_count, 2)
        self.assertTrue(all(call.kwargs["film_compact"] is True for call in prepare.call_args_list))
        self.assertTrue(all(call.kwargs["publish"] is False for call in upload.call_args_list))
        self.assertFalse(drive.files.return_value.update.called)

    def test_film_upload_only_rejects_claim_clear_before_drive_access(self):
        env = {
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "instagram",
            "FILM_IG_UPLOAD_ONLY": "true",
            "FILM_CLAIM_TO_CLEAR": "manual-2026-10-17-0817-film",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "scheduled_multi_publisher.get_drive_client"
        ) as drive:
            with self.assertRaisesRegex(RuntimeError, "claim temizleme"):
                run_publisher()
        drive.assert_not_called()

    def test_film_upload_only_rejects_backfill_before_drive_access(self):
        env = {
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "instagram",
            "FILM_IG_UPLOAD_ONLY": "true", "BACKFILL_ROUTE": "film",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "scheduled_multi_publisher.get_drive_client"
        ) as drive:
            with self.assertRaisesRegex(RuntimeError, "backfill"):
                run_publisher()
        drive.assert_not_called()

    def test_film_duplicate_prefers_exact_mp4_and_matching_txt(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": [
            {"id":"copy-mp4","name":"Avanak_Apti_Part_1 (1).mp4","parents":["film"],"appProperties":{}},
            {"id":"copy-txt","name":"Avanak_Apti_Part_1 (1).txt","parents":["film"]},
            {"id":"exact-mp4","name":"Avanak_Apti_Part_1.mp4","parents":["film"],"appProperties":{}},
            {"id":"exact-txt","name":"Avanak_Apti_Part_1.txt","parents":["film"]},
        ]}
        drive.files.return_value.get.return_value.execute.return_value = {"id":"film","appProperties":{}}
        active, part, video, txt = select_next_film_part(drive,"film","slot")
        self.assertEqual((active,part),("avanak_apti",1))
        self.assertEqual((video["id"],txt["id"]),("exact-mp4","exact-txt"))

    def test_film_numbered_copy_is_fallback_with_its_matching_txt(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": [
            {"id":"copy-mp4","name":"Avanak_Apti_Part_1 (1).mp4","parents":["film"],"appProperties":{}},
            {"id":"copy-txt","name":"Avanak_Apti_Part_1 (1).txt","parents":["film"]},
        ]}
        drive.files.return_value.get.return_value.execute.return_value = {"id":"film","appProperties":{}}
        _, _, video, txt = select_next_film_part(drive,"film","slot")
        self.assertEqual((video["id"],txt["id"]),("copy-mp4","copy-txt"))

    def test_film_selector_does_not_persist_active_film_in_read_only_mode(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": [
            {"id": "v1", "name": "Yoksul_1986_Part_1.mp4", "parents": ["film"], "appProperties": {}},
            {"id": "t1", "name": "Yoksul_1986_Part_1.txt", "parents": ["film"]},
        ]}
        drive.files.return_value.get.return_value.execute.return_value = {"id": "film", "appProperties": {}}
        selected = select_next_film_part(drive, "film", "slot", persist_active=False)
        self.assertEqual(selected[1], 1)
        drive.files.return_value.update.assert_not_called()

    def test_film_selector_reads_all_pages_and_advances_past_published_part(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.side_effect = [
            {"files": [
                {"id": "v1", "name": "Yoksul_1986_Part_1.mp4", "appProperties": {"film_used": "1"}},
                {"id": "t1", "name": "Yoksul_1986_Part_1.txt"},
            ], "nextPageToken": "page-2"},
            {"files": [
                {"id": "v2", "name": "Yoksul_1986_Part_2.mp4", "appProperties": {}},
                {"id": "t2", "name": "Yoksul_1986_Part_2.txt"},
            ]},
        ]
        drive.files.return_value.get.return_value.execute.return_value = {
            "id": "film", "appProperties": {"film_active_key": "yoksul_1986"}
        }
        _, part, video, txt = select_next_film_part(drive, "film", "slot", persist_active=False)
        self.assertEqual((part, video["id"], txt["id"]), (2, "v2", "t2"))
        self.assertEqual(drive.files.return_value.list.call_args.kwargs["pageToken"], "page-2")
        drive.files.return_value.update.assert_not_called()

    def test_normal_film_selection_fails_closed_when_next_part_has_claim(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": [
            {"id": "v1", "name": "Yoksul_1986_Part_1.mp4", "parents": ["film"], "appProperties": {"claimed_route_slot": "unknown-slot"}},
            {"id": "t1", "name": "Yoksul_1986_Part_1.txt", "parents": ["film"]},
            {"id": "v2", "name": "Yoksul_1986_Part_2.mp4", "parents": ["film"], "appProperties": {}},
            {"id": "t2", "name": "Yoksul_1986_Part_2.txt", "parents": ["film"]},
        ]}
        drive.files.return_value.get.return_value.execute.return_value = {
            "id": "film", "appProperties": {"film_active_key": "yoksul_1986"}
        }
        with self.assertRaisesRegex(RuntimeError, "açık claim"):
            select_next_film_part(drive, "film", "slot", persist_active=False)
        drive.files.return_value.update.assert_not_called()

    def test_upload_only_can_probe_claimed_next_part_without_queue_mutation(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {"files": [
            {"id": "v1", "name": "Yoksul_1986_Part_1.mp4", "parents": ["film"], "appProperties": {"claimed_route_slot": "unknown-slot"}},
            {"id": "t1", "name": "Yoksul_1986_Part_1.txt", "parents": ["film"]},
            {"id": "v2", "name": "Yoksul_1986_Part_2.mp4", "parents": ["film"], "appProperties": {}},
            {"id": "t2", "name": "Yoksul_1986_Part_2.txt", "parents": ["film"]},
        ]}
        drive.files.return_value.get.return_value.execute.return_value = {
            "id": "film", "appProperties": {"film_active_key": "yoksul_1986"}
        }
        selected = select_next_film_part(
            drive, "film", "slot", persist_active=False, allow_claimed_next=True
        )
        self.assertEqual((selected[1], selected[2]["id"]), (1, "v1"))
        drive.files.return_value.update.assert_not_called()

    def test_film_instagram_upload_only_does_not_publish_or_mutate_drive_state(self):
        drive = Mock()
        video = {"id": "drive-video", "name": "Yoksul_1986_Part_6.mp4", "appProperties": {}}

        class FakeDownloader:
            def __init__(self, stream, _request, **_kwargs):
                stream.write(b"source-video")

            def next_chunk(self):
                return None, True

        with tempfile.TemporaryDirectory() as workdir:
            original_cwd = os.getcwd()
            os.chdir(workdir)
            try:
                env = {
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_EVENT_NAME": "workflow_dispatch",
                    "FORCE_ROUTE": "film",
                    "FORCE_PLATFORM": "instagram",
                    "FILM_IG_UPLOAD_ONLY": "true",
                    "FILM_IG_DIAGNOSTIC_CLIP_SECONDS": "0",
                    "FILM_DRIVE_FOLDER_ID": "film-folder",
                    "ENABLE_FILM_ROUTES": "true",
                    "FILM_RIGHTS_APPROVED": "true",
                }
                with patch.dict("os.environ", env, clear=True), \
                     patch("scheduled_multi_publisher.validate_drive_routing"), \
                     patch("scheduled_multi_publisher.quarantine_legacy_shared_claims") as quarantine, \
                     patch("scheduled_multi_publisher.select_next_film_part", return_value=("yoksul_1986", 6, video, {"id": "drive-txt", "name": ""})) as select, \
                     patch("scheduled_multi_publisher.verify_file_in_folder"), \
                     patch("scheduled_multi_publisher.MediaIoBaseDownload", FakeDownloader), \
                     patch("scheduled_multi_publisher.log_media_diagnostics"), \
                     patch("scheduled_multi_publisher.check_full_decode", return_value=True), \
                     patch("scheduled_multi_publisher.prepare_instagram_upload", side_effect=lambda source, _output, **_kwargs: source) as prepare, \
                     patch("scheduled_multi_publisher.get_meta_page_info", return_value={"page_id": "page", "page_token": "not-logged", "instagram_id": "ig"}), \
                     patch("scheduled_multi_publisher.requests.get", return_value=Mock(json=lambda: {"id": "page"})), \
                     patch("scheduled_multi_publisher.upload_instagram_reel", return_value={"container_id": "container", "status": "FINISHED", "published": False}) as upload:
                    run_publisher(drive=drive, selected=("film", "diagnostic-slot"))
                quarantine.assert_not_called()
                self.assertFalse(select.call_args.kwargs["persist_active"])
                self.assertTrue(select.call_args.kwargs["allow_claimed_next"])
                self.assertTrue(prepare.call_args.kwargs["prefer_remux"])
                upload.assert_called_once()
                self.assertIs(upload.call_args.kwargs["publish"], False)
                drive.files.return_value.update.assert_not_called()
            finally:
                os.chdir(original_cwd)

    def test_toonzone_upload_only_uses_fixed_failed_file_and_never_publishes_or_writes_drive(self):
        video = {
            "id": TOONZONE_IG_FAILED_TEST_FILE_ID,
            "name": "S01E01_The_Power_Part1.mp4",
            "parents": ["cartoon-folder"],
            "mimeType": "video/mp4",
        }
        cover = {"id": "cover-1", "name": "S01E01_The_Power_Part1.png"}
        drive = Mock()
        drive.files.return_value.get.return_value.execute.return_value = video

        class FakeDownloader:
            def __init__(self, stream, _request, **_kwargs):
                stream.write(b"toonzone-source")
            def next_chunk(self):
                return None, True

        def write_file(_source, _cover, output):
            Path(output).write_bytes(b"cover-composite")
            return Path(output)

        def prepare(_source, output, **kwargs):
            self.assertTrue(kwargs["toonzone_compact"])
            Path(output).write_bytes(b"normalized-video")
            return Path(output), "transcode"

        with patch("scheduled_multi_publisher.meta_page", return_value={"instagram_id": "ig"}), \
             patch("scheduled_multi_publisher.list_pairs", return_value=([cover], [])), \
             patch("scheduled_multi_publisher.match_toonzone_cover", return_value=cover), \
             patch("scheduled_multi_publisher.download_and_validate_cover", return_value=(b"cover", (1086, 1448))), \
             patch("scheduled_multi_publisher.verify_file_in_folder"), \
             patch("scheduled_multi_publisher.MediaIoBaseDownload", FakeDownloader), \
             patch("scheduled_multi_publisher.create_instagram_cover_video", side_effect=write_file), \
             patch("scheduled_multi_publisher.prepare_instagram_upload", side_effect=prepare), \
             patch("scheduled_multi_publisher.log_media_diagnostics"), \
             patch("scheduled_multi_publisher.upload_instagram_reel", return_value={
                 "container_id": "container", "status": "FINISHED", "published": False,
             }) as upload:
            result = _toonzone_ig_upload_only_test(drive, "cartoon-folder")

        self.assertEqual(result["status"], "FINISHED")
        self.assertEqual(drive.files.return_value.get.call_args.kwargs["fileId"], TOONZONE_IG_FAILED_TEST_FILE_ID)
        self.assertIs(upload.call_args.kwargs["publish"], False)
        drive.files.return_value.update.assert_not_called()

    def test_normal_film_instagram_uses_verified_compact_upload(self):
        drive = Mock()
        video = {"id": "film-video", "name": "Yoksul_1986_Part_2.mp4", "appProperties": {}}

        class FakeDownloader:
            def __init__(self, stream, _request, **_kwargs):
                stream.write(b"source-video")

            def next_chunk(self):
                return None, True

        def run_ig(_drive, _video, _slot, _required, jobs, _properties, **_kwargs):
            jobs["ig"]()
            return {"ig": "media-id"}, {}

        with tempfile.TemporaryDirectory() as workdir:
            original_cwd = os.getcwd()
            os.chdir(workdir)
            try:
                env = {
                    "GITHUB_ACTIONS": "true", "ENABLE_FILM_ROUTES": "true",
                    "FILM_RIGHTS_APPROVED": "true", "FORCE_PLATFORM": "instagram",
                }
                with patch.dict("os.environ", env, clear=True), \
                     patch("scheduled_multi_publisher.folder_for_route", return_value="film-folder"), \
                     patch("scheduled_multi_publisher.select_next_film_part", return_value=("yoksul_1986", 2, video, {"id": "", "name": ""})), \
                     patch("scheduled_multi_publisher.verify_file_in_folder"), \
                     patch("scheduled_multi_publisher.MediaIoBaseDownload", FakeDownloader), \
                     patch("scheduled_multi_publisher.prepare_instagram_upload", side_effect=lambda source, _output, **_kwargs: source) as prepare, \
                     patch("scheduled_multi_publisher.meta_page", return_value={"page_id": "page"}), \
                     patch("scheduled_multi_publisher.upload_instagram_reel", return_value="media-id") as upload, \
                     patch("scheduled_multi_publisher.execute_platform_jobs", side_effect=run_ig), \
                     patch("scheduled_multi_publisher.notify", return_value=False):
                    run_publisher(drive=drive, selected=("film", "2026-10-18-18-film"), routing_validated=True)
                self.assertTrue(prepare.call_args.kwargs["film_compact"])
                self.assertTrue(upload.call_args.kwargs["publish"])
            finally:
                os.chdir(original_cwd)

    def test_normal_gonle_instagram_uses_compact_upload(self):
        drive = Mock()
        video = {"id": "gonle-video", "name": "video.mp4", "appProperties": {}}
        pair = ("video", video, {"id": "", "name": ""})

        class FakeDownloader:
            def __init__(self, stream, _request, **_kwargs):
                stream.write(b"source-video")

            def next_chunk(self):
                return None, True

        def run_ig(_drive, _video, _slot, _required, jobs, _properties, **_kwargs):
            jobs["ig"]()
            return {"ig": "media-id"}, {}

        with tempfile.TemporaryDirectory() as workdir:
            original_cwd = os.getcwd()
            os.chdir(workdir)
            try:
                env = {
                    "GITHUB_ACTIONS": "true", "ENABLE_GONLE_NORMAL_ROUTES": "true",
                    "ENABLE_GONLE_INSTAGRAM_ROUTES": "true", "FORCE_PLATFORM": "instagram",
                }
                with patch.dict("os.environ", env, clear=True), \
                     patch("scheduled_multi_publisher.folder_for_route", return_value="gonle-folder"), \
                     patch("scheduled_multi_publisher.list_pairs", return_value=([video], [pair])), \
                     patch("scheduled_multi_publisher.select_random_unused", return_value=pair), \
                     patch("scheduled_multi_publisher.verify_file_in_folder"), \
                     patch("scheduled_multi_publisher.MediaIoBaseDownload", FakeDownloader), \
                     patch("scheduled_multi_publisher.prepare_instagram_upload", side_effect=lambda source, _output, **_kwargs: source) as prepare, \
                     patch("scheduled_multi_publisher.meta_page", return_value={"page_id": "page"}), \
                     patch("scheduled_multi_publisher.upload_instagram_reel", return_value="media-id") as upload, \
                     patch("scheduled_multi_publisher.execute_platform_jobs", side_effect=run_ig), \
                     patch("scheduled_multi_publisher.notify", return_value=False):
                    run_publisher(drive=drive, selected=("gonle", "2026-10-18-21-gonle"), routing_validated=True)
                self.assertTrue(prepare.call_args.kwargs["film_compact"])
                self.assertTrue(upload.call_args.kwargs["publish"])
            finally:
                os.chdir(original_cwd)

    def test_controlled_gonle_upload_only_never_publishes_or_mutates_drive(self):
        file_id = "1PmQueyQl7iD1RguTimcwBYLsXSn_M6jc"
        item = {"id": file_id, "name": "70.mp4", "parents": ["gonle-folder"],
                "mimeType": "video/mp4", "size": "20"}
        page = {"page_name": "Gönle Düşen", "instagram_id": "ig-id", "page_token": "not-logged"}

        class FakeDownloader:
            def __init__(self, target, _request, chunksize):
                self.target = target
                self.done = False
            def next_chunk(self):
                if not self.done:
                    self.target.write(b"gonle-source-video")
                    self.done = True
                return None, True

        drive = Mock()
        drive.files.return_value.get.return_value.execute.return_value = item
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GONLE_IG_CONTROLLED_TEST": "true", "FORCE_ROUTE": "gonle_ig",
            "FORCE_PLATFORM": "instagram",
        }, clear=True), \
             patch("scheduled_multi_publisher.folder_for_route", return_value="gonle-folder"), \
             patch("scheduled_multi_publisher.meta_page", return_value=page) as meta_page, \
             patch("scheduled_multi_publisher.verify_file_in_folder"), \
             patch("scheduled_multi_publisher.MediaIoBaseDownload", FakeDownloader), \
             patch("scheduled_multi_publisher.log_media_diagnostics"), \
             patch("scheduled_multi_publisher.check_full_decode"), \
             patch("scheduled_multi_publisher.prepare_instagram_upload", side_effect=lambda source, *_a, **_kw: (source, "direct")) as prepare, \
             patch("scheduled_multi_publisher.upload_instagram_reel", return_value={
                 "container_id": "container-gonle", "status": "FINISHED", "published": False,
             }) as upload:
            result = run_publisher(drive=drive, routing_validated=True)

        self.assertEqual(result["container_id"], "container-gonle")
        meta_page.assert_called_once_with("Gönle Düşen")
        self.assertTrue(prepare.call_args.kwargs["film_compact"])
        self.assertTrue(prepare.call_args.kwargs["prefer_remux"])
        self.assertFalse(upload.call_args.kwargs["append_store_link"])
        self.assertIs(upload.call_args.kwargs["publish"], False)
        drive.files.return_value.update.assert_not_called()

    def test_controlled_gonle_upload_only_rejects_wrong_route_before_drive_access(self):
        env = {
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GONLE_IG_CONTROLLED_TEST": "true", "FORCE_ROUTE": "film",
            "FORCE_PLATFORM": "instagram",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "scheduled_multi_publisher.get_drive_client"
        ) as get_drive:
            with self.assertRaisesRegex(RuntimeError, "Gönle kontrollü upload-only"):
                run_publisher()
        get_drive.assert_not_called()

    def test_thumbnail_failure_is_nonfatal(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "cover-1", "name": "tarladaki.jpg", "mimeType": "image/jpeg", "parents": ["covers"]}]
        }
        env = {
            "COVER_FEATURE_ENABLED": "true",
            "COVER_DRIVE_FOLDER_ID": "root",
            "COVER_TARLADAKI_FOLDER_ID": "covers",
        }
        with patch.dict("os.environ", env, clear=True), patch(
            "scheduled_multi_publisher.download_and_validate_cover", return_value=(b"jpg", (900, 1200))
        ), patch("scheduled_multi_publisher.set_youtube_thumbnail", side_effect=RuntimeError("forbidden")):
            self.assertFalse(apply_youtube_fixed_cover(drive, Mock(), "tarladaki", "source", "video", Path("temp")))

    def test_cover_disabled_makes_no_drive_call(self):
        drive = Mock()
        with patch.dict("os.environ", {"COVER_FEATURE_ENABLED": "false"}, clear=True):
            self.assertFalse(apply_youtube_fixed_cover(drive, Mock(), "tarladaki", "source", "video", Path("temp")))
        drive.files.assert_not_called()

    def test_drive_name_normalization_handles_turkish_dotted_i(self):
        self.assertEqual(_normalized_name("İslam olan"), _normalized_name("islam olan"))
        self.assertEqual(_normalized_name("İngilizce Mizah"), _normalized_name("ingilizce mizah"))

    def test_daily_routes(self):
        cases = {
            (9, 15): "gonle", (12, 20): "gonle", (21, 15): "gonle",
            (9, 0): "tarladaki", (18, 20): "tarladaki", (21, 29): "tarladaki",
            (9, 30): "penguen", (18, 50): "penguen", (21, 30): "penguen",
        }
        for (hour, minute), expected in cases.items():
            with self.subTest(hour=hour, minute=minute):
                routes = routes_for_time(datetime(2026, 10, 11, hour, minute))
                self.assertIn(expected, {route for route, _ in routes})

    def test_outside_schedule(self):
        self.assertEqual(route_for_time(datetime(2026, 10, 11, 7, 0)), (None, None))

    def test_toonzone_four_ordered_daily_slots_are_gated(self):
        env = {
            "ENABLE_TOONZONE_ROUTES": "true",
            "ENABLE_NEW_META_ROUTES": "true",
            "META_NEW_ROUTES_RIGHTS_APPROVED": "true",
        }
        with patch.dict("os.environ", env, clear=True):
            for minute, part in ((0, 1), (5, 1), (10, 2), (15, 2), (20, 3), (25, 3), (30, 4), (35, 4)):
                with self.subTest(minute=minute):
                    self.assertIn(
                        ("toonzone", f"2026-10-18-12-toonzone-part{part}"),
                        routes_for_time(datetime(2026, 10, 18, 12, minute)),
                    )
            self.assertNotIn(
                "toonzone", {route for route, _ in routes_for_time(datetime(2026, 10, 18, 12, 40))}
            )
        with patch.dict("os.environ", {}, clear=True):
            self.assertNotIn(
                "toonzone", {route for route, _ in routes_for_time(datetime(2026, 10, 18, 12, 0))}
            )

    def test_toonzone_due_slots_reach_live_batch_dispatcher_only_when_approved(self):
        now = datetime(2026, 10, 21, 12, 35)
        gate = {
            "ENABLE_TOONZONE_ROUTES": "true",
            "ENABLE_NEW_META_ROUTES": "true",
            "META_NEW_ROUTES_RIGHTS_APPROVED": "true",
        }
        with patch.dict("os.environ", gate, clear=True):
            rows = [slot for _planned, route, slot in due_slots(now, lookback_minutes=40)
                    if route == "toonzone"]
            self.assertEqual(rows, [
                "2026-10-21-12-toonzone-part1",
                "2026-10-21-12-toonzone-part2",
                "2026-10-21-12-toonzone-part3",
                "2026-10-21-12-toonzone-part4",
            ])
        for missing in gate:
            env = {k: v for k, v in gate.items() if k != missing}
            with self.subTest(missing=missing), patch.dict("os.environ", env, clear=True):
                self.assertFalse([row for row in due_slots(now, lookback_minutes=40)
                                  if row[1] == "toonzone"])

    def test_toonzone_manual_recovery_does_not_complete_other_parts(self):
        day = datetime(2026, 10, 21, 12, 0)
        videos = [{
            "appProperties": {
                "last_route_slot": "manual-2026-10-21-1205-toonzone-toonzone-part1",
            },
        }]
        self.assertTrue(slot_is_done(videos, day, "toonzone", "2026-10-21-12-toonzone-part1"))
        for part in (2, 3, 4):
            with self.subTest(part=part):
                planned = day.replace(minute=(part - 1) * 10)
                slot = f"2026-10-21-12-toonzone-part{part}"
                self.assertFalse(slot_is_done(videos, planned, "toonzone", slot))
        videos[0]["appProperties"]["last_route_slot"] = "manual-2026-10-21-1215-toonzone-toonzone-part2"
        self.assertTrue(slot_is_done(videos, day.replace(minute=10), "toonzone",
                                    "2026-10-21-12-toonzone-part2"))
        self.assertFalse(slot_is_done(videos, day, "toonzone", "2026-10-21-12-toonzone-part1"))

    def test_next_due_toonzone_part_resumes_after_manual_part_one(self):
        gate = {
            "ENABLE_TOONZONE_ROUTES": "true",
            "ENABLE_NEW_META_ROUTES": "true",
            "META_NEW_ROUTES_RIGHTS_APPROVED": "true",
        }
        files = [
            {"id": f"v{i}", "name": f"S01E01_The_Power_Part{i}.mp4",
             "appProperties": {TOONZONE_USED: "1"} if i == 1 else {}}
            for i in range(1, 5)
        ]
        with patch.dict("os.environ", gate, clear=True), patch(
            "scheduled_multi_publisher.folder_for_route", return_value="toonzone-folder"
        ), patch("scheduled_multi_publisher.list_pairs", return_value=(files, [])):
            self.assertEqual(
                next_due_route(Mock(), now=datetime(2026, 10, 21, 12, 15),
                               allowed_routes={"toonzone"}),
                ("toonzone", "2026-10-21-12-toonzone-part2"),
            )
            files[0]["appProperties"] = {"claimed_route_slot": "manual-old-part1"}
            self.assertEqual(
                next_due_route(Mock(), now=datetime(2026, 10, 21, 12, 15),
                               allowed_routes={"toonzone"}),
                ("toonzone", "2026-10-21-12-toonzone-part1"),
            )

    def test_toonzone_new_episode_cannot_replay_part_one_after_part_four_today(self):
        gate = {
            "ENABLE_TOONZONE_ROUTES": "true",
            "ENABLE_NEW_META_ROUTES": "true",
            "META_NEW_ROUTES_RIGHTS_APPROVED": "true",
        }
        files = [
            {"id": f"v{i}", "name": f"S01E01_The_Power_Part{i}.mp4",
             "appProperties": {TOONZONE_USED: "1",
                               "last_route_slot": f"2026-10-21-12-toonzone-part{i}"}}
            for i in range(1, 5)
        ] + [{"id": "v5", "name": "S01E02_Just_Setting_Up_The_Chairs_Part1.mp4",
              "appProperties": {}}]
        with patch.dict("os.environ", gate, clear=True), patch(
            "scheduled_multi_publisher.folder_for_route", return_value="toonzone-folder"
        ), patch("scheduled_multi_publisher.list_pairs", return_value=(files, [])):
            self.assertEqual(
                next_due_route(Mock(), now=datetime(2026, 10, 21, 12, 35),
                               allowed_routes={"toonzone"}),
                (None, None),
            )

    def test_forced_toonzone_launch_is_bound_to_part_one(self):
        with patch.dict("os.environ", {"FORCE_ROUTE": "toonzone"}, clear=True):
            self.assertEqual(
                route_for_time(datetime(2026, 10, 18, 21, 30)),
                ("toonzone", "manual-2026-10-18-2130-toonzone-toonzone-part1"),
            )

    def test_forced_toonzone_part_uses_explicit_suffix(self):
        with patch.dict("os.environ", {
            "FORCE_ROUTE": "toonzone", "FORCE_SLOT_SUFFIX": "toonzone-part3",
        }, clear=True):
            self.assertEqual(
                route_for_time(datetime(2026, 10, 18, 21, 30)),
                ("toonzone", "manual-2026-10-18-2130-toonzone-toonzone-part3"),
            )
        with patch.dict("os.environ", {
            "FORCE_ROUTE": "toonzone", "FORCE_SLOT_SUFFIX": "toonzone-part5",
        }, clear=True):
            with self.assertRaises(RuntimeError):
                route_for_time(datetime(2026, 10, 18, 21, 30))

    def test_toonzone_selector_keeps_episode_parts_in_order(self):
        files = [
            {"id": f"p{part}", "name": f"S01E01_The_Power_Part{part}.mp4", "appProperties": {}}
            for part in range(1, 5)
        ]
        self.assertEqual(
            select_next_toonzone_part(files, "2026-10-18-12-toonzone-part1")[0],
            "S01E01_The_Power_Part1",
        )
        files[0]["appProperties"][TOONZONE_USED] = "1"
        self.assertEqual(
            select_next_toonzone_part(files, "2026-10-18-12-toonzone-part2")[0],
            "S01E01_The_Power_Part2",
        )
        self.assertIsNone(select_next_toonzone_part(files, "2026-10-18-12-toonzone-part3"))
        files[1]["appProperties"]["done_fb_slot"] = "2026-10-17-old-slot"
        with self.assertRaises(RuntimeError):
            select_next_toonzone_part(files, "2026-10-18-12-toonzone-part2")
        files[1]["appProperties"].pop("done_fb_slot")
        files[1]["appProperties"]["claimed_route_slot"] = "2026-10-18-12-toonzone-part2"
        with self.assertRaises(RuntimeError):
            select_next_toonzone_part(files, "2026-10-18-12-toonzone-part2")
        files[1]["appProperties"].clear()
        files.append({"id": "duplicate", "name": "S01E01_The_Power_Part2.mp4", "appProperties": {}})
        with self.assertRaises(RuntimeError):
            select_next_toonzone_part(files, "2026-10-18-12-toonzone-part2")

    def test_toonzone_part1_ig_recovery_requires_exact_known_fb_only_state(self):
        video = {
            "id": "1WPrqw8SEmCyjaSLDvAe-VuP2S-AWYeuX",
            "name": "S01E01_The_Power_Part1.mp4",
            "appProperties": {
                "claimed_route_slot": "manual-2026-10-18-2135-toonzone-toonzone-part1",
                "failed_route_slot": "manual-2026-10-18-2135-toonzone-toonzone-part1",
                "done_fb_slot": "manual-2026-10-18-2135-toonzone-toonzone-part1",
                "result_fb": "1427675756211474",
            },
        }
        files = [video] + [
            {"id": f"p{part}", "name": f"S01E01_The_Power_Part{part}.mp4", "appProperties": {}}
            for part in range(2, 5)
        ]
        self.assertEqual(
            select_next_toonzone_part(
                files,
                "manual-2026-10-19-0800-toonzone-toonzone-part1",
                allow_part1_ig_recovery=True,
            )[0],
            "S01E01_The_Power_Part1",
        )
        video["appProperties"]["intent_ig_slot"] = "manual-2026-10-18-2135-toonzone-toonzone-part1"
        with self.assertRaises(RuntimeError):
            select_next_toonzone_part(
                files,
                "manual-2026-10-19-0800-toonzone-toonzone-part1",
                allow_part1_ig_recovery=True,
            )
        video["appProperties"].pop("intent_ig_slot")
        video["appProperties"]["claimed_route_slot"] = "different-claim"
        with self.assertRaises(RuntimeError):
            select_next_toonzone_part(
                files,
                "manual-2026-10-19-0800-toonzone-toonzone-part1",
                allow_part1_ig_recovery=True,
            )

    def test_toonzone_starting_episode_requires_exact_cover_for_all_four_parts(self):
        folder_id = "14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF"
        cover_folder_id = TOONZONE_COVER_FOLDER_ID
        videos, covers = [], []
        for part in range(1, 5):
            stem = f"S01E01_The_Power_Part{part}"
            videos.append({"id": f"v{part}", "name": stem + ".mp4", "parents": [folder_id], "mimeType": "video/mp4"})
            covers.append({"id": f"c{part}", "name": stem + ".png", "parents": [cover_folder_id], "mimeType": "image/png"})
        drive = Mock()
        def get_folder(fileId, **_kwargs):
            result = (
                {"id": folder_id, "name": "cizgi film", "mimeType": "application/vnd.google-apps.folder", "trashed": False}
                if fileId == folder_id else
                {"id": cover_folder_id, "name": "Kapaklar", "mimeType": "application/vnd.google-apps.folder",
                 "parents": [folder_id], "trashed": False}
            )
            return Mock(execute=Mock(return_value=result))
        drive.files.return_value.get.side_effect = get_folder
        def list_files(_drive, requested_folder):
            return (videos, []) if requested_folder == folder_id else (covers, [])
        with patch("scheduled_multi_publisher.list_pairs", side_effect=list_files):
            result = validate_toonzone_starting_episode(drive)
        self.assertEqual(result["parts"], 4)
        self.assertEqual(result["covers"], 4)
        covers.pop()  # Remove Part 4's cover; fail closed before any publish.
        with patch("scheduled_multi_publisher.list_pairs", side_effect=list_files):
            with self.assertRaises(RuntimeError):
                validate_toonzone_starting_episode(drive)

    def test_daily_uses_new_york_dst_schedule(self):
        # 09:00 New York is 16:00 Turkey while DST is active.
        now = datetime(2026, 10, 11, 16, 0)
        self.assertIn(("daily_laugh", "2026-10-11-09-daily_laugh"), routes_for_time(now))
        # New 08:00 New York slot becomes 16:00 Turkey after US DST ends.
        standard = datetime(2026, 11, 8, 16, 0)
        self.assertIn(("daily_laugh", "2026-11-08-08-daily_laugh"), routes_for_time(standard))

    def test_delayed_cron_stays_within_current_slot(self):
        with patch.dict("os.environ", {"ENABLE_FILM_ROUTES": "true"}, clear=True):
            at_1629 = {route for route, _ in routes_for_time(datetime(2026, 10, 18, 16, 29))}
            at_1630 = {route for route, _ in routes_for_time(datetime(2026, 10, 18, 16, 30))}
        self.assertIn("film", at_1629)
        self.assertIn("daily_laugh", at_1629)
        self.assertNotIn("film", at_1630)
        self.assertNotIn("daily_laugh", at_1630)
        self.assertIn("gonle", {route for route, _ in routes_for_time(datetime(2026, 10, 18, 18, 44))})
        self.assertNotIn("gonle", {route for route, _ in routes_for_time(datetime(2026, 10, 18, 18, 45))})

    def test_manual_route(self):
        with patch.dict("os.environ", {"FORCE_ROUTE": "penguen"}):
            route, slot = route_for_time(datetime(2026, 10, 11, 23, 0))
        self.assertEqual(route, "penguen")
        self.assertIn("manual-", slot)

    def test_manual_route_supports_unique_backfill_slots(self):
        env = {"FORCE_ROUTE": "penguen", "FORCE_SLOT_SUFFIX": "backfill-2"}
        with patch.dict("os.environ", env, clear=True):
            _, slot = route_for_time(datetime(2026, 10, 11, 23, 0))
        self.assertTrue(slot.endswith("penguen-backfill-2"))

    def test_gonle_platform_routes_can_be_forced(self):
        for forced in ("gonle_fb", "gonle_ig"):
            with self.subTest(forced=forced):
                with patch.dict("os.environ", {"FORCE_ROUTE": forced}, clear=True):
                    route, _ = route_for_time(datetime(2026, 10, 11, 23, 0))
                self.assertEqual(route, forced)

    def test_only_midnight_daily_laugh_is_first_daily_notification(self):
        self.assertTrue(
            is_first_daily_slot("daily_laugh", "2026-10-12-09-daily_laugh")
        )
        self.assertFalse(
            is_first_daily_slot("daily_laugh", "2026-10-12-12-daily_laugh")
        )
        self.assertFalse(is_first_daily_slot("gonle", "2026-10-12-08-gonle"))

    def test_youtube_description_is_valid_and_keeps_store_link(self):
        description = "<metin>" * 1000
        cleaned = youtube_safe_description(description)
        self.assertLessEqual(len(cleaned), 5000)
        self.assertNotIn("<", cleaned)
        self.assertNotIn(">", cleaned)
        self.assertTrue(cleaned.endswith("https://www.etsy.com/shop/MiroviaStudio?ref=dashboard-header"))

    def test_each_video_keeps_its_own_txt_and_store_link_at_end(self):
        title, caption = content_from_txt(
            "Bu videonun özel başlığı\nÖzgün açıklama\n#kendiEtiketi",
            "video-264", "gonle",
        )
        self.assertEqual(title, "Bu videonun özel başlığı")
        self.assertEqual(
            caption,
            "Bu videonun özel başlığı\nÖzgün açıklama\n#kendiEtiketi\n\n"
            "https://www.etsy.com/shop/MiroviaStudio?ref=dashboard-header",
        )
        self.assertNotIn("#islam", caption)

    def test_generic_channel_title_uses_unique_filename(self):
        title, caption = content_from_txt("Daily Laugh Lab\nVideo açıklaması", "Funny_207", "daily_laugh")
        self.assertEqual(title, "Funny_207")
        self.assertTrue(caption.startswith("Daily Laugh Lab\nVideo açıklaması"))

    def test_platform_sections_produce_separate_clean_captions(self):
        raw = """=== INSTAGRAM REELS ===
🎥 FILM_MAGRASI
41w
YOKSUL (1986) — Part 3 🎬
Instagram için kısa açıklama.
👇 Yorumlara yaz!
💾 Kaydet → sonra izle
👇 Yorumlarda buluşalım!
💾 Kaydetmeyi unutma!
#Yoksul #Yeşilçam
=== TIKTOK ===
TikTok'a özel metin.
=== YOUTUBE SHORTS ===
BAŞLIK:
Yoksul Part 3 #shorts
AÇIKLAMA:
YouTube için ayrı açıklama.
#shorts
=== FACEBOOK REELS ===
🎥 FILM_MAGRASI
41w
YOKSUL (1986) — Part 3 🎬
Facebook için ayrı açıklama.
👉 Arkadaşına gönder!
"""
        title, youtube, facebook, instagram, sectioned = platform_content_from_txt(
            raw, "Yoksul_1986_Part_3", "film"
        )
        self.assertTrue(sectioned)
        self.assertEqual(title, "Yoksul Part 3 #shorts")
        self.assertIn("YouTube için ayrı açıklama", youtube)
        self.assertNotIn("Instagram için", youtube)
        self.assertIn("Facebook için ayrı açıklama", facebook)
        self.assertNotIn("TikTok", facebook)
        self.assertIn("Instagram için kısa açıklama", instagram)
        self.assertNotIn("Facebook için", instagram)
        self.assertNotIn("41w", instagram)
        self.assertNotIn("FILM_MAGRASI", instagram)
        self.assertEqual(instagram.count("Yorum"), 1)
        self.assertEqual(instagram.count("Kaydet"), 1)
        self.assertNotIn("etsy.com", facebook.lower())

    def test_sectioned_txt_missing_platform_uses_clean_source_not_other_sections(self):
        raw = """=== YOUTUBE SHORTS ===
        BAŞLIK: Short title
        AÇIKLAMA: Core video description
        #shorts
        === INSTAGRAM REELS ===
        Instagram-only copy
        """
        title, youtube, facebook, instagram, sectioned = platform_content_from_txt(
            raw, "clip_1", "daily_laugh"
        )
        self.assertTrue(sectioned)
        self.assertEqual(title, "Short title")
        self.assertIn("Core video description", youtube)
        self.assertEqual(facebook, "Core video description\n#shorts")
        self.assertEqual(instagram, "Instagram-only copy")

    def test_due_slots_are_processed_in_chronological_order(self):
        slots = due_slots(datetime(2026, 10, 13, 9, 47))
        self.assertEqual(slots, sorted(slots))
        current_day = [item[1:] for item in slots if item[0].date().isoformat() == "2026-10-13"]
        self.assertLess(
            current_day.index(("tarladaki", "2026-10-13-09-tarladaki")),
            current_day.index(("gonle", "2026-10-13-09-gonle")),
        )
        self.assertLess(
            current_day.index(("gonle", "2026-10-13-09-gonle")),
            current_day.index(("penguen", "2026-10-13-09-penguen")),
        )

    def test_next_due_route_selects_oldest_unfinished_slot(self):
        env = {
            "DRIVE_FOLDER_ID": "shared",
            "DAILY_LAUGH_DRIVE_FOLDER_ID": "english",
            "GONLE_DUSEN_DRIVE_FOLDER_ID": "gonle",
            "ENABLE_GONLE_NORMAL_ROUTES": "true",
            "ENABLE_TP_NORMAL_ROUTES": "true",
        }
        with patch.dict("os.environ", env, clear=True), patch(
            "scheduled_multi_publisher.list_pairs", return_value=([], [])
        ):
            route, slot = next_due_route(
                object(), datetime(2026, 10, 13, 10, 1, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Istanbul"))
            )
        self.assertEqual((route, slot), ("tarladaki", "2026-10-12-12-tarladaki"))

    def test_next_due_route_respects_normal_automation_allowlist(self):
        tz = __import__("zoneinfo").ZoneInfo("Europe/Istanbul")
        now = datetime(2026, 10, 13, 10, 1, tzinfo=tz)
        slots = [
            (datetime(2026, 10, 13, 9, 0, tzinfo=tz), "tarladaki", "2026-10-13-09-tarladaki"),
            (datetime(2026, 10, 13, 9, 30, tzinfo=tz), "penguen", "2026-10-13-09-penguen"),
        ]
        env = {
            "DRIVE_FOLDER_ID": "shared",
            "ENABLE_TP_NORMAL_ROUTES": "true",
        }
        with patch.dict("os.environ", env, clear=True), patch(
            "scheduled_multi_publisher.due_slots", return_value=slots
        ), patch("scheduled_multi_publisher.list_pairs", return_value=([], [])):
            route, slot = next_due_route(
                object(), now=now, allowed_routes={"penguen"},
            )
        self.assertEqual((route, slot), ("penguen", "2026-10-13-09-penguen"))

    def test_primary_and_backup_workflows_share_serialized_queue(self):
        workflow_dir = Path(__file__).parent / ".github" / "workflows"
        main = yaml.safe_load((workflow_dir / "omnichannel_schedule.yml").read_text(encoding="utf-8"))
        backup = yaml.safe_load((workflow_dir / "cloud_schedule_backup.yml").read_text(encoding="utf-8"))
        main_concurrency = main["concurrency"]
        self.assertEqual(main_concurrency["group"], "cloud-omni-uploader")
        self.assertFalse(main_concurrency["cancel-in-progress"])
        self.assertEqual(main_concurrency["queue"], "max")
        self.assertEqual(
            backup["jobs"]["cloud-backup"]["uses"],
            "./.github/workflows/omnichannel_schedule.yml",
        )

    def test_due_slots_keep_daily_local_slot_identity(self):
        slots = due_slots(datetime(2026, 10, 13, 16, 30))
        self.assertIn(
            ("daily_laugh", "2026-10-13-09-daily_laugh"),
            [item[1:] for item in slots],
        )

    def test_catchup_handles_each_route_at_most_once_per_invocation(self):
        observed_exclusions = []
        def choose(_drive, **kwargs):
            excluded = kwargs.get("excluded_routes", set())
            observed_exclusions.append(set(excluded))
            if {"gonle", "penguen"}.issubset(excluded):
                return None, None
            if "gonle" in excluded:
                return "penguen", "penguen"
            return "gonle", "old-gonle"
        with patch("scheduled_multi_publisher.get_drive_client", return_value=object()), patch(
            "scheduled_multi_publisher.validate_drive_routing"
        ), patch("scheduled_multi_publisher.quarantine_legacy_shared_claims"), patch(
            "scheduled_multi_publisher.next_due_route", side_effect=choose
        ) as choose, patch("scheduled_multi_publisher.run", return_value=None) as publish:
            run_due(max_slots=4)
        self.assertEqual(publish.call_count, 2)
        self.assertEqual(observed_exclusions[1], {"gonle"})

    def test_due_slot_cap_is_safe_and_configurable(self):
        self.assertEqual(configured_max_due_slots("3"), 3)
        self.assertEqual(configured_max_due_slots("99"), 4)
        self.assertEqual(configured_max_due_slots("bad"), 2)

    def test_platform_pacing_is_scoped_to_account_and_platform(self):
        publisher._LAST_PLATFORM_PUBLISH_AT.clear()
        with patch.dict(os.environ, {"MIN_PLATFORM_INTERVAL_SECONDS": "60"}), patch(
            "scheduled_multi_publisher.time.monotonic", side_effect=[0.0, 10.0, 10.0, 10.0]
        ), patch("scheduled_multi_publisher.time.sleep") as sleep:
            publisher._paced_platform_call(lambda: None, "tarladaki", "instagram")
            publisher._paced_platform_call(lambda: None, "tarladaki", "instagram")
            publisher._paced_platform_call(lambda: None, "penguen", "instagram")
        sleep.assert_called_once_with(50.0)

    def test_one_failed_slot_does_not_block_other_due_slots(self):
        selected = [("gonle", "slot-a"), ("penguen", "slot-b"), (None, None)]
        with patch("scheduled_multi_publisher.get_drive_client", return_value=object()), patch(
            "scheduled_multi_publisher.validate_drive_routing"
        ), patch("scheduled_multi_publisher.quarantine_legacy_shared_claims"), patch(
            "scheduled_multi_publisher.next_due_route", side_effect=selected
        ), patch("scheduled_multi_publisher.run", side_effect=[RuntimeError("failed"), None]) as publish:
            with self.assertRaisesRegex(RuntimeError, "slot-a"):
                run_due(max_slots=3)
        self.assertEqual(publish.call_count, 2)

    def test_blocked_film_and_toonzone_cannot_starve_two_healthy_routes(self):
        selected = [
            ("film", "blocked-film"), ("toonzone", "blocked-toonzone"),
            ("gonle", "good-gonle"), ("penguen", "good-penguen"),
        ]
        excluded = []
        def choose(_drive, **kwargs):
            excluded.append(set(kwargs["excluded_routes"]))
            remaining = [row for row in selected if row[0] not in kwargs["excluded_routes"]]
            return remaining[0] if remaining else (None, None)
        with patch("scheduled_multi_publisher.get_drive_client", return_value=object()), patch(
            "scheduled_multi_publisher.validate_drive_routing"
        ), patch("scheduled_multi_publisher.quarantine_legacy_shared_claims"), patch(
            "scheduled_multi_publisher.next_due_route", side_effect=choose
        ), patch("scheduled_multi_publisher.run", side_effect=[
            RuntimeError("stale Film claim"), RuntimeError("stale ToonZone claim"), None, None
        ]) as publish:
            with self.assertRaisesRegex(RuntimeError, "blocked-film"):
                run_due(max_slots=2)
        self.assertEqual(publish.call_count, 4)
        self.assertEqual([c.kwargs["selected"] for c in publish.call_args_list], selected)
        self.assertEqual(excluded[1], {"film"})
        self.assertEqual(excluded[2], {"film", "toonzone"})
        self.assertEqual(excluded[3], {"film", "toonzone", "gonle"})

    def test_successful_route_cap_stays_two_when_more_routes_are_due(self):
        selected = [
            ("gonle", "slot-1"), ("penguen", "slot-2"), ("tarladaki", "slot-3"),
        ]
        with patch("scheduled_multi_publisher.get_drive_client", return_value=object()), patch(
            "scheduled_multi_publisher.validate_drive_routing"
        ), patch("scheduled_multi_publisher.quarantine_legacy_shared_claims"), patch(
            "scheduled_multi_publisher.next_due_route", side_effect=selected
        ), patch("scheduled_multi_publisher.run", return_value=None) as publish:
            run_due(max_slots=2)
        self.assertEqual(publish.call_count, 2)

    def test_normal_catchup_can_skip_legacy_claim_mutation_and_scopes_routes(self):
        selected = [("penguen", "slot-penguen"), (None, None)]
        with patch("scheduled_multi_publisher.get_drive_client", return_value=object()), patch(
            "scheduled_multi_publisher.validate_drive_routing"
        ), patch("scheduled_multi_publisher.quarantine_legacy_shared_claims") as quarantine, patch(
            "scheduled_multi_publisher.next_due_route", side_effect=selected
        ) as choose, patch("scheduled_multi_publisher.run", return_value=None) as publish:
            run_due(
                max_slots=1, allowed_routes={"penguen"}, quarantine_shared_claims=False,
            )
        quarantine.assert_not_called()
        self.assertEqual(choose.call_args.kwargs["allowed_routes"], {"penguen"})
        self.assertEqual(publish.call_count, 1)

    def test_manual_recovery_satisfies_its_scheduled_window(self):
        planned = datetime(2026, 10, 13, 9, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Istanbul"))
        files = [{"appProperties": {"last_route_slot": "manual-2026-10-13-0924-tarladaki-backfill-1"}}]
        self.assertTrue(slot_is_done(files, planned, "tarladaki", "2026-10-13-09-tarladaki"))
        self.assertFalse(slot_is_done(files, planned, "penguen", "2026-10-13-09-penguen"))

    def test_terminal_failed_slot_is_not_selected_again(self):
        planned = datetime(2026, 10, 13, 9, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Istanbul"))
        files = [{"appProperties": {FAILED_SLOT: "2026-10-13-09-tarladaki"}}]
        self.assertTrue(slot_is_done(files, planned, "tarladaki", "2026-10-13-09-tarladaki"))

    def test_drive_name_cannot_escape_temp_directory(self):
        from pathlib import Path

        result = safe_temp_path(Path("temp"), "raw", "../../route", "../bad/id", ".mp4")
        self.assertEqual(result.parent, Path("temp"))
        self.assertNotIn("..", result.name)

    def test_retry_reuses_the_video_claimed_for_the_slot(self):
        claimed = {
            "id": "video-1",
            "appProperties": {"claimed_route_slot": "2026-10-13-09-tarladaki"},
        }
        other = {"id": "video-2", "appProperties": {}}
        pairs = [("one", claimed, {}), ("two", other, {})]
        picked = select_random_unused(
            None, [claimed, other], pairs, "shared_mizah_used", "2026-10-13-09-tarladaki"
        )
        self.assertEqual(picked[1]["id"], "video-1")

    def test_checksum_copy_of_published_video_is_not_selected(self):
        used = {"id": "used", "md5Checksum": "same", "appProperties": {"shared_mizah_used": "1"}}
        copied = {"id": "copy", "md5Checksum": "same", "appProperties": {}}
        fresh = {"id": "fresh", "md5Checksum": "new", "appProperties": {}}
        with patch("scheduled_multi_publisher.random.choice", side_effect=lambda choices: choices[0]):
            picked = select_random_unused(
                None, [used, copied, fresh], [("copy", copied, {}), ("fresh", fresh, {})],
                "shared_mizah_used", "2026-10-16-09-tarladaki",
            )
        self.assertEqual(picked[1]["id"], "fresh")

    def test_tp_daily_slots_follow_turkey_time(self):
        tz = __import__("zoneinfo").ZoneInfo("Europe/Istanbul")
        self.assertEqual(route_for_time(datetime(2026, 10, 17, 9, 0, tzinfo=tz))[0], "tarladaki")
        self.assertEqual(route_for_time(datetime(2026, 10, 17, 9, 30, tzinfo=tz))[0], "penguen")

    def test_old_shared_slot_never_uses_legacy_folder(self):
        slot = "2026-10-13-21-penguen"
        legacy = [{"appProperties": {"claimed_route_slot": slot}}]
        env = {
            "DRIVE_FOLDER_ID": "correct-shared-folder",
            "DAILY_LAUGH_DRIVE_FOLDER_ID": "old-english-folder",
        }
        with patch.dict("os.environ", env):
            self.assertEqual(shared_folder_for_slot(object(), slot), "correct-shared-folder")

    def test_shared_route_rejects_unapproved_content_even_in_correct_folder(self):
        from approved_content import approved_shared_pairs
        pairs = [
            ("approved", {"id": "1X-dlZPYrf4pFatQjry_mxvk0cgattWlw", "md5Checksum": "b95a552cae245da7273a0dec8bfef204"}, {}),
            ("copy", {"id": "215", "md5Checksum": "b95a552cae245da7273a0dec8bfef204"}, {}),
        ]
        self.assertEqual(
            [p[0] for p in approved_shared_pairs("tarladaki", "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M", pairs)],
            ["approved"],
        )

    def test_wrong_drive_secret_stops_before_api_lookup(self):
        env = {
            "DRIVE_FOLDER_ID": "wrong",
            "GONLE_DUSEN_DRIVE_FOLDER_ID": "1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt",
            "DAILY_LAUGH_DRIVE_FOLDER_ID": "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M",
        }
        drive = Mock()
        with patch.dict("os.environ", env, clear=True), self.assertRaisesRegex(RuntimeError, "eşleşmiyor"):
            validate_drive_routing(drive)
        drive.files.assert_not_called()

    def test_wrong_drive_folder_name_stops_publishing(self):
        env = {
            "DRIVE_FOLDER_ID": "11zbrunHoiTZyJ8JDsj99ascO66mmCj-M",
            "GONLE_DUSEN_DRIVE_FOLDER_ID": "1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt",
            "DAILY_LAUGH_DRIVE_FOLDER_ID": "137--TeBht1yikZpMfV9VSEADbKuXZtLT",
        }
        drive = Mock()
        drive.files.return_value.get.return_value.execute.return_value = {
            "id": env["DRIVE_FOLDER_ID"], "name": "İngilizce Mizah",
            "mimeType": "application/vnd.google-apps.folder", "trashed": False,
        }
        with patch.dict("os.environ", env, clear=True), self.assertRaisesRegex(RuntimeError, "klasör adı"):
            validate_drive_routing(drive)

    def test_selected_file_must_be_direct_child_of_allowed_folder(self):
        drive = Mock()
        drive.files.return_value.get.return_value.execute.return_value = {
            "id": "video-1", "name": "1.mp4", "parents": ["wrong-folder"], "trashed": False,
        }
        with self.assertRaisesRegex(RuntimeError, "izin verilen"):
            verify_file_in_folder(drive, {"id": "video-1"}, "allowed-folder")

    def test_duplicate_mp4_stems_fail_closed_instead_of_overwriting(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "first", "name": "132.mp4", "parents": ["shared"], "appProperties": {}},
                {"id": "second", "name": "132.mp4", "parents": ["shared"], "appProperties": {}},
                {"id": "txt", "name": "132.txt", "parents": ["shared"], "appProperties": {}},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "Aynı gövdeli MP4"):
            list_pairs(drive, "shared")

    def test_legacy_cross_folder_claim_is_quarantined_not_published(self):
        drive = Mock()
        drive.files.return_value.update.return_value.execute.return_value = {}
        legacy = [{
            "id": "bad-video",
            "appProperties": {"claimed_route_slot": "2026-10-13-21-penguen"},
        }]
        drive.files.return_value.list.return_value.execute.return_value = {"files": legacy}
        with patch.dict("os.environ", {"DAILY_LAUGH_DRIVE_FOLDER_ID": "english"}):
            self.assertEqual(quarantine_legacy_shared_claims(drive), 1)
        body = drive.files.return_value.update.call_args.kwargs["body"]["appProperties"]
        self.assertEqual(body[FAILED_SLOT], "2026-10-13-21-penguen")
        self.assertIsNone(body["claimed_route_slot"])

    def test_penguen_route_has_no_kova_post_fallback(self):
        source = (Path(__file__).parent / "scheduled_multi_publisher.py").read_text(encoding="utf-8")
        self.assertNotIn('get_page("Beyinsiz Penguen", "Kova Post")', source)
        self.assertNotIn('upload_ig("Beyinsiz Penguen", "Kova Post")', source)

    def test_routing_audit_is_read_only_and_checks_every_active_account(self):
        drive = Mock()
        with patch("scheduled_multi_publisher.get_drive_client", return_value=drive), patch(
            "scheduled_multi_publisher.validate_drive_routing"
        ) as validate, patch("scheduled_multi_publisher.meta_page") as account, patch(
            "scheduled_multi_publisher.validate_toonzone_starting_episode", return_value={"parts": 4}
        ) as toonzone_assets:
            audit_routing_only()
        validate.assert_called_once_with(drive)
        self.assertEqual(
            [call.args[0] for call in account.call_args_list],
            ["Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen", "Daily Laugh Lab",
             "Film Mağarası", "Filmmagrasi", "ToonZone"],
        )
        toonzone_assets.assert_called_once_with(drive)
        drive.files.return_value.update.assert_not_called()


class PublishStateTests(unittest.TestCase):
    def setUp(self):
        publisher._LAST_PLATFORM_PUBLISH_AT.clear()
        self.env_patch = patch.dict(os.environ, {"MIN_PLATFORM_INTERVAL_SECONDS": "0"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.drive = Mock()
        self.drive.files.return_value.update.return_value.execute.return_value = {}
        self.video = {"id": "video-1", "appProperties": {}}
        self.slot = "2026-10-13-09-tarladaki"

    def test_pipeline_failure_notifies_once_but_upload_only_test_failure_stays_separate(self):
        failure = RuntimeError("preflight failed")
        with patch.dict(os.environ, {}, clear=True), patch(
            "scheduled_multi_publisher._run_impl", side_effect=failure
        ), patch("scheduled_multi_publisher.notify", return_value=True) as send:
            with self.assertRaisesRegex(RuntimeError, "preflight failed"):
                run_publisher(drive=self.drive, selected=("gonle", "slot-1"))
        send.assert_called_once()
        self.assertEqual(send.call_args.args[:2], ("gonle", "slot-1"))

        with patch.dict(os.environ, {"FILM_IG_UPLOAD_ONLY": "true"}, clear=True), patch(
            "scheduled_multi_publisher._run_impl", side_effect=RuntimeError("test failed")
        ), patch("scheduled_multi_publisher.notify") as send:
            with self.assertRaisesRegex(RuntimeError, "test failed"):
                run_publisher(drive=self.drive, selected=("film", "slot-2"))
        send.assert_not_called()

    def test_success_is_persisted_per_platform_and_not_repeated(self):
        yt = Mock(return_value="https://youtube.com/shorts/abc")
        fb = Mock(side_effect=RuntimeError("Meta API açık ret"))
        results, errors = execute_platform_jobs(
            self.drive, self.video, self.slot, ["yt1", "fb"], {"yt1": yt, "fb": fb}, self.video["appProperties"]
        )
        self.assertIn("yt1", results)
        self.assertIn("fb", errors)
        self.assertEqual(self.video["appProperties"]["failure_slot_fb"], self.slot)
        self.assertEqual(self.video["appProperties"]["done_yt1_slot"], self.slot)
        self.assertEqual(self.video["appProperties"]["result_yt1"], "https://youtube.com/shorts/abc")

        yt.reset_mock()
        fb.reset_mock()
        execute_platform_jobs(
            self.drive, self.video, self.slot, ["yt1", "fb"], {"yt1": yt, "fb": fb}, self.video["appProperties"]
        )
        yt.assert_not_called()
        fb.assert_called_once()

    def test_primary_and_backup_invocations_do_not_repeat_successful_publish(self):
        publish = Mock(return_value="ig-media-123")
        for _workflow in ("primary", "backup"):
            execute_platform_jobs(
                self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
            )
        publish.assert_called_once()

    def test_ambiguous_timeout_is_not_retried(self):
        publish = Mock(side_effect=requests.Timeout("response lost"))
        _, errors = execute_platform_jobs(
            self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
        )
        self.assertIn("ig", errors)
        self.assertEqual(self.video["appProperties"]["intent_ig_slot"], self.slot)
        self.assertEqual(self.video["appProperties"][FAILED_SLOT], self.slot)

        _, errors = execute_platform_jobs(
            self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
        )
        self.assertIn("belirsiz", errors["ig"])
        publish.assert_called_once()

    def test_explicit_429_retries_with_retry_after_without_repeating_intent(self):
        rejected = RuntimeError("rate limited")
        rejected.http_status = 429
        rejected.response_headers = {"retry-after": "2"}
        publish = Mock(side_effect=[rejected, "media-123"])
        with patch("scheduled_multi_publisher.time.sleep") as sleep:
            results, errors = execute_platform_jobs(
                self.drive, self.video, self.slot, ["ig"], {"ig": publish},
                self.video["appProperties"], account="tarladaki",
            )
        self.assertEqual(errors, {})
        self.assertEqual(results["ig"], "media-123")
        self.assertEqual(publish.call_count, 2)
        sleep.assert_called_once_with(2.0)

    def test_transient_error_uses_exponential_backoff(self):
        first = RuntimeError("temporary provider rejection")
        first.retriable = True
        second = RuntimeError("temporary provider rejection")
        second.is_transient = True
        publish = Mock(side_effect=[first, second, "media-123"])
        with patch("scheduled_multi_publisher.time.sleep") as sleep:
            results, errors = execute_platform_jobs(
                self.drive, self.video, self.slot, ["ig"], {"ig": publish},
                self.video["appProperties"], account="tarladaki",
            )
        self.assertEqual(errors, {})
        self.assertEqual(results["ig"], "media-123")
        self.assertEqual(publish.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_non_rate_limit_ambiguous_5xx_is_not_retried(self):
        failure = RuntimeError("server response lost")
        failure.http_status = 503
        publish = Mock(side_effect=failure)
        _, errors = execute_platform_jobs(
            self.drive, self.video, self.slot, ["ig"], {"ig": publish},
            self.video["appProperties"], account="tarladaki",
        )
        self.assertIn("ig", errors)
        publish.assert_called_once()
        self.assertEqual(self.video["appProperties"]["intent_ig_slot"], self.slot)

    def test_lost_drive_ack_after_publish_keeps_intent_and_prevents_duplicate(self):
        execute = self.drive.files.return_value.update.return_value.execute
        execute.side_effect = [{}, OSError("Drive response lost"), {}]
        publish = Mock(return_value="ig-media-123")
        with self.assertRaisesRegex(OSError, "Drive response lost"):
            execute_platform_jobs(
                self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
            )
        self.assertEqual(self.video["appProperties"]["intent_ig_slot"], self.slot)

        execute_platform_jobs(
            self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
        )
        publish.assert_called_once()

    def test_intent_write_failure_prevents_external_publish(self):
        self.drive.files.return_value.update.return_value.execute.side_effect = OSError("Drive down")
        publish = Mock()
        with self.assertRaisesRegex(OSError, "Drive down"):
            execute_platform_jobs(
                self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
            )
        publish.assert_not_called()

    def test_notification_outage_does_not_fail_publisher(self):
        with patch.dict("os.environ", {"NTFY_TOPIC": "topic"}), patch(
            "scheduled_multi_publisher.requests.post", side_effect=requests.ConnectionError("offline")
        ):
            notify("gonle", "slot", "video", {}, {"ig": "API rejected"})

    def test_success_notification_contains_platform_result(self):
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.dict("os.environ", {"NTFY_TOPIC": "topic"}), patch(
            "scheduled_multi_publisher.requests.post", return_value=response
        ) as post:
            self.assertTrue(notify("gonle", "slot", "video", {"ig": "media-123"}, {}))
        payload = post.call_args.kwargs["json"]
        self.assertIn("Instagram: Yayınlandı (media-123)", payload["message"])
        self.assertIn("YAYIN BAŞARILI", payload["title"])

    def test_success_digest_groups_multiple_slots_by_account(self):
        response = Mock()
        response.raise_for_status.return_value = None
        items = [
            {"stem": "episode-a", "slot": "2026-10-19-12-toonzone", "results": {"ig": "m1"}},
            {"stem": "episode-b", "slot": "2026-10-19-12-toonzone", "results": {"fb": "m2"}},
        ]
        with patch.dict("os.environ", {"NTFY_TOPIC": "topic"}), patch(
            "scheduled_multi_publisher.requests.post", return_value=response
        ) as post:
            self.assertTrue(notify("toonzone", "", "", {}, {}, grouped_items=items))
        message = post.call_args.kwargs["json"]["message"]
        self.assertIn("episode-a", message)
        self.assertIn("episode-b", message)
        self.assertIn("Instagram: Yayınlandı (m1)", message)
        self.assertIn("Facebook: Yayınlandı (m2)", message)

    def test_http_server_errors_are_ambiguous_but_explicit_rejections_are_not(self):
        server_error = Exception()
        server_error.resp = type("Response", (), {"status": 503})()
        rejected = Exception()
        rejected.resp = type("Response", (), {"status": 400})()
        self.assertTrue(is_ambiguous_publish_error(server_error))
        self.assertFalse(is_ambiguous_publish_error(rejected))
        rate_limited = Exception()
        rate_limited.resp = type("Response", (), {"status": 429})()
        self.assertFalse(is_ambiguous_publish_error(rate_limited))
        self.assertTrue(is_ambiguous_publish_error(RuntimeError("Meta API HTTP 503")))

    def test_meta_prep_server_error_gets_bounded_retry_but_publish_error_does_not(self):
        prep_error = Exception("temporary")
        prep_error.http_status = 503
        prep_error.stage = "Instagram container oluşturma"
        publish_error = Exception("response lost")
        publish_error.http_status = 503
        publish_error.stage = "Instagram media_publish"
        self.assertFalse(is_ambiguous_publish_error(prep_error))
        self.assertTrue(is_ambiguous_publish_error(publish_error))

    def test_explicit_http_400_is_quarantined_after_one_attempt(self):
        rejected = RuntimeError("Meta API hatası (HTTP=400)")
        self.assertTrue(is_permanent_publish_error(rejected))
        publish = Mock(side_effect=rejected)
        _, errors = execute_platform_jobs(
            self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
        )
        self.assertIn("ig", errors)
        self.assertEqual(self.video["appProperties"][FAILED_SLOT], self.slot)
        self.assertEqual(self.video["appProperties"]["failure_ig_count"], "3")
        execute_platform_jobs(
            self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
        )
        publish.assert_called_once()

    def test_manual_ig_recovery_allows_exactly_one_exhausted_counter_retry(self):
        self.video["appProperties"]["failure_ig_count"] = "3"
        publish = Mock(return_value="media-123")
        with patch.dict(os.environ, {
            "CONTROLLED_IG_RECOVERY": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "tarladaki_ig",
            "FORCE_STEM": "652",
        }, clear=False):
            results, errors = execute_platform_jobs(
                self.drive, self.video, self.slot, ["ig"], {"ig": publish}, self.video["appProperties"]
            )
        self.assertEqual(errors, {})
        self.assertEqual(results["ig"], "media-123")
        self.assertEqual(self.video["appProperties"]["failure_ig_count"], "0")
        self.assertEqual(self.video["appProperties"]["controlled_ig_recovery_used"], "1")


if __name__ == "__main__":
    unittest.main()
