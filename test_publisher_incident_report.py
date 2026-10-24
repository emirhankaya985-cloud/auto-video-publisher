"""Old mistakes stay covered by tests, without exposing private API responses."""
import unittest

from publisher_incident_report import build_incident_report


class IncidentReportTests(unittest.TestCase):
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

    def test_invalid_runid_never_attributes_old_upload_to_new_run(self):
        with self.assertRaises(ValueError):
            build_incident_report({"entries": {}}, "../../oops")

    def test_unknown_ledger_state_is_not_reported_as_green(self):
        state = {"entries": {"bad": {"run_id": "300", "status": "magic_publish"}}}
        with self.assertRaises(ValueError):
            build_incident_report(state, "300")


if __name__ == "__main__":
    unittest.main()
