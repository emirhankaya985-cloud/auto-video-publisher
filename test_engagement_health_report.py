import io
import json
import os
import zipfile
import unittest
from unittest.mock import Mock, patch

from engagement_health_report import ACCOUNTS, collect_report, format_digest, format_report, unknown_report


def zipped_report(report):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("cross-engagement/report.json", json.dumps(report))
    return buf.getvalue()


def fixture_report():
    return {
        "mode": "dry_run", "verified_account_names": list(ACCOUNTS),
        "verified_facebook_identities": 6, "verified_instagram_identities": 6,
        "facebook_unverified_routes": [], "instagram_unverified_routes": [],
        "verified_like_coverage": {
            "facebook": {"permission_eligible_actor_routes": list(ACCOUNTS),
                         "historical_api_ack_count_in_retained_ledger": 17},
            "instagram": {"historical_api_ack_count_in_retained_ledger": 0},
        },
        "blocked_counts": {"facebook/like/disabled_by_policy": 2,
                           "instagram/like/unsupported_by_verified_api": 3},
    }


class EngagementHealthReportTests(unittest.TestCase):
    def test_missing_github_access_reports_unknown_not_zero(self):
        with patch.dict(os.environ, {}, clear=True):
            report = collect_report(repository="emirhankaya985-cloud/auto-video-publisher")
        self.assertEqual(report["status"], "unknown")
        self.assertTrue(all(row["historical_verified_interactions"] != 0
                            for row in report["accounts"]))
        self.assertTrue(all(row["connection"] == "unknown" for row in report["accounts"]))

    def test_latest_readonly_run_produces_six_account_platform_rows_without_secrets(self):
        runs = {"workflow_runs": [
            {"id": 11, "head_branch": "main", "head_repository": {"full_name": "emirhankaya985-cloud/auto-video-publisher"},
             "status": "completed", "conclusion": "success", "event": "workflow_dispatch",
             "created_at": "2026-11-25T23:00:00Z", "updated_at": "2026-11-25T23:01:00Z", "head_sha": "oldsha"},
            {"id": 10, "head_branch": "main", "head_repository": {"full_name": "emirhankaya985-cloud/auto-video-publisher"},
             "status": "completed", "conclusion": "success", "event": "schedule",
             "created_at": "2026-11-25T22:00:00Z", "updated_at": "2026-11-25T22:01:00Z", "head_sha": "older"},
        ]}
        artifacts = {"artifacts": [
            {"name": f"account-audit-{focus}", "expired": False,
             "archive_download_url": f"https://api.github.com/artifacts/{focus}"}
            for focus in ("tarladaki", "gonle", "penguen", "daily_laugh", "film", "toonzone")
        ]}
        session = Mock()
        session.get.side_effect = [
            Mock(json=Mock(return_value=runs), raise_for_status=Mock()),
            Mock(json=Mock(return_value=artifacts), raise_for_status=Mock()),
            *[Mock(content=zipped_report(fixture_report()), raise_for_status=Mock()) for _ in range(6)],
        ]
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-secret", "GITHUB_REPOSITORY": "emirhankaya985-cloud/auto-video-publisher"}):
            report = collect_report(session=session, current_sha="newsha")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["freshness"], "stale_code")
        self.assertFalse(report["natural_schedule_on_current_sha"])
        self.assertEqual(len(report["accounts"]), 12)
        fb = next(row for row in report["accounts"]
                  if row["account"] == "Tarladaki Fasulye" and row["platform"] == "facebook")
        ig = next(row for row in report["accounts"]
                  if row["account"] == "Tarladaki Fasulye" and row["platform"] == "instagram")
        self.assertEqual(fb["connection"], "ok_at_last_read")
        self.assertEqual(fb["platform_historical_api_ack_count"], 17)
        self.assertEqual(fb["historical_verified_interactions"], "Hesap bazında bilinmiyor")
        self.assertEqual(ig["write_status"], "unsupported_by_verified_api")
        self.assertEqual(report["latest_natural_schedule"]["id"], 10)
        body = format_report(report)
        self.assertNotIn("test-secret", body)
        self.assertIn("Hesap bazında bilinmiyor", body)
        self.assertIn("disabled_by_policy", body)
        self.assertIn("güncel main commit'inde görüldü: hayır / doğrulanmadı", body)
        digest = format_digest(report)
        self.assertLessEqual(len(digest.encode("utf-8")), 4096)
        self.assertIn("Daily Laugh Lab", digest)

    def test_incomplete_artifacts_do_not_claim_health_or_zero_history(self):
        runs = {"workflow_runs": [{
            "id": 2, "head_branch": "main", "head_repository": {"full_name": "emirhankaya985-cloud/auto-video-publisher"},
            "status": "completed", "conclusion": "success", "event": "schedule",
            "created_at": "2026-11-25T22:00:00Z", "head_sha": "sha",
        }]}
        artifacts = {"artifacts": []}
        session = Mock()
        session.get.side_effect = [Mock(json=Mock(return_value=runs), raise_for_status=Mock()),
                                   Mock(json=Mock(return_value=artifacts), raise_for_status=Mock())]
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token", "GITHUB_REPOSITORY": "emirhankaya985-cloud/auto-video-publisher"}):
            report = collect_report(session=session, current_sha="sha")
        self.assertEqual(report["status"], "unknown")
        self.assertEqual(report["reason"], "account_health_artifacts_incomplete")
        self.assertTrue(all(row["last_runtime"] == "unknown" for row in report["accounts"]))


if __name__ == "__main__":
    unittest.main()
