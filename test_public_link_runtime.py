"""No network or production tokens: exercise actual link-runtime safety logic."""
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo


def load_runtime():
    cloud = types.ModuleType("cloud_omnichannel_publisher")
    cloud.GRAPH_API_VERSION = "v24.0"
    cloud.MetaAPIError = type("MetaAPIError", (RuntimeError,), {})
    cloud._sanitize_meta_text = str
    for name in ("create_instagram_cover_video", "upload_facebook_reel", "upload_instagram_reel"):
        setattr(cloud, name, Mock(side_effect=AssertionError("No live upload in tests")))
    scheduled = types.ModuleType("scheduled_multi_publisher")
    for name in ("TARLADAKI_HOURS", "PENGUEN_HOURS", "GONLE_HOURS"):
        setattr(scheduled, name, (9, 12, 15, 18, 21))
    scheduled.FILM_HOURS = (10, 12, 14, 16, 18)
    scheduled.daily_laugh_hours_for_date = lambda day: (8, 10, 12, 14, 16, 18, 20, 22)
    scheduled.platform_content_from_txt = Mock(return_value=(None, None, "FB from TXT", "IG from TXT", True))
    auth = types.ModuleType("meta_auth_loader")
    auth.load_meta_auth = Mock(return_value={"pages": []})
    compat = types.ModuleType("instagram_media_compat")
    compat.prepare_instagram_upload = Mock()
    compat.probe = Mock(return_value={"streams": [{"codec_type": "video"}], "format": {"duration": "12.0"}})
    ordered = types.ModuleType("ordered_channels")
    ordered.parse_order = Mock(return_value=(1, 2, 2, "title"))
    def fake_toonzone_metadata(stem):
        match = re.fullmatch(r"S(\d+)E(\d+)_(.+)_Part_?(\d+)", stem)
        if not match or int(match[4]) not in (1, 2, 3, 4):
            raise ValueError("invalid ToonZone filename")
        return {"season": int(match[1]), "episode": int(match[2]),
                "part": int(match[4]),
                "title": match[3].replace("_", " ") + f" — Part {match[4]}",
                "description": "Unused fallback"}
    ordered.toonzone_metadata = Mock(side_effect=fake_toonzone_metadata)
    ordered.TOONZONE_ETSY_LINK = "https://www.etsy.com/shop/MiroviaStudio"
    safety = types.ModuleType("publication_safety")
    safety.route_paused = Mock(return_value=False)
    stubs = {"requests": types.ModuleType("requests"), "gdown": types.ModuleType("gdown"),
             "cloud_omnichannel_publisher": cloud, "scheduled_multi_publisher": scheduled,
             "meta_auth_loader": auth, "instagram_media_compat": compat,
             "ordered_channels": ordered, "publication_safety": safety}
    spec = importlib.util.spec_from_file_location("tested_public_link_runtime", Path(__file__).with_name("public_link_runtime.py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    # Offline tests deliberately create mock HTTP 400 and HELD errors; avoid
    # printing those fake incidents in the real publishing workflow logs.
    # unittest assertions/errors still go to stderr and remain visible.
    module.print = Mock()
    return module


runtime = load_runtime()
# Mocked safety regressions intentionally generate synthetic errors. Never
# write those to production-run error artifacts or send false phone alarms.
runtime.record_error = Mock()


class LinkRuntimeSafety(unittest.TestCase):
    def test_unresolved_publish_hold_alerts_once_each_istanbul_day(self):
        tr = ZoneInfo("Europe/Istanbul")
        utc = ZoneInfo("UTC")
        now = datetime(2026, 10, 26, 9, 7, tzinfo=tr)
        self.assertTrue(runtime.previous_intent_alert_due({}, now))
        self.assertTrue(runtime.previous_intent_alert_due(
            {"hold_alerted_at": "2026-10-25T22:30:00+03:00"}, now))
        self.assertFalse(runtime.previous_intent_alert_due(
            {"hold_alerted_at": "2026-10-26T00:10:00+03:00"}, now))
        self.assertFalse(runtime.previous_intent_alert_due(
            {"hold_alerted_at": "2026-10-25T22:10:00+00:00"}, now))
        self.assertTrue(runtime.previous_intent_alert_due(
            {"hold_alerted_at": "invalid-timestamp"}, now))
        self.assertTrue(runtime.previous_intent_alert_due(
            {"hold_alerted_at": "2026-10-25T22:30:00"}, now))
        self.assertFalse(runtime.previous_intent_alert_due(
            {"hold_alerted_at": "2026-10-27T09:10:00+03:00"}, now))

    def test_exact_video_instagram_mention_does_not_modify_facebook_caption(self):
        from instagram_tagging import _parse_rules
        rules = _parse_rules({"schema": 1, "rules": [
            {"route": "film", "stem": "ronaldo_goal_01",
             "usernames": ["cristiano"], "hashtags": ["CR7"]}
        ]})
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text("Ronaldo goal analysis", encoding="utf-8")
            with patch.object(runtime, "download", return_value=source), \
                    patch.dict(runtime.enhance_instagram_caption.__globals__, {"load_rules": lambda: rules}):
                captions, origin = runtime.copies(
                    "film", {"name": "ronaldo_goal_01.mp4"},
                    {"ronaldo_goal_01.txt": {"id": "test"}}, Path(tmp),
                )
            self.assertEqual(origin, "matching-txt")
            self.assertEqual(captions["facebook"], "FB from TXT")
            self.assertIn("@cristiano", captions["instagram"])
            self.assertIn("#CR7", captions["instagram"])
            self.assertNotIn("@cristiano", captions["facebook"])

    def test_drive_download_retries_transient_url_error_and_removes_partial(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "video.mp4"
            tries = []

            def fake_drive(**kwargs):
                tries.append(1)
                if len(tries) == 1:
                    dest.write_bytes(b"incomplete")
                    raise RuntimeError("FileURLRetrievalError https://secret.private/link")
                self.assertFalse(dest.exists())
                dest.write_bytes(b"good mp4 data")
                return str(dest)

            with patch.object(runtime.gdown, "download", create=True, side_effect=fake_drive), \
                    patch.object(runtime.time, "sleep") as sleeping:
                self.assertEqual(runtime.download("id", dest), dest)
            self.assertEqual(dest.read_bytes(), b"good mp4 data")
            self.assertEqual(len(tries), 2)
            sleeping.assert_called_once_with(1)

    def test_drive_download_does_not_accept_partial_or_empty_files(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "video.mp4"
            def always_partial(**kwargs):
                dest.write_bytes(b"partial")
                raise ValueError("sensitive Drive URL not for logs")
            with patch.object(runtime.gdown, "download", create=True, side_effect=always_partial), \
                    patch.object(runtime.time, "sleep") as sleeping:
                with self.assertRaisesRegex(RuntimeError, "3 denemede") as caught:
                    runtime.download("id", dest)
            self.assertFalse(dest.exists())
            self.assertNotIn("sensitive Drive URL", str(caught.exception))
            self.assertEqual(sleeping.call_count, 2)

    def test_drive_download_retries_missing_output_even_if_provider_returns_path(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "video.mp4"
            with patch.object(runtime.gdown, "download", create=True, return_value=str(dest)) as fetch, \
                    patch.object(runtime.time, "sleep"):
                with self.assertRaises(RuntimeError):
                    runtime.download("id", dest)
            self.assertEqual(fetch.call_count, 3)

    def test_caption_dedupe_ignores_store_suffix_and_spacing(self):
        self.assertEqual(runtime.caption_key("A  video\nEtsy: https://www.etsy.com/shop/x"), runtime.caption_key("A video"))
        self.assertNotEqual(runtime.caption_key("Part 2"), runtime.caption_key("Part 3"))

    def test_matching_toonzone_txt_is_read_instead_of_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / "caption.txt"
            text.write_text("Actual Drive text", encoding="utf-8")
            with patch.object(runtime, "download", return_value=text):
                result, origin = runtime.copies("toonzone", {"name": "episode.mp4"}, {"episode.txt": {"id": "txt"}}, root)
            self.assertEqual(origin, "matching-txt")
            self.assertEqual(result["instagram"], "IG from TXT")

    def test_missing_txt_blocks_ordinary_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for route in ("gonle", "film", "tarladaki", "penguen", "film_second"):
                with self.subTest(route=route), self.assertRaisesRegex(RuntimeError, "TXT bulunamadı"):
                    runtime.copies(route, {"name": "1.mp4"}, {}, Path(tmp))

    def test_daily_laugh_generates_exact_txt_only_when_missing(self):
        catalog = {"101.mp4": {"id": "a"}, "102.mp4": {"id": "b"},
                   "102.txt": {"id": "existing"}, "1.mp4": {"id": "c"},
                   "notes.txt": {"id": "ignored"}, "invalid.mp4": {"id": "bad"}}
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            generated, invalid = runtime.generate_daily_laugh_txts(catalog, dest)
            self.assertEqual((generated, invalid), (2, 1))
            self.assertEqual(sorted(path.name for path in dest.glob("*.txt")), ["1.txt", "101.txt"])
            self.assertIn("#DailyLaughLab", (dest / "101.txt").read_text(encoding="utf-8"))
            self.assertNotIn("102.txt", [x.name for x in dest.iterdir()])

    def test_daily_laugh_missing_txt_is_materialized_before_caption_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(runtime, "ROOT", root):
                result, origin = runtime.copies("daily_laugh", {"name": "101.mp4"}, {}, root)
            self.assertEqual(origin, "generated-daily-laugh-txt")
            self.assertTrue((root / "daily_laugh_txt" / "101.txt").is_file())
            self.assertIn("Video 101", result["facebook"])
            self.assertIn("Video 101", result["instagram"])

    def test_daily_laugh_existing_txt_is_not_replaced_by_generated_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "caption.txt"
            source.write_text("Original approved description", encoding="utf-8")
            with patch.object(runtime, "ROOT", root), patch.object(runtime, "download", return_value=source):
                _captions, origin = runtime.copies("daily_laugh", {"name": "101.mp4"}, {"101.txt": {"id": "source"}}, root)
            self.assertEqual(origin, "matching-txt")
            self.assertFalse((root / "daily_laugh_txt" / "101.txt").exists())

    def test_daily_laugh_rejects_unsafe_filename_for_auto_caption(self):
        with self.assertRaises(ValueError):
            runtime.daily_laugh_txt_text("../secrets")

    def test_unreadable_txt_blocks_ordinary_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runtime, "download", side_effect=Exception("Drive limit")):
                with self.assertRaisesRegex(RuntimeError, "TXT indirilemedi"):
                    runtime.copies("gonle", {"name": "2.mp4"}, {"2.txt": {"id": "txt"}}, Path(tmp))

    def test_empty_txt_blocks_ordinary_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "empty.txt"
            dest.write_text("   ", encoding="utf-8")
            with patch.object(runtime, "download", return_value=dest):
                with self.assertRaisesRegex(RuntimeError, "TXT boş"):
                    runtime.copies("film", {"name": "2.mp4"}, {"2.txt": {"id": "txt"}}, Path(tmp))

    def test_exact_txt_coverage_catches_missing_or_mismatched_names(self):
        catalog = {
            "1.mp4": {"id": "video-1"}, "1.txt": {"id": "text-1"},
            "2.mp4": {"id": "video-2"}, "2.TXT": {"id": "wrong-case"},
            "3.mp4": {"id": "video-3"}, "other.txt": {"id": "extra"},
        }
        actual = runtime.exact_txt_coverage(catalog)
        self.assertEqual(actual["mp4"], 3)
        self.assertEqual(actual["matched"], 1)
        self.assertEqual(actual["missing"], 2)
        self.assertEqual(actual["missing_examples"], ["2", "3"])

    def test_all_exact_txt_pairs_are_ready(self):
        pairs = {"a.mp4": {}, "a.txt": {}, "b.mp4": {}, "b.txt": {}}
        self.assertEqual(runtime.exact_txt_coverage(pairs)["missing"], 0)

    def test_toonzone_txts_generated_for_each_video_and_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = {
                "S01E01_The_Power_Part1.mp4": {"id": "a"},
                "S01E01_The_Power_Part2.mp4": {"id": "b"},
                "readme.txt": {"id": "text"},
                "bad-file.mp4": {"id": "bad"},
            }
            with patch.object(runtime, "ROOT", root):
                generated, invalid = runtime.generate_toonzone_txts(catalog, root / "toonzone_txt")
                self.assertEqual((generated, invalid), (2, 1))
                self.assertEqual(len(list((root / "toonzone_txt").glob("*.txt"))), 2)
                first = (root / "toonzone_txt" / "S01E01_The_Power_Part1.txt").read_text()
                captions, origin = runtime.copies("toonzone", {"name": "S01E01_The_Power_Part2.mp4"}, {}, root)
                self.assertEqual(origin, "generated-toonzone-txt")
                self.assertIn("Part 2/4", captions["instagram"])
                self.assertIn("#S01E01 #Part2", captions["instagram"])
                self.assertIn("sihirli bir klavyeye", captions["facebook"])
                self.assertIn("sihirli bir klavyeye", first)
                self.assertNotEqual(first, captions["instagram"])

    def test_toonzone_generated_txt_is_deterministic_and_no_txt_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runtime, "ROOT", Path(tmp)):
                captions, origin = runtime.copies("toonzone", {"name": "S01E01_The_Power_Part3.mp4"}, {}, Path(tmp))
            self.assertEqual(origin, "generated-toonzone-txt")
            self.assertIn("Part 3/4", captions["facebook"])
            self.assertIn("#RegularShow", captions["facebook"])
            self.assertEqual(captions["facebook"], captions["instagram"])

    def test_unsourced_future_episode_is_not_given_fake_plot(self):
        with self.assertRaisesRegex(ValueError, "ozeti onayli degil"):
            runtime.toonzone_txt_text("S03E01_Stick_Hockey_Part1")

    def test_schedule_remains_five_film_slots_after_catchup_date(self):
        with patch.dict(os.environ, {"COMPLETE_DAY_DATE": "2026-10-23"}):
            self.assertEqual(runtime.target_count("film", datetime(2026, 10, 24, 9, tzinfo=runtime.TR)), 0)
            self.assertEqual(runtime.target_count("film", datetime(2026, 10, 24, 18, tzinfo=runtime.TR)), 5)
            self.assertEqual(runtime.target_count("toonzone", datetime(2026, 10, 24, 7, tzinfo=runtime.TR)), 0)
            self.assertEqual(runtime.target_count("toonzone", datetime(2026, 10, 24, 12, 20, tzinfo=runtime.TR)), 3)

    def test_zero_due_target_is_reported_as_not_due_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = {"schema": 1, "entries": {}, "episode_days": {}}
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                                         "GITHUB_RUN_ID": "123"}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "FOLDERS", {"toonzone": "folder", "covers": "covers"}), \
                    patch.object(runtime, "ROUTES", {"toonzone": ("toonzone", "ToonZone")}), \
                    patch.object(runtime, "restore", return_value=state), \
                    patch.object(runtime, "load_meta_auth",
                                 return_value={"pages": [{"page_name": "ToonZone"}]}), \
                    patch.object(runtime, "inventory", return_value={}), \
                    patch.object(runtime, "graph_rows", return_value=[]), \
                    patch.object(runtime, "target_count", return_value=0), \
                    patch.object(runtime, "copies") as captions:
                runtime.plan()
            report = (root / "report.md").read_text(encoding="utf-8")
            self.assertIn("NOT DUE", report)
            self.assertNotIn("Daily target already complete.", report)
            captions.assert_not_called()
            self.assertEqual(json.loads((root / "plan.json").read_text()), [])

    def test_toonzone_cover_audit_requires_exact_part_png(self):
        videos = {
            "s03_e01_part1.mp4": {"id": "a"},
            "s03_e01_part2.mp4": {"id": "b"},
            "notes.txt": {"id": "c"},
        }
        covers = {"s03_e01_part1.png": {"id": "cover-1"},
                  "s03_e02_part2.png": {"id": "other-episode"}}
        self.assertEqual(runtime.toonzone_cover_coverage(videos, covers), (1, 1))

    def test_toonzone_cover_audit_ignores_non_mp4_sources(self):
        self.assertEqual(runtime.toonzone_cover_coverage(
            {"s03_e01_part1.txt": {}, "image.jpg": {}}, {}), (0, 0))

    def test_instagram_history_counts_videos_not_photos(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": [
            {"id": "photo", "media_type": "IMAGE", "caption": "photo", "timestamp": "2026-10-24T10:00:00Z"},
            {"id": "carousel", "media_type": "CAROUSEL_ALBUM", "caption": "album", "timestamp": "2026-10-24T10:00:00Z"},
            {"id": "123", "media_type": "VIDEO", "caption": "reel", "timestamp": "2026-10-24T10:00:00Z"},
        ]}
        with patch.object(runtime.requests, "get", create=True, return_value=response) as fetch:
            result = runtime.graph_rows({"instagram_id": "123", "page_token": "test-token"}, "instagram")
        self.assertEqual([row["id"] for row in result], ["123"])
        self.assertIn("media_type", fetch.call_args.kwargs["params"]["fields"])

    def test_graph_history_throttle_recovers_before_publication_planning(self):
        limited, ok = Mock(status_code=400), Mock(status_code=200)
        limited.json.return_value = {"error": {"code": 4}}
        ok.json.return_value = {"data": [{"id": "123", "media_type": "VIDEO", "timestamp": "2026-10-24T10:00:00Z"}]}
        with patch.object(runtime.requests, "get", create=True, side_effect=[limited, ok]) as get, \
                patch.dict(runtime.read_with_retry.__kwdefaults__, {"sleep": Mock()}):
            rows = runtime.graph_rows({"instagram_id": "123", "page_token": "test-token"}, "instagram")
        self.assertEqual([row["id"] for row in rows], ["123"])
        self.assertEqual(get.call_count, 2)

    def test_malformed_graph_history_never_counts_as_empty_success_or_leaks_body(self):
        for payload in (None, [], "secret-body", {"error": "secret-error"},
                        {"data": [], "error": {"code": "secret-code"}}):
            with self.subTest(payload=payload):
                response = Mock(status_code=200)
                response.json.return_value = payload
                with patch.object(runtime.requests, "get", create=True, return_value=response):
                    with self.assertRaises(RuntimeError) as raised:
                        runtime.graph_rows({"instagram_id": "123", "page_token": "test-token"}, "instagram")
                self.assertNotIn("secret", str(raised.exception))

    def test_instagram_history_without_media_type_fails_closed(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": [
            {"id": "unclassified", "caption": "cannot determine video"}
        ]}
        with patch.object(runtime.requests, "get", create=True, return_value=response):
            with self.assertRaisesRegex(RuntimeError, "medya türü"):
                runtime.graph_rows({"instagram_id": "123", "page_token": "test-token"}, "instagram")

    def test_daily_laugh_confirmed_post_uses_new_york_calendar_day(self):
        # 00:30 UTC on Oct 24 is Oct 24 in Istanbul, Oct 23 in New York.
        row = {"created_time": "2026-10-24T00:30:00Z"}
        self.assertEqual(runtime.timestamp(row).date().isoformat(), "2026-10-24")
        self.assertEqual(runtime.publication_day("daily_laugh", row), "2026-10-23")
        self.assertEqual(runtime.publication_day("film", row), "2026-10-24")

    def test_daily_laugh_publication_day_after_new_york_midnight(self):
        row = {"timestamp": "2026-10-24T06:00:00Z"}
        self.assertEqual(runtime.publication_day("daily_laugh", row), "2026-10-24")

    def test_catchup_preserves_daily_laugh_eight_target(self):
        with patch.dict(os.environ, {"COMPLETE_DAY_DATE": "2026-10-23"}):
            self.assertEqual(runtime.target_count("daily_laugh", datetime(2026, 10, 23, 9, tzinfo=runtime.TR)), 8)
            self.assertEqual(runtime.target_count("film_second", datetime(2026, 10, 23, 9, tzinfo=runtime.TR)), 6)

    def test_daily_reused_txt_has_distinct_video_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = Path(tmp) / "caption.txt"
            text.write_text("Shared short caption", encoding="utf-8")
            with patch.object(runtime, "download", return_value=text):
                first, _ = runtime.copies("daily_laugh", {"name": "100.mp4"}, {"100.txt": {"id": "txt"}}, Path(tmp))
                second, _ = runtime.copies("daily_laugh", {"name": "101.mp4"}, {"101.txt": {"id": "txt"}}, Path(tmp))
            self.assertNotEqual(runtime.caption_key(first["facebook"]), runtime.caption_key(second["facebook"]))

    def test_newer_intent_beats_older_result_on_crash(self):
        old = {"id": 10, "name": "link-state-result", "workflow_run": {"id": 100}}
        new = {"id": 11, "name": "link-state-intent", "workflow_run": {"id": 101}}
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("state.json", json.dumps({"schema": 1, "entries": {"pending": {"status": "intent"}}}))
        def fake_get(path):
            if "name=link-state-result" in path:
                return Mock(json=lambda: {"artifacts": [old]})
            if "name=link-state-intent" in path:
                return Mock(json=lambda: {"artifacts": [new]})
            self.assertEqual(path, "actions/artifacts/11/zip")
            return Mock(content=memory.getvalue())
        with patch.object(runtime, "github_get", side_effect=fake_get):
            self.assertEqual(runtime.restore()["entries"]["pending"]["status"], "intent")

    def test_missing_or_malformed_state_is_not_reset(self):
        with patch.object(runtime, "github_get", side_effect=RuntimeError("denied")):
            with self.assertRaises(RuntimeError):
                runtime.restore()

    def test_malformed_successful_artifact_response_does_not_reset_state(self):
        with patch.object(runtime, "github_get", return_value=Mock(json=lambda: {})):
            with self.assertRaisesRegex(RuntimeError, "durum listesi"):
                runtime.restore()

    def test_daily_duplicate_names_are_excluded_without_losing_other_files(self):
        rows = [types.SimpleNamespace(id="a", path="1.mp4"),
                types.SimpleNamespace(id="b", path="1.mp4"),
                types.SimpleNamespace(id="c", path="2.mp4")]
        with patch.object(runtime.gdown, "download_folder", create=True, return_value=rows):
            result = runtime.inventory(runtime.FOLDERS["daily_laugh"])
        self.assertEqual(set(result), {"2.mp4"})

    def test_film_and_toonzone_facebook_advance_without_reposting_held_ig(self):
        for route, stem1, stem2 in (
            ("film", "Yoksul_1986_Part_16", "Yoksul_1986_Part_17"),
            ("toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3",
             "S01E03_Caffeinated_Concert_Tickets_Part4"),
        ):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                file1, file2 = stem1 + ".mp4", stem2 + ".mp4"
                items = {
                    file1: {"name": file1, "id": "old"},
                    file2: {"name": file2, "id": "next"},
                }
                entry = {
                    "route": route, "platform": "instagram",
                    "file": file1, "status": "uncertain",
                    "caption_hash": runtime.caption_key("IG caption"),
                    "prepublish_retry_count": 1,
                    "run_id": "40224351466",
                    "failure": {
                        "stage": "Instagram ikili video aktarımı",
                        "http_status": 400, "graph_code": 100,
                    },
                    "hold_alerted_at": datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
                }
                state = {
                    "schema": 1, "episode_days": {}, "entries": {
                        f"{route}:facebook:old": {
                            "route": route, "platform": "facebook",
                            "file": file1, "status": "done", "post_id": "fb-original",
                            "day": "2026-10-25",
                        },
                        f"{route}:instagram:old": entry,
                    },
                }
                page_name = "Film Mağarası" if route == "film" else "ToonZone"
                folders = {route: "videos", "covers": "covers"}
                def catalog(folder):
                    return items if folder == "videos" else {}
                with patch.dict(os.environ, {
                        "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                        "GITHUB_RUN_ID": "77777",
                        "TOONZONE_AUTO_COVER_ENABLED": "true",
                    }), patch.object(runtime, "ROOT", root), patch.object(
                        runtime, "STATE", root / "state.json"
                    ), patch.object(runtime, "PLAN", root / "plan.json"), patch.object(
                        runtime, "FOLDERS", folders
                    ), patch.object(runtime, "ROUTES", {route: (route, page_name)}), patch.object(
                        runtime, "restore", return_value=state
                    ), patch.object(runtime, "apply_verified_migration"), patch.object(
                        runtime, "load_meta_auth", return_value={
                            "pages": [{"page_name": page_name, "instagram_id": "ig123"}]
                        }
                    ), patch.object(runtime, "inventory", side_effect=catalog), patch.object(
                        runtime, "graph_rows", return_value=[]
                    ), patch.object(runtime, "target_count", return_value=1), patch.object(
                        runtime, "seed_done", return_value=False
                    ), patch.object(runtime, "copies", return_value=(
                        {"facebook": "FB caption", "instagram": "IG caption"}, "matching-txt"
                    )), patch.object(runtime, "generate_toonzone_txts", return_value=(0, 0)), patch.object(
                        runtime, "toonzone_cover_coverage", return_value=(0, 2)):
                    runtime.plan()
                planned = json.loads((root / "plan.json").read_text())
                self.assertEqual(len(planned), 2)
                self.assertEqual([(p["name"], p["platforms"]) for p in planned],
                                 [(file1, ["instagram"]), (file2, ["facebook"])])
                saved = json.loads((root / "state.json").read_text())
                self.assertEqual(saved["entries"][f"{route}:instagram:old"]["status"], "intent")
                self.assertEqual(saved["entries"][f"{route}:instagram:old"]["prepublish_retry_count"], 2)
                self.assertEqual(saved["entries"][f"{route}:facebook:old"]["post_id"], "fb-original")
                self.assertNotIn(f"{route}:instagram:next", saved["entries"])

    def test_old_ig_publish_stage_uncertainty_still_blocks_everything(self):
        old = {
            "status": "uncertain", "prepublish_retry_count": 1,
            "failure": {"stage": "Instagram media_publish",
                        "http_status": 400, "graph_code": 100},
        }
        self.assertFalse(runtime.facebook_can_continue_past_ig_rejection(
            "film", "instagram", old))
        old["failure"]["stage"] = "Instagram ikili video aktarımı"
        self.assertTrue(runtime.facebook_can_continue_past_ig_rejection(
            "film", "instagram", old))
        old["prepublish_retry_count"] = 2
        self.assertTrue(runtime.facebook_can_continue_past_ig_rejection(
            "toonzone", "instagram", old))
        self.assertFalse(runtime.facebook_can_continue_past_ig_rejection(
            "gonle", "instagram", old))
        self.assertFalse(runtime.facebook_can_continue_past_ig_rejection(
            "film", "facebook", old))

    def test_uncertain_toonzone_part_blocks_later_parts(self):
        runtime.record_error.reset_mock()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {"a.mp4": {"name": "a.mp4", "id": "a"}, "b.mp4": {"name": "b.mp4", "id": "b"}}
            initial = {"schema": 1, "episode_days": {}, "entries": {
                "toonzone:facebook:a": {"route": "toonzone", "platform": "facebook", "status": "uncertain", "caption_hash": "old"}}}
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(root / "summary.md"), "GITHUB_RUN_ID": "123"}), patch.object(runtime, "ROOT", root), patch.object(runtime, "STATE", root / "state.json"), patch.object(runtime, "PLAN", root / "plan.json"), patch.object(runtime, "FOLDERS", {"toonzone": "folder", "covers": "coverfolder"}), patch.object(runtime, "ROUTES", {"toonzone": ("toonzone", "ToonZone")}), patch.object(runtime, "restore", return_value=initial), patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "ToonZone"}]}), patch.object(runtime, "inventory", side_effect=lambda folder: source if folder == "folder" else {}), patch.object(runtime, "graph_rows", return_value=[]), patch.object(runtime, "seed_done", return_value=False), patch.object(runtime, "copies", return_value=({"facebook": "caption", "instagram": "caption"}, "matching-txt")) as caption_mock:
                # Exercise uncertain-intent protection independently of CI clock time.
                with patch.object(runtime, "target_count", return_value=4):
                    runtime.plan()
                self.assertEqual(json.loads((root / "plan.json").read_text()), [])
                self.assertEqual(caption_mock.call_count, 1)
                self.assertEqual(runtime.record_error.call_count, 1)
                self.assertEqual(runtime.record_error.call_args.args[:2],
                                 ("previous_intent_hold", "unreconciled_previous_intent"))
                state = json.loads((root / "state.json").read_text())
                self.assertTrue(state["entries"]["toonzone:facebook:a"].get("hold_alerted_at"))
                # The same unresolved old intent must remain blocked, but
                # half-hourly runs must not send duplicate phone alerts.
                runtime.record_error.reset_mock()
                runtime.plan()
                runtime.record_error.assert_not_called()
                self.assertEqual(json.loads((root / "plan.json").read_text()), [])

    def test_old_film_binary_http400_is_safely_reconciled_before_one_alternate_retry(self):
        # Film Part 16 historically failed during rupload before media_publish.
        # It must not remain permanently blocked as an "unknown publish".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "Yoksul_1986_Part_16.mp4"
            caption = "FILM-IG-original-caption"
            old = {"schema": 1, "episode_days": {}, "entries": {
                "film:instagram:vid": {
                    "route": "film", "platform": "instagram", "file": name,
                    "status": "uncertain", "caption_hash": runtime.caption_key(caption),
                    "prepublish_retry_count": 0, "run_id": "40107188749",
                    "failure": {"stage": "Instagram ikili video aktarımı",
                                "http_status": 400, "graph_code": None,
                                "reason": "invalid_media_or_graph_request"}
                }
            }}
            inventory = {name: {"name": name, "id": "vid"}}
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                                         "GITHUB_RUN_ID": "500"}), \
                 patch.object(runtime, "ROOT", root), \
                 patch.object(runtime, "STATE", root / "state.json"), \
                 patch.object(runtime, "PLAN", root / "plan.json"), \
                 patch.object(runtime, "FOLDERS", {"film": "folder"}), \
                 patch.object(runtime, "ROUTES", {"film": ("film", "Film Mağarası")}), \
                 patch.object(runtime, "restore", return_value=old), \
                 patch.object(runtime, "apply_verified_migration"), \
                 patch.object(runtime, "load_meta_auth", return_value={"pages": [
                     {"page_name": "Film Mağarası", "instagram_id": "123"}]}), \
                 patch.object(runtime, "inventory", return_value=inventory), \
                 patch.object(runtime, "graph_rows", return_value=[]), \
                 patch.object(runtime, "target_count", return_value=1), \
                 patch.object(runtime, "seed_done", return_value=False), \
                 patch.object(runtime, "copies", return_value=(
                     {"facebook": "FB-caption", "instagram": caption}, "matching-txt")):
                runtime.plan()
            plans = json.loads((root / "plan.json").read_text())
            ledger = json.loads((root / "state.json").read_text())
            self.assertEqual(len(plans), 1)
            self.assertIn("instagram", plans[0]["platforms"])
            self.assertEqual(ledger["entries"]["film:instagram:vid"]["status"], "intent")
            self.assertEqual(ledger["entries"]["film:instagram:vid"]["prepublish_retry_count"], 1)
            self.assertIn("RECOVERY: Yoksul_1986_Part_16.mp4",
                          (root / "report.md").read_text())

    def test_old_media_publish_timeout_remains_held_and_notified_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "Yoksul_1986_Part_16.mp4"
            caption = "FILM-IG-original-caption"
            old = {"schema": 1, "episode_days": {}, "entries": {
                "film:instagram:vid": {
                    "route": "film", "platform": "instagram", "file": name,
                    "status": "uncertain", "caption_hash": runtime.caption_key(caption),
                    "prepublish_retry_count": 0,
                    "failure": {"stage": "Instagram media_publish", "http_status": 400,
                                "graph_code": 100}
                }
            }}
            inventory = {name: {"name": name, "id": "vid"}}
            runtime.record_error.reset_mock()
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                                         "GITHUB_RUN_ID": "500"}), \
                 patch.object(runtime, "ROOT", root), \
                 patch.object(runtime, "STATE", root / "state.json"), \
                 patch.object(runtime, "PLAN", root / "plan.json"), \
                 patch.object(runtime, "FOLDERS", {"film": "folder"}), \
                 patch.object(runtime, "ROUTES", {"film": ("film", "Film Mağarası")}), \
                 patch.object(runtime, "restore", return_value=old), \
                 patch.object(runtime, "apply_verified_migration"), \
                 patch.object(runtime, "load_meta_auth", return_value={"pages": [
                     {"page_name": "Film Mağarası", "instagram_id": "123"}]}), \
                 patch.object(runtime, "inventory", return_value=inventory), \
                 patch.object(runtime, "graph_rows", return_value=[]), \
                 patch.object(runtime, "target_count", return_value=1), \
                 patch.object(runtime, "seed_done", return_value=False), \
                 patch.object(runtime, "copies", return_value=(
                     {"facebook": "FB-caption", "instagram": caption}, "matching-txt")):
                runtime.plan()
                runtime.plan()
            self.assertEqual(json.loads((root / "plan.json").read_text()), [])
            self.assertEqual(old["entries"]["film:instagram:vid"]["status"], "uncertain")
            self.assertEqual(runtime.record_error.call_count, 1)
            self.assertEqual(runtime.record_error.call_args.args[:2],
                             ("previous_intent_hold", "unreconciled_previous_intent"))

    def test_invalid_mp4_codec_metadata_blocks_upload_before_meta(self):
        with patch.object(runtime, "probe", return_value={"streams": [], "format": {"duration": "10"}}):
            with self.assertRaisesRegex(RuntimeError, "ön doğrulaması"):
                runtime.verify_source_video(Path("fake.mp4"))

    def test_ffprobe_timeout_blocks_meta_without_leaking_video_path(self):
        with patch.object(runtime, "probe", side_effect=TimeoutError("private-file-location")):
            with self.assertRaises(RuntimeError) as raised:
                runtime.verify_source_video(Path("private.mp4"))
            self.assertNotIn("private-file-location", str(raised.exception))

    def test_local_ig_prepare_failure_keeps_fb_publishable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path, plan_path = root / "state.json", root / "plan.json"
            item = {"page": "Daily Laugh Lab", "route": "daily_laugh", "id": "vid",
                    "name": "101.mp4", "platforms": ["facebook", "instagram"],
                    "captions": {"facebook": "fb text", "instagram": "ig text"}}
            runtime.save(state_path, {"entries": {
                "daily_laugh:facebook:vid": {"status": "intent"},
                "daily_laugh:instagram:vid": {"status": "intent"}}})
            runtime.save(plan_path, [item])
            def download(_id, path):
                path.write_bytes(b"1234ftypOK")
                return path
            with patch.object(runtime, "STATE", state_path), patch.object(runtime, "PLAN", plan_path), \
                    patch.object(runtime, "download", side_effect=download), \
                    patch.object(runtime, "load_meta_auth", return_value={"pages": [
                        {"page_name": "Daily Laugh Lab", "page_token": "test"}]}), \
                    patch.object(runtime, "prepare_instagram_upload", side_effect=RuntimeError("ffmpeg failed")), \
                    patch.object(runtime, "upload_facebook_reel", return_value="fb123") as facebook, \
                    patch.object(runtime, "upload_instagram_reel") as instagram:
                with self.assertRaises(SystemExit):
                    runtime.publish()
            entries = json.loads(state_path.read_text())["entries"]
            self.assertEqual(entries["daily_laugh:facebook:vid"]["status"], "done")
            self.assertEqual(entries["daily_laugh:facebook:vid"]["post_id"], "fb123")
            self.assertEqual(entries["daily_laugh:instagram:vid"]["status"], "ready")
            self.assertEqual(entries["daily_laugh:instagram:vid"]["failure"]["reason"], "media_preparation_failed")
            facebook.assert_called_once()
            instagram.assert_not_called()

    def test_known_ig_binary_400_queues_only_one_strict_profile_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path, plan_path = root / "state.json", root / "plan.json"
            runtime.save(state_path, {"entries": {
                "penguen:instagram:vid": {"status": "intent", "prepublish_retry_count": 0}
            }})
            runtime.save(plan_path, [{"page": "Beyinsiz Penguen", "route": "penguen",
                "id": "vid", "name": "22.mp4", "platforms": ["instagram"],
                "captions": {"instagram": "IG text"}}])
            def download(_id, path):
                path.write_bytes(b"1234ftypOK")
                return path
            err = runtime.MetaAPIError("HTTP 400")
            err.http_status, err.code, err.subcode = 400, 100, 2207009
            err.stage = "Instagram ikili video aktarımı"
            with patch.object(runtime, "STATE", state_path), patch.object(runtime, "PLAN", plan_path), \
                    patch.object(runtime, "download", side_effect=download), \
                    patch.object(runtime, "load_meta_auth", return_value={"pages": [
                        {"page_name": "Beyinsiz Penguen", "page_token": "test"}]}), \
                    patch.object(runtime, "prepare_instagram_upload", side_effect=lambda path, *a, **kw: path) as prepare, \
                    patch.object(runtime, "upload_instagram_reel", side_effect=err) as ig:
                with self.assertRaises(SystemExit):
                    runtime.publish()
                first = json.loads(state_path.read_text())["entries"]["penguen:instagram:vid"]
                self.assertEqual(first["status"], "ready")
                self.assertEqual(first["prepublish_retry_count"], 1)
                self.assertFalse(prepare.call_args.kwargs["film_compact"])
                self.assertTrue(prepare.call_args.kwargs["short_reel"])
                self.assertFalse(prepare.call_args.kwargs["prefer_remux"])
                self.assertTrue(prepare.call_args.kwargs["force_transcode"])
                ig.assert_called_once()
                state = json.loads(state_path.read_text())
                state["entries"]["penguen:instagram:vid"]["status"] = "intent"
                runtime.save(state_path, state)
                ig.reset_mock(side_effect=True)
                ig.return_value = "ig-post-confirmed"
                runtime.publish()
                second = json.loads(state_path.read_text())["entries"]["penguen:instagram:vid"]
                self.assertEqual(second["status"], "done")
                self.assertEqual(second["post_id"], "ig-post-confirmed")
                self.assertTrue(prepare.call_args.kwargs["film_compact"])
                self.assertFalse(prepare.call_args.kwargs["short_reel"])
                self.assertEqual(ig.call_count, 1)

    def test_second_known_instagram_400_schedules_final_safe_profile(self):
        for route in ("penguen", "gonle"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                state_path, plan_path = root / "state.json", root / "plan.json"
                key = f"{route}:instagram:vid"
                runtime.save(state_path, {"entries": {
                    key: {"status": "intent", "prepublish_retry_count": 1}
                }})
                runtime.save(plan_path, [{
                    "page": "Beyinsiz Penguen", "route": route,
                    "id": "vid", "name": "clip.mp4",
                    "platforms": ["instagram"], "captions": {"instagram": "unique"}
                }])
                def download(_id, target):
                    target.write_bytes(b"0000ftypmedia")
                    return target
                error = runtime.MetaAPIError("HTTP 400")
                error.stage = "Instagram ikili video aktarımı"
                error.http_status, error.code, error.subcode = 400, 100, 2207009
                with patch.object(runtime, "STATE", state_path), \
                     patch.object(runtime, "PLAN", plan_path), \
                     patch.object(runtime, "download", side_effect=download), \
                     patch.object(runtime, "load_meta_auth", return_value={"pages": [
                         {"page_name": "Beyinsiz Penguen", "page_token": "test"}
                     ]}), \
                     patch.object(runtime, "prepare_instagram_upload",
                                  side_effect=lambda video, *a, **kw: video) as prepare, \
                     patch.object(runtime, "upload_instagram_reel", side_effect=error) as upload:
                    with self.assertRaises(SystemExit):
                        runtime.publish()
                    flags = prepare.call_args.kwargs
                    self.assertTrue(flags["force_transcode"])
                    self.assertFalse(flags["recovery_v3"])
                    if route == "gonle":
                        self.assertFalse(flags["film_compact"])
                    else:
                        self.assertTrue(flags["film_compact"])
                    upload.assert_called_once()
                record = json.loads(state_path.read_text())["entries"][key]
                self.assertEqual(record["status"], "ready")
                self.assertEqual(record["prepublish_retry_count"], 2)
                self.assertEqual(record["failure"]["recovery_next_profile"], 2)

    def test_final_profile_is_normalized_and_success_is_persisted(self):
        for route in ("penguen", "gonle"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                state_path, plan_path = root / "state.json", root / "plan.json"
                key = f"{route}:instagram:vid"
                runtime.save(state_path, {"entries": {
                    key: {"status": "intent", "prepublish_retry_count": 2}
                }})
                runtime.save(plan_path, [{
                    "page": "Beyinsiz Penguen", "route": route,
                    "id": "vid", "name": "clip.mp4",
                    "platforms": ["instagram"], "captions": {"instagram": "unique"}
                }])
                def download(_id, target):
                    target.write_bytes(b"0000ftypmedia")
                    return target
                with patch.object(runtime, "STATE", state_path), \
                     patch.object(runtime, "PLAN", plan_path), \
                     patch.object(runtime, "download", side_effect=download), \
                     patch.object(runtime, "load_meta_auth", return_value={"pages": [
                         {"page_name": "Beyinsiz Penguen", "page_token": "test"}
                     ]}), \
                     patch.object(runtime, "prepare_instagram_upload",
                                  side_effect=lambda video, *a, **kw: video) as prepare, \
                     patch.object(runtime, "upload_instagram_reel",
                                  return_value="ig-live-post-verified") as upload:
                    runtime.publish()
                    self.assertTrue(prepare.call_args.kwargs["recovery_v3"])
                    self.assertTrue(prepare.call_args.kwargs["force_transcode"])
                    self.assertFalse(prepare.call_args.kwargs["film_compact"])
                    upload.assert_called_once()
                record = json.loads(state_path.read_text())["entries"][key]
                self.assertEqual(record["status"], "done")
                self.assertEqual(record["post_id"], "ig-live-post-verified")

    def test_third_failed_binary_400_holds_instead_of_infinite_posts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path, plan_path = root / "state.json", root / "plan.json"
            key = "penguen:instagram:vid"
            runtime.save(state_path, {"entries": {
                key: {"status": "intent", "prepublish_retry_count": 2}
            }})
            runtime.save(plan_path, [{
                "page": "Beyinsiz Penguen", "route": "penguen", "id": "vid",
                "name": "clip.mp4", "platforms": ["instagram"],
                "captions": {"instagram": "unique"}
            }])
            def download(_id, target):
                target.write_bytes(b"0000ftypmedia")
                return target
            error = runtime.MetaAPIError("HTTP 400")
            error.stage = "Instagram ikili video aktarımı"
            error.http_status, error.code, error.subcode = 400, 100, 2207009
            with patch.object(runtime, "STATE", state_path), \
                 patch.object(runtime, "PLAN", plan_path), \
                 patch.object(runtime, "download", side_effect=download), \
                 patch.object(runtime, "load_meta_auth", return_value={"pages": [
                     {"page_name": "Beyinsiz Penguen", "page_token": "test"}
                 ]}), \
                 patch.object(runtime, "prepare_instagram_upload",
                              side_effect=lambda video, *a, **kw: video), \
                 patch.object(runtime, "upload_instagram_reel", side_effect=error) as upload:
                with self.assertRaises(SystemExit):
                    runtime.publish()
                upload.assert_called_once()
            record = json.loads(state_path.read_text())["entries"][key]
            self.assertEqual(record["status"], "uncertain")
            self.assertEqual(record["prepublish_retry_count"], 2)
            self.assertFalse(record["failure"]["safe_to_repost"])

    def test_film_recovery_upload_prepares_distinct_noncompact_bitstream(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path, plan_path = root / "state.json", root / "plan.json"
            runtime.save(state_path, {"entries": {
                "film:instagram:vid": {
                    "status": "intent", "prepublish_retry_count": 1
                }
            }})
            runtime.save(plan_path, [{
                "page": "Film Mağarası", "route": "film", "id": "vid",
                "name": "Yoksul_1986_Part_16.mp4",
                "platforms": ["instagram"], "captions": {"instagram": "Film part 16"}
            }])
            def download(_id, path):
                path.write_bytes(b"1234ftypOK")
                return path
            with patch.object(runtime, "STATE", state_path), \
                 patch.object(runtime, "PLAN", plan_path), \
                 patch.object(runtime, "download", side_effect=download), \
                 patch.object(runtime, "load_meta_auth", return_value={"pages": [
                     {"page_name": "Film Mağarası", "page_token": "test"}]}), \
                 patch.object(runtime, "prepare_instagram_upload",
                              side_effect=lambda path, *a, **kw: path) as prepare, \
                 patch.object(runtime, "upload_instagram_reel", return_value="ig-confirmed") as ig:
                runtime.publish()
            self.assertTrue(prepare.call_args.kwargs["force_transcode"])
            self.assertFalse(prepare.call_args.kwargs["film_compact"])
            self.assertFalse(prepare.call_args.kwargs["toonzone_compact"])
            self.assertEqual(json.loads(state_path.read_text())["entries"][
                "film:instagram:vid"]["status"], "done")
            ig.assert_called_once()

    def test_meta_http_400_is_held_uncertain_with_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path, plan_path = root / "state.json", root / "plan.json"
            runtime.save(state_path, {"entries": {"toonzone:instagram:vid": {"status": "intent"}}})
            runtime.save(plan_path, [{"page": "ToonZone", "route": "toonzone",
                "id": "vid", "name": "S01E01_The_Power_Part2.mp4",
                "platforms": ["instagram"], "captions": {"instagram": "IG text"}}])
            def download(_id, path):
                path.write_bytes(b"1234ftypOK")
                return path
            err = runtime.MetaAPIError("HTTP 400 invalid media")
            err.http_status, err.code, err.subcode = 400, 100, 2207009
            err.stage = "Instagram binary upload"
            with patch.object(runtime, "STATE", state_path), patch.object(runtime, "PLAN", plan_path), \
                    patch.object(runtime, "download", side_effect=download), \
                    patch.object(runtime, "load_meta_auth", return_value={"pages": [
                        {"page_name": "ToonZone", "page_token": "test"}]}), \
                    patch.object(runtime, "prepare_instagram_upload", side_effect=lambda path, *a, **kw: path), \
                    patch.object(runtime, "upload_instagram_reel", side_effect=err) as ig:
                with self.assertRaises(SystemExit):
                    runtime.publish()
            entry = json.loads(state_path.read_text())["entries"]["toonzone:instagram:vid"]
            self.assertEqual(entry["status"], "uncertain")
            self.assertEqual(entry["failure"]["reason"], "invalid_media_or_graph_request")
            self.assertEqual(entry["failure"]["graph_subcode"], 2207009)
            self.assertFalse(entry["failure"]["safe_to_repost"])
            ig.assert_called_once()

    def test_unique_remote_caption_index_rejects_duplicate_and_blank_captions(self):
        rows = [
            {"id": "1", "description": "Same video"},
            {"id": "2", "description": "Same video"},
            {"id": "3", "caption": "Unique video"},
            {"id": "4", "description": ""},
        ]
        index, ambiguous = runtime.index_history_captions(rows)
        self.assertIn(runtime.caption_key("Same video"), ambiguous)
        self.assertNotIn(runtime.caption_key("Same video"), index)
        self.assertEqual(index[runtime.caption_key("Unique video")]["id"], "3")
        self.assertNotIn(runtime.caption_key(""), index)

    def test_reconciled_platform_date_uses_ny_and_istanbul_separately(self):
        post = {"id": "123", "timestamp": "2026-10-24T00:30:00+03:00"}
        self.assertEqual(runtime.history_publication_match("daily_laugh", post),
                         ("123", "2026-10-23"))
        self.assertEqual(runtime.history_publication_match("gonle", post),
                         ("123", "2026-10-24"))

    def test_missing_invalid_or_naive_meta_timestamp_remains_uncertain(self):
        for timestamp in (None, "invalid", "2026-10-24T00:30:00"):
            row = {"id": "123", "timestamp": timestamp}
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(RuntimeError):
                    runtime.history_publication_match("film", row)
        with self.assertRaisesRegex(RuntimeError, "kimliği"):
            runtime.history_publication_match("film", {"id": "", "timestamp": "2026-10-24T00:30:00Z"})

    def test_plan_reconciles_only_unique_confirmed_post_preserving_original_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = {"schema": 1, "episode_days": {}, "entries": {
                "daily_laugh:facebook:video-old": {
                    "route": "daily_laugh", "platform": "facebook", "status": "uncertain",
                    "caption_hash": runtime.caption_key("A specific clip"),
                    "file": "video-old.mp4", "day": "2026-10-24",
                    "run_id": "111"
                }
            }}
            remote_post = {"id": "123456", "description": "A specific clip",
                           "created_time": "2026-10-24T00:30:00+03:00"}
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "222",
                                         "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"daily_laugh": ("daily_laugh", "Daily Laugh Lab")}), \
                    patch.object(runtime, "FOLDERS", {"daily_laugh": "folder"}), \
                    patch.object(runtime, "restore", return_value=original), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "load_meta_auth",
                                 return_value={"pages": [{"page_name": "Daily Laugh Lab", "page_token": "test"}]}), \
                    patch.object(runtime, "inventory", return_value={}), \
                    patch.object(runtime, "graph_rows", return_value=[remote_post]), \
                    patch.object(runtime, "target_count", return_value=0):
                runtime.plan()
            reconciled = json.loads((root / "state.json").read_text())["entries"]["daily_laugh:facebook:video-old"]
            self.assertEqual(reconciled["day"], "2026-10-23")
            self.assertEqual(reconciled["post_id"], "123456")
            self.assertEqual(reconciled["run_id"], "111")
            self.assertEqual(reconciled["reconciled_in_run_id"], "222")
            self.assertEqual(reconciled["reconciliation_proof"], "unique_platform_history_caption")
            self.assertEqual(json.loads((root / "plan.json").read_text()), [])

    def test_plan_multiple_caption_matches_never_marks_uncertain_as_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = {"schema": 1, "episode_days": {}, "entries": {
                "film_second:facebook:clip": {
                    "route": "film_second", "platform": "facebook", "status": "uncertain",
                    "caption_hash": runtime.caption_key("Repeated title"),
                    "day": "2026-10-23", "run_id": "333"
                }
            }}
            remote_rows = [
                {"id": "111", "description": "Repeated title",
                 "created_time": "2026-10-24T01:00:00+03:00"},
                {"id": "222", "description": "Repeated title",
                 "created_time": "2026-10-24T02:00:00+03:00"},
            ]
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "444",
                                         "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"film_second": ("film", "Filmmagrasi")}), \
                    patch.object(runtime, "FOLDERS", {"film": "folder"}), \
                    patch.object(runtime, "restore", return_value=original), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "load_meta_auth",
                                 return_value={"pages": [{"page_name": "Filmmagrasi", "page_token": "test"}]}), \
                    patch.object(runtime, "inventory", return_value={}), \
                    patch.object(runtime, "graph_rows", return_value=remote_rows), \
                    patch.object(runtime, "target_count", return_value=0):
                runtime.plan()
            entry = json.loads((root / "state.json").read_text())["entries"]["film_second:facebook:clip"]
            self.assertEqual(entry["status"], "uncertain")
            self.assertNotIn("post_id", entry)
            self.assertIn("multiple remote posts", (root / "report.md").read_text())

    def test_source_failure_records_ready_without_calling_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path, plan_path = Path(tmp) / "state.json", Path(tmp) / "plan.json"
            item = {"page": "ToonZone", "route": "toonzone", "id": "v", "name": "ep.mp4", "platforms": ["facebook"], "captions": {"facebook": "copy"}}
            runtime.save(state_path, {"entries": {"toonzone:facebook:v": {"status": "intent"}}})
            runtime.save(plan_path, [item])
            with patch.object(runtime, "STATE", state_path), patch.object(runtime, "PLAN", plan_path), patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "ToonZone"}]}), patch.object(runtime, "download", side_effect=RuntimeError("download failed")):
                with self.assertRaises(SystemExit):
                    runtime.publish()
            self.assertEqual(json.loads(state_path.read_text())["entries"]["toonzone:facebook:v"]["status"], "ready")


    def test_daily_laugh_caption_collision_skips_old_and_plans_new_without_duplicate(self):
        """Old remote captions cannot lock out new unique clips or fabricate post IDs."""
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = {
                    "101.mp4": {"id": "id-101", "name": "101.mp4"},
                    "102.mp4": {"id": "id-102", "name": "102.mp4"},
                }
                remote = [{
                    "id": "111", "description": "Daily Laugh Lab · Video 101\n\nApproved comedy text",
                    "created_time": "2026-10-20T10:00:00Z",
                }]
                if duplicate:
                    remote.append({
                        "id": "222", "description": "Daily Laugh Lab · Video 101\n\nApproved comedy text",
                        "created_time": "2026-10-20T12:00:00Z",
                    })
                def captions(route, item, files, temp):
                    body = f"Daily Laugh Lab · Video {Path(item['name']).stem}\n\nApproved comedy text"
                    return {"facebook": body, "instagram": body}, "matching-txt"
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "456",
                                             "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                        patch.object(runtime, "ROOT", root), \
                        patch.object(runtime, "STATE", root / "state.json"), \
                        patch.object(runtime, "PLAN", root / "plan.json"), \
                        patch.object(runtime, "ROUTES", {"daily_laugh": ("daily_laugh", "Daily Laugh Lab")}), \
                        patch.object(runtime, "FOLDERS", {"daily_laugh": "folder"}), \
                        patch.object(runtime, "restore", return_value={"schema": 1, "entries": {}, "episode_days": {}}), \
                        patch.object(runtime, "apply_verified_migration"), \
                        patch.object(runtime, "load_meta_auth",
                                     return_value={"pages": [{"page_name": "Daily Laugh Lab", "page_token": "test"}]}), \
                        patch.object(runtime, "inventory", return_value=source), \
                        patch.object(runtime, "graph_rows", return_value=remote), \
                        patch.object(runtime, "target_count", return_value=5), \
                        patch.object(runtime, "copies", side_effect=captions):
                    runtime.plan()
                planned = json.loads((root / "plan.json").read_text())
                self.assertEqual(len(planned), 1)
                self.assertEqual(planned[0]["name"], "102.mp4")
                self.assertEqual(planned[0]["platforms"], ["facebook"])
                state = json.loads((root / "state.json").read_text())["entries"]
                self.assertNotIn("daily_laugh:facebook:id-101", state)
                self.assertEqual(state["daily_laugh:facebook:id-102"]["status"], "intent")
                self.assertNotIn("post_id", state["daily_laugh:facebook:id-102"])
                summary = (root / "report.md").read_text()
                self.assertIn("SKIP Daily Laugh Lab 101.mp4 facebook", summary)
                self.assertIn("NEXT: 102.mp4", summary)

    def test_gonle_caption_collision_skips_old_and_plans_new_without_duplicate(self):
        """Old remote captions cannot lock out new unique clips or fabricate post IDs."""
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = {
                    "101.mp4": {"id": "id-101", "name": "101.mp4"},
                    "102.mp4": {"id": "id-102", "name": "102.mp4"},
                }
                remote = [{
                    "id": "111", "description": "Gönle Düşen · Video 101\n\nApproved comedy text",
                    "created_time": "2026-10-20T10:00:00Z",
                }]
                if duplicate:
                    remote.append({
                        "id": "222", "description": "Gönle Düşen · Video 101\n\nApproved comedy text",
                        "created_time": "2026-10-20T12:00:00Z",
                    })
                def captions(route, item, files, temp):
                    body = f"Gönle Düşen · Video {Path(item['name']).stem}\n\nApproved comedy text"
                    return {"facebook": body, "instagram": body}, "matching-txt"
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "456",
                                             "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                        patch.object(runtime, "ROOT", root), \
                        patch.object(runtime, "STATE", root / "state.json"), \
                        patch.object(runtime, "PLAN", root / "plan.json"), \
                        patch.object(runtime, "ROUTES", {"gonle": ("gonle", "Gönle Düşen")}), \
                        patch.object(runtime, "FOLDERS", {"gonle": "folder"}), \
                        patch.object(runtime, "restore", return_value={"schema": 1, "entries": {}, "episode_days": {}}), \
                        patch.object(runtime, "apply_verified_migration"), \
                        patch.object(runtime, "load_meta_auth",
                                     return_value={"pages": [{"page_name": "Gönle Düşen", "page_token": "test"}]}), \
                        patch.object(runtime, "inventory", return_value=source), \
                        patch.object(runtime, "graph_rows", return_value=remote), \
                        patch.object(runtime, "target_count", return_value=5), \
                        patch.object(runtime, "copies", side_effect=captions):
                    runtime.plan()
                planned = json.loads((root / "plan.json").read_text())
                self.assertEqual(len(planned), 1)
                self.assertEqual(planned[0]["name"], "102.mp4")
                self.assertEqual(planned[0]["platforms"], ["facebook"])
                state = json.loads((root / "state.json").read_text())["entries"]
                self.assertNotIn("gonle:facebook:id-101", state)
                self.assertEqual(state["gonle:facebook:id-102"]["status"], "intent")
                self.assertNotIn("post_id", state["gonle:facebook:id-102"])
                summary = (root / "report.md").read_text()
                planned_caption = planned[0]["captions"]["facebook"]
                self.assertEqual(state["gonle:facebook:id-102"]["publish_caption"], planned_caption)
                self.assertEqual(state["gonle:facebook:id-102"]["caption_hash"], runtime.caption_key(planned_caption))
                self.assertIn("SKIP Gönle Düşen 101.mp4 facebook", summary)
                self.assertIn("NEXT: 102.mp4", summary)

    def test_ordered_film_caption_collision_preserves_sequence(self):
        """Old remote captions cannot lock out new unique clips or fabricate post IDs."""
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = {
                    "101.mp4": {"id": "id-101", "name": "101.mp4"},
                    "102.mp4": {"id": "id-102", "name": "102.mp4"},
                }
                remote = [{
                    "id": "111", "description": "Filmmagrasi · Video 101\n\nApproved comedy text",
                    "created_time": "2026-10-20T10:00:00Z",
                }]
                if duplicate:
                    remote.append({
                        "id": "222", "description": "Filmmagrasi · Video 101\n\nApproved comedy text",
                        "created_time": "2026-10-20T12:00:00Z",
                    })
                def captions(route, item, files, temp):
                    body = f"Filmmagrasi · Video {Path(item['name']).stem}\n\nApproved comedy text"
                    return {"facebook": body, "instagram": body}, "matching-txt"
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "456",
                                             "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                        patch.object(runtime, "ROOT", root), \
                        patch.object(runtime, "STATE", root / "state.json"), \
                        patch.object(runtime, "PLAN", root / "plan.json"), \
                        patch.object(runtime, "ROUTES", {"film_second": ("film", "Filmmagrasi")}), \
                        patch.object(runtime, "FOLDERS", {"film": "folder"}), \
                        patch.object(runtime, "restore", return_value={"schema": 1, "entries": {}, "episode_days": {}}), \
                        patch.object(runtime, "apply_verified_migration"), \
                        patch.object(runtime, "load_meta_auth",
                                     return_value={"pages": [{"page_name": "Filmmagrasi", "page_token": "test"}]}), \
                        patch.object(runtime, "inventory", return_value=source), \
                        patch.object(runtime, "graph_rows", return_value=remote), \
                        patch.object(runtime, "target_count", return_value=5), \
                        patch.object(runtime, "copies", side_effect=captions):
                    runtime.plan()
                planned = json.loads((root / "plan.json").read_text())
                self.assertEqual(planned, [])
                state = json.loads((root / "state.json").read_text())["entries"]
                self.assertEqual(state, {})
                self.assertIn("HELD:", (root / "report.md").read_text())

    def test_daily_laugh_instagram_collision_does_not_trigger_facebook_duplicate(self):
        """If IG has a matching unverified caption, skip the *whole* clip."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {
                "101.mp4": {"id": "id-101", "name": "101.mp4"},
                "102.mp4": {"id": "id-102", "name": "102.mp4"},
            }
            def captions(route, item, files, temp):
                body = f"Daily Laugh Lab · Video {Path(item['name']).stem}\n\nApproved comedy text"
                return {"facebook": body, "instagram": body}, "matching-txt"
            def history(page, platform):
                if platform == "instagram":
                    return [{"id": "111", "caption": "Daily Laugh Lab · Video 101\n\nApproved comedy text",
                             "timestamp": "2026-10-20T10:00:00Z"}]
                return []
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "456",
                                         "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"daily_laugh": ("daily_laugh", "Daily Laugh Lab")}), \
                    patch.object(runtime, "FOLDERS", {"daily_laugh": "folder"}), \
                    patch.object(runtime, "restore", return_value={"schema": 1, "entries": {}, "episode_days": {}}), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "load_meta_auth",
                                 return_value={"pages": [{"page_name": "Daily Laugh Lab", "page_token": "test", "instagram_id": "ig"}]}), \
                    patch.object(runtime, "inventory", return_value=source), \
                    patch.object(runtime, "graph_rows", side_effect=history), \
                    patch.object(runtime, "target_count", return_value=5), \
                    patch.object(runtime, "copies", side_effect=captions):
                runtime.plan()
            planned = json.loads((root / "plan.json").read_text())
            self.assertEqual(len(planned), 1)
            self.assertEqual(planned[0]["name"], "102.mp4")
            self.assertEqual(set(planned[0]["platforms"]), {"facebook", "instagram"})
            state = json.loads((root / "state.json").read_text())["entries"]
            self.assertFalse(any(key.endswith(":id-101") for key in state))
            self.assertIn("SKIP Daily Laugh Lab 101.mp4 instagram", (root / "report.md").read_text())

    def test_gonle_instagram_collision_quarantines_both_platforms(self):
        """If IG has a matching unverified caption, skip the *whole* clip."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {
                "101.mp4": {"id": "id-101", "name": "101.mp4"},
                "102.mp4": {"id": "id-102", "name": "102.mp4"},
            }
            def captions(route, item, files, temp):
                body = f"Gönle Düşen · Video {Path(item['name']).stem}\n\nApproved comedy text"
                return {"facebook": body, "instagram": body}, "matching-txt"
            def history(page, platform):
                if platform == "instagram":
                    return [{"id": "111", "caption": "Gönle Düşen · Video 101\n\nApproved comedy text",
                             "timestamp": "2026-10-20T10:00:00Z"}]
                return []
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "456",
                                         "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"gonle": ("gonle", "Gönle Düşen")}), \
                    patch.object(runtime, "FOLDERS", {"gonle": "folder"}), \
                    patch.object(runtime, "restore", return_value={"schema": 1, "entries": {}, "episode_days": {}}), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "load_meta_auth",
                                 return_value={"pages": [{"page_name": "Gönle Düşen", "page_token": "test", "instagram_id": "ig"}]}), \
                    patch.object(runtime, "inventory", return_value=source), \
                    patch.object(runtime, "graph_rows", side_effect=history), \
                    patch.object(runtime, "target_count", return_value=5), \
                    patch.object(runtime, "copies", side_effect=captions):
                runtime.plan()
            planned = json.loads((root / "plan.json").read_text())
            self.assertEqual(len(planned), 1)
            self.assertEqual(planned[0]["name"], "102.mp4")
            self.assertEqual(set(planned[0]["platforms"]), {"facebook", "instagram"})
            state = json.loads((root / "state.json").read_text())["entries"]
            self.assertFalse(any(key.endswith(":id-101") for key in state))
            self.assertIn("SKIP Gönle Düşen 101.mp4 instagram", (root / "report.md").read_text())

    def test_daily_laugh_existing_uncertain_intent_stays_held_on_duplicate_caption(self):
        """Do not evade an actual uncertain Meta POST by skipping its source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "Daily Laugh Lab · Video 101\n\nApproved comedy text"
            original = {"schema": 1, "episode_days": {}, "entries": {
                "daily_laugh:facebook:id-101": {
                    "route": "daily_laugh", "platform": "facebook", "status": "uncertain",
                    "caption_hash": runtime.caption_key(body), "run_id": "111",
                    "file": "101.mp4", "day": "2026-10-20",
                }
            }}
            source = {
                "101.mp4": {"id": "id-101", "name": "101.mp4"},
                "102.mp4": {"id": "id-102", "name": "102.mp4"},
            }
            remote = [
                {"id": "111", "description": body, "created_time": "2026-10-20T10:00:00Z"},
                {"id": "222", "description": body, "created_time": "2026-10-20T12:00:00Z"},
            ]
            def captions(route, item, files, temp):
                caption = f"Daily Laugh Lab · Video {Path(item['name']).stem}\n\nApproved comedy text"
                return {"facebook": caption, "instagram": caption}, "matching-txt"
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "456",
                                         "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"daily_laugh": ("daily_laugh", "Daily Laugh Lab")}), \
                    patch.object(runtime, "FOLDERS", {"daily_laugh": "folder"}), \
                    patch.object(runtime, "restore", return_value=original), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "load_meta_auth",
                                 return_value={"pages": [{"page_name": "Daily Laugh Lab", "page_token": "test"}]}), \
                    patch.object(runtime, "inventory", return_value=source), \
                    patch.object(runtime, "graph_rows", return_value=remote), \
                    patch.object(runtime, "target_count", return_value=5), \
                    patch.object(runtime, "copies", side_effect=captions):
                runtime.plan()
            self.assertEqual(json.loads((root / "plan.json").read_text()), [])
            state = json.loads((root / "state.json").read_text())["entries"]
            self.assertEqual(state["daily_laugh:facebook:id-101"]["status"], "uncertain")
            self.assertNotIn("post_id", state["daily_laugh:facebook:id-101"])
            self.assertNotIn("daily_laugh:facebook:id-102", state)
            self.assertIn("HELD: multiple Meta posts share the same caption", (root / "report.md").read_text())

    def test_gonle_existing_uncertain_intent_stays_held_on_duplicate_caption(self):
        """Do not evade an actual uncertain Meta POST by skipping its source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "Gönle Düşen · Video 101\n\nApproved comedy text"
            original = {"schema": 1, "episode_days": {}, "entries": {
                "gonle:facebook:id-101": {
                    "route": "gonle", "platform": "facebook", "status": "uncertain",
                    "caption_hash": runtime.caption_key(body), "run_id": "111",
                    "file": "101.mp4", "day": "2026-10-20",
                }
            }}
            source = {
                "101.mp4": {"id": "id-101", "name": "101.mp4"},
                "102.mp4": {"id": "id-102", "name": "102.mp4"},
            }
            remote = [
                {"id": "111", "description": body, "created_time": "2026-10-20T10:00:00Z"},
                {"id": "222", "description": body, "created_time": "2026-10-20T12:00:00Z"},
            ]
            def captions(route, item, files, temp):
                caption = f"Gönle Düşen · Video {Path(item['name']).stem}\n\nApproved comedy text"
                return {"facebook": caption, "instagram": caption}, "matching-txt"
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "456",
                                         "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"gonle": ("gonle", "Gönle Düşen")}), \
                    patch.object(runtime, "FOLDERS", {"gonle": "folder"}), \
                    patch.object(runtime, "restore", return_value=original), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "load_meta_auth",
                                 return_value={"pages": [{"page_name": "Gönle Düşen", "page_token": "test"}]}), \
                    patch.object(runtime, "inventory", return_value=source), \
                    patch.object(runtime, "graph_rows", return_value=remote), \
                    patch.object(runtime, "target_count", return_value=5), \
                    patch.object(runtime, "copies", side_effect=captions):
                runtime.plan()
            self.assertEqual(json.loads((root / "plan.json").read_text()), [])
            state = json.loads((root / "state.json").read_text())["entries"]
            self.assertEqual(state["gonle:facebook:id-101"]["status"], "uncertain")
            self.assertNotIn("post_id", state["gonle:facebook:id-101"])
            self.assertNotIn("gonle:facebook:id-102", state)
            self.assertIn("HELD: multiple Meta posts share the same caption", (root / "report.md").read_text())

    def test_saved_tagged_caption_stays_exact_on_ready_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "Frozen caption #Approved"
            initial = {"schema": 1, "episode_days": {}, "entries": {
                "gonle:facebook:v1": {
                    "route": "gonle", "platform": "facebook", "status": "ready",
                    "caption_hash": runtime.caption_key(body), "publish_caption": body,
                    "file": "1.mp4", "day": "2026-10-20", "prepublish_retry_count": 1,
                }
            }}
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "456", "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                    patch.object(runtime, "ROOT", root), \
                    patch.object(runtime, "STATE", root / "state.json"), \
                    patch.object(runtime, "PLAN", root / "plan.json"), \
                    patch.object(runtime, "ROUTES", {"gonle": ("gonle", "Gönle Düşen")}), \
                    patch.object(runtime, "FOLDERS", {"gonle": "folder"}), \
                    patch.object(runtime, "restore", return_value=initial), \
                    patch.object(runtime, "apply_verified_migration"), \
                    patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "Gönle Düşen", "page_token": "test"}]}), \
                    patch.object(runtime, "inventory", return_value={"1.mp4": {"id": "v1", "name": "1.mp4"}}), \
                    patch.object(runtime, "graph_rows", return_value=[]), \
                    patch.object(runtime, "target_count", return_value=5), \
                    patch.object(runtime, "copies", return_value=({"facebook": "changed TXT", "instagram": "changed TXT"}, "matching-txt")), \
                    patch.object(runtime, "prepare_caption", side_effect=AssertionError("Do not redecorate existing intent")):
                runtime.plan()
            planned = json.loads((root / "plan.json").read_text())
            self.assertEqual(planned[0]["captions"]["facebook"], body)
            entry = json.loads((root / "state.json").read_text())["entries"]["gonle:facebook:v1"]
            self.assertEqual(entry["caption_hash"], runtime.caption_key(body))
            self.assertEqual(entry["prepublish_retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
