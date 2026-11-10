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
    def test_known_meta_token_expiry_has_safe_distinct_reason(self):
        reason = m.safe_hold_reason(RuntimeError(
            "Meta hesap erişimi reddedildi (HTTP 401, kod 190, alt_kod 463)"))
        self.assertEqual(reason, "meta_user_token_expired")
        # Do not misdiagnose revoked or transient API failures as expiry.
        self.assertEqual(m.safe_hold_reason(RuntimeError(
            "Meta hesap erişimi reddedildi (HTTP 401, kod 190, alt_kod 458)")),
            "read_or_runtime_failure")
        self.assertEqual(m.safe_hold_reason(RuntimeError(
            "token-value confidential secret: abcdef")), "read_or_runtime_failure")

    def test_failed_plan_preserves_redacted_audit_without_any_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "report.json"
            with patch.object(m, "REPORT", destination):
                reason = m.preserve_failed_audit(ValueError("no verified enabled accounts"))
                report = json.loads(destination.read_text(encoding="utf-8"))
                self.assertEqual(reason, "no_verified_enabled_accounts")
                self.assertEqual(report["runtime_status"], "held")
                self.assertFalse(report["writes_retried"])
                self.assertEqual(report["runtime_reason_code"], reason)
                self.assertFalse(m.STATE.exists() and m.STATE == destination)

    def test_unknown_exception_text_not_leaked_to_failure_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "report.json"
            destination.write_text('{"planned": 0}', encoding="utf-8")
            with patch.object(m, "REPORT", destination):
                reason = m.preserve_failed_audit(ValueError("private access token in provider message"))
                report_text = destination.read_text(encoding="utf-8")
                self.assertEqual(reason, "preflight_validation_failed")
                self.assertNotIn("private access token", report_text)
                self.assertEqual(json.loads(report_text)["planned"], 0)

    def setUp(self):
        p = patch.object(m, "account_enabled", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        enabled_for_legacy_repost_tests = patch.dict("os.environ", {"META_CROSS_REPOST_ENABLED": "true"})
        enabled_for_legacy_repost_tests.start()
        self.addCleanup(enabled_for_legacy_repost_tests.stop)

    def test_like_coverage_only_accepted_identity_matched_and_permissioned(self):
        aa = actors()
        ledger = {"schema": 1, "actions": {}}
        accepted = task("like", "facebook", "22", "11")
        ledger["actions"][m.key(accepted)] = {
            **accepted, "status": "accepted", "api_ack": True,
            "run_id": "200", "at": NOW.isoformat()
        }
        pending = task("like", "instagram", "44", "33")
        ledger["actions"][m.key(pending)] = {
            **pending, "status": "reserved", "api_ack": False,
            "run_id": "200", "at": NOW.isoformat()
        }
        other = task("like", "instagram", "33", "44")
        aa[("instagram", "33")]["grants"] = set()
        ledger["actions"][m.key(other)] = {
            **other, "status": "accepted", "api_ack": True,
            "run_id": "200", "at": NOW.isoformat()
        }
        wrong = task("like", "facebook", "999", "11")
        ledger["actions"][m.key(wrong)] = {
            **wrong, "status": "accepted", "api_ack": True,
            "run_id": "200", "at": NOW.isoformat()
        }
        health = m.verified_like_coverage(aa, ledger)
        self.assertEqual(health["facebook"]["confirmed_actor_routes"], ["Beyinsiz Penguen"])
        self.assertEqual(health["facebook"]["confirmed_target_routes"], ["Tarladaki Fasulye"])
        self.assertEqual(health["facebook"]["confirmed_like_count_in_retained_ledger"], 1)
        self.assertEqual(health["instagram"]["confirmed_actor_routes"], [])
        self.assertEqual(health["instagram"]["permission_missing_actor_routes"],
                         ["Tarladaki Fasulye"])
        self.assertEqual(health["instagram"]["eligible_routes_without_confirmed_like"],
                         ["Beyinsiz Penguen"])
        self.assertNotIn("private-token", json.dumps(health))
        self.assertNotIn('"999"', json.dumps(health))

    def test_owner_like_counts_only_after_verifiable_api_ack(self):
        aa = actors()
        own = task("like", "instagram", "33", "33")
        ledger = {"schema": 1, "actions": {m.key(own): {
            **own, "run_id": "500", "at": NOW.isoformat(),
            "status": "reserved", "api_ack": False,
        }}}
        health = m.verified_like_coverage(aa, ledger)["instagram"]
        self.assertEqual(health["confirmed_self_like_count_in_retained_ledger"], 0)
        ledger["actions"][m.key(own)].update(status="accepted", api_ack=True)
        health = m.verified_like_coverage(aa, ledger)["instagram"]
        self.assertEqual(health["confirmed_self_like_count_in_retained_ledger"], 1)
        self.assertEqual(health["confirmed_cross_like_count_in_retained_ledger"], 0)
        self.assertEqual(health["confirmed_like_count_in_retained_ledger"], 1)

    def test_like_coverage_does_not_count_unverified_history_as_success(self):
        aa = actors()
        bogus = task("like", "facebook", "22", "11")
        ledger = {"schema": 1, "actions": {m.key(bogus):
                  {**bogus, "status": "accepted", "api_ack": False}}}
        health = m.verified_like_coverage(aa, ledger)
        self.assertEqual(health["facebook"]["confirmed_actor_routes"], [])
        self.assertIn("Beyinsiz Penguen",
                      health["facebook"]["eligible_routes_without_confirmed_like"])

    def test_inventory_reports_verified_routes_separately_from_platforms(self):
        aa = actors()
        aa[("facebook", "55")] = dict(platform="facebook", id="55", name="ToonZone",
            grants=set(GRANTS), token="private-token", owner_page="55")
        inventory = m.verified_inventory(aa)
        self.assertEqual(inventory["verified_account_routes"], 3)
        self.assertEqual(inventory["verified_platform_identities"], 5)
        self.assertEqual(inventory["verified_facebook_identities"], 3)
        self.assertEqual(inventory["verified_instagram_identities"], 2)
        self.assertEqual(inventory["verified_account_names"],
            ["Beyinsiz Penguen", "Tarladaki Fasulye", "ToonZone"])
        self.assertNotIn("private-token", json.dumps(inventory))
        self.assertNotIn('"55"', json.dumps(inventory))

    def test_toonzone_focus_scopes_read_only_report_to_verified_sources(self):
        aa = actors()
        aa[("instagram", "55")] = dict(platform="instagram", id="55",
            name="ToonZone", grants=set(GRANTS), token="secret", owner_page="11")
        posts = [dict(platform="instagram", post_id="123", owner="55"),
                 dict(platform="facebook", post_id="456", owner="11"),
                 dict(platform="instagram", post_id="789", owner="33")]
        chosen, info = m.scope_audit_posts(posts, aa, "ToonZone")
        self.assertEqual(chosen, posts[:1])
        self.assertEqual(info["focus_account"], "ToonZone")
        self.assertEqual(info["other_source_posts_excluded"], 2)
        self.assertEqual(info["candidate_review_accounts"],
                         ["Beyinsiz Penguen", "Tarladaki Fasulye"])
        self.assertNotIn("secret", json.dumps(info))
        with self.assertRaises(ValueError):
            m.scope_audit_posts(posts, aa, "unknown")

    def test_toonzone_focus_fails_closed_on_apply(self):
        with patch.dict(m.os.environ, {"GITHUB_REPOSITORY": m.REPO,
                "GITHUB_RUN_ID": "200", "SOURCE_RUN_ID": "100",
                "ENGAGEMENT_MODE": "apply", "META_CROSS_ENGAGEMENT_ENABLED": "true",
                "META_AUDIT_FOCUS": "ToonZone"}), \
             patch("sys.argv", ["meta_cross_engagement.py", "plan"]), \
             patch.object(m, "accounts") as accounts:
            with self.assertRaisesRegex(ValueError, "read-only"):
                m.main()
            accounts.assert_not_called()

    def test_inventory_flags_unverified_routes_not_all_platforms(self):
        inventory = m.verified_inventory(actors())
        self.assertEqual(inventory["verified_account_routes"], 2)
        self.assertIn("ToonZone", inventory["unverified_account_routes"])
        self.assertIn("ToonZone", inventory["facebook_unverified_routes"])
        self.assertIn("ToonZone", inventory["instagram_unverified_routes"])

    def test_fair_selector_considers_facebook_after_instagram_attempt(self):
        aa = actors()
        previous = task("like", "instagram", "44", "33")
        previous["post_id"] = "222"
        ledger = reserved(previous)
        ledger["actions"][m.key(previous)]["status"] = "accepted"
        ledger["actions"][m.key(previous)]["api_ack"] = True
        posts = [dict(platform="instagram", post_id="456", owner="33"),
                 dict(platform="facebook", post_id="123", owner="11")]
        with patch.object(m, "verified_media", return_value=None), \
             patch.dict(m.os.environ, {"META_CROSS_REPOST_ENABLED": "false"}):
            tasks, _ = m.build_one_like(posts, aa, ledger, "201", "100", now=NOW)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["platform"], "facebook")
        self.assertNotEqual(tasks[0]["owner"], tasks[0]["actor"])

    def test_fair_selector_rotates_to_actor_without_recent_activity(self):
        aa = actors()
        aa[("instagram", "55")] = dict(platform="instagram", id="55",
            name="ToonZone", grants=set(GRANTS), token="token", owner_page="55")
        previous = task("like", "instagram", "33", "55")
        previous["post_id"] = "222"
        ledger = reserved(previous)
        ledger["actions"][m.key(previous)]["status"] = "accepted"
        ledger["actions"][m.key(previous)]["api_ack"] = True
        posts = [dict(platform="instagram", post_id="999", owner="55")]
        with patch.object(m, "verified_media", return_value=None):
            tasks, _ = m.build_one_like(posts, aa, ledger, "201", "100", now=NOW)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["actor"], "44")

    def test_invalid_source_spends_one_check_not_one_per_actor(self):
        aa = actors()
        aa[("instagram", "55")] = dict(platform="instagram", id="55",
            name="ToonZone", grants=set(GRANTS), token="token", owner_page="55")
        posts = [dict(platform="instagram", post_id="999", owner="55"),
                 dict(platform="instagram", post_id="456", owner="33")]
        checked = []
        def preflight(task, accounts):
            checked.append(task["post_id"])
            if task["post_id"] == "999":
                raise ValueError("source_owner_missing")
        with patch.object(m, "verified_media", side_effect=preflight):
            tasks, _ = m.build_one_like(posts, aa, {"schema": 1, "actions": {}},
                                        "200", "100", now=NOW)
        self.assertEqual(checked, ["999", "456"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["post_id"], "456")

    def test_scheduled_dedupe_outlives_three_day_recent_post_window(self):
        previous = task()
        ledger = reserved(previous)
        ledger["actions"][m.key(previous)]["at"] = (NOW-timedelta(hours=60)).isoformat()
        ledger["actions"][m.key(previous)]["status"] = "accepted"
        tasks, report = m.build_plan([dict(platform="facebook", post_id="123", owner="11")],
                                     actors(), ledger, "201", "100", now=NOW)
        self.assertIn(m.key(previous), ledger["actions"])
        self.assertNotIn(previous, tasks)
        self.assertIn("already_recorded", {x["status"] for x in report})

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

    def test_definite_cross_page_permission_denial_holds_original_post_only(self):
        first = task("like", actor="22", owner="11")
        next_page = dict(first, actor="55")
        owner_self = dict(first, actor="11")
        aa = actors()
        aa[("facebook", "55")] = dict(aa[("facebook", "22")], id="55")
        ledger = reserved(first)
        ledger["actions"].update(reserved(next_page)["actions"])
        ledger["actions"].update(reserved(owner_self)["actions"])
        with patch.object(m, "verified_media", return_value=None), \
             patch.object(m, "perform", side_effect=[
                 m.GraphFailure(403, 200, definite=True), {"api_ack": True}
             ]) as post:
            m.execute([first, next_page, owner_self], aa, ledger, "200",
                      persist=Mock(), sleep=Mock())
            self.assertEqual(post.call_count, 2)
        hold_key = "facebook/like/cross_post/123"
        self.assertIn(hold_key, ledger["provider_holds"])
        self.assertEqual(ledger["provider_holds"][hold_key]["http_status"], 403)
        self.assertEqual(ledger["actions"][m.key(first)]["status"], "rejected")
        self.assertEqual(ledger["actions"][m.key(next_page)]["status"], "provider_permission_hold")
        self.assertEqual(ledger["actions"][m.key(owner_self)]["status"], "accepted")
        self.assertNotIn("facebook/like", ledger["provider_holds"])

        # The 7-day ledger cleanup must never reauthorize a denied target.
        ledger["actions"][m.key(first)]["at"] = (NOW - timedelta(days=9)).isoformat()
        ledger["actions"][m.key(next_page)]["at"] = (NOW - timedelta(days=9)).isoformat()
        ledger["actions"][m.key(owner_self)]["at"] = (NOW - timedelta(days=9)).isoformat()
        with patch.dict(m.os.environ, {"META_CROSS_REPOST_ENABLED": "false"}):
            planned, report = m.build_plan(
                [dict(platform="facebook", post_id="123", owner="11")],
                aa, ledger, "201", "100", now=NOW)
        likes = [row for row in planned if row["operation"] == "like"]
        self.assertEqual([row["actor"] for row in likes], ["11"])
        self.assertEqual(sum(r["status"] == "provider_permission_hold" for r in report), 2)
        with patch.dict(m.os.environ, {"META_CROSS_REPOST_ENABLED": "false"}):
            other, _ = m.build_plan(
                [dict(platform="facebook", post_id="124", owner="11")],
                aa, ledger, "202", "100", now=NOW)
        self.assertEqual({a["actor"] for a in other if a["operation"] == "like"},
                         {"11", "22", "55"})

    def test_provider_denial_hold_never_assumed_for_self_like_or_other_code(self):
        for actor, http, code in (("11", 403, 200), ("22", 400, 100),
                                  ("22", 503, 200)):
            t = task(actor=actor)
            ledger = reserved(t)
            with patch.object(m, "verified_media", return_value=None), \
                 patch.object(m, "perform",
                              side_effect=m.GraphFailure(http, code, definite=True)):
                m.execute([t], actors(), ledger, "200", persist=Mock(), sleep=Mock())
            self.assertNotIn("facebook/like/cross_post/123",
                             ledger.get("provider_holds", {}))

    def test_migrated_403_200_hold_survives_old_receipt_pruning(self):
        t = task()
        ledger = reserved(t)
        ledger["actions"][m.key(t)].update(
            status="rejected", graph_code=200, http_status=403,
            at=(NOW - timedelta(days=8)).isoformat())
        with patch.dict(m.os.environ, {"META_CROSS_REPOST_ENABLED": "false"}):
            planned, report = m.build_plan(
                [dict(platform="facebook", post_id="123", owner="11")],
                actors(), ledger, "201", "100", now=NOW)
        self.assertTrue(any(row["status"] == "provider_permission_hold" for row in report))
        self.assertIn("facebook/like/cross_post/123", ledger["provider_holds"])
        self.assertNotIn(m.key(t), ledger["actions"])
        self.assertFalse(any(a["actor"] == "22" and a["operation"] == "like" for a in planned))

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
        record.update(status="rejected",graph_code=368,at=(NOW-timedelta(days=8)).isoformat())
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

    def fallback_fixture(self):
        run = {"id": 101, "path": m.SOURCE_WORKFLOW, "head_branch": "main",
               "head_repository": {"full_name": m.REPO}, "status": "completed",
               "conclusion": "failure", "created_at": (NOW-timedelta(minutes=10)).isoformat()}
        earlier = dict(run, id=100, conclusion="success",
                       created_at=(NOW-timedelta(hours=1)).isoformat())
        conclusions = {
            "Fail early on invalid Meta credentials before any video work": "success",
            "Install media runtime only after Meta preflight passed": "failure",
            "Verify state, account and caption safety without API writes": "skipped",
            "Check public folders, captions, histories and prepare intent": "skipped",
            "Prepare verified YouTube channel intents for current plans": "skipped",
            "Persist intent before any Meta upload": "skipped",
            "Publish explicitly planned Meta videos": "skipped",
            "Publish planned YouTube videos with archived intent": "skipped",
        }
        return {
            "actions/workflows/public_link_schedule.yml/runs?branch=main&per_page=30": {
                "workflow_runs": [earlier, run]},
            "actions/runs/101/artifacts?per_page=100": {"total_count": 0, "artifacts": []},
            "actions/runs/100/artifacts?per_page=100": {"total_count": 1, "artifacts": [
                {"id": 900, "name": "link-state-result", "expired": False}]},
            "actions/runs/101/jobs?per_page=100": {"total_count": 1, "jobs": [{
                "name": "meta", "run_id": 101, "status": "completed", "conclusion": "failure",
                "steps": [{"name": name, "status": "completed", "conclusion": conclusion}
                          for name, conclusion in conclusions.items()]}]},
        }

    def choose_fallback(self, data, *, allow=True):
        visited, skipped = [], []
        def get(path):
            visited.append(path)
            response = Mock()
            value = data[path]
            if isinstance(value, Exception):
                raise value
            response.json.return_value = value
            return response
        with patch.object(m, "github", side_effect=get):
            rid = m.latest_source_id(now=NOW, allow_prestate_fallback=allow, skipped_runs=skipped)
        return rid, skipped, visited

    def test_readonly_fallback_requires_proven_prestate_failure_and_reports_skipped_run(self):
        data = self.fallback_fixture()
        rid, skipped, visited = self.choose_fallback(data)
        self.assertEqual(rid, "100")
        self.assertEqual(skipped, ["101"])
        self.assertIn("actions/runs/101/jobs?per_page=100", visited)
        # Default selection, used by apply/manual paths, retains newest then fails closed.
        rid, skipped, visited = self.choose_fallback(data, allow=False)
        self.assertEqual(rid, "101")
        self.assertEqual(skipped, [])
        self.assertEqual(len(visited), 1)

    def test_modern_matrix_no_post_verify_failure_can_be_skipped_readonly(self):
        data = self.fallback_fixture()
        stages = data["actions/runs/101/jobs?per_page=100"]["jobs"][0]["steps"]
        for row in stages:
            if row["name"] == "Install media runtime only after Meta preflight passed":
                row["conclusion"] = "success"
            if row["name"] == "Verify state, account and caption safety without API writes":
                row["conclusion"] = "failure"
        data["actions/runs/101/jobs?per_page=100"]["jobs"][0]["name"] = "meta (film)"
        data["actions/runs/101/jobs?per_page=100"]["jobs"].append({
            "name": "merge-account-receipts", "status": "completed",
            "conclusion": "failure", "run_id": 101, "steps": []})
        data["actions/runs/101/jobs?per_page=100"]["total_count"] = 2
        rid, skipped, visited = self.choose_fallback(data)
        self.assertEqual(rid, "100")
        self.assertEqual(skipped, ["101"])

        for change in ("plan_ran", "intent_started", "publish_started", "merge_success",
                       "wrong_job", "wrong_archive_count"):
            case = copy.deepcopy(data)
            job = case["actions/runs/101/jobs?per_page=100"]["jobs"][0]
            byname = {x["name"]: x for x in job["steps"]}
            if change == "plan_ran":
                byname["Check public folders, captions, histories and prepare intent"]["conclusion"] = "success"
            if change == "intent_started":
                byname["Persist intent before any Meta upload"]["conclusion"] = "success"
            if change == "publish_started":
                byname["Publish explicitly planned Meta videos"]["conclusion"] = "success"
            if change == "merge_success":
                case["actions/runs/101/jobs?per_page=100"]["jobs"][1]["conclusion"] = "success"
            if change == "wrong_job":
                job["name"] = "meta (foreign)"
            if change == "wrong_archive_count":
                case["actions/runs/101/jobs?per_page=100"]["total_count"] = 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.choose_fallback(case)

    def test_fallback_never_skips_expired_duplicate_or_intent_artifact(self):
        for artifacts in (
            [{"name": "link-state-result", "expired": True}],
            [{"name": "link-state-result", "expired": False}] * 2,
            [{"name": "link-state-intent", "expired": False}],
        ):
            data = self.fallback_fixture()
            data["actions/runs/101/artifacts?per_page=100"] = {
                "total_count": len(artifacts), "artifacts": artifacts}
            with self.subTest(artifacts=artifacts), self.assertRaises(ValueError):
                self.choose_fallback(data)

    def test_fallback_does_not_hide_auth_malformed_or_incomplete_artifact_reads(self):
        for body in (ValueError("GitHub read failed"), None, {"artifacts": []},
                     {"total_count": 1, "artifacts": []},
                     {"total_count": 1, "artifacts": [None]}):
            data = self.fallback_fixture()
            data["actions/runs/101/artifacts?per_page=100"] = body
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.choose_fallback(data)

    def test_fallback_never_skips_unknown_or_publishing_job_states(self):
        base = self.fallback_fixture()
        for mutation in ("missing_setup", "setup_success", "plan_started", "publish_started",
                         "wrong_job", "wrong_run", "extra_job", "missing_steps", "jobs_read_failed"):
            data = copy.deepcopy(base)
            job = data["actions/runs/101/jobs?per_page=100"]["jobs"][0]
            if mutation == "missing_setup": job["steps"].pop(1)
            if mutation == "setup_success": job["steps"][1]["conclusion"] = "success"
            if mutation == "plan_started": job["steps"][3]["conclusion"] = "failure"
            if mutation == "publish_started": job["steps"][6]["conclusion"] = "success"
            if mutation == "wrong_job": job["name"] = "foreign"
            if mutation == "wrong_run": job["run_id"] = 999
            if mutation == "extra_job": data["actions/runs/101/jobs?per_page=100"]["total_count"] = 2
            if mutation == "missing_steps": job["steps"] = None
            if mutation == "jobs_read_failed":
                data["actions/runs/101/jobs?per_page=100"] = ValueError("GitHub read failed")
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.choose_fallback(data)

    def test_main_allows_fallback_only_for_scheduled_readonly_recent_latest(self):
        for mode, event, scope, source, allowed in (
            ("dry_run", "schedule", "recent_window", "latest", True),
            ("apply", "schedule", "recent_window", "latest", False),
            ("dry_run", "push", "recent_window", "latest", False),
            ("dry_run", "workflow_dispatch", "recent_window", "latest", False),
            ("dry_run", "schedule", "single_run", "latest", False),
            ("dry_run", "schedule", "recent_window", "100", False),
        ):
            with self.subTest(mode=mode, event=event, scope=scope, source=source), \
                 patch.dict(m.os.environ, {"GITHUB_REPOSITORY": m.REPO, "GITHUB_RUN_ID": "200",
                    "SOURCE_RUN_ID": source, "ENGAGEMENT_MODE": mode, "GITHUB_EVENT_NAME": event,
                    "ENGAGEMENT_SCOPE": scope, "META_CROSS_ENGAGEMENT_ENABLED": "true",
                    "META_AUDIT_FOCUS": ""}), \
                 patch("sys.argv", ["meta_cross_engagement.py", "plan"]), \
                 patch.object(m, "load_meta_auth", return_value={}), \
                 patch.object(m, "accounts", return_value=actors()), \
                 patch.object(m, "latest_source_id", return_value="100") as choose, \
                 patch.object(m, "restore", return_value={"schema": 1, "actions": {}}), \
                 patch.object(m, "read_source", side_effect=ValueError("stop before plan")), \
                 patch.object(m, "save") as save, patch.object(m, "perform") as post:
                with self.assertRaisesRegex(ValueError, "stop before plan"):
                    m.main()
                if source == "latest":
                    self.assertEqual(choose.call_args.kwargs["allow_prestate_fallback"], allowed)
                else:
                    choose.assert_not_called()
                save.assert_not_called()
                post.assert_not_called()

    def test_focused_readonly_health_gets_fail_closed_source_fallback(self):
        with patch.dict(m.os.environ, {
                "GITHUB_REPOSITORY": m.REPO, "GITHUB_RUN_ID": "200",
                "SOURCE_RUN_ID": "latest", "ENGAGEMENT_MODE": "dry_run",
                "GITHUB_EVENT_NAME": "workflow_dispatch", "ENGAGEMENT_SCOPE": "recent_window",
                "META_CROSS_ENGAGEMENT_ENABLED": "false",
                "META_AUDIT_FOCUS": "Film Mağarası"}), \
             patch("sys.argv", ["meta_cross_engagement.py", "plan"]), \
             patch.object(m, "load_meta_auth", return_value={}), \
             patch.object(m, "accounts", return_value=actors()), \
             patch.object(m, "latest_source_id", return_value="100") as choose, \
             patch.object(m, "restore", return_value={"schema": 1, "actions": {}}), \
             patch.object(m, "read_source", side_effect=ValueError("stopped before plan")), \
             patch.object(m, "save") as save, patch.object(m, "perform") as post:
            with self.assertRaisesRegex(ValueError, "stopped before plan"):
                m.main()
            self.assertTrue(choose.call_args.kwargs["allow_prestate_fallback"])
            save.assert_not_called()
            post.assert_not_called()

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


    def test_scheduled_live_run_with_no_eligible_likes_is_safe_no_op(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = {
                "GITHUB_REPOSITORY": m.REPO,
                "GITHUB_RUN_ID": "200",
                "SOURCE_RUN_ID": "latest",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_EVENT_NAME": "schedule",
                "ENGAGEMENT_SCOPE": "recent_window",
                "ENGAGEMENT_MODE": "single_like",
                "META_CROSS_ENGAGEMENT_ENABLED": "true",
                "META_AUDIT_FOCUS": "",
            }
            with patch.dict(m.os.environ, env, clear=True), \
                 patch.object(m, "STATE", root / "engagement.json"), \
                 patch.object(m, "PLAN", root / "plan.json"), \
                 patch.object(m, "REPORT", root / "report.json"), \
                 patch("sys.argv", ["meta_cross_engagement.py", "plan"]), \
                 patch.object(m, "load_meta_auth", return_value={}), \
                 patch.object(m, "accounts", return_value=actors()), \
                 patch.object(m, "latest_source_id", return_value="100") as choose, \
                 patch.object(m, "restore", return_value={"schema": 1, "actions": {}}), \
                 patch.object(m, "read_source", return_value={"entries": {}}), \
                 patch.object(m, "perform") as post:
                m.main()
                self.assertFalse(choose.call_args.kwargs["allow_prestate_fallback"])
                self.assertEqual(json.loads((root / "plan.json").read_text()), [])
                self.assertEqual(json.loads((root / "report.json").read_text())["mode"], "apply")
                self.assertTrue((root / "engagement.json").exists())
                with patch("sys.argv", ["meta_cross_engagement.py", "execute"]):
                    m.main()
                post.assert_not_called()

    def test_scheduled_toonzone_like_one_per_run_with_verified_actor(self):
        aa = actors()
        aa[("instagram", "55")] = dict(platform="instagram", id="55", name="ToonZone",
                                        grants=set(GRANTS), token="token", owner_page="11")
        posts = [dict(platform="instagram", post_id="111", owner="33"),
                 dict(platform="instagram", post_id="999", owner="55")]
        ledger = {"schema": 1, "actions": {}}
        with patch.object(m, "verified_media", return_value=None), \
             patch.dict(m.os.environ, {"META_CROSS_REPOST_ENABLED": "false"}):
            planned, _ = m.build_one_like(posts, aa, ledger, "200", "100", now=NOW)
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["operation"], "like")
        self.assertEqual(planned[0]["owner"], "55")
        self.assertNotEqual(planned[0]["actor"], planned[0]["owner"])
        self.assertFalse(any(t["operation"] in ("save", "repost") for t in planned))


    def test_account_batch_rotates_one_target_but_covers_all_native_platform_posts(self):
        aa = actors()
        for platform, identity in (("facebook", "55"), ("instagram", "66")):
            aa[(platform, identity)] = dict(platform=platform, id=identity,
                name="ToonZone", grants=set(GRANTS), token="token", owner_page="55")
        posts = [
            dict(platform="instagram", post_id="901", owner="66"),
            dict(platform="instagram", post_id="902", owner="66"),
            dict(platform="facebook", post_id="903", owner="55"),
            dict(platform="facebook", post_id="904", owner="11"),
        ]
        ledger = {"schema": 1, "actions": {}}
        with patch.object(m, "verified_media", return_value=None) as check, \
             patch.dict(m.os.environ, {"META_CROSS_REPOST_ENABLED": "false"}):
            planned, _ = m.build_account_batch(posts, aa, ledger, "200", "100", now=NOW)
        self.assertEqual(len(planned), 9)
        self.assertEqual(check.call_count, 3)
        self.assertEqual({t["operation"] for t in planned}, {"like"})
        self.assertEqual({t["owner"] for t in planned}, {"55", "66"})
        self.assertEqual({t["platform"] for t in planned}, {"facebook", "instagram"})
        self.assertEqual(sum(t["actor"] == t["owner"] for t in planned), 3)
        self.assertEqual(len(ledger["actions"]), len(planned))
        self.assertTrue(all(x["status"] == "reserved" for x in ledger["actions"].values()))
        # Intent/accepted receipts are never replayed; next tick selects another account.
        for record in ledger["actions"].values():
            record.update(status="accepted", api_ack=True)
        with patch.object(m, "verified_media", return_value=None):
            next_batch, _ = m.build_account_batch(posts, aa, ledger, "201", "100",
                                                   now=NOW + timedelta(minutes=15))
        self.assertEqual(len(next_batch), 3)
        self.assertEqual({x["owner"] for x in next_batch}, {"11"})
        self.assertEqual(sum(x["actor"] == x["owner"] for x in next_batch), 1)

    def test_exact_rolling_24h_uses_meta_publication_time_for_both_platforms(self):
        for platform, owner, actor in (("facebook", "11", "22"),
                                       ("instagram", "33", "44")):
            t = task("like", platform, actor, owner)
            stamp_key = "created_time" if platform == "facebook" else "timestamp"
            owner_key = "from" if platform == "facebook" else "owner"
            base = {"id": "123", owner_key: {"id": owner}}
            if platform == "instagram":
                base["media_type"] = "VIDEO"
            for age, accepted in ((timedelta(hours=23), True),
                                  (timedelta(hours=24), True),
                                  (timedelta(hours=24, seconds=1), False),
                                  (-timedelta(seconds=1), False)):
                payload = dict(base, **{stamp_key: (NOW - age).isoformat()})
                with self.subTest(platform=platform, age=str(age)), \
                     patch.object(m, "graph", return_value=payload) as graph:
                    if accepted:
                        m.verified_media(t, actors(), recent_now=NOW)
                    else:
                        with self.assertRaisesRegex(ValueError, "outside_recent_24h_window"):
                            m.verified_media(t, actors(), recent_now=NOW)
                    self.assertIn(stamp_key, graph.call_args.args[3]["fields"])
            with patch.object(m, "graph", return_value=base):
                with self.assertRaisesRegex(ValueError, "invalid timestamp"):
                    m.verified_media(t, actors(), recent_now=NOW)

    def test_account_batch_fails_closed_for_post_older_than_24h(self):
        aa = actors()
        post = {"platform": "instagram", "post_id": "123", "owner": "33"}
        ledger = {"schema": 1, "actions": {}}
        body = {"id": "123", "owner": {"id": "33"}, "media_type": "VIDEO",
                "timestamp": (NOW - timedelta(hours=25)).isoformat()}
        with patch.object(m, "graph", return_value=body), \
             patch.object(m, "perform") as writer:
            planned, report = m.build_account_batch([post], aa, ledger,
                                                    "200", "100", now=NOW)
        writer.assert_not_called()
        self.assertEqual(planned, [])
        self.assertEqual(ledger["actions"], {})
        self.assertIn("source_preflight_failed", {r["status"] for r in report})

    def test_account_batch_skips_invalid_source_and_does_not_write_in_plan(self):
        aa = actors()
        aa[("instagram", "55")] = dict(platform="instagram", id="55",
            name="ToonZone", grants=set(GRANTS), token="token", owner_page="55")
        posts = [dict(platform="instagram", post_id="101", owner="55"),
                 dict(platform="instagram", post_id="102", owner="55")]
        ledger = {"schema": 1, "actions": {}}
        def verify(t, _, *, recent_now=None):
            self.assertEqual(recent_now, NOW)
            if t["post_id"] == "101":
                raise ValueError("source_owner_mismatch")
        with patch.object(m, "verified_media", side_effect=verify), \
             patch.object(m, "perform") as writer, \
             patch.dict(m.os.environ, {"META_CROSS_REPOST_ENABLED": "false"}):
            planned, report = m.build_account_batch(posts, aa, ledger, "200", "100", now=NOW)
            writer.assert_not_called()
        self.assertEqual(len(planned), 3)
        self.assertEqual({t["post_id"] for t in planned}, {"102"})
        self.assertIn("source_preflight_failed", {x["status"] for x in report})



if __name__ == "__main__":
    unittest.main()
