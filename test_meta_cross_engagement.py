"""No live Meta/GitHub writes: identity, dedupe and crash safety checks."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import meta_cross_engagement as m

NOW = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
GRANTS = {"pages_manage_posts", "pages_manage_engagement", "instagram_basic", "instagram_manage_engagement"}


def actors():
    return {(p, i): dict(platform=p, id=i, name=n, grants=set(GRANTS), token="private-token", owner_page=i)
            for p, i, n in (("facebook", "11", "Tarladaki Fasulye"),
                            ("facebook", "22", "Beyinsiz Penguen"),
                            ("instagram", "33", "Tarladaki Fasulye"),
                            ("instagram", "44", "Beyinsiz Penguen"))}


def task(operation="like", platform="facebook", actor="22", owner="11"):
    return dict(operation=operation, platform=platform, actor=actor, owner=owner,
                post_id="123", source_run_id="100")


def reserved(t):
    return {"schema": 1, "actions": {m.key(t): dict(t, run_id="200", status="reserved", at=NOW.isoformat())}}


class EngagementTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(m, "account_enabled", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_plan_all_accounts_and_own_likes_reports_unsupported(self):
        ledger = {"schema": 1, "actions": {}}
        tasks, report = m.build_plan([
            dict(platform="facebook", post_id="123", owner="11"),
            dict(platform="instagram", post_id="456", owner="33")],
            actors(), ledger, "200", "100", now=NOW)
        self.assertEqual(len(tasks), 5)  # 2 FB likes + 1 share + 2 IG likes
        self.assertEqual(sum(t["actor"] == t["owner"] for t in tasks), 2)
        self.assertTrue(all(t["operation"] != "save" for t in tasks))
        self.assertTrue(all(t["operation"] != "repost" or t["platform"] == "facebook" for t in tasks))
        self.assertEqual(sum(r["status"] == "unsupported_by_verified_api" for r in report), 6)
        self.assertNotIn("private-token", json.dumps([tasks, report, ledger]))

    def test_prior_intent_and_accepted_posts_cannot_repeat(self):
        for status in ("accepted", "reserved", "uncertain", "rejected"):
            t = task()
            ledger = reserved(t)
            ledger["actions"][m.key(t)]["status"] = status
            tasks, _ = m.build_plan([dict(platform="facebook", post_id="123", owner="11")],
                                     actors(), ledger, "201", "100", now=NOW)
            self.assertNotIn(t, tasks)

    def test_missing_permissions_block_without_reserving(self):
        aa = actors()
        for a in aa.values():
            a["grants"] = set()
        ledger = {"schema": 1, "actions": {}}
        tasks, report = m.build_plan([dict(platform="facebook", post_id="123", owner="11")],
                                    aa, ledger, "200", "100", now=NOW)
        self.assertEqual(tasks, [])
        self.assertEqual(ledger["actions"], {})
        self.assertIn("missing_permission", {r["status"] for r in report})

    def test_corrupt_ledger_is_not_reset(self):
        for ledger in ({}, {"schema": 2, "actions": {}}, {"schema": 1, "actions": []}):
            with self.assertRaises(ValueError):
                m.build_plan([], actors(), ledger, "200", "100", now=NOW)

    def test_only_new_native_publisher_ids_are_sources(self):
        base = dict(status="done", run_id="100", route="tarladaki", platform="facebook", post_id="123")
        rows = {"new": base, "duplicate": dict(base), "old": dict(base, run_id="99", post_id="456"),
                "alias": dict(base, post_id="789", duplicate_of_file_id="a"),
                "reconciled": dict(base, post_id="800", reconciled_in_run_id="100"),
                "held": dict(base, status="uncertain", post_id="900")}
        result = m.source_posts({"entries": rows}, "100", actors())
        self.assertEqual(result, [dict(platform="facebook", post_id="123", owner="11")])

    def test_facebook_like_and_instagram_like_use_different_official_nodes(self):
        for t, expected, data in ((task(), "123/likes", {}),
                (task(platform="instagram", actor="44", owner="33"), "44/likes", {"media_id": "123"})):
            with patch.object(m, "graph", return_value={"success": True}) as graph:
                self.assertEqual(m.perform(t, actors()[(t["platform"], t["actor"])], None), {"api_ack": True})
                self.assertEqual(graph.call_args.args[:2], ("POST", expected))
                self.assertEqual(graph.call_args.args[3], data)

    def test_share_posts_exact_verified_link_and_requires_receipt(self):
        t = task("repost")
        with patch.object(m, "graph", return_value={"id": "22_999"}) as graph:
            out = m.perform(t, actors()[("facebook", "22")], "https://www.facebook.com/reel/123/")
            self.assertEqual(out["share_post_id"], "22_999")
            self.assertEqual(graph.call_args.args[3], {"link": "https://www.facebook.com/reel/123/"})
        with patch.object(m, "graph", return_value={}):
            with self.assertRaises(m.GraphFailure):
                m.perform(t, actors()[("facebook", "22")], "https://www.facebook.com/reel/123/")

    def test_no_unsupported_operation_can_reach_a_write(self):
        for t in (task("save"), task("repost", "instagram", "44", "33")):
            with patch.object(m, "graph") as graph:
                with self.assertRaises(ValueError):
                    m.perform(t, actors()[(t["platform"], t["actor"])], None)
                graph.assert_not_called()

    def test_mismatched_owner_and_external_links_block(self):
        for body in ({"id": "123", "from": {"id": "99"}, "permalink_url": "https://www.facebook.com/reel/123/"},
                     {"id": "123", "from": {"id": "11"}, "permalink_url": "https://evil.test/"},
                     {"id": "123", "from": {"id": "11"}, "permalink_url": "https://www.facebook.com.evil.test/"}):
            with patch.object(m, "graph", return_value=body):
                with self.assertRaises(ValueError):
                    m.verified_media(task("repost"), actors())

    def test_crash_after_post_is_persisted_uncertain_and_not_retried(self):
        t = task("repost")
        ledger = reserved(t)
        writes, snapshots = Mock(side_effect=KeyboardInterrupt()), []
        with patch.object(m, "verified_media", return_value="https://www.facebook.com/reel/123/"), \
             patch.object(m, "perform", writes):
            with self.assertRaises(KeyboardInterrupt):
                m.execute([t], actors(), ledger, "200", persist=lambda d:snapshots.append(copy.deepcopy(d)), sleep=Mock())
            self.assertEqual(snapshots[-1]["actions"][m.key(t)]["status"], "uncertain")
            m.execute([t], actors(), ledger, "200", persist=Mock(), sleep=Mock())
            self.assertEqual(writes.call_count, 1)

    def test_success_and_ambiguous_response_are_recorded_separately(self):
        for reply, status in (({"api_ack": True}, "accepted"), (m.GraphFailure(503), "uncertain"),
                              (m.GraphFailure(400, 100, definite=True), "rejected")):
            t = task();ledger = reserved(t)
            with patch.object(m, "verified_media", return_value=None), \
                 patch.object(m, "perform", side_effect=reply if isinstance(reply, Exception) else None,
                              return_value=reply):
                m.execute([t], actors(), ledger, "200", persist=Mock(), sleep=Mock())
            self.assertEqual(ledger["actions"][m.key(t)]["status"], status)

    def test_wrong_run_and_plan_tampering_do_not_write(self):
        t = task();ledger = reserved(t)
        with patch.object(m, "perform") as post:
            m.execute([t], actors(), ledger, "201", persist=Mock(), sleep=Mock())
            m.execute([dict(t, owner="99")], actors(), ledger, "200", persist=Mock(), sleep=Mock())
            post.assert_not_called()

    def test_rate_limit_stops_actor_without_repeating_post(self):
        one, two = task(), dict(task(), post_id="124")
        ledger = reserved(one)
        ledger["actions"].update(reserved(two)["actions"])
        with patch.object(m, "verified_media", return_value=None), \
             patch.object(m, "perform", side_effect=m.GraphFailure(429, 4, definite=True)) as post:
            m.execute([one, two], actors(), ledger, "200", persist=Mock(), sleep=Mock())
            post.assert_called_once()
        self.assertEqual(ledger["actions"][m.key(two)]["status"], "blocked_actor")

    def test_lost_ownership_before_execute_never_posts(self):
        t = task();ledger=reserved(t)
        with patch.object(m, "verified_media", side_effect=ValueError("wrong owner")), patch.object(m, "perform") as post:
            m.execute([t], actors(), ledger, "200", persist=Mock(), sleep=Mock())
            post.assert_not_called()
        self.assertEqual(ledger["actions"][m.key(t)]["status"], "source_or_permission_unverified")

    def test_pausing_actor_after_plan_prevents_engagement(self):
        t=task();ledger=reserved(t)
        with patch.object(m,"account_enabled",return_value=False),patch.object(m,"perform") as post:
            m.execute([t],actors(),ledger,"200",persist=Mock(),sleep=Mock())
            post.assert_not_called()
        self.assertEqual(ledger["actions"][m.key(t)]["status"],"blocked_actor")

    def test_graph_transport_failure_is_single_attempt_and_redacted(self):
        post = Mock(side_effect=requests.Timeout("private-token signed-url"))
        with self.assertRaises(m.GraphFailure) as error:
            m.graph("POST", "123/likes", "private-token", post=post)
        post.assert_called_once()
        self.assertNotIn("private-token", str(error.exception))
        self.assertFalse(error.exception.definite)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_graph_malformed_success_does_not_claim_acceptance(self):
        response=Mock(status_code=200)
        response.json.return_value=[]
        with self.assertRaises(m.GraphFailure):
            m.graph("POST", "123/likes", "token", post=Mock(return_value=response))
        response.close.assert_called_once()

    def test_account_identity_and_user_grants_are_required(self):
        config={"pages":[{"page_id":"11","page_name":"Tarladaki Fasulye", "page_token":"page-secret", "instagram_id":"33"}]}
        def listing(node, token, fields=None):
            self.assertEqual(token, "user-secret")
            return ([{"permission":p,"status":"granted"} for p in GRANTS] if node=="me/permissions"
                    else [{"id":"11","instagram_business_account":{"id":"33"}}])
        with patch.object(m, "graph", return_value={"id":"11"}), patch.object(m, "rows",side_effect=listing):
            aa=m.accounts(config,"user-secret")
            self.assertEqual(aa[("instagram","33")]["token"],"user-secret")
            self.assertEqual(aa[("facebook","11")]["token"],"page-secret")
        with patch.object(m,"graph",return_value={"id":"99"}):
            self.assertEqual(m.accounts(config,"user-secret"),{})
        with patch.object(m,"graph",return_value={"id":"11"}), patch.object(m,"rows",return_value=[]):
            self.assertEqual(m.accounts(config,"user-secret"),{})

    def test_stale_source_run_cannot_replay_after_ledger_pruning(self):
        run={"path":m.SOURCE_WORKFLOW,"head_branch":"main", "head_repository":{"full_name":m.REPO},
             "status":"completed","conclusion":"success", "created_at":(NOW-timedelta(hours=25)).isoformat()}
        response=Mock();response.json.return_value=run
        with patch.object(m,"github",return_value=response):
            with self.assertRaises(ValueError):m.read_source("100",now=NOW)

    def test_latest_source_ignores_running_foreign_and_stale_runs(self):
        good = {"id": 100, "path": m.SOURCE_WORKFLOW, "head_branch": "main",
                "head_repository": {"full_name": m.REPO}, "status": "completed",
                "conclusion": "failure", "created_at": (NOW-timedelta(hours=1)).isoformat()}
        response = Mock()
        response.json.return_value = {"workflow_runs": [
            dict(good, id=101, status="in_progress"),
            dict(good, id=102, head_branch="other"),
            dict(good, id=103, head_repository={"full_name":"foreign/repo"}),
            dict(good, id=104, created_at=(NOW-timedelta(hours=25)).isoformat()), good]}
        with patch.object(m, "github", return_value=response):
            self.assertEqual(m.latest_source_id(now=NOW), "100")
        response.json.return_value={"workflow_runs":[]}
        with patch.object(m,"github",return_value=response):
            with self.assertRaises(ValueError):m.latest_source_id(now=NOW)

    def test_daily_window_collects_several_provenance_runs_without_old_or_alias_posts(self):
        def row(rid, pid, **extra):
            return dict(status="done",run_id=rid,day="2026-10-30",route="tarladaki",
                        platform="facebook",post_id=pid,**extra)
        state={"entries":{"a":row("100","1000"),"b":row("99","1001"),
                          "old":row("98","1002"),"alias":row("99","1003",duplicate_of_file_id="orig")}}
        recent={"path":m.SOURCE_WORKFLOW,"head_branch":"main","head_repository":{"full_name":m.REPO},
                "status":"completed","conclusion":"success","created_at":(NOW-timedelta(hours=2)).isoformat()}
        def get(path):
            response=Mock()
            response.json.return_value=(dict(recent,created_at=(NOW-timedelta(hours=25)).isoformat())
                                        if path.endswith("98") else recent)
            return response
        with patch.object(m,"github",side_effect=get):
            posts=m.recent_posts(state,"100",actors(),now=NOW)
        self.assertEqual({p["post_id"] for p in posts},{"1000","1001"})
        self.assertEqual({p["source_run_id"] for p in posts},{"100","99"})
        ledger={"schema":1,"actions":{}}
        tasks,_=m.build_plan(posts,actors(),ledger,"200","100",now=NOW)
        self.assertEqual({t["source_run_id"] for t in tasks},{"100","99"})

    def test_unavailable_provenance_stops_batch_before_claiming(self):
        state={"entries":{"a":dict(status="done",run_id="99",day="2026-10-30",
               route="tarladaki",platform="facebook",post_id="123")}}
        with patch.object(m,"github",side_effect=ValueError("unavailable")):
            with self.assertRaises(ValueError):m.recent_posts(state,"100",actors(),now=NOW)

    def test_source_run_timestamp_and_metadata_fail_closed(self):
        good={"path":m.SOURCE_WORKFLOW,"head_branch":"main","head_repository":{"full_name":m.REPO},
              "status":"completed","conclusion":"success","created_at":NOW.isoformat()}
        for value in (None,"bad",NOW.replace(tzinfo=None).isoformat(),(NOW+timedelta(minutes=1)).isoformat()):
            self.assertFalse(m.source_run_valid(dict(good,created_at=value),NOW))
        self.assertFalse(m.source_run_valid(dict(good,head_repository=None),NOW))

    def test_foreign_workflow_artifact_cannot_be_used_as_prior_state(self):
        listing=Mock();listing.json.return_value={"artifacts":[{"id":123,"name":"cross-engagement-result","workflow_run":{"id":200}}]}
        run=Mock();run.json.return_value={"path":"foreign.yml","head_branch":"main","head_repository":{"full_name":m.REPO}}
        with patch.object(m,"github",side_effect=[listing,listing,run]),patch.object(m,"archive") as archive:
            with self.assertRaises(ValueError):m.restore()
            archive.assert_not_called()

    def test_dry_run_creates_plan_but_never_persists_claim_or_posts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.dict(m.os.environ,{"GITHUB_REPOSITORY":m.REPO,"GITHUB_RUN_ID":"200","SOURCE_RUN_ID":"100", "META_CROSS_ENGAGEMENT_ENABLED":"false","ENGAGEMENT_MODE":"apply"}), \
                 patch("sys.argv",["meta_cross_engagement.py","plan"]), \
                 patch.object(m,"STATE",root/"state.json"),patch.object(m,"PLAN",root/"plan.json"), \
                 patch.object(m,"REPORT",root/"report.json"),patch.object(m,"load_meta_auth",return_value={}), \
                 patch.object(m,"accounts",return_value=actors()),patch.object(m,"restore",return_value={"schema":1,"actions":{}}), \
                 patch.object(m,"read_source",return_value={"entries":{"a":dict(status="done",run_id="100",route="tarladaki",platform="facebook",post_id="123")}}), \
                 patch.object(m,"perform") as post:
                m.main()
                self.assertTrue((root/"plan.json").exists())
                self.assertFalse((root/"state.json").exists())
                post.assert_not_called()
                self.assertEqual(json.loads((root/"report.json").read_text())["mode"],"dry_run")


if __name__ == "__main__":
    unittest.main()
