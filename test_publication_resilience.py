"""Offline failure injection across account discovery, planning and upload stages."""
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
    def test_ledger_aliases_or_unverified_results_do_not_inflate_daily_quota(self):
        base = {"route": "gonle", "platform": "facebook", "status": "done",
                "day": "2026-10-27", "post_id": "123"}
        state = {"entries": {"one": base, "alias": dict(base),
                             "unverified": dict(base, post_id=None),
                             "yesterday": dict(base, day="2026-10-26", post_id="456"),
                             "instagram": dict(base, platform="instagram", post_id="789"),
                             "pending": dict(base, status="uncertain", post_id="222")}}
        self.assertEqual(runtime.ledger_daily_count(state, "gonle", "facebook", "2026-10-27"), 1)

    def test_due_empty_queue_warns_once_per_day_but_not_before_slot_or_during_audit(self):
        for due, audit in ((1, False), (0, False), (1, True)):
            with self.subTest(due=due, audit=audit), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state = {"schema": 1, "entries": {}, "episode_days": {}}
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
                    journal.assert_called_once_with("planning_queue", "no_eligible_content",
                                                    route="gonle", safe_to_retry=True)
                else:
                    journal.assert_not_called()
                self.assertEqual(state["entries"], {})

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

    def test_facebook_explicit_failure_cannot_be_claimed_as_a_published_id(self):
        for failed_stage in ("upload", "finish"):
            calls = [response({"video_id": "123", "upload_url": "https://upload.invalid"})]
            if failed_stage == "finish":
                calls.append(response({"success": True}))
            calls.append(response({"success": False}))
            with self.subTest(stage=failed_stage), tempfile.NamedTemporaryFile() as video:
                video.write(b"data")
                video.flush()
                with patch.object(cloud.requests, "post", side_effect=calls) as post:
                    with self.assertRaises(cloud.MetaAPIError):
                        cloud.upload_facebook_reel({"page_id": "123", "page_token": "test"},
                                                   video.name, "caption")
                self.assertEqual(post.call_count, len(calls))


if __name__ == "__main__":
    unittest.main()
