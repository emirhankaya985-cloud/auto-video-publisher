"""Old mistakes stay covered by tests, without exposing private API responses."""
import unittest

from publisher_incident_report import build_incident_report, blocked_due_publication


class IncidentReportTests(unittest.TestCase):
    def test_due_empty_queue_fails_only_live_publish(self):
        summary = build_incident_report({'entries': {}}, '300',
            plan_text='No eligible unpublished item below the daily target.')
        self.assertTrue(blocked_due_publication(summary, publishing_allowed=True))
        self.assertFalse(blocked_due_publication(summary, publishing_allowed=False))
        self.assertFalse(blocked_due_publication(
            build_incident_report({'entries': {}}, '300', plan_text='NOT DUE'),
            publishing_allowed=True))
        summary['confirmed_new_posts'] = 1
        self.assertFalse(blocked_due_publication(summary, publishing_allowed=True))

    def test_zero_post_reasons_stay_distinct_in_artifact(self):
        text = ("QUARANTINE: exact source failed local MP4 preparation in a prior run; no blind media retry.\n"
                "QUARANTINE: proven local-only visual duplicate; look for next unique clip.\n"
                "HELD: 326.mp4 instagram has an uncertain previous intent.\n"
                "No eligible unpublished item below the daily target.\n")
        result = build_incident_report({'entries': {}}, '300', plan_text=text)
        self.assertEqual(result['confirmed_new_posts'], 0)
        self.assertEqual(result['no_post_signals'], {
            'no_eligible_content': 1, 'local_quality_quarantine': 1,
            'visual_duplicate_hold': 1, 'uncertain_previous_intent': 1,
        })

    def test_confirmed_post_does_not_claim_no_post_signals(self):
        state = {'entries': {'x': {'run_id': '300', 'status': 'done',
                                  'post_id': '123', 'route': 'film', 'platform': 'facebook'}}}
        result = build_incident_report(state, '300', plan_text='No eligible unpublished item below the daily target.')
        self.assertEqual(result['no_post_signals'], {})

    def test_visual_hold_remains_visible_without_breaking_incident_writer(self):
        result = build_incident_report({'entries': {'x': {
            'run_id': '300', 'status': 'held', 'route': 'film', 'platform': 'facebook',
            'failure': {'reason': 'visual_duplicate_review'}}}}, '300',
            step_outcomes={'youtube_publish': 'failure', 'post_verification': 'success'})
        self.assertEqual(result['held_for_review'], 1)
        self.assertEqual(result['confirmed_new_posts'], 0)
        self.assertEqual(result['incidents'][0]['action'], 'source_review_required_no_repost')
        self.assertEqual(result['step_outcomes']['youtube_publish'], 'failure')

    def test_only_current_run_is_counted(self):
        state = {"entries": {
            "fb": {"run_id": "200", "status": "done", "route": "film", "platform": "facebook", "post_id": "77"},
            "ig": {"run_id": "200", "status": "uncertain", "route": "film", "platform": "instagram",
                   "failure": {"reason": "invalid_media_or_graph_request", "http_status": 400,
                               "graph_subcode": 2207009, "message": "secret token"}},
            "old": {"run_id": "199", "status": "done", "route": "film", "platform": "instagram"},
        }}
        actual = build_incident_report(state, "200")
        self.assertEqual(actual["confirmed_new_posts"], 1)
        self.assertEqual(actual["uncertain_pending_reconciliation"], 1)
        self.assertEqual(len(actual["incidents"]), 1)
        self.assertEqual(actual["incidents"][0]["http_status"], 400)
        self.assertEqual(actual["incidents"][0]["graph_subcode"], 2207009)
        self.assertEqual(actual["incidents"][0]["action"], "remote_reconciliation_required")
        self.assertNotIn("secret token", str(actual))

    def test_local_ffmpeg_failure_is_safe_to_retry_prep_not_publish(self):
        state = {"entries": {"ig": {
            "run_id": "300", "status": "ready", "route": "gonle", "platform": "instagram",
            "failure": {"reason": "media_preparation_failed", "error_type": "RuntimeError",
                        "safe_to_repost": True}
        }}}
        actual = build_incident_report(state, "300")
        self.assertEqual(actual["safe_pre_upload_retries"], 1)
        self.assertEqual(actual["incidents"][0]["action"], "safe_to_reprepare_next_tick")

    def test_missing_txt_cover_source_and_route_switches_are_counted(self):
        state = {"entries": {}}
        text = ("HELD source film: RuntimeError\nHELD TXT/caption: missing TXT\n"
                "HELD: exact ToonZone cover missing.\n"
                "HELD: existing route/rights switch is disabled.\n")
        result = build_incident_report(state, "300", plan_text=text)
        self.assertEqual(result["planning_blocker_counts"]["missing_drive_folder"], 1)
        self.assertEqual(result["planning_blocker_counts"]["txt_or_caption_blocked"], 1)
        self.assertEqual(result["planning_blocker_counts"]["toonzone_exact_cover_missing"], 1)
        self.assertEqual(result["planning_blocker_counts"]["disabled_route"], 1)

    def test_failed_preflight_is_recorded_without_falsely_claiming_prior_state_clean(self):
        result = build_incident_report(
            {"entries": {}}, "41223244923", state_available=False,
            step_outcomes={"preflight": "failure", "verify": "skipped",
                           "plan": "skipped", "publish": "skipped"},
        )
        self.assertEqual(result["confirmed_new_posts"], 0)
        self.assertFalse(result["state_available"])
        self.assertEqual(result["step_outcomes"]["preflight"], "failure")
        self.assertEqual(result["incidents"][0]["reason"], "meta_preflight_failed")
        self.assertEqual(result["incidents"][0]["action"], "inspect_redacted_preflight_log_no_meta_post")
        self.assertNotIn("token", str(result["incidents"]))

    def test_successful_preflight_adds_no_false_incident(self):
        result = build_incident_report(
            {"entries": {}}, "300", step_outcomes={"preflight": "success"},
        )
        self.assertTrue(result["state_available"])
        self.assertEqual(result["incidents"], [])

    def test_delivery_failure_is_explicitly_separate_from_verified_publish(self):
        state = {"entries": {"ig": {
            "run_id": "777", "status": "done", "route": "film",
            "platform": "instagram", "post_id": "18000000000000",
        }}}
        r = build_incident_report(state, "777", step_outcomes={
            "publish": "success", "post_verification": "success", "notify": "failure",
        })
        self.assertEqual(r["confirmed_new_posts"], 1)
        self.assertEqual(r["unverified_done_entries"], 0)
        self.assertEqual(r["step_outcomes"]["publish"], "success")
        self.assertEqual(r["step_outcomes"]["notify"], "failure")
        self.assertEqual(r["uncertain_pending_reconciliation"], 0)

    def test_invalid_runid_never_attributes_old_upload_to_new_run(self):
        with self.assertRaises(ValueError):
            build_incident_report({"entries": {}}, "../../oops")

    def test_unknown_ledger_state_is_not_reported_as_green(self):
        state = {"entries": {"bad": {"run_id": "300", "status": "magic_publish"}}}
        with self.assertRaises(ValueError):
            build_incident_report(state, "300")


if __name__ == "__main__":
    unittest.main()
