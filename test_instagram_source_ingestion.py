"""Offline-only tests for Instagram source intake, pool selection and publisher gates."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import instagram_source_collection as collector
import instagram_source_config as config_module
import instagram_source_store as store
import public_link_runtime as publisher
import stats_reporter
import instagram_source_report as source_report


class Response:
    def __init__(self, payload=None, *, status=200, headers=None, chunks=None, url=""):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks or []
        self.url = url
        self.closed = False

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=65536):
        return iter(self._chunks)

    def close(self):
        self.closed = True


def base_config():
    return config_module.load_config()


def source_row(post_id, *, username="source_a", pool="new", route="tarladaki",
               source_day="2026-11-25", score=0, status="available"):
    return {
        "route": route,
        "source_username": username,
        "source_post_id": post_id,
        "source_published_at": f"{source_day}T10:00:00+00:00",
        "pool": pool,
        "status": status,
        "sha256": f"{int(post_id):064x}",
        "drive_video_id": "drive-" + post_id,
        "width": 720,
        "height": 1280,
        "duration": 24,
        "view_count": score,
    }


class ConfigTests(unittest.TestCase):
    def test_six_active_target_accounts_exclude_film_second_and_are_disabled_by_default(self):
        config = base_config()
        self.assertEqual(len(config["accounts"]), 6)
        self.assertNotIn("film_second", config["accounts"])
        self.assertEqual(set(config["accounts"]), config_module.ROUTES)
        for account in config["accounts"].values():
            self.assertFalse(account["enabled"])
            self.assertFalse(account["auto_collection"])
            self.assertFalse(account["auto_publish"])
            self.assertEqual(account["daily_new"], 3)
            self.assertEqual(account["daily_archive"], 3)
            self.assertEqual(account["source_accounts"], [])

    def test_active_source_requires_rights_evidence_and_isolated_folder(self):
        config = base_config()
        account = config["accounts"]["tarladaki"]
        account.update(enabled=True, auto_collection=True, collection_folder_id="folder_source_001")
        account["source_accounts"] = [{
            "username": "creator_name", "enabled": True,
            "rights_approved": False, "official_api_download_allowed": True,
        }]
        invalid = config_module.validate_config(config)
        self.assertIn("auto_collection_has_no_authorized_sources",
                      invalid["accounts"]["tarladaki"]["config_errors"])
        self.assertNotIn("tarladaki", config_module.collection_targets(invalid))
        account["source_accounts"][0].update(rights_approved=True, rights_evidence="license-2026-11")
        account["collection_folder_id"] = account["target_folder_id"]
        invalid = config_module.validate_config(config)
        self.assertIn("collection_folder_not_isolated",
                      invalid["accounts"]["tarladaki"]["config_errors"])
        self.assertNotIn("tarladaki", config_module.collection_targets(invalid))

    def test_serial_routes_cannot_auto_publish_without_ordered_slots(self):
        config = base_config()
        account = config["accounts"]["toonzone"]
        account.update(enabled=True, auto_collection=True, auto_publish=True,
                       collection_folder_id="folder_source_001")
        account["source_accounts"] = [{"username": "creator", "enabled": True,
            "rights_approved": True, "official_api_download_allowed": True,
            "rights_evidence": "license"}]
        with self.assertRaisesRegex(ValueError, "serial routes"):
            config_module.validate_config(config)

    def test_source_config_error_in_one_route_does_not_block_another_route(self):
        config = base_config()
        tarladaki = config["accounts"]["tarladaki"]
        tarladaki.update(enabled=True, auto_collection=True, collection_folder_id="source_folder_001")
        tarladaki["source_accounts"] = [{"username": "bad username", "enabled": True,
            "rights_approved": True, "official_api_download_allowed": True,
            "rights_evidence": "license"}]
        gonle = config["accounts"]["gonle"]
        gonle.update(enabled=True, auto_collection=True, collection_folder_id="source_folder_002")
        gonle["source_accounts"] = [{"username": "valid_creator", "enabled": True,
            "rights_approved": True, "official_api_download_allowed": True,
            "rights_evidence": "license", "content_categories": ["comedy"]}]
        normalized = config_module.validate_config(config)
        self.assertNotIn("tarladaki", config_module.collection_targets(normalized))
        self.assertIn("gonle", config_module.collection_targets(normalized))
        self.assertEqual(normalized["accounts"]["gonle"]["source_accounts"][0]["content_categories"], ["comedy"])

    def test_collection_folder_cannot_be_reused_across_routes(self):
        config = base_config()
        shared_folder = "source_folder_shared_001"
        for route in ("tarladaki", "penguen"):
            account = config["accounts"][route]
            account.update(enabled=True, auto_collection=True,
                           collection_folder_id=shared_folder)
            account["source_accounts"] = [{"username": f"creator_{route}",
                "enabled": True, "rights_approved": True,
                "official_api_download_allowed": True, "rights_evidence": "license"}]
        normalized = config_module.validate_config(config)
        for route in ("tarladaki", "penguen"):
            self.assertIn("collection_folder_reused_by_routes",
                          normalized["accounts"][route]["config_errors"])
            self.assertNotIn(route, config_module.collection_targets(normalized))

    def test_collection_requires_explicit_official_api_download_permission(self):
        config = base_config()
        account = config["accounts"]["tarladaki"]
        account.update(enabled=True, auto_collection=True,
                       collection_folder_id="source_folder_001")
        account["source_accounts"] = [{"username": "creator_name", "enabled": True,
            "rights_approved": True, "rights_evidence": "license",
            "official_api_download_allowed": False}]
        normalized = config_module.validate_config(config)
        self.assertIn("auto_collection_has_no_authorized_sources",
                      normalized["accounts"]["tarladaki"]["config_errors"])
        self.assertNotIn("tarladaki", config_module.collection_targets(normalized))

    def test_due_schedule_filters_only_activated_routes_in_turkey_time(self):
        config = base_config()
        account = config["accounts"]["tarladaki"]
        account.update(enabled=True, auto_collection=True, auto_publish=True,
                       collection_folder_id="folder_source_001")
        account["source_accounts"] = [{"username": "creator", "enabled": True,
            "rights_approved": True, "official_api_download_allowed": True,
            "rights_evidence": "license"}]
        local = datetime(2026, 11, 25, 9, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
        self.assertEqual(config_module.due_publish_routes(config, local), ["tarladaki"])
        self.assertEqual(config_module.due_publish_routes(config, local.replace(minute=15)), [])

    def test_source_slots_match_existing_publish_schedule_and_film_second_is_excluded(self):
        config = base_config()
        self.assertEqual(config["accounts"]["tarladaki"]["publish_times"],
                         ["09:00", "12:00", "15:00", "18:00", "21:00"])
        self.assertEqual(config["accounts"]["gonle"]["publish_times"],
                         ["09:15", "12:15", "15:15", "18:15", "21:15"])
        self.assertEqual(config["accounts"]["penguen"]["publish_times"],
                         ["09:30", "12:30", "15:30", "18:30", "21:30"])
        self.assertEqual(config["accounts"]["daily_laugh"]["publish_timezone"], "America/New_York")
        publisher_workflow = Path(".github/workflows/public_link_schedule.yml").read_text()
        collection_workflow = Path(".github/workflows/instagram_source_collection.yml").read_text()
        self.assertNotIn("cron: '*/30 * * * *'", publisher_workflow)
        self.assertIn("cron: '*/30 * * * *'", collection_workflow)
        self.assertNotIn('["film","film_second"]', publisher_workflow)
        self.assertNotIn('"film_second"', publisher_workflow.split("account_scope:", 1)[1].split("    # An invalid", 1)[0])


class GraphDiscoveryTests(unittest.TestCase):
    def test_all_pages_from_five_sources_are_returned_without_a_three_item_limit(self):
        for source_index in range(5):
            calls = []

            def get(url, **kwargs):
                calls.append((url, kwargs))
                if len(calls) == 1:
                    return Response({"business_discovery": {"media": {
                        "data": [{"id": f"{source_index}-a"}, {"id": f"{source_index}-b"}],
                        "paging": {"next": "https://graph.facebook.com/v27.0/123?after=2"},
                    }}})
                return Response({"business_discovery": {"media": {
                    "data": [{"id": f"{source_index}-c"}, {"id": f"{source_index}-d"}],
                    "paging": {},
                }}})

            rows = collector.discover_source_media(
                f"creator_{source_index}", actor_id="12345", access_token="test-token",
                graph_version="v27.0", get=get,
            )
            self.assertEqual(len(rows), 4)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][1]["params"]["access_token"], "test-token")

    def test_paging_cycle_and_untrusted_next_link_fail_closed(self):
        cyc = "https://graph.facebook.com/v27.0/123?after=2"
        payload = {"business_discovery": {"media": {"data": [], "paging": {"next": cyc}}}}
        with self.assertRaisesRegex(collector.SourceAPIError, "paging_cycle"):
            collector.discover_source_media("creator", actor_id="12345", access_token="x",
                graph_version="v27.0", get=lambda *_a, **_k: Response(payload))
        bad = {"business_discovery": {"media": {"data": [], "paging": {
            "next": "https://attacker.invalid/v27.0/123?after=2"}}}}
        with self.assertRaisesRegex(collector.SourceAPIError, "untrusted_page_link"):
            collector.discover_source_media("creator", actor_id="12345", access_token="x",
                graph_version="v27.0", get=lambda *_a, **_k: Response(bad))

    def test_source_account_id_and_username_are_verified(self):
        self.assertEqual(collector.verify_source_identity("creator", {
            "username": "Creator", "instagram_user_id": "123456789"}, "123456789"), "123456789")
        with self.assertRaisesRegex(collector.SourceAPIError, "source_identity_mismatch"):
            collector.verify_source_identity("creator", {
                "username": "someone_else", "instagram_user_id": "123456789"})

    def test_istanbul_day_filter_keeps_reels_and_feed_videos_only(self):
        today = date(2026, 11, 25)
        rows = [
            {"id": "reel", "media_type": "VIDEO", "media_product_type": "REELS",
             "timestamp": "2026-11-24T21:05:00Z", "media_url": "https://x"},
            {"id": "feed-video", "media_type": "VIDEO", "media_product_type": "FEED",
             "timestamp": "2026-11-25T20:59:59Z", "media_url": "https://x"},
            {"id": "photo", "media_type": "IMAGE", "media_product_type": "FEED",
             "timestamp": "2026-11-25T10:00:00Z", "media_url": "https://x"},
            {"id": "yesterday", "media_type": "VIDEO", "media_product_type": "REELS",
             "timestamp": "2026-11-24T20:59:59Z", "media_url": "https://x"},
            {"id": "url-withheld", "media_type": "VIDEO", "media_product_type": "REELS",
             "timestamp": "2026-11-25T00:15:00Z"},
        ]
        result = collector.todays_videos(rows, today=today)
        self.assertEqual({row["id"] for row in result}, {"reel", "feed-video", "url-withheld"})
        self.assertIsNone(result[0].get("view_count"))


class SafeDownloadTests(unittest.TestCase):
    def test_near_full_drive_stops_before_video_download(self):
        with self.assertRaisesRegex(collector.SourceCollectionError, "drive_storage_quota_low"):
            collector._process_source_post(None, None, "tarladaki", {}, "source", {},
                today=None, get=None,
                download_video=lambda *_a, **_k: self.fail("quota gate must run before download"),
                drive_storage={"status": "low"})

    def test_official_cdn_video_download_hashes_and_probes_before_atomic_rename(self):
        payload = b"0000ftypisom" + b"video-data"
        response = Response(status=200, headers={"Content-Type": "video/mp4",
            "Content-Length": str(len(payload))}, chunks=[payload])
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "video.mp4"
            path, digest, size, metadata = collector.download_official_video(
                "https://video.cdninstagram.com/test.mp4", destination,
                get=lambda *_a, **_k: response,
                probe_video=lambda file: {"streams": [{"codec_type": "video"}],
                                          "format": {"duration": "20"}},
            )
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(size, len(payload))
            self.assertEqual(digest, __import__("hashlib").sha256(payload).hexdigest())
            self.assertFalse(Path(str(destination) + ".partial").exists())
            self.assertEqual(metadata["format"]["duration"], "20")

    def test_untrusted_redirect_and_bad_mp4_are_rejected_and_partial_files_removed(self):
        redirect = Response(status=302, headers={"Location": "https://attacker.invalid/file.mp4"})
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "x.mp4"
            with self.assertRaisesRegex(ValueError, "untrusted_media_redirect"):
                collector.download_official_video("https://video.cdninstagram.com/x",
                    destination, get=lambda *_a, **_k: redirect)
            self.assertFalse(Path(str(destination) + ".partial").exists())
            invalid = Response(status=200, headers={"Content-Type": "video/mp4"}, chunks=[b"not an mp4"])
            with self.assertRaisesRegex(ValueError, "not_mp4"):
                collector.download_official_video("https://video.cdninstagram.com/x",
                    destination, get=lambda *_a, **_k: invalid)
            self.assertFalse(destination.exists())

    def test_size_cap_rejects_before_probe(self):
        payload = b"0000ftypisom"
        response = Response(status=200, headers={"Content-Type": "video/mp4"}, chunks=[payload])
        with tempfile.TemporaryDirectory() as temp, patch.object(collector, "MAX_VIDEO_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "size_limit"):
                collector.download_official_video("https://video.cdninstagram.com/x",
                    Path(temp) / "x.mp4", get=lambda *_a, **_k: response,
                    probe_video=lambda _p: self.fail("probe must not run on oversize media"))


class PoolSelectionTests(unittest.TestCase):
    def test_3_new_and_3_archive_are_selected_with_source_diversity_and_leftovers(self):
        rows = []
        for pool in ("new", "archive"):
            for source_index in range(5):
                for clip in range(2):
                    row = source_row(str(len(rows) + 1), username=f"source_{source_index}", pool=pool)
                    row["view_count"] = source_index * 10 + clip
                    rows.append(row)
        plan = store.choose_daily_assets(rows)
        self.assertEqual(len(plan["selected"]["new"]), 3)
        self.assertEqual(len(plan["selected"]["archive"]), 3)
        sources = [row["source_username"] for pool in ("new", "archive") for row in plan["selected"][pool]]
        self.assertLessEqual(max(sources.count(source) for source in set(sources)), 2)
        self.assertEqual(plan["remaining"], {"new": 7, "archive": 7})

    def test_short_new_pool_does_not_get_silently_filled_from_archive(self):
        rows = [source_row("1", username="one", pool="new"),
                source_row("2", username="two", pool="new")]
        rows.extend(source_row(str(i), username=f"archive_{i}", pool="archive") for i in range(3, 10))
        plan = store.choose_daily_assets(rows, daily_new=3, daily_archive=3, max_per_source=2)
        self.assertEqual(len(plan["selected"]["new"]), 2)
        self.assertEqual(len(plan["selected"]["archive"]), 3)
        self.assertEqual(plan["deficit"], {"new": 1, "archive": 0})

    def test_unselected_yesterday_assets_roll_into_archive_in_istanbul_day(self):
        self.assertEqual(store.rollover_pool("new", "2026-11-24", "2026-11-25"), "archive")
        self.assertEqual(store.rollover_pool("new", "2026-11-25", "2026-11-25"), "new")
        self.assertEqual(store.rollover_pool("archive", "2026-11-20", "2026-11-25"), "archive")

    def test_global_hash_dedup_preserves_route_and_platform_scopes_in_schema(self):
        self.assertIn("PRIMARY KEY (route, sha256)", store.DDL)
        self.assertIn("PRIMARY KEY (source_username, source_post_id, route)", store.DDL)
        self.assertIn("PRIMARY KEY (route, platform, sha256)", store.DDL)
        self.assertIn("UNIQUE (route, local_day, sha256)", store.DDL)

    def test_publication_schedule_keeps_existing_target_default_off(self):
        default = base_config()
        self.assertEqual(config_module.due_publish_routes(default,
            datetime(2026, 11, 25, 8, 0, tzinfo=ZoneInfo("Europe/Istanbul"))), [])
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(publisher._instagram_source_publish_account("tarladaki"))

    def test_shared_humor_folder_files_are_assigned_by_explicit_route_prefix(self):
        self.assertTrue(publisher.owned_humor_source("tarladaki", "any-id", "igsrc_tarladaki_user_post_hash.mp4"))
        self.assertFalse(publisher.owned_humor_source("penguen", "any-id", "igsrc_tarladaki_user_post_hash.mp4"))
        self.assertTrue(publisher.owned_humor_source("penguen", "any-id", "igsrc_penguen_user_post_hash.mp4"))

    def test_film_second_is_not_an_active_publisher_scope_and_new_neon_registry_is_six_route_only(self):
        with patch.dict(os.environ, {"PUBLISH_ACCOUNT_SCOPE": "film_second"}):
            with self.assertRaisesRegex(RuntimeError, "Unrecognized"):
                publisher.account_scope()
        self.assertNotIn("film_second", store.ROUTES)
        self.assertIn("film_second", store.LEGACY_ROUTES)
        self.assertIn("instagram_source_rights", store.DDL)
        self.assertIn("instagram_source_scan_runs", store.DDL)
        self.assertIn("instagram_user_id", store.DDL)
        self.assertIn("content_categories", store.DDL)
        self.assertIn("drive_usage_bytes", store.DDL)

    def test_daily_source_report_is_in_the_existing_turkish_ntfy_report(self):
        routes = {
            route: {"name": name, "enabled": True, "configured_sources": 1,
                "scanned_sources": 1, "found": 2, "downloaded": 2, "duplicates": 1,
                "archive_count": 4, "new_pool_count": 2, "ready_count": 3,
                "missing_caption_or_cover": 0,
                "api_status": "ok", "drive_status": "ok", "storage_status": "ok",
                "drive_usage_bytes": 1000, "drive_limit_bytes": 10000,
                "neon_status": "ok", "errors": [], "sources": []}
            for route, name in source_report.DISPLAY_NAMES.items()
        }
        summary = {"day": "2026-11-26", "status": "active", "routes": routes,
                   "manual_actions": [], "neon_status": "ok"}
        with patch.dict(os.environ, {"NTFY_TOPIC": "mock-topic", "NTFY_TOPIC_URL": "",
                                    "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=True), \
             patch.object(stats_reporter, "send_ntfy") as ntfy:
            stats_reporter.notify(type("Report", (), {"comparison": {
                "accounts": [], "report_errors": [], "instagram_source_report": summary}})())
        ntfy.assert_called_once()
        self.assertIn("📥 Günlük Instagram kaynak özeti", ntfy.call_args.args[0])
        self.assertIn("mükerrer 1", ntfy.call_args.args[1])
        self.assertIn("Drive alanı erişilebilir", ntfy.call_args.args[1])

    def test_disabled_source_report_does_not_emit_a_new_ntfy_message(self):
        with patch.dict(os.environ, {"NTFY_TOPIC": "mock-topic", "NTFY_TOPIC_URL": "",
                                    "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=True), \
             patch.object(stats_reporter, "send_ntfy") as ntfy:
            stats_reporter.notify(type("Report", (), {"comparison": {
                "accounts": [], "report_errors": [],
                "instagram_source_report": {"status": "disabled", "routes": {}}}})())
        ntfy.assert_not_called()

    def test_published_source_receipt_cannot_be_downgraded_to_new_intent(self):
        class Cursor:
            rowcount = 1
            def __init__(self): self.statements = []
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def execute(self, sql, _params): self.statements.append(sql)
            def fetchone(self): return ("published", "confirmed-post")
        class Connection:
            def __init__(self): self.cur = Cursor(); self.commits = 0
            def cursor(self): return self.cur
            def commit(self): self.commits += 1
        conn = Connection()
        store.record_platform_result(conn, route="tarladaki", platform="facebook",
            sha256="a" * 64, status="intent", post_id="confirmed-post")
        self.assertEqual(len(conn.cur.statements), 1)
        self.assertEqual(conn.commits, 1)

    def test_publisher_checks_exact_source_hash_before_any_upload(self):
        payload = b"expected-video-content"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.mp4"
            path.write_bytes(payload)
            self.assertEqual(publisher._source_sha256(path), __import__("hashlib").sha256(payload).hexdigest())


class DriveIdempotencyTests(unittest.TestCase):
    def test_existing_exact_drive_file_is_reused_without_create_or_overwrite(self):
        import base64, hashlib
        properties = {"source_sha256": "a" * 64, "target_route": "tarladaki", "source_post_id": "123"}
        current = {"id": "drive-existing", "name": "igsrc.mp4", "size": "1",
                   "md5Checksum": base64.b64encode(hashlib.md5(b"x", usedforsecurity=False).digest()).decode(),
                   "parents": ["folder1"], "appProperties": properties}

        class Request:
            def __init__(self, result): self.result = result
            def execute(self): return self.result

        class Files:
            def list(self, **_kwargs): return Request({"files": [current]})
            def create(self, **_kwargs): raise AssertionError("existing Drive file must not be overwritten")

        drive = type("Drive", (), {"files": lambda self: Files()})()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x"
            path.write_bytes(b"x")
            self.assertEqual(collector.upload_drive_file(drive, folder_id="folder1", name="igsrc.mp4",
                path=path, mime_type="video/mp4", app_properties=properties)["id"], "drive-existing")

    def test_hash_collision_with_different_source_identity_is_held(self):
        current = {"id": "drive-existing", "name": "igsrc.mp4", "parents": ["folder1"],
                   "appProperties": {"source_sha256": "a" * 64, "target_route": "penguen",
                                     "source_post_id": "123"}}

        class Request:
            def execute(self): return {"files": [current]}
        class Files:
            def list(self, **_kwargs): return Request()
            def create(self, **_kwargs): raise AssertionError("collision must not be overwritten")
        drive = type("Drive", (), {"files": lambda self: Files()})()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x"
            path.write_bytes(b"x")
            with self.assertRaisesRegex(RuntimeError, "identity_mismatch"):
                collector.upload_drive_file(drive, folder_id="folder1", name="igsrc.mp4",
                    path=path, mime_type="video/mp4", app_properties={
                        "source_sha256": "a" * 64, "target_route": "tarladaki", "source_post_id": "123"})

    def test_existing_file_with_matching_properties_but_different_checksum_is_held(self):
        properties = {"source_sha256": "a" * 64, "target_route": "tarladaki", "source_post_id": "123"}
        current = {"id": "drive-existing", "name": "igsrc.mp4", "size": "1",
                   "md5Checksum": "wrong", "parents": ["folder1"], "appProperties": properties}
        class Request:
            def execute(self): return {"files": [current]}
        class Files:
            def list(self, **_kwargs): return Request()
            def create(self, **_kwargs): raise AssertionError("mismatched Drive bytes must not be overwritten")
        drive = type("Drive", (), {"files": lambda self: Files()})()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x"
            path.write_bytes(b"x")
            with self.assertRaisesRegex(RuntimeError, "identity_mismatch"):
                collector.upload_drive_file(drive, folder_id="folder1", name="igsrc.mp4",
                    path=path, mime_type="video/mp4", app_properties=properties)

    def test_drive_quota_is_read_and_high_usage_is_reported(self):
        class Request:
            def execute(self):
                return {"storageQuota": {"usage": "960", "limit": "1000"}}
        drive = type("Drive", (), {"about": lambda self: type("About", (), {
            "get": lambda _self, **_kwargs: Request()})()})()
        self.assertEqual(collector.drive_storage_status(drive), {
            "status": "low", "usage_bytes": 960, "limit_bytes": 1000,
            "used_percent": 96.0})


if __name__ == "__main__":
    unittest.main()
