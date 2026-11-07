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


    def test_remote_unknown_separated_from_local_visual_duplicates_without_mutation(self):
        import copy
        rows = {}
        for i in range(7):
            route = ("tarladaki" if i < 2 else "penguen" if i == 2
                     else "film" if i == 3 else "daily_laugh")
            rows[f"uncertain:{i}"] = {"run_id": "111", "route": route,
                                     "platform": "instagram", "status": "uncertain"}
        for i in range(4):
            route = ("film" if i == 0 else "film_second" if i == 1
                     else "daily_laugh")
            rows[f"held:{i}"] = {
                "run_id": "222", "route": route,
                "platform": "facebook" if i < 2 else "instagram",
                "status": "held",
                "failure": {"reason": "visual_duplicate_review",
                            "external_post_attempted": False,
                            "safe_to_repost": False,
                            "private_provider_message": "NEVER_ECHO_SECRET"}}
        state = {"entries": rows}
        before = copy.deepcopy(state)
        report = build_incident_report(state, "999")
        self.assertEqual(report["previous_unreconciled_intents"], 11)
        self.assertEqual(report["previous_remote_reconciliation_required"], 7)
        self.assertEqual(report["previous_known_nonposted_visual_holds"], 4)
        self.assertEqual(report["previous_other_review_holds"], 0)
        self.assertEqual(report["previous_ambiguous_by_route"],
                         {"tarladaki": 2, "penguen": 1, "film": 1, "daily_laugh": 3})
        self.assertEqual(report["confirmed_new_posts"], 0)
        self.assertNotIn("NEVER_ECHO_SECRET", str(report))
        self.assertEqual(state, before)

    def test_unproven_held_post_is_not_falsely_called_a_safe_local_duplicate(self):
        rows = {"risky": {"status": "held", "run_id": "15", "route": "film",
                          "failure": {"reason": "visual_duplicate_review",
                                      "external_post_attempted": None,
                                      "safe_to_repost": False}},
                "actual": {"status": "intent", "run_id": "15", "route": "film"}}
        r = build_incident_report({"entries": rows}, "999")
        self.assertEqual(r["previous_remote_reconciliation_required"], 1)
        self.assertEqual(r["previous_known_nonposted_visual_holds"], 0)
        self.assertEqual(r["previous_other_review_holds"], 1)


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
