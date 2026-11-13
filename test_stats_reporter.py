import os
from unittest.mock import Mock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

from googleapiclient.errors import HttpError

from stats_reporter import (
    ACCOUNT_TARGETS, YOUTUBE_TARGETS, _daily_delta_text, _platform_totals,
    notify, publication_progress, safe_error, youtube_video_snapshot,
)


def test_youtube_scope_error_is_short_and_actionable():
    response = Mock(status=403, reason="Request had insufficient authentication scopes")
    error = HttpError(response, b'{"error":{"message":"denied"}}')
    assert safe_error(error) == "HTTP 403: istatistik okuma erişimi/yetkisi reddedildi"


def test_ntfy_success_is_checked():
    response = Mock(status_code=200)
    response.json.return_value = {
        "id": "confirmed-123", "event": "message",
        "topic": "private-topic",
    }
    with patch.dict(os.environ, {"NTFY_TOPIC": "private-topic"}, clear=True), patch(
        "ntfy_notifications.requests.post", return_value=response
    ) as post:
        notify("report")
    response.raise_for_status.assert_called_once_with()
    response.json.assert_called_once_with()
    assert post.call_args.kwargs["json"]["title"] == "🌙 Günlük Sosyal Medya Raporu"


def test_ntfy_topic_url_posts_json_to_root_with_explicit_topic():
    response = Mock(status_code=200)
    response.json.return_value = {
        "id": "confirmed-456", "event": "message",
        "topic": "private-topic",
    }
    with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://ntfy.sh/private-topic"}, clear=True), patch(
        "ntfy_notifications.requests.post", return_value=response
    ) as post:
        notify("report")
    assert post.call_args.args[0] == "https://ntfy.sh/"
    assert post.call_args.kwargs["json"]["topic"] == "private-topic"
    assert post.call_args.kwargs["allow_redirects"] is False


def test_ntfy_transport_error_never_echoes_secret_topic_url():
    secret_url = "https://ntfy.sh/private-secret-topic"
    with patch.dict(os.environ, {"NTFY_TOPIC_URL": secret_url}, clear=True), patch(
        "ntfy_notifications.requests.post", side_effect=requests.ConnectionError(secret_url)
    ):
        try:
            notify("report")
        except RuntimeError as exc:
            assert secret_url not in str(exc)
            assert "ConnectionError" in str(exc)
        else:
            raise AssertionError("expected sanitized ntfy transport failure")


def test_ntfy_http_200_with_wrong_server_topic_is_failure():
    response = Mock(status_code=200)
    response.json.return_value = {
        "id": "confirmed-789", "event": "message",
        "topic": "different-topic",
    }
    with patch.dict(os.environ, {"NTFY_TOPIC_URL": "https://ntfy.sh/secret-topic"}, clear=True), patch(
        "ntfy_notifications.requests.post", return_value=response
    ) as post:
        try:
            notify("report")
        except RuntimeError as exc:
            assert "secret-topic" not in str(exc)
            assert "different-topic" not in str(exc)
            assert "receipt mismatch" in str(exc)
        else:
            raise AssertionError("wrong server topic must fail")
    assert post.call_count == 1


def test_daily_delta_requires_a_prior_snapshot_and_known_video_baselines():
    today = {("acct", "YouTube"): {"v1": {"views": 20, "published_at": "2025-01-01T00:00:00Z"}}}
    assert _platform_totals(today, {}, "acct", "YouTube", "2026-10-19") == (20, None)
    previous = {
        ("acct", "YouTube", "account", "acct", "snapshot_status"): {"status": "ok", "value": 1},
        ("acct", "YouTube", "video", "v1", "view_count"): {"value": 12},
    }
    assert _platform_totals(today, previous, "acct", "YouTube", "2026-10-19") == (20, 8)


def test_first_snapshot_is_labeled_na_but_failed_metric_is_unavailable():
    assert _daily_delta_text(20, None, None) == "N/A (ilk ölçüm)"
    assert _daily_delta_text(None, None, None) == "⚠️ Veri alınamadı"
    assert _daily_delta_text(20, None, {"status": "error"}) == "⚠️ Veri alınamadı"


def test_daily_targets_and_film_fanout_match_requested_scope():
    assert [ACCOUNT_TARGETS[name][0] for name in ACCOUNT_TARGETS] == [5, 5, 5, 8, 5, 4]
    assert ACCOUNT_TARGETS["🎬 Film Mağarası + Filmmagrasi"][3] == ("fb_film_1", "fb_film_2", "ig")
    assert any(account == "❤️ Gönle Düşen" for account, *_rest in YOUTUBE_TARGETS)


def test_publication_progress_reports_platform_failures_and_last_verified_status():
    drive = Mock()
    drive.files.return_value.list.return_value.execute.return_value = {
        "files": [{
            "id": "video-1", "mimeType": "video/mp4",
            "appProperties": {
                "done_ig_slot": "2026-10-18-12-gonle",
                "failure_slot_fb": "2026-10-19-09-gonle",
            },
        }],
    }
    with patch.dict(os.environ, {"GONLE_DUSEN_DRIVE_FOLDER_ID": "folder-id"}, clear=True):
        result = publication_progress(drive, "❤️ Gönle Düşen", "2026-10-19")
    assert result["platforms"]["fb"]["failure"] == 1
    assert result["platforms"]["fb"]["latest_status"] == "başarısız / belirsiz"
    assert result["platforms"]["ig"]["latest_status"] == "başarılı"


def test_missing_or_reset_video_counter_does_not_become_zero_delta():
    current = {("acct", "Facebook"): {"v1": {"views": 10, "published_at": "2025-01-01T00:00:00Z"}}}
    previous = {
        ("acct", "Facebook", "account", "acct", "snapshot_status"): {"status": "ok", "value": 1},
        ("acct", "Facebook", "video", "v1", "view_count"): {"value": 12},
    }
    assert _platform_totals(current, previous, "acct", "Facebook", "2026-10-19") == (10, None)


def test_missing_previously_observed_video_blocks_partial_account_lifetime_and_daily():
    current = {("acct", "Instagram"): {"v1": {"views": 30, "published_at": "2025-01-01T00:00:00Z"}}}
    prev = {
        ("acct", "Instagram", "account", "acct", "snapshot_status"): {"status": "ok", "value": 2},
        ("acct", "Instagram", "video", "v1", "view_count"): {"value": 20, "status": "ok"},
        ("acct", "Instagram", "video", "v2", "view_count"): {"value": 10, "status": "ok"},
    }
    assert _platform_totals(current, prev, "acct", "Instagram", "2026-10-20") == (None, None)


def test_incomplete_prior_archive_cannot_create_fake_daily_gain():
    current = {("acct", "YouTube"): {"v1": {"views": 30, "published_at": "2025-01-01T00:00:00Z"}}}
    prev = {
        ("acct", "YouTube", "account", "acct", "snapshot_status"): {"status": "ok", "value": 2},
        ("acct", "YouTube", "video", "v1", "view_count"): {"value": 20, "status": "ok"},
    }
    assert _platform_totals(current, prev, "acct", "YouTube", "2026-10-20") == (30, None)


def test_missing_prior_view_value_never_becomes_fake_zero():
    current = {("acct", "Facebook"): {"v1": {"views": 100, "published_at": "2025-01-01T00:00:00Z"}}}
    prev = {
        ("acct", "Facebook", "account", "acct", "snapshot_status"): {"status": "ok", "value": 1},
        ("acct", "Facebook", "video", "v1", "view_count"): {"value": None, "status": "unavailable"},
    }
    assert _platform_totals(current, prev, "acct", "Facebook", "2026-10-20") == (100, None)


def test_history_download_failure_never_overwrites_existing_drive_archive():
    import stats_reporter
    date = datetime(2026, 10, 20, 23, 59, tzinfo=ZoneInfo("Europe/Istanbul"))
    with patch("stats_reporter.get_drive_client", return_value=Mock()), patch(
        "stats_reporter.get_or_create_archive_folder", return_value="folder"
    ), patch("stats_reporter.download_history", side_effect=OSError("protected-drive-history")), patch(
        "stats_reporter._collect_snapshot", return_value=({}, [], [])
    ), patch("stats_reporter.publication_progress", return_value=None), patch(
        "stats_reporter.save_history_and_csv"
    ) as save:
        report = stats_reporter.build_report(date)
    save.assert_not_called()
    assert "Geçmiş okunamadığı için Drive arşivi korunuyor" in report
    assert "🗄️ Geçmiş: ⚠️ Drive arşivi kaydedilemedi" in report


def test_notify_sends_only_aggregated_collection_errors():
    import stats_reporter
    from views_comparison import ViewReport
    comparison = {
        "accounts": [
            {"account": "Penguen", "platforms": [
                {"platform": "Facebook", "total": 10},
                {"platform": "YouTube", "total": None},
            ]},
        ],
        "collection_errors": ["Penguen / YouTube: HTTP 403"],
    }
    report = ViewReport("normal stats", comparison)
    with patch("stats_reporter.send_ntfy", return_value={
        "http_status": 200, "server_ack": True,
    }) as send:
        stats_reporter.notify(report)
    assert send.call_count == 1
    body = send.call_args.args[1]
    assert send.call_args.kwargs["require_ack"] is True
    assert "Penguen — YouTube" in body
    assert "HTTP 403" in body
    assert "Facebook" not in body






def _fake_youtube_api(video_rows, upload_video_id="video-1"):
    api = Mock()
    api.channels.return_value.list.return_value.execute.return_value = {
        "items": [{
            "id": "yt-channel",
            "snippet": {"title": "Example Channel"},
            "contentDetails": {"relatedPlaylists": {"uploads": "playlist-upload"}},
        }],
    }
    api.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"videoId": upload_video_id},
                   "snippet": {"publishedAt": "2026-10-01T00:00:00Z"}}],
    }
    api.videos.return_value.list.return_value.execute.return_value = {
        "items": video_rows,
    }
    return api


def test_youtube_missing_view_count_fails_closed_in_daily_report():
    api = _fake_youtube_api([{"id": "video-1", "statistics": {}}])
    with patch("stats_reporter.get_youtube_client", return_value=api):
        try:
            youtube_video_snapshot("TOKEN", "file.json", "yt-channel")
        except RuntimeError as exc:
            assert "görüntülenme alanı eksik" in str(exc)
        else:
            raise AssertionError("missing viewCount must fail, not undercount")


def test_youtube_missing_video_in_statistics_response_fails_closed():
    api = _fake_youtube_api([])
    with patch("stats_reporter.get_youtube_client", return_value=api):
        try:
            youtube_video_snapshot("TOKEN", "file.json", "yt-channel")
        except RuntimeError as exc:
            assert "istatistikleri eksik" in str(exc)
        else:
            raise AssertionError("playlist/video API inventory mismatch must fail")


def test_youtube_invalid_playlist_video_id_fails_closed():
    api = _fake_youtube_api([], upload_video_id=None)
    with patch("stats_reporter.get_youtube_client", return_value=api):
        try:
            youtube_video_snapshot("TOKEN", "file.json", "yt-channel")
        except RuntimeError as exc:
            assert "eksik video kimlikleri" in str(exc)
        else:
            raise AssertionError("missing playlist video id must fail")


def test_youtube_complete_snapshot_keeps_exact_counter():
    api = _fake_youtube_api([{
        "id": "video-1", "statistics": {"viewCount": "1050"},
        "snippet": {"publishedAt": "2026-10-01T00:00:00Z"},
    }])
    with patch("stats_reporter.get_youtube_client", return_value=api):
        videos, channel = youtube_video_snapshot("TOKEN", "file.json", "yt-channel")
    assert videos["video-1"]["views"] == 1050
    assert channel == "Example Channel"




def test_archive_rerun_error_does_not_erase_same_day_good_history():
    import json
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from analytics_archive import make_record, upsert_records
    fields = dict(
        measured_at="2026-10-20T23:30:00+03:00",
        timezone="Europe/Istanbul", account="acct",
        platform="Instagram", entity_id="acct",
        entity_type="account", metric="snapshot_status",
        unit="videos", period="2026-10-20",
        source_api="graph", source_metric="video_views",
    )
    healthy = make_record(**fields, value=2, status="ok")
    lifetime = make_record(**{**fields, "metric": "lifetime_views"}, value=101, status="ok")
    video = make_record(**{**fields, "entity_type": "video", "entity_id": "id-1",
                           "metric": "view_count"}, value=51, status="ok")
    error = make_record(**{**fields, "measured_at": "2026-10-20T23:59:00+03:00"},
                        value=None, status="error")
    with TemporaryDirectory() as directory:
        history = Path(directory) / "snapshots.jsonl"
        assert upsert_records(history, [healthy, lifetime, video],
                              preserve_success_on_failure=True) == 3
        assert upsert_records(history, [error],
                              preserve_success_on_failure=True) == 0
        rows = [json.loads(line) for line in history.read_text().splitlines()]
        assert len(rows) == 3
        assert next(x for x in rows if x["metric"] == "snapshot_status") == healthy
        assert next(x for x in rows if x["metric"] == "lifetime_views") == lifetime
        assert next(x for x in rows if x["metric"] == "view_count") == video


def test_archive_rerun_shrinking_inventory_keeps_whole_last_good_group():
    import json
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from analytics_archive import make_record, upsert_records
    base = dict(measured_at="2026-10-20T20:00:00+03:00",
                timezone="Europe/Istanbul", account="acct", platform="Facebook",
                entity_type="account", entity_id="acct", unit="views",
                period="2026-10-20", source_api="graph", source_metric="views")
    def record(metric, value, stamp, *, status="ok"):
        return make_record(**{**base, "measured_at": stamp, "metric": metric},
                           value=value, status=status)
    old_time = "2026-10-20T21:00:00+03:00"
    new_time = "2026-10-20T23:59:00+03:00"
    snapshot = record("snapshot_status", 2, old_time)
    total = record("lifetime_views", 200, old_time)
    smaller_snapshot = record("snapshot_status", 1, new_time)
    smaller_total = record("lifetime_views", 120, new_time)
    with TemporaryDirectory() as directory:
        history = Path(directory) / "snapshots.jsonl"
        assert upsert_records(history, [snapshot, total],
                              preserve_success_on_failure=True) == 2
        assert upsert_records(history, [smaller_snapshot, smaller_total],
                              preserve_success_on_failure=True) == 0
        rows = [json.loads(line) for line in history.read_text().splitlines()]
        assert next(x for x in rows if x["metric"] == "snapshot_status") == snapshot
        assert next(x for x in rows if x["metric"] == "lifetime_views") == total
        # A complete newer snapshot may still replace older measurements.
        newer = record("lifetime_views", 240, new_time)
        newer_snapshot = record("snapshot_status", 2, new_time)
        assert upsert_records(history, [newer_snapshot, newer],
                              preserve_success_on_failure=True) == 2


def test_archive_default_upsert_contract_remains_unchanged():
    import json
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from analytics_archive import make_record, upsert_records
    base = dict(measured_at="2026-10-20T23:00:00+03:00",
                timezone="Europe/Istanbul", account="acct", platform="Youtube",
                entity_type="account", entity_id="acct", metric="snapshot_status",
                period="2026-10-20", source_api="test", source_metric="views")
    with TemporaryDirectory() as directory:
        history = Path(directory) / "snapshot.jsonl"
        assert upsert_records(history, [make_record(**base, value=3, status="ok")]) == 1
        assert upsert_records(history, [make_record(**base, value=None, status="error")]) == 1
        assert json.loads(history.read_text().strip())["status"] == "error"




def test_delayed_scheduled_run_still_reports_prior_turkey_day():
    from stats_reporter import resolve_report_day
    actual = datetime(2026, 10, 21, 0, 15, tzinfo=ZoneInfo("Europe/Istanbul"))
    assert resolve_report_day(actual, event_name="schedule").isoformat() == "2026-10-20"


def test_on_time_schedule_uses_current_turkey_day():
    from stats_reporter import resolve_report_day
    actual = datetime(2026, 10, 20, 23, 59, tzinfo=ZoneInfo("Europe/Istanbul"))
    assert resolve_report_day(actual, event_name="schedule").isoformat() == "2026-10-20"


def test_manual_run_after_midnight_is_not_backdated():
    from stats_reporter import resolve_report_day
    actual = datetime(2026, 10, 21, 0, 15, tzinfo=ZoneInfo("Europe/Istanbul"))
    assert resolve_report_day(actual, event_name="workflow_dispatch").isoformat() == "2026-10-21"


def test_scheduled_window_after_six_am_does_not_backdate_arbitrarily():
    from stats_reporter import resolve_report_day
    actual = datetime(2026, 10, 21, 6, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
    assert resolve_report_day(actual, event_name="schedule").isoformat() == "2026-10-21"


def test_delayed_snapshot_keeps_actual_measurement_timestamp_and_scheduled_period():
    from datetime import date
    import stats_reporter
    actual = datetime(2026, 10, 21, 0, 12, tzinfo=ZoneInfo("Europe/Istanbul"))
    video = {"id-1": {"views": 125, "published_at": "2026-10-20T08:00:00+03:00"}}
    with patch.object(stats_reporter, "META_TARGETS", [("account", "page", "Facebook")]), patch.object(
        stats_reporter, "YOUTUBE_TARGETS", []
    ), patch("stats_reporter.get_meta_page_info", return_value={"page_id": "1"}), patch(
        "stats_reporter.facebook_video_snapshot", return_value=video
    ):
        snapshot, records, errors = stats_reporter._collect_snapshot(
            actual, report_day=date(2026, 10, 20)
        )
    assert not errors
    assert snapshot[("account", "Facebook")]["id-1"]["views"] == 125
    assert {rec["period"] for rec in records} == {"2026-10-20"}
    assert all(rec["measured_at"].startswith("2026-10-21T00:12:") for rec in records)


def test_late_scheduled_report_retains_previous_date_but_refuses_daily_gains():
    import stats_reporter
    actual = datetime(2026, 10, 21, 0, 12, tzinfo=ZoneInfo("Europe/Istanbul"))
    sample = {
        ("🌱 Tarladaki Fasulye", "Facebook"): {
            "id-1": {"views": 125, "published_at": "2026-10-18T08:00:00+03:00"}
        }
    }
    baseline = {
        ("🌱 Tarladaki Fasulye", "Facebook", "account",
         "🌱 Tarladaki Fasulye", "snapshot_status"): {"status": "ok", "value": 1},
        ("🌱 Tarladaki Fasulye", "Facebook", "video", "id-1",
         "view_count"): {"value": 100, "status": "ok"},
    }
    with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True), patch(
        "stats_reporter.get_drive_client", side_effect=OSError("no fixture drive")
    ), patch("stats_reporter._read_day_records", return_value=baseline) as read, patch(
        "stats_reporter._collect_snapshot", return_value=(sample, [], [])
    ) as collect, patch("stats_reporter.publication_progress", return_value=None) as progress:
        result = stats_reporter.build_report(actual)
    assert result.startswith("🌙 GÜNLÜK SOSYAL MEDYA RAPORU — 20.10.2026")
    assert "⏰ Gecikmeli ölçüm: 21.10.2026 00:12 TRT." in result
    assert "günlük izlenme farkı N/A" in result
    assert "📈 Bugün: N/A (ilk ölçüm / karşılaştırılamıyor)" not in result or "📈 Bugün: ⚠️ Veri alınamadı" in result
    assert "Facebook: N/A (gecikmeli ölçüm) | Genel 125" in result
    assert "📈 Bugün: N/A (gecikmeli ölçüm)" in result
    assert "📈 BUGÜNKÜ TOPLAM: N/A (gecikmeli ölçüm)" in result
    assert read.call_args.args[1] == "2026-10-19"
    assert collect.call_args.kwargs["report_day"].isoformat() == "2026-10-20"
    assert all(call.args[2] == "2026-10-20" for call in progress.call_args_list)




def test_threads_snapshot_keeps_followers_when_video_insights_are_unavailable():
    import unittest
    from stats_reporter import threads_video_snapshot

    followers = Mock()
    replies = [
        {"data": [{"name": "followers_count", "total_value": {"value": 0}}]},
        {"data": []},
    ]
    with patch("threads_live_publish.account_config", return_value=Mock(token="test")), \
            patch("threads_live_publish.profile", return_value="1"), \
            patch("threads_live_publish.rows", return_value=[
                {"id": "2", "media_type": "TEXT_POST"},
                {"id": "3", "media_type": "VIDEO"},
            ]), patch("threads_live_publish.graph", side_effect=replies) as graph:
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "threads_video_views_unavailable"):
            threads_video_snapshot("film", on_followers=followers)
    followers.assert_called_once_with(0)
    assert [call.args[1] for call in graph.call_args_list] == ["1/threads_insights", "3/insights"]


def test_meta_publication_ledger_does_not_block_youtube_view_report(tmp_path, monkeypatch):
    import stats_reporter

    account = "🌱 Tarladaki Fasulye"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("META_ONLY_REPORTING", "true")
    monkeypatch.setenv("MULTIPLATFORM_STATS_ENABLED", "true")
    monkeypatch.setenv("ENGAGEMENT_HISTORY_ENABLED", "false")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(stats_reporter, "restore_history", lambda path: {"status": "first_snapshot"})
    monkeypatch.setattr(stats_reporter, "restore_publication_state", lambda: {})
    monkeypatch.setattr(stats_reporter, "ledger_progress", lambda *args: {
        "completed": 0, "failures": 0, "posts": 0, "expected_posts": 0, "platforms": {},
    })
    monkeypatch.setattr(stats_reporter, "_collect_snapshot", lambda now: (
        {(account, "YouTube"): {"video": {"views": 125}}}, [], [],
    ))
    report = stats_reporter.build_report(datetime(2026, 11, 4, 23, 55, tzinfo=ZoneInfo("Europe/Istanbul")))
    assert "YouTube: N/A (ilk ölçüm) | Genel 125\n  Yayın: ⚠️ sayaç alınamadı" in report
    assert report.comparison["accounts"][0]["platforms"][-1]["total"] == 125


def test_threads_optional_engagement_keeps_views_and_missing_metrics():
    from stats_reporter import threads_video_snapshot
    import threads_live_publish as api
    account = Mock(token="private")
    def graph(_host, path, _token, **params):
        if path.endswith("threads_insights"):
            return {"data": []}
        if params["metric"] == "views":
            return {"data": [{"name": "views", "values": [{"value": 12}]}]}
        return {"data": [{"name": "likes", "values": [{"value": 0}]},
                         {"name": "replies", "values": [{"value": 3}]}]}
    with patch.object(api, "account_config", return_value=account), patch.object(api, "profile", return_value="123456"), patch.object(api, "rows", return_value=[{"id": "1234567890", "media_type": "VIDEO"}]), patch.object(api, "graph", side_effect=graph):
        data = threads_video_snapshot("film", on_followers=Mock())
    assert data["1234567890"]["views"] == 12
    assert data["1234567890"]["engagement"] == {
        "likes": 0, "replies": 3, "reposts": None, "quotes": None, "shares": None}
    with patch.object(api, "account_config", return_value=account), patch.object(api, "profile", return_value="123456"), patch.object(api, "rows", return_value=[{"id": "1234567890", "media_type": "VIDEO"}]), patch.object(api, "graph", side_effect=[{}, {"data": [{"name": "views", "values": [{"value": 12}]}]}, RuntimeError("denied")]):
        data = threads_video_snapshot("film", on_followers=Mock())
    assert data["1234567890"]["views"] == 12
    assert all(value is None for value in data["1234567890"]["engagement"].values())


def test_threads_aggregation_never_sums_partial_metrics_as_complete():
    import stats_reporter as stats
    data = {"1": {"views": 1, "engagement": {"likes": 2, "replies": 0}},
            "2": {"views": 5, "engagement": {"likes": None, "replies": 0}}}
    with patch.dict(os.environ, {"MULTIPLATFORM_STATS_ENABLED": "true"}), patch.object(stats, "META_TARGETS", []), patch.object(stats, "YOUTUBE_TARGETS", []), patch.object(stats, "ACCOUNT_TARGETS", {"Film": (1, "film", "folder", [])}), patch.object(stats, "threads_video_snapshot", return_value=data):
        snapshot, records, errors = stats._collect_snapshot(datetime(2026, 11, 7, tzinfo=ZoneInfo("Europe/Istanbul")))
    metrics = {r["metric"]: r for r in records if r["entity_type"] == "account"}
    assert metrics["likes"]["value"] is None
    assert metrics["likes"]["status"] == "unavailable"
    assert metrics["replies"]["value"] == 0
    assert metrics["lifetime_views"]["value"] == 6
    assert not errors


def test_threads_unsupported_batch_metric_falls_back_without_losing_supported_counts():
    from stats_reporter import threads_video_snapshot
    import threads_live_publish as api
    response = Mock(status_code=400)
    response.json.return_value = {"error": {"code": 100}}
    def graph(_host, path, _token, **params):
        metric = params["metric"]
        if path.endswith("threads_insights"):
            return {}
        if "," in metric or metric == "shares":
            raise api.ProviderError("read", response)
        return {"data": [{"name": metric, "values": [{"value": 2}]}]}
    with patch.object(api, "account_config", return_value=Mock(token="private")), patch.object(api, "profile", return_value="123456"), patch.object(api, "rows", return_value=[{"id": "1234567890", "media_type": "VIDEO"}]), patch.object(api, "graph", side_effect=graph) as get:
        data = threads_video_snapshot("film", on_followers=Mock())
    assert data["1234567890"]["engagement"] == {"likes": 2, "replies": 2, "reposts": 2, "quotes": 2, "shares": None}
    assert get.call_count == 8



def test_facebook_view_snapshot_rejects_invalid_or_duplicate_records():
    from stats_reporter import facebook_video_snapshot

    page = {"page_id": "page", "page_token": "token"}
    with patch("stats_reporter.graph_pages", return_value=iter([
        {"id": "v1", "views": "12", "created_time": "2026-11-13T10:00:00+03:00"}
    ])):
        assert facebook_video_snapshot(page)["v1"]["views"] == 12

    for bad in (-1, True, 1.5, "bad", None):
        with patch("stats_reporter.graph_pages", return_value=iter([{"id": "v1", "views": bad}])):
            try:
                facebook_video_snapshot(page)
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"invalid Facebook counter accepted: {bad!r}")

    for rows in ([{"views": 1}], [{"id": "v1", "views": 1}, {"id": "v1", "views": 2}]):
        with patch("stats_reporter.graph_pages", return_value=iter(rows)):
            try:
                facebook_video_snapshot(page)
            except RuntimeError:
                pass
            else:
                raise AssertionError("missing or duplicate Facebook video ID accepted")


def test_instagram_view_snapshot_rejects_invalid_or_duplicate_records():
    from stats_reporter import instagram_video_snapshot

    page = {"instagram_id": "instagram", "page_token": "token"}
    video = {"id": "v1", "media_type": "VIDEO", "timestamp": "2026-11-13T10:00:00+03:00"}
    with patch("stats_reporter.graph_pages", return_value=iter([video])), patch(
        "stats_reporter.graph_get", return_value={"data": [{"name": "views", "value": "19"}]}
    ):
        assert instagram_video_snapshot(page)["v1"]["views"] == 19

    for bad in (-1, True, 1.5, "bad", None):
        with patch("stats_reporter.graph_pages", return_value=iter([video])), patch(
            "stats_reporter.graph_get", return_value={"data": [{"name": "views", "value": bad}]}
        ):
            try:
                instagram_video_snapshot(page)
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"invalid Instagram counter accepted: {bad!r}")

    with patch("stats_reporter.graph_pages", return_value=iter([video, video])), patch(
        "stats_reporter.graph_get", return_value={"data": [{"name": "views", "value": 19}]}
    ):
        try:
            instagram_video_snapshot(page)
        except RuntimeError:
            pass
        else:
            raise AssertionError("duplicate Instagram video ID accepted")
