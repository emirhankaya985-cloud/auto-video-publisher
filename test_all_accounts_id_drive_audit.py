"""Read-only all-account ID/Drive correlation regression tests."""
import unittest
from all_accounts_id_drive_audit import analyze


class IdDriveAuditTests(unittest.TestCase):
    def setUp(self):
        self.state = {"schema": 1, "entries": {
            "film:instagram:DRIVE_A": {
                "route": "film", "platform": "instagram",
                "status": "done", "file": "Bickin_Part_7.mp4", "post_id": "123"},
            "film:instagram:DRIVE_B": {
                "route": "film", "platform": "instagram",
                "status": "held", "file": "Bickin_Part_8.mp4"},
            "film:facebook:DRIVE_A": {
                "route": "film", "platform": "facebook",
                "status": "done", "file": "Bickin_Part_7.mp4", "post_id": "456"},
        }}
        self.catalogs = {"film": {
            "Bickin_Part_7.mp4": {"id": "DRIVE_A"},
            "Bickin_Part_8.mp4": {"id": "DRIVE_B"},
            "Bickin_Part_9.mp4": {"id": "DRIVE_C"},
        }}
        self.feeds = {
            ("film", "instagram"): {"123", "999"},
            ("film", "facebook"): {"999"},
        }

    def test_requires_correct_platform_history(self):
        rows = analyze(self.state, self.catalogs, self.feeds)["accounts"]
        by_platform = {r["platform"]: r for r in rows if r["route"] == "film"}
        self.assertEqual(by_platform["instagram"]["historical_ids_seen_live"], 1)
        self.assertEqual(by_platform["facebook"]["historical_ids_seen_live"], 0)
        self.assertEqual(by_platform["facebook"]["historical_ids_not_seen_in_bounded_feed"], 1)
        self.assertEqual(by_platform["instagram"]["unmatched_remote_ids"], 1)

    def test_drive_no_receipt_and_held_differ(self):
        rows = analyze(self.state, self.catalogs, self.feeds)["videos"]
        videos = {v["file"]: v["classification"] for v in rows
                  if v["route"] == "film" and v["platform"] == "instagram"}
        self.assertEqual(videos["Bickin_Part_8.mp4"], "held_or_unverified")
        self.assertEqual(videos["Bickin_Part_9.mp4"], "drive_video_no_route_receipt")

    def test_failed_read_is_not_an_absence_proof(self):
        data = analyze(self.state, self.catalogs,
                       {("film", "instagram"): None})
        rows = [v for v in data["videos"] if v["route"] == "film"
                and v["platform"] == "instagram"
                and v["file"] == "Bickin_Part_7.mp4"]
        self.assertEqual(rows[0]["classification"], "past_receipt_remote_unavailable")
        self.assertEqual(rows[0]["currently_observed_matching_post_ids"], [])
        self.assertEqual(data["provider_write_requests"], 0)
        self.assertEqual(data["ledger_writes"], 0)

    def test_same_post_id_cannot_prove_two_sources(self):
        self.state["entries"]["film:instagram:DRIVE_C"] = {
            "route": "film", "platform": "instagram",
            "status": "done", "file": "Bickin_Part_9.mp4", "post_id": "123"}
        rows = analyze(self.state, self.catalogs, self.feeds)["accounts"]
        film_ig = next(r for r in rows
                       if r["route"] == "film" and r["platform"] == "instagram")
        self.assertEqual(film_ig["historical_id_collisions"], 1)
        self.assertEqual(film_ig["historical_ids_seen_live"], 0)


if __name__ == "__main__":
    unittest.main()
