"""No network; confirmed-publication evidence must not be overstated."""
import unittest
from publisher_incident_report import build_incident_report


class IncidentEvidenceTests(unittest.TestCase):
    def test_done_without_post_id_is_not_counted_or_silent(self):
        ledger = {"entries": {
            "example": {"run_id": "12345", "status": "done",
                        "route": "film", "platform": "instagram"}
        }}
        report = build_incident_report(ledger, "12345")
        self.assertEqual(report["confirmed_new_posts"], 0)
        self.assertEqual(report["unverified_done_entries"], 1)
        self.assertTrue(any(i["reason"] == "missing_confirmed_post_id"
                            for i in report["incidents"]))

    def test_done_with_real_post_id_is_counted(self):
        ledger = {"entries": {
            "example": {"run_id": "12345", "status": "done",
                        "post_id": "123456789", "route": "film",
                        "platform": "instagram"}
        }}
        report = build_incident_report(ledger, "12345")
        self.assertEqual(report["confirmed_new_posts"], 1)
        self.assertEqual(report["unverified_done_entries"], 0)


    def test_prior_uncertain_intent_is_visible_in_new_green_run(self):
        ledger = {"entries": {
            "old_film": {"run_id": "11111", "status": "uncertain",
                         "route": "film", "platform": "instagram"},
            "old_toon": {"run_id": "22222", "status": "uncertain",
                         "route": "toonzone", "platform": "instagram"},
            "new_post": {"run_id": "12345", "status": "done", "post_id": "333",
                         "route": "daily_laugh", "platform": "facebook"}
        }}
        result = build_incident_report(ledger, "12345")
        self.assertEqual(result["confirmed_new_posts"], 1)
        self.assertEqual(result["uncertain_pending_reconciliation"], 0)
        self.assertEqual(result["previous_unreconciled_intents"], 2)
        self.assertEqual(result["previous_unreconciled_by_route"],
                         {"film": 1, "toonzone": 1})


if __name__ == "__main__":
    unittest.main()
