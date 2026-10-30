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
        enabled_for_legacy_repost_tests = patch.dict("os.environ", {"META_CROSS_REPOST_ENABLED": "true"})
        enabled_for_legacy_repost_tests.start()
        self.addCleanup(enabled_for_legacy_repost_tests.stop)

    def test_one_like_prefers_instagram_and_never_reserves_repost(self):
        posts = [dict(platform="facebook", post_id="123", owner="11"),
                 dict(platform="instagram", post_id="456", owner="33")]
        ledger = {"schema": 1, "actions": {}}
        with patch.object(m, "verified_media", return_value=None):
            tasks, report = m.build_one_like(posts, actors(), ledger, "200", "100", now=NOW)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["operation"], "like")
        self.assertEqual(tasks[0]["platform"], "instagram")
        self.assertNotEqual(tasks[0]["actor"], tasks[0]["owner"])
        self.assertEqual(len(ledger["actions"]), 1)
        self.assertTrue(all(x["operation"] != "repost" for x in tasks))

    def test_one_like_respects_prior_receipt_and_permission(self):
        t = task("like", "instagram", "44", "33")
        ledger = reserved(t)
        posts = [dict(platform="instagram", post_id="123", owner="33")]
        with patch.object(m, "verified_media", return_value=None) as check:
            tasks, report = m.build_one_like(posts, actors(), ledger, "201", "100", now=NOW)
        self.assertEqual(tasks, [])
        check.assert_not_called()
        self.assertEqual(len(ledger["actions"]), 1)

    def test_one_like_requires_preflight_success_and_no_meta_writes(self):
        posts = [dict(platform="instagram", post_id="123", owner="33")]
        ledger = {"schema": 1, "actions": {}}
        with (patch.object(m, "verified_media", side_effect=ValueError("bad owner")),
              patch.object(m, "perform") as writer):
            tasks, report = m.build_one_like(posts, actors(), ledger, "200", "100", now=NOW)
            writer.assert_not_called()
        self.assertEqual(tasks, [])
        self.assertEqual(ledger["actions"], {})

    def test_owner_disabled_repost_blocks_plan_execution_and_direct_perform(self):
        t = task("repost")
        with patch.dict("os.environ", {"META_CROSS_REPOST_ENABLED": "false"}):
            ledger = {"schema": 1, "actions": {}}
            jobs, report = m.build_plan([dict(platform="facebook", post_id="123", owner="11")],
                                         actors(), ledger, "200", "100", now=NOW)
            self.assertFalse(any(x["operation"] == "repost" for x in jobs))
            self.assertTrue(any(x["status"] == "disabled_by_owner" for x in report))
            state = reserved(t)
            with patch.object(m, "perform") as post:
                m.execute([t], actors(), state, "200", persist=Mock(), sleep=Mock())
                post.assert_not_called()
            self.assertEqual(state["actions"][m.key(t)]["status"], "disabled_by_owner")
            with self.assertRaises(ValueError):
                m.perform(t, actors()[("facebook", "22")], "https://www.facebook.com/watch/?v=123")

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

    def test_video_ownership_does_not_request_pagepost_permalink_field(self):
        with patch.object(m,"graph",return_value={"id":"123","from":{"id":"11"}}) as graph:
            self.assertEqual(m.verified_media(task("repost"),actors()),"https://www.facebook.com/watch/?v=123")
            self.assertEqual(graph.call_args.args[3],{"fields":"id,from"})
        with patch.object(m,"graph",return_value={"id":"123","from":{"id":"99"}}):
            with self.assertRaises(ValueError):m.verified_media(task("repost"),actors())
        with patch.object(m,"graph",return_value={"id":"999","from":{"id":"11"}}):
            with self.assertRaises(ValueError):m.verified_media(task("repost"),actors())

    def test_video_link_is_constructed_only_from_verified_id_not_response_url(self):
        with patch.object(m,"graph",return_value={"id":"123","from":{"id":"11"},"permalink_url":"https://evil.test/"}):
            self.assertEqual(m.verified_media(task("repost"),actors()),"https://www.facebook.com/watch/?v=123")

    def test_only_audited_no_post_preflight_can_be_rechecked_once(self):
        t=task("repost")
        for status in ("source_or_permission_unverified","uncertain","accepted","rejected","reserved"):
            ledger=reserved(t)
            prior=ledger["actions"][m.key(t)]
            prior.update(status=status,run_id="41044986946")
            planned,_=m.build_plan([dict(platform="facebook",post_id="123",owner="11")],actors(),ledger,"201","100",now=NOW)
            selected=[p for p in planned if m.key(p)==m.key(t)]
            self.assertEqual(len(selected),int(status=="source_or_permission_unverified"))
            if selected:
                self.assertEqual(ledger["actions"][m.key(t)]["source_check_version"],2)
                ledger["actions"][m.key(t)]["status"]="source_or_permission_unverified"
                again,_=m.build_plan([dict(platform="facebook",post_id="123",owner="11")],actors(),ledger,"202","100",now=NOW)
                self.assertFalse(any(m.key(p)==m.key(t) for p in again))

    def test_source_owner_check_is_cached_without_skipping_actor_posts(self):
        first=task("repost");second=dict(first,actor="55")
        aa=actors()
        aa[("facebook","55")]=dict(aa[("facebook","22")],id="55")
        ledger=reserved(first);ledger["actions"].update(reserved(second)["actions"])
        with patch.object(m,"verified_media",return_value="https://www.facebook.com/watch/?v=123") as check, \
             patch.object(m,"perform",return_value={"api_ack":True,"share_post_id":"9"}) as post:
            m.execute([first,second],aa,ledger,"200",persist=Mock(),sleep=Mock())
            self.assertEqual(check.call_count,1)
            self.assertEqual(post.call_count,2)

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

    def test_policy_block_stops_other_actors_without_more_posts(self):
        one=task("repost");two=dict(one,actor="11")
        ledger=reserved(one);ledger["actions"].update(reserved(two)["actions"])
        with patch.object(m,"verified_media",return_value="https://www.facebook.com/watch/?v=123"), \
             patch.object(m,"perform",side_effect=m.GraphFailure(400,368,definite=True)) as post:
            m.execute([one,two],actors(),ledger,"200",persist=Mock(),sleep=Mock())
            post.assert_called_once()
        self.assertEqual(ledger["actions"][m.key(two)]["status"],"provider_restriction_hold")
        self.assertEqual(ledger["provider_holds"]["facebook/repost"]["graph_code"],368)

    def test_prior_368_hold_survives_pruning_and_blocks_new_sources(self):
        old=task("repost");ledger=reserved(old)
        record=ledger["actions"][m.key(old)]
        record.update(status="rejected",graph_code=368,at=(NOW-timedelta(hours=49)).isoformat())
        posts=[dict(platform="facebook",post_id="456",owner="11")]
        planned,report=m.build_plan(posts,actors(),ledger,"201","100",now=NOW)
        self.assertFalse(any(t["operation"]=="repost" for t in planned))
        self.assertTrue(any(r["status"]=="provider_restriction_hold" for r in report))
        self.assertNotIn(m.key(old),ledger["actions"])
        planned,_=m.build_plan(posts,actors(),ledger,"202","100",now=NOW+timedelta(days=3))
        self.assertFalse(any(t["operation"]=="repost" for t in planned))
        self.assertIn("facebook/repost",ledger["provider_holds"])

    def test_malformed_provider_hold_state_cannot_be_reset(self):
        with self.assertRaises(ValueError):
            m.build_plan([],actors(),{"schema":1,"actions":{},"provider_holds":[]},"200","100",now=NOW)

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
