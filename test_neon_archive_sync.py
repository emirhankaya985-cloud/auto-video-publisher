"""Offline Neon direct-ingest safety tests; never contact GitHub or PostgreSQL."""
import json
import os
import io
import unittest
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

import neon_archive_sync as sync


def sample(**changes):
    row = {
        "account": "🌱 Tarladaki Fasulye",
        "platform": "Instagram",
        "entity_type": "account",
        "entity_id": "tarladaki:instagram",
        "metric": "lifetime_views",
        "period": "2026-11-16",
        "measured_at": "2026-11-16T20:59:00Z",
        "status": "ok",
        "value": 456,
    }
    row.update(changes)
    return row


def sample_report(**changes):
    row = {
        "report_date": date(2026, 11, 16),
        "timezone": "Europe/Istanbul",
        "status": "partial",
        "generated_at": datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc),
        "payload": json.dumps({"day": "2026-11-16", "source_run_id": "123"}),
        "error": "Threads authentication failed",
    }
    row.update(changes)
    return row


class FakeCursor:
    def __init__(self, *, existing=False, tls=True):
        self.existing = existing
        self.tls = tls
        self.sql = []
        self.rows = []
        self.rowcount = 0
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls += 1
        self.sql.append(sql)
        self.rows.append(params)
        if "current_database()" in sql:
            self.next = ("neondb", self.tls)
        elif "SELECT id FROM archive_import_runs" in sql:
            self.next = (7,) if self.existing else None
        elif "INSERT INTO daily_reports" in sql:
            self.next = (params[0],)
        elif "INSERT INTO social_accounts" in sql:
            self.next = (42,)
        elif "INSERT INTO archive_import_runs" in sql:
            self.next = (87,)
        else:
            self.next = None
        return self

    def fetchone(self):
        return self.next

    def executemany(self, sql, rows):
        self.sql.append(sql)
        self.rows.append(rows)
        self.rowcount = len(rows)
        return self


class FakeConn:
    def __init__(self, *, existing=False, tls=True):
        self.cur = FakeCursor(existing=existing, tls=tls)
        self.transaction_started = False
        self.transaction_exited = False

    @contextmanager
    def transaction(self):
        self.transaction_started = True
        yield
        self.transaction_exited = True

    def cursor(self):
        return self.cur


class NeonDirectArchiveSafetyTests(unittest.TestCase):
    def test_only_existing_social_database_is_allowed(self):
        good = "postgresql://social:private@ep-foo.c-8.eu-central-1.aws.neon.tech/neondb?sslmode=require"
        self.assertEqual(sync.validate_neon_url(good), good)
        for wrong in (
            good.replace("/neondb", "/careerhunter_live"),
            "postgresql://social:private@evil.example/neondb",
            "http://evil.example/neondb",
            "postgresql://social@ep-foo.c-8.eu-central-1.aws.neon.tech/neondb",
        ):
            with self.subTest(wrong=wrong.split("@")[-1]):
                with self.assertRaisesRegex(ValueError, "wrong_neon_connection_scope"):
                    sync.validate_neon_url(wrong)

    def test_successful_main_source_required_not_pr_or_other_workflow(self):
        base = {"id": 123, "name": sync.DAILY_WORKFLOW,
                "status": "completed", "conclusion": "success", "head_branch": "main"}
        reply = Mock(json=lambda: base)
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": sync.REPOSITORY}), \
             patch.object(sync, "request_with_retry", return_value=reply) as get:
            self.assertTrue(sync.verify_successful_main_run(Mock(),run_id="123",github_token="PRIVATE"))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[1], "get")
        self.assertNotIn("PRIVATE", str(base))
        for change in ({"head_branch": "feature"}, {"conclusion": "failure"},
                       {"name": "Some other workflow"}, {"status": "in_progress"}):
            with patch.dict(os.environ, {"GITHUB_REPOSITORY": sync.REPOSITORY}), \
                 patch.object(sync, "request_with_retry",
                              return_value=Mock(json=lambda: dict(base, **change))):
                with self.assertRaisesRegex(ValueError, "daily_source_not_successful"):
                    sync.verify_successful_main_run(Mock(),run_id="123",github_token="PRIVATE")

    def test_missing_is_not_zero_and_untrusted_rows_are_redacted_to_review(self):
        validated, review = sync.normalize_for_neon([
            sample(), sample(metric="followers",value=0),
            sample(metric="followers", value=None),
            sample(metric="likes", measured_at=None),
            sample(metric="likes",value=float("nan")),
            {"_review_reason": "invalid_json", "_raw_line": "PRIVATE_TOKEN"},
        ])
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0]["value"], 456)
        self.assertEqual(validated[1]["value"], 0)
        self.assertEqual(len(review), 4)
        self.assertTrue(all("PRIVATE_TOKEN" not in str(x) for x in review))
        self.assertTrue(all("source_key" in row for row in validated))

    def test_atomic_ingest_never_turns_video_id_into_account_or_post_id(self):
        prepared, review = sync.normalize_for_neon([
            sample(), sample(entity_type="video", entity_id="video123",
                             metric="view_count", value=33),
        ])
        conn = FakeConn()
        outcome = sync.ingest(conn, prepared, review,source_run_id="123",
            archive_sha="a"*64,latest_period="2026-11-16",
            rows_seen=2,deduplicated=0,days=7,
            started=datetime(2026,11,16,tzinfo=timezone.utc),
            report=sample_report())
        self.assertEqual(outcome["inserted"], 2)
        self.assertEqual(outcome["audit_id"], 87)
        self.assertTrue(conn.transaction_started and conn.transaction_exited)
        acct = [params for sql,params in zip(conn.cur.sql,conn.cur.rows)
                if "INSERT INTO social_accounts" in sql]
        self.assertEqual(len(acct), 1)
        self.assertIsNone(acct[0][2])
        metrics = [params for sql,params in zip(conn.cur.sql,conn.cur.rows)
                   if "INSERT INTO metric_snapshots" in sql][0]
        self.assertIsNone(metrics[1][-1])  # video ID never becomes a platform post ID
        self.assertEqual(metrics[1][-2], "video123")
        self.assertIn("DO NOTHING",sync.MEASUREMENT_INSERT)
        report_sql = next(sql for sql in conn.cur.sql if "INSERT INTO daily_reports" in sql)
        self.assertIn("ON CONFLICT(report_date) DO UPDATE", report_sql)
        self.assertIn("WHERE daily_reports.generated_at <= EXCLUDED.generated_at", report_sql)
        audit_params = next(params for sql, params in zip(conn.cur.sql, conn.cur.rows)
                            if "INSERT INTO archive_import_runs" in sql)
        details = json.loads(audit_params[7])
        self.assertEqual(details["daily_report_status"], "partial")
        self.assertTrue(details["daily_report_written"])

    def test_daily_report_keeps_partial_state_and_source_run_provenance(self):
        comparison = {
            "day": "2026-11-16", "measured_at": "2026-11-16T23:59:00+03:00",
            "accounts": [{"account": "Page", "total": None}],
            "collection": {"status": "incomplete"},
            "meta_collection": {"status": "complete"},
            "report_errors": ["Page / Threads: token rejected"],
        }
        record = sync.daily_report_record(comparison, source_run_id="123",
                                          artifact_sha256="b"*64)
        self.assertEqual(record["report_date"], date(2026, 11, 16))
        self.assertEqual(record["timezone"], "Europe/Istanbul")
        self.assertEqual(record["status"], "partial")
        payload = json.loads(record["payload"])
        self.assertEqual(payload["source_run_id"], "123")
        self.assertEqual(payload["source_report_artifact_sha256"], "b"*64)
        self.assertIsNone(payload["accounts"][0]["total"])
        self.assertEqual(record["error"], "Page / Threads: token rejected")

    def test_daily_report_rejects_missing_timezone_and_required_coverage(self):
        base = {"day": "2026-11-16", "measured_at": "2026-11-16T20:00:00Z",
                "accounts": [], "collection": {"status": "complete"},
                "meta_collection": {"status": "complete"}}
        with self.assertRaisesRegex(ValueError, "timestamp_timezone_missing"):
            sync.daily_report_record(dict(base, measured_at="2026-11-16T20:00:00"),
                                    source_run_id="1", artifact_sha256="a"*64)
        with self.assertRaisesRegex(ValueError, "coverage_missing"):
            sync.daily_report_record({k: v for k, v in base.items() if k != "collection"},
                                    source_run_id="1", artifact_sha256="a"*64)

    def test_report_artifact_is_selected_by_name_and_hash_recorded(self):
        contents = {"day": "2026-11-16", "measured_at": "2026-11-16T20:00:00+03:00",
                    "accounts": [], "collection": {"status": "complete"},
                    "meta_collection": {"status": "complete"}}
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("link-runtime/account_views_comparison.json",
                            json.dumps(contents))

        class Reply:
            status_code = 200
            def __init__(self, data=None, payload=b""):
                self.data, self.content = data, payload
            def json(self):
                return self.data
            def raise_for_status(self):
                return None

        responses = [
            Reply({"artifacts": [{"name": sync.REPORT_ARTIFACT_NAME,
                                   "expired": False,
                                   "archive_download_url": "https://api.github.com/artifact.zip"}]}),
            Reply(payload=archive.getvalue()),
        ]
        with patch.object(sync, "request_with_retry", side_effect=responses):
            result, digest = sync.read_report_comparison(
                Mock(), run_id="123", github_token="token")
        self.assertEqual(result["day"], "2026-11-16")
        self.assertEqual(digest, __import__("hashlib").sha256(archive.getvalue()).hexdigest())

    def test_same_archived_run_is_idempotent_no_metric_writes(self):
        prepared, review = sync.normalize_for_neon([sample()])
        conn = FakeConn(existing=True)
        outcome = sync.ingest(conn, prepared, review,source_run_id="123",
            archive_sha="a"*64,latest_period="2026-11-16",
            rows_seen=1,deduplicated=0,days=7,
            started=datetime(2026,11,16,tzinfo=timezone.utc),
            report=sample_report())
        self.assertEqual(outcome["status"], "already_synced")
        self.assertTrue(outcome["daily_report_written"])
        self.assertTrue(any("INSERT INTO daily_reports" in sql for sql in conn.cur.sql))
        self.assertFalse(any("INSERT INTO metric_snapshots" in sql for sql in conn.cur.sql))

    def test_without_neon_tls_transaction_fails_closed(self):
        prepared, review = sync.normalize_for_neon([sample()])
        conn = FakeConn(tls=False)
        with self.assertRaisesRegex(ValueError,"wrong_neon_database_or_tls"):
            sync.ingest(conn, prepared, review,source_run_id="123",
                archive_sha="a"*64,latest_period="2026-11-16",
                rows_seen=1,deduplicated=0,days=7,
                started=datetime(2026,11,16,tzinfo=timezone.utc),
                report=sample_report())
        self.assertFalse(any("INSERT INTO metric_snapshots" in sql for sql in conn.cur.sql))

    def test_failures_expose_only_bounded_stage_and_exception_class(self):
        import io
        from contextlib import redirect_stdout
        private = "postgresql://private:DO_NOT_PRINT_SECRET@ep-foo.neon.tech/neondb"
        for failing_step, expected_stage in (
            ("validate_neon_url", "connection_scope"),
            ("verify_successful_main_run", "trusted_source_run"),
            ("read_source_rows", "analytics_artifact"),
        ):
            with self.subTest(stage=failing_step):
                output = io.StringIO()
                with (
                    patch.dict(os.environ, {
                        "DASHBOARD_DATABASE_URL": private,
                        "SOURCE_RUN_ID": "43961941936",
                        "GITHUB_TOKEN": "PRIVATE_TOKEN",
                    }),
                    patch.object(sync, "_session", return_value=Mock()),
                    patch.object(sync, "validate_neon_url"),
                    patch.object(sync, "verify_successful_main_run"),
                    patch.object(sync, "read_source_rows"),
                    patch.object(sync, failing_step,
                                 side_effect=ValueError("DO_NOT_PRINT_SECRET")),
                    redirect_stdout(output),
                ):
                    self.assertEqual(sync.main(), 1)
                log = output.getvalue()
                self.assertIn("stage=" + expected_stage, log)
                self.assertIn("error_type=ValueError", log)
                self.assertNotIn("DO_NOT_PRINT_SECRET", log)
                self.assertNotIn("PRIVATE_TOKEN", log)

    def test_no_new_secrets_means_explicit_blocked_without_network(self):
        with patch.dict(os.environ, {},clear=True), \
             patch.object(sync, "_session") as session:
            self.assertEqual(sync.main(), 2)
        session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
