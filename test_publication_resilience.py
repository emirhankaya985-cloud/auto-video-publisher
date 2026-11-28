"""Offline failure injection across account discovery, planning and upload stages."""
from contextlib import ExitStack
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cloud_omnichannel_publisher as cloud
import meta_auth_loader as auth
from test_public_link_runtime import runtime


def response(payload, status=200):
    return Mock(status_code=status, ok=status < 400, headers={},
                json=Mock(return_value=payload), text="")


class PublicationResilienceTests(unittest.TestCase):
    def publication_fixture(self, root, status="intent"):
        item = {"route": "gonle", "page": "Gönle Düşen", "id": "v1", "name": "1.mp4",
                "platforms": ["facebook"], "captions": {"facebook": "approved caption"}}
        state = {"schema": 1, "entries": {"gonle:facebook:v1": {
            "route": "gonle", "platform": "facebook", "status": status,
            "file": "1.mp4", "run_id": "999", "publish_caption": "approved caption",
            "caption_hash": runtime.caption_key("approved caption")}}}
        runtime.save(root / "state.json", state)
        runtime.save(root / "plan.json", [item])
        video = root / "source.mp4"
        video.write_bytes(b"0000ftypoffline-test")
        return item, state, video

    def test_publish_replay_never_uploads_a_confirmed_post_twice(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            item, state, video = self.publication_fixture(root)
            stack.enter_context(patch.dict(os.environ, {"GITHUB_RUN_ID": "999"}))
            stack.enter_context(patch.object(runtime, "STATE", root / "state.json"))
            stack.enter_context(patch.object(runtime, "PLAN", root / "plan.json"))
            stack.enter_context(patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "Gönle Düşen"}]}))
            download = stack.enter_context(patch.object(runtime, "download", return_value=video))
            stack.enter_context(patch.object(runtime, "verify_source_video", return_value=True))
            def uploaded(*args):
                saved = json.loads((root / "state.json").read_text())
                self.assertEqual(saved["entries"]["gonle:facebook:v1"]["status"], "uncertain")
                return "123"
            post = stack.enter_context(patch.object(runtime, "upload_facebook_reel", side_effect=uploaded))
            runtime.publish()
            runtime.publish()
            post.assert_called_once()
            download.assert_called_once()
            saved = json.loads((root / "state.json").read_text())
            self.assertEqual(saved["entries"]["gonle:facebook:v1"]["post_id"], "123")

    def test_crash_during_post_leaves_uncertain_and_replay_cannot_post(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            item, state, video = self.publication_fixture(root)
            stack.enter_context(patch.dict(os.environ, {"GITHUB_RUN_ID": "999"}))
            stack.enter_context(patch.object(runtime, "STATE", root / "state.json"))
            stack.enter_context(patch.object(runtime, "PLAN", root / "plan.json"))
            stack.enter_context(patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "Gönle Düşen"}]}))
            download = stack.enter_context(patch.object(runtime, "download", return_value=video))
            stack.enter_context(patch.object(runtime, "verify_source_video", return_value=True))
            post = stack.enter_context(patch.object(runtime, "upload_facebook_reel", side_effect=KeyboardInterrupt))
            with self.assertRaises(KeyboardInterrupt):
                runtime.publish()
            with self.assertRaises(SystemExit):
                runtime.publish()
            post.assert_called_once()
            download.assert_called_once()
            saved = json.loads((root / "state.json").read_text())
            self.assertEqual(saved["entries"]["gonle:facebook:v1"]["status"], "uncertain")

    def test_intent_bindings_and_unreconciled_states_fail_before_upload(self):
        for change in ({"status": "ready"}, {"status": "uncertain"},
                       {"run_id": "old"}, {"file": "other.mp4"},
                       {"caption_hash": "wrong"}, {"publish_caption": "changed"},
                       {"status": "done"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                item, state, video = self.publication_fixture(Path(tmp))
                state["entries"]["gonle:facebook:v1"].update(change)
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "999"}):
                    with self.assertRaises(RuntimeError):
                        runtime.pending_publication_platforms(item, state)

    def test_partial_success_only_keeps_unpublished_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            item, state, video = self.publication_fixture(Path(tmp))
            item["platforms"].append("instagram")
            item["captions"]["instagram"] = "approved caption"
            state["entries"]["gonle:instagram:v1"] = dict(state["entries"]["gonle:facebook:v1"], platform="instagram")
            state["entries"]["gonle:facebook:v1"].update(status="done", post_id="123")
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "999"}):
                self.assertEqual(runtime.pending_publication_platforms(item, state), ["instagram"])
            item["platforms"].append("instagram")
            with self.assertRaises(RuntimeError):
                runtime.pending_publication_platforms(item, state)

    def test_ledger_aliases_or_unverified_results_do_not_inflate_daily_quota(self):
        base = {"route": "gonle", "platform": "facebook", "status": "done",
                "day": "2026-10-27", "post_id": "123"}
        state = {"entries": {"one": base, "alias": dict(base),
                             "unverified": dict(base, post_id=None),
                             "yesterday": dict(base, day="2026-10-26", post_id="456"),
                             "instagram": dict(base, platform="instagram", post_id="789"),
                             "pending": dict(base, status="uncertain", post_id="222")}}
        self.assertEqual(runtime.ledger_daily_count(state, "gonle", "facebook", "2026-10-27"), 1)

    def test_due_empty_queue_journals_every_tick_but_not_before_slot_or_during_audit(self):
        for due, audit, held in ((1, False, False), (1, False, True),
                                 (0, False, True), (1, True, True)):
            with self.subTest(due=due, audit=audit, held=held), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                entries = {"gonle:facebook:old": {
                    "route": "gonle", "platform": "facebook", "status": "uncertain",
                    "file": "old.mp4", "caption_hash": "old",
                }} if held else {}
                original_entries = json.loads(json.dumps(entries))
                state = {"schema": 1, "entries": entries, "episode_days": {}}
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "999", "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                        patch.object(runtime, "ROOT", root), \
                        patch.object(runtime, "STATE", root / "state.json"), \
                        patch.object(runtime, "PLAN", root / "plan.json"), \
                        patch.object(runtime, "ROUTES", {"gonle": ("gonle", "Gönle Düşen")}), \
                        patch.object(runtime, "FOLDERS", {"gonle": "g"}), \
                        patch.object(runtime, "restore", return_value=state), \
                        patch.object(runtime, "apply_verified_migration"), \
                        patch.object(runtime, "route_enabled", return_value=True), \
                        patch.object(runtime, "load_meta_auth", return_value={"pages": [{"page_name": "Gönle Düşen"}]}), \
                        patch.object(runtime, "inventory", return_value={}), \
                        patch.object(runtime, "graph_rows", return_value=[]), \
                        patch.object(runtime, "target_count", return_value=due), \
                        patch.object(runtime, "record_error") as journal:
                    runtime.plan(audit=audit)
                    runtime.plan(audit=audit)
                if due and not audit:
                    self.assertEqual(journal.call_count, 2)
                    for event in journal.call_args_list:
                        self.assertEqual(event.args, ("planning_queue", "no_eligible_content"))
                        self.assertEqual(event.kwargs, {"route": "gonle", "safe_to_retry": True})
                else:
                    journal.assert_not_called()
                self.assertEqual(state["entries"], original_entries)

    def test_account_discovery_recovers_transient_reads_without_posting(self):
        for first in (OSError("private-url"), response({}, 503),
                      response({"error": {"code": 4}}, 400)):
            with self.subTest(first=type(first).__name__):
                get = Mock(side_effect=[first, response({"data": []})])
                with patch.object(auth.time, "sleep"), patch.object(auth.requests, "post") as post:
                    self.assertEqual(auth.discover_pages("private-token", get=get), {"pages": []})
                self.assertEqual(get.call_count, 2)
                self.assertFalse(get.call_args.kwargs["allow_redirects"])
                post.assert_not_called()

    def test_discovery_auth_error_remains_permanent(self):
        get = Mock(return_value=response({"error": {"code": 190}}, 400))
        with patch.object(auth.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                auth.discover_pages("private-token", get=get)
        get.assert_called_once()
        sleep.assert_not_called()

    def test_history_network_exhaustion_is_sanitized_and_account_scoped(self):
        with patch.object(runtime.requests, "get", create=True,
                          side_effect=OSError("https://private-url/?token=private-token")) as get, \
                patch.dict(runtime.read_with_retry.__kwdefaults__, {"sleep": Mock()}):
            with self.assertRaises(RuntimeError) as raised:
                runtime.graph_rows({"page_id": "123", "page_token": "test"}, "facebook")
        self.assertEqual(get.call_count, 3)
        self.assertNotIn("private", str(raised.exception))

    def test_repeated_paginated_post_id_does_not_fill_daily_quota_twice(self):
        row = {"id": "123", "created_time": "2026-10-27T10:00:00Z"}
        second = dict(row, id="456")
        get = Mock(side_effect=[
            response({"data": [row], "paging": {"next": "ignored", "cursors": {"after": "two"}}}),
            response({"data": [row, second]}),
        ])
        with patch.object(runtime.requests, "get", get, create=True):
            rows = runtime.graph_rows({"page_id": "123", "page_token": "test"}, "facebook")
        self.assertEqual([r["id"] for r in rows], ["123", "456"])
        self.assertNotIn("after", get.call_args_list[0].kwargs["params"])
        self.assertEqual(get.call_args_list[1].kwargs["params"]["after"], "two")

    def test_malformed_paging_or_missing_id_holds_account(self):
        row = {"id": "123", "created_time": "2026-10-27T10:00:00Z"}
        for payload in ({"data": [row], "paging": "private"},
                        {"data": [row], "paging": {"next": "ignored", "cursors": []}},
                        {"data": [dict(row, id="")]}):
            with self.subTest(payload=payload), \
                    patch.object(runtime.requests, "get", create=True, return_value=response(payload)):
                with self.assertRaises(RuntimeError):
                    runtime.graph_rows({"page_id": "123", "page_token": "test"}, "facebook")

    def test_one_bad_account_does_not_erase_other_accounts_plan(self):
        for broken in (RuntimeError("Meta history unavailable"),
                       [{"id": "123", "created_time": "invalid"}]):
            with self.subTest(broken=type(broken).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                def history(page, platform):
                    if page["page_name"] == "Gönle Düşen":
                        if isinstance(broken, Exception):
                            raise broken
                        return broken
                    return []
                source = {"101.mp4": {"name": "101.mp4", "id": "file101"}}
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "999", "GITHUB_STEP_SUMMARY": str(root / "summary.md")}), \
                        patch.object(runtime, "ROOT", root), \
                        patch.object(runtime, "STATE", root / "state.json"), \
                        patch.object(runtime, "PLAN", root / "plan.json"), \
                        patch.object(runtime, "ROUTES", {"gonle": ("gonle", "Gönle Düşen"),
                                                         "daily_laugh": ("daily_laugh", "Daily Laugh Lab")}), \
                        patch.object(runtime, "FOLDERS", {"gonle": "g", "daily_laugh": "d"}), \
                        patch.object(runtime, "restore", return_value={"schema": 1, "entries": {}, "episode_days": {}}), \
                        patch.object(runtime, "apply_verified_migration"), \
                        patch.object(runtime, "route_enabled", return_value=True), \
                        patch.object(runtime, "load_meta_auth", return_value={"pages": [
                            {"page_name": "Gönle Düşen"}, {"page_name": "Daily Laugh Lab"}]}), \
                        patch.object(runtime, "inventory", return_value=source), \
                        patch.object(runtime, "graph_rows", side_effect=history), \
                        patch.object(runtime, "target_count", return_value=1), \
                        patch.object(runtime, "copies", return_value=({"facebook": "unique", "instagram": "unique"}, "matching-txt")), \
                        patch.object(runtime, "upload_facebook_reel") as post:
                    runtime.plan()
                plans = json.loads((root / "plan.json").read_text())
                self.assertEqual([p["route"] for p in plans], ["daily_laugh"])
                self.assertEqual(plans[0]["platforms"], ["facebook"])
                state = json.loads((root / "state.json").read_text())
                self.assertEqual(list(state["entries"]), ["daily_laugh:facebook:file101"])
                self.assertIn("HELD:", (root / "report.md").read_text())
                post.assert_not_called()

    def test_instagram_status_read_retries_without_repeating_container_or_publish(self):
        post = Mock(side_effect=[response({"id": "container", "uri": "https://rupload.facebook.com/1"}),
                                 response({"id": "media"})])
        get = Mock(side_effect=[response({}, 503), response({"status_code": "FINISHED"}),
                                response({"id": "media"})])
        with patch.object(cloud.os.path, "getsize", return_value=5), \
                patch.object(cloud, "_sha256_file", return_value="a" * 64), \
                patch.object(cloud, "_upload_instagram_binary", return_value={}) as upload, \
                patch.object(cloud.time, "sleep"), \
                patch.object(cloud.requests, "post", post), \
                patch.object(cloud.requests, "get", get):
            self.assertEqual(cloud.upload_instagram_reel({"instagram_id": "ig", "page_token": "test"},
                                                       "video.mp4", "caption"), "media")
        self.assertEqual(get.call_count, 3)
        self.assertEqual(post.call_count, 2)
        upload.assert_called_once()

    def test_facebook_code6000_quarantines_exact_unordered_clip(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            _item, _state, video = self.publication_fixture(root)
            error = runtime.MetaAPIError("HTTP 400 video upload rejected")
            error.stage, error.http_status, error.code, error.subcode = (
                "Facebook video_reels binary upload", 400, 6000, None)
            stack.enter_context(patch.dict(os.environ, {"GITHUB_RUN_ID": "999"}))
            stack.enter_context(patch.object(runtime, "STATE", root / "state.json"))
            stack.enter_context(patch.object(runtime, "PLAN", root / "plan.json"))
            stack.enter_context(patch.object(runtime, "load_meta_auth", return_value={
                "pages": [{"page_name": "Gönle Düşen"}]}))
            stack.enter_context(patch.object(runtime, "download", return_value=video))
            stack.enter_context(patch.object(runtime, "verify_source_video", return_value=True))
            upload = stack.enter_context(patch.object(runtime, "upload_facebook_reel",
                                                        side_effect=error))

            with self.assertRaises(SystemExit):
                runtime.publish()

            row = json.loads((root / "state.json").read_text())["entries"]["gonle:facebook:v1"]
            self.assertEqual(row["status"], "held")
            self.assertTrue(row["video_quarantined"])
            self.assertEqual(row["failure"]["recovery_action"], "skip_this_video")
            self.assertEqual(row["failure"]["stage"], "Facebook video_reels binary upload")
            self.assertEqual(row["failure"]["graph_code"], 6000)
            upload.assert_called_once()

    def test_facebook_finish_auth_and_rate_400_stay_uncertain(self):
        for stage, code in (("Facebook video_reels finish", 6000),
                            ("Facebook video_reels binary upload", 190),
                            ("Facebook video_reels binary upload", 613)):
            with self.subTest(stage=stage, code=code), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                root = Path(tmp)
                _item, _state, video = self.publication_fixture(root)
                error = runtime.MetaAPIError("HTTP 400")
                error.stage, error.http_status, error.code, error.subcode = stage, 400, code, None
                stack.enter_context(patch.dict(os.environ, {"GITHUB_RUN_ID": "999"}))
                stack.enter_context(patch.object(runtime, "STATE", root / "state.json"))
                stack.enter_context(patch.object(runtime, "PLAN", root / "plan.json"))
                stack.enter_context(patch.object(runtime, "load_meta_auth", return_value={
                    "pages": [{"page_name": "Gönle Düşen"}]}))
                stack.enter_context(patch.object(runtime, "download", return_value=video))
                stack.enter_context(patch.object(runtime, "verify_source_video", return_value=True))
                stack.enter_context(patch.object(runtime, "upload_facebook_reel", side_effect=error))
                with self.assertRaises(SystemExit):
                    runtime.publish()
                row = json.loads((root / "state.json").read_text())["entries"]["gonle:facebook:v1"]
                self.assertEqual(row["status"], "uncertain")
                self.assertNotIn("video_quarantined", row)

    def test_facebook_explicit_failure_cannot_be_claimed_as_a_published_id(self):
        cases = (
            ("start", [response({"error": {"message": "bad request", "code": 100}}, 400)],
             "Facebook video_reels start"),
            ("binary", [response({"video_id": "123", "upload_url": "https://upload.invalid"}),
                        response({"error": {"message": "upload failed", "code": 6000}}, 400)],
             "Facebook video_reels binary upload"),
            ("finish", [response({"video_id": "123", "upload_url": "https://upload.invalid"}),
                        response({"success": True}),
                        response({"error": {"message": "finish failed", "code": 6000}}, 400)],
             "Facebook video_reels finish"),
        )
        for phase, calls, expected_stage in cases:
            with self.subTest(stage=phase), tempfile.TemporaryDirectory() as temp_dir:
                video = Path(temp_dir) / "video.mp4"
                video.write_bytes(b"data")
                with patch.object(cloud.requests, "post", side_effect=calls) as post:
                    with self.assertRaises(cloud.MetaAPIError) as caught:
                        cloud.upload_facebook_reel({"page_id": "123", "page_token": "test"},
                                                   str(video), "caption")
                self.assertEqual(caught.exception.stage, expected_stage)
                self.assertEqual(post.call_count, len(calls))


if __name__ == "__main__":
    unittest.main()
