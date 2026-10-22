import os
import re
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests
from googleapiclient.errors import HttpError

import analytics_sheets as sheets_export


def record(day, *, account="Film Mağarası", platform="Instagram", metric="view_count",
           value=10, entity="video-1", entity_type="video", published="2026-10-18T09:00:00+03:00",
           status="ok"):
    return {
        "measured_at": f"{day}T23:00:00+03:00", "timezone": "Europe/Istanbul",
        "account": account, "platform": platform, "entity_type": entity_type,
        "entity_id": entity, "published_at": published, "metric": metric,
        "value": value, "unit": "views", "period": day, "source_api": "mock.api",
        "source_metric": "views", "status": status,
    }


def test_account_rows_cover_brands_platforms_and_separate_film_pages():
    rows = sheets_export._account_rows()
    film_fb = [row for row in rows if row[1] in {"Film Mağarası", "Filmmagrasi"} and row[2] == "Facebook"]
    assert len(film_fb) == 2
    assert {row[1] for row in film_fb} == {"Film Mağarası", "Filmmagrasi"}
    assert {row[1] for row in rows} == {
        "Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen", "Daily Laugh Lab",
        "Film Mağarası", "Filmmagrasi", "ToonZone",
    }
    assert sum(row[2] == "Threads" for row in rows) == 6
    film_threads = next(row for row in rows if row[1:3] == ["Film Mağarası", "Threads"])
    assert film_threads[3:6] == ["film_magrasi", "@film_magrasi", "28752898447698066"]


def test_summary_tabs_identify_their_data_sources():
    assert "veri_kaynağı" in sheets_export.HEADERS["PANEL"]
    assert "veri_kaynağı" in sheets_export.HEADERS["HESAP TOPLAMLARI"]
    tables = sheets_export.build_tables([], [], now=datetime(2026, 10, 20, 12, tzinfo=ZoneInfo("Europe/Istanbul")))
    assert all(row[-1] == "daily_video_views.jsonl + Google Drive appProperties"
               for tab in ("PANEL", "HESAP TOPLAMLARI") for row in tables[tab])


def test_daily_and_lifetime_views_are_separate_and_negative_delta_is_unavailable():
    rows, summaries = sheets_export._daily_metric_rows([
        record("2026-10-18", value=20),
        record("2026-10-19", value=17),
        record("2026-10-18", metric="lifetime_views", value=20, entity="Film Mağarası", entity_type="account"),
        record("2026-10-19", metric="lifetime_views", value=17, entity="Film Mağarası", entity_type="account"),
        record("2026-10-19", metric="snapshot_status", value=1, entity="Film Mağarası", entity_type="account"),
    ])
    daily = [row for row in rows if row[7] == "daily_views" and row[6] == "video-1"]
    assert daily[-1][8] == "N/A"
    assert daily[-1][13] == "unavailable"
    assert summaries[("Film Mağarası", "Instagram")]["total"] == 17


def test_thirty_day_growth_and_threads_style_followers_count_are_supported():
    records = [
        record("2026-09-20", value=100, published="2026-09-01T09:00:00+03:00"),
        record("2026-09-20", metric="snapshot_status", value=1, entity="Film Mağarası", entity_type="account"),
        record("2026-10-20", value=150, published="2026-09-01T09:00:00+03:00"),
        record("2026-10-20", metric="snapshot_status", value=1, entity="Film Mağarası", entity_type="account"),
        record("2026-10-20", metric="followers_count", value=42, entity="Film Mağarası", entity_type="account"),
    ]
    _rows, summaries = sheets_export._daily_metric_rows(records)
    summary = summaries[("Film Mağarası", "Instagram")]
    assert summary["monthly"] == 50
    assert summary["followers"] == 42



def test_missing_old_video_invalidates_daily_seven_and_thirty_day_growth():
    """A smaller 'successful' API inventory is not evidence of complete totals."""
    records = []
    for day, survivor_views, old_views in (
        ("2026-09-20", 10, 5), ("2026-10-13", 20, 8),
        ("2026-10-19", 50, 15),
    ):
        records.extend([
            record(day, entity="survivor", value=survivor_views, published="2026-09-01T09:00:00+03:00"),
            record(day, entity="gone", value=old_views, published="2026-09-01T09:00:00+03:00"),
            record(day, metric="snapshot_status", value=2, entity="Film Mağarası", entity_type="account"),
        ])
    records.extend([
        record("2026-10-20", entity="survivor", value=60,
               published="2026-09-01T09:00:00+03:00"),
        record("2026-10-20", metric="snapshot_status", value=1,
               entity="Film Mağarası", entity_type="account"),
        record("2026-10-20", metric="lifetime_views", value=60,
               entity="Film Mağarası", entity_type="account"),
    ])
    rows, summaries = sheets_export._daily_metric_rows(records)
    summary = summaries[("Film Mağarası", "Instagram")]
    assert summary["daily"]["2026-10-20"] is None
    assert summary["weekly"] is None
    assert summary["monthly"] is None
    assert summary["total"] is None
    account_daily = next(row for row in rows if row[7] == "daily_views"
                         and row[5] == "account" and row[2] == "2026-10-20")
    assert account_daily[8] == "N/A"
    assert account_daily[13] == "unavailable"

    tables = sheets_export.build_tables(records, [], now=datetime(
        2026, 10, 20, 23, tzinfo=ZoneInfo("Europe/Istanbul")))
    totals = next(row for row in tables["HESAP TOPLAMLARI"]
                  if row[2:4] == ["Film Mağarası", "Instagram"])
    assert totals[4] == "N/A"
    assert totals[5] == "N/A"
    assert totals[7:9] == ["N/A", "N/A"]


def test_genuine_new_video_keeps_complete_daily_and_weekly_gains():
    records = [
        record("2026-10-13", entity="survivor", value=100, published="2026-09-01T09:00:00+03:00"),
        record("2026-10-13", metric="snapshot_status", value=1,
               entity="Film Mağarası", entity_type="account"),
        record("2026-10-19", entity="survivor", value=110, published="2026-09-01T09:00:00+03:00"),
        record("2026-10-19", metric="snapshot_status", value=1,
               entity="Film Mağarası", entity_type="account"),
        record("2026-10-20", entity="survivor", value=120, published="2026-09-01T09:00:00+03:00"),
        record("2026-10-20", entity="new", value=3, published="2026-10-20T11:00:00+03:00"),
        record("2026-10-20", metric="snapshot_status", value=2,
               entity="Film Mağarası", entity_type="account"),
    ]
    _rows, summaries = sheets_export._daily_metric_rows(records)
    summary = summaries[("Film Mağarası", "Instagram")]
    assert summary["daily"]["2026-10-20"] == 13
    assert summary["weekly"] == 23


def test_daily_gain_can_decrease_without_implying_negative_video_views():
    # Daily gained views: 100 yesterday and 30 today means a valid -70
    # change in *daily gain*, not a negative number of total views.
    records = [
        record("2026-10-18", value=100),
        record("2026-10-18", metric="snapshot_status", value=1,
               entity="Film Mağarası", entity_type="account"),
        record("2026-10-19", value=200),
        record("2026-10-19", metric="snapshot_status", value=1,
               entity="Film Mağarası", entity_type="account"),
        record("2026-10-20", value=230),
        record("2026-10-20", metric="snapshot_status", value=1,
               entity="Film Mağarası", entity_type="account"),
        record("2026-10-20", metric="lifetime_views", value=230,
               entity="Film Mağarası", entity_type="account"),
    ]
    tables = sheets_export.build_tables(records, [], now=datetime(
        2026, 10, 20, 23, tzinfo=ZoneInfo("Europe/Istanbul")))
    row = next(item for item in tables["HESAP TOPLAMLARI"]
               if item[2:4] == ["Film Mağarası", "Instagram"])
    assert row[4] == 230
    assert row[5] == 30
    assert row[6] == -70

def test_missing_metrics_render_na_not_zero():
    tables = sheets_export.build_tables([], [], now=datetime(2026, 10, 20, 12, tzinfo=ZoneInfo("Europe/Istanbul")))
    penguen_ig = next(row for row in tables["HESAP TOPLAMLARI"] if row[2:4] == ["Beyinsiz Penguen", "Instagram"])
    assert penguen_ig[4:10] == ["N/A"] * 6
    assert penguen_ig[10:12] == ["N/A", "N/A"]
    assert "N/A" in next(row for row in tables["PANEL"] if row[1:3] == ["Beyinsiz Penguen", "Instagram"])


def test_film_facebook_pages_are_separately_attributed_in_publication_rows():
    drive = Mock()
    drive.files.return_value.list.return_value.execute.return_value = {
        "files": [{
            "id": "drive-file", "name": "clip.mp4", "mimeType": "video/mp4",
            "appProperties": {
                "done_fb_film_1_slot": "2026-10-20-10-film", "result_fb_film_1": "12345678",
                "done_fb_film_2_slot": "2026-10-20-10-film", "result_fb_film_2": "87654321",
            },
        }],
    }
    with patch.dict(os.environ, {"FILM_DRIVE_FOLDER_ID": "film-folder"}, clear=True):
        publications, _errors, _evidence, counts = sheets_export._drive_publications(drive, "2026-10-20")
    assert {row[1] for row in publications} == {"Film Mağarası", "Filmmagrasi"}
    assert counts[("Film Mağarası", "Facebook")]["total"] == 1
    assert counts[("Filmmagrasi", "Facebook")]["total"] == 1


def test_permalink_drops_query_fragment_and_rejects_signed_or_unknown_hosts():
    assert sheets_export.safe_public_url("https://www.instagram.com/reel/abc/?token=secret#x") == "https://www.instagram.com/reel/abc/"
    assert sheets_export.safe_public_url("https://evil.example/post/abc") == "N/A"
    assert sheets_export.safe_public_url("https://drive.google.com/uc?id=x&token=secret") == "N/A"
    assert sheets_export.safe_public_url("https://www.youtube.com/watch?v=abcdefghijk&token=secret") == "https://www.youtube.com/watch?v=abcdefghijk"


class FakeRequest:
    def __init__(self, callback):
        self.callback = callback

    def execute(self, **_kwargs):
        return self.callback()


class FakeValues:
    def __init__(self):
        self.data = {}
        self.write_calls = 0

    def get(self, spreadsheetId, range, valueRenderOption=None):
        title = range.split("!", 1)[0].strip("'")
        return FakeRequest(lambda: {"values": self.data.get(title, [])})

    def update(self, spreadsheetId, range, valueInputOption, body):
        title, cell = range.split("!", 1)
        title = title.strip("'")
        start = int(re.search(r"\d+", cell).group(0) if re.search(r"\d+", cell) else "1")
        values = body["values"]
        def update():
            self.write_calls += 1
            rows = self.data.setdefault(title, [])
            while len(rows) < start - 1 + len(values):
                rows.append([])
            for idx, row in enumerate(values, start=start - 1):
                rows[idx] = row
            return {}
        return FakeRequest(update)

    def batchUpdate(self, spreadsheetId, body):
        def update():
            self.write_calls += 1
            for entry in body["data"]:
                title, cell = entry["range"].split("!", 1)
                title = title.strip("'")
                start = int(re.search(r"\d+", cell).group(0) if re.search(r"\d+", cell) else "1")
                rows = self.data.setdefault(title, [])
                while len(rows) < start:
                    rows.append([])
                rows[start - 1] = entry["values"][0]
            return {}
        return FakeRequest(update)


def test_retry_is_idempotent_and_does_not_append_duplicate_rows():
    values = FakeValues()
    header = ("kayıt_anahtarı", "değer")
    data = [["event-1", 17], ["event-1", 17]]
    # Exercise the value-range upsert separately with a minimal fake facade.
    class Sheet:
        def spreadsheets(self):
            return self
        def values(self):
            return values
    sheet = Sheet()
    assert sheets_export._sync_tab(sheet, "id", "T", header, data) == (0, 1)
    writes_after_insert = values.write_calls
    assert sheets_export._sync_tab(sheet, "id", "T", header, data) == (0, 0)
    assert values.write_calls == writes_after_insert
    assert values.data["T"] == [list(header), ["event-1", 17]]


def test_locale_formatted_numbers_do_not_cause_repeat_writes():
    # A Turkish-locale Sheets response formats RAW number 1234 as "1.234"
    # by default, leading to a needless update unless UNFORMATTED is used.
    class LocaleValues(FakeValues):
        def __init__(self):
            super().__init__()
            self.render_modes = []

        def get(self, spreadsheetId, range, valueRenderOption=None):
            self.render_modes.append(valueRenderOption)
            if valueRenderOption != "UNFORMATTED_VALUE":
                return FakeRequest(lambda: {
                    "values": [["key", "views"], ["event-1", "1.234"]]
                })
            return super().get(spreadsheetId, range,
                               valueRenderOption=valueRenderOption)

    values = LocaleValues()
    values.data["T"] = [["key", "views"], ["event-1", 1234]]

    class Sheet:
        def spreadsheets(self):
            return self

        def values(self):
            return values

    result = sheets_export._sync_tab(
        Sheet(), "synthetic-id", "T",
        ("key", "views"), [["event-1", 1234]]
    )
    assert result == (0, 0)
    assert values.write_calls == 0
    assert values.render_modes == ["UNFORMATTED_VALUE"]


def test_sheet_header_mismatch_fails_closed():
    values = FakeValues()
    values.data["T"] = [["wrong", "header"]]
    class Sheet:
        def spreadsheets(self):
            return self
        def values(self):
            return values
    try:
        sheets_export._sync_tab(Sheet(), "id", "T", ("key", "value"), [])
    except RuntimeError as exc:
        assert "header mismatch" in str(exc)
    else:
        raise AssertionError("expected fail-closed schema check")



def test_later_tab_header_mismatch_prevents_all_earlier_writes():
    # HESAPLAR is checked before creating tabs or updating PANEL.
    values = FakeValues()
    values.data["PANEL"] = [list(sheets_export.HEADERS["PANEL"])]
    values.data["HESAPLAR"] = [["unexpected", "columns"]]

    class Sheet:
        def spreadsheets(self):
            return self

        def get(self, spreadsheetId, fields):
            return FakeRequest(lambda: {"sheets": [
                {"properties": {"title": "PANEL"}},
                {"properties": {"title": "HESAPLAR"}},
            ]})

        def values(self):
            return values

    with patch("analytics_sheets._ensure_tabs") as create_tabs, patch(
        "analytics_sheets._sync_tab"
    ) as write_tab:
        try:
            sheets_export.sync_tables(Sheet(), "id", {"PANEL": []})
        except RuntimeError as exc:
            assert "sheet header mismatch: HESAPLAR" in str(exc)
        else:
            raise AssertionError("expected preflight to reject HESAPLAR")
    create_tabs.assert_not_called()
    write_tab.assert_not_called()
    assert values.write_calls == 0


def test_valid_existing_headers_pass_preflight_then_sync():
    values = FakeValues()
    values.data["PANEL"] = [list(sheets_export.HEADERS["PANEL"])]

    class Sheet:
        def spreadsheets(self):
            return self

        def get(self, spreadsheetId, fields):
            return FakeRequest(lambda: {"sheets": [
                {"properties": {"title": "PANEL"}},
            ]})

        def values(self):
            return values

    with patch("analytics_sheets._ensure_tabs") as create_tabs, patch(
        "analytics_sheets._sync_tab", return_value=(0, 0)
    ) as write_tab:
        outcome = sheets_export.sync_tables(Sheet(), "id", {"PANEL": []})
    create_tabs.assert_called_once()
    assert write_tab.call_count == len(sheets_export.HEADERS)
    assert outcome["PANEL"] == (0, 0)


def test_duplicate_keys_in_later_tab_prevent_earlier_tab_writes():
    values = FakeValues()
    values.data["PANEL"] = [list(sheets_export.HEADERS["PANEL"])]
    values.data["HESAPLAR"] = [
        list(sheets_export.HEADERS["HESAPLAR"]),
        ["record-1"], ["record-1"],
    ]

    class Sheet:
        def spreadsheets(self):
            return self

        def get(self, spreadsheetId, fields):
            return FakeRequest(lambda: {"sheets": [
                {"properties": {"title": "PANEL"}},
                {"properties": {"title": "HESAPLAR"}},
            ]})

        def values(self):
            return values

    with patch("analytics_sheets._ensure_tabs") as create_tabs, patch(
        "analytics_sheets._sync_tab"
    ) as write_tab:
        try:
            sheets_export.sync_tables(Sheet(), "id", {})
        except RuntimeError as exc:
            assert "duplicate existing sheet record key: HESAPLAR" in str(exc)
        else:
            raise AssertionError("expected duplicate key preflight failure")
    create_tabs.assert_not_called()
    write_tab.assert_not_called()
    assert values.write_calls == 0


def test_duplicate_existing_sheet_keys_fail_closed_without_writing():
    values = FakeValues()
    values.data["T"] = [["key", "value"], ["duplicate", 1], ["duplicate", 2]]

    class Sheet:
        def spreadsheets(self):
            return self

        def values(self):
            return values

    try:
        sheets_export._sync_tab(Sheet(), "id", "T", ("key", "value"),
                                [["duplicate", 3]])
    except RuntimeError as exc:
        assert "duplicate existing sheet record key: T" in str(exc)
    else:
        raise AssertionError("expected duplicate record key validation")
    assert values.write_calls == 0


def test_http_429_uses_bounded_retry_without_logging_body():
    response = Mock(status=429)
    response.get.return_value = "0"
    error = HttpError(response, b'{"error":{"message":"secret must not be printed"}}')
    request = Mock()
    request.execute.side_effect = [error, {"ok": True}]
    waits = []
    assert sheets_export._execute_with_retry(request, sleep=waits.append) == {"ok": True}
    assert waits == [1]
    assert request.execute.call_count == 2


def test_http_503_uses_bounded_retry():
    response = Mock(status=503)
    response.get.return_value = "0"
    error = HttpError(response, b"temporary backend failure")
    request = Mock()
    request.execute.side_effect = [error, {"ok": True}]
    waits = []
    assert sheets_export._execute_with_retry(request, sleep=waits.append) == {"ok": True}
    assert waits == [1]


def test_github_api_error_is_sanitized_and_does_not_echo_bearer():
    token = "ghs_secret_example"
    with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}), patch(
        "analytics_sheets.requests.get", side_effect=requests.ConnectionError(token)
    ) as get:
        runs, status = sheets_export._github_runs(token, datetime(2026, 10, 20, tzinfo=ZoneInfo("UTC")))
    assert runs == []
    assert status == "error_transport_or_parse"
    assert token not in status
    assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {token}"


def test_github_runs_are_paginated_for_a_retryable_rolling_window():
    first = Mock(status_code=200)
    first.raise_for_status.return_value = None
    first.json.return_value = {"total_count": 101, "workflow_runs": [{"id": n} for n in range(100)]}
    second = Mock(status_code=200)
    second.raise_for_status.return_value = None
    second.json.return_value = {"total_count": 101, "workflow_runs": [{"id": 100}]}
    with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}), patch(
        "analytics_sheets.requests.get", side_effect=[first, second]
    ) as get:
        runs, status = sheets_export._github_runs("test-token", datetime(2026, 10, 20, tzinfo=ZoneInfo("UTC")))
    assert len(runs) == 101
    assert status == "ok"
    assert get.call_count == 2
    assert get.call_args_list[0].kwargs["params"]["page"] == 1
    assert get.call_args_list[1].kwargs["params"]["page"] == 2
    assert get.call_args_list[0].kwargs["params"]["created"] == ">=2026-09-20"


def test_github_get_retries_transient_503_without_exposing_token():
    token = "ghs_do_not_log_this"
    failed = Mock(status_code=503, headers={"Retry-After": "0"})
    successful = Mock(status_code=200)
    successful.raise_for_status.return_value = None
    successful.json.return_value = {"total_count": 0, "workflow_runs": []}
    waits = []
    with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}), patch(
        "analytics_sheets.requests.get", side_effect=[failed, successful]
    ) as get:
        runs, status = sheets_export._github_runs(token, datetime(2026, 10, 20, tzinfo=ZoneInfo("UTC")))
    assert runs == []
    assert status == "ok"
    assert get.call_count == 2
    assert token not in status


def test_dry_run_never_constructs_or_calls_sheets_client():
    with patch.dict(os.environ, {}, clear=True), patch(
        "analytics_sheets.get_drive_client", side_effect=RuntimeError("not configured")
    ), patch("analytics_sheets._sheets_client") as make_sheets:
        result = sheets_export.run_sync(write=False, github_runs=[])
    assert result["mode"] == "dry-run"
    assert result["writes"] == 0
    make_sheets.assert_not_called()


def test_unconfigured_write_mode_is_disabled_before_sheets_api_call():
    with patch.dict(os.environ, {}, clear=True), patch(
        "analytics_sheets.load_archive_records", return_value=([], "ok")
    ), patch("analytics_sheets._drive_publications", return_value=([], [], [], {})), patch(
        "analytics_sheets._sheets_client"
    ) as make_sheets:
        result = sheets_export.run_sync(write=True, drive=Mock(), github_runs=[])
    assert result["mode"] == "disabled"
    assert result["writes"] == 0
    make_sheets.assert_not_called()


def test_write_mode_skips_all_sheet_calls_when_drive_archive_fails():
    settings = {
        "ANALYTICS_SHEET_ID": "A" * 35,
        "ANALYTICS_SHEETS_CREDENTIALS_JSON": '{"type":"service_account"}',
    }
    for status, records in [
        ("archive_file_not_found", []),
        ("error", []),
        ("ok", []),  # A structurally empty archive is not a complete snapshot.
    ]:
        with patch.dict(os.environ, settings, clear=True), patch(
            "analytics_sheets.load_archive_records", return_value=(records, status)
        ), patch("analytics_sheets._drive_publications", return_value=([], [], [], {})), patch(
            "analytics_sheets._sheets_client"
        ) as make_client, patch("analytics_sheets.sync_tables") as write_tables:
            result = sheets_export.run_sync(write=True, drive=Mock(), github_runs=[])
        assert result["mode"] == "source_unavailable"
        assert result["writes"] == 0
        make_client.assert_not_called()
        write_tables.assert_not_called()


def test_write_mode_skips_all_sheet_calls_when_github_api_fails():
    settings = {
        "ANALYTICS_SHEET_ID": "A" * 35,
        "ANALYTICS_SHEETS_CREDENTIALS_JSON": '{"type":"service_account"}',
    }
    records = [record("2026-10-20")]
    with patch.dict(os.environ, settings, clear=True), patch(
        "analytics_sheets.load_archive_records", return_value=(records, "ok")
    ), patch("analytics_sheets._drive_publications", return_value=([], [], [], {})), patch(
        "analytics_sheets.collect_github_runs", return_value=([], "error_http_503")
    ), patch("analytics_sheets._sheets_client") as make_client, patch(
        "analytics_sheets.sync_tables"
    ) as write_tables:
        result = sheets_export.run_sync(write=True, drive=Mock())
    assert result["mode"] == "source_unavailable"
    assert result["github_status"] == "error_http_503"
    assert result["writes"] == 0
    make_client.assert_not_called()
    write_tables.assert_not_called()


def test_source_failure_still_allows_safe_dry_run_preview():
    settings = {
        "ANALYTICS_SHEET_ID": "A" * 35,
        "ANALYTICS_SHEETS_CREDENTIALS_JSON": '{"type":"service_account"}',
    }
    with patch.dict(os.environ, settings, clear=True), patch(
        "analytics_sheets.load_archive_records", return_value=([], "error")
    ), patch("analytics_sheets._drive_publications", return_value=([], [], [], {})), patch(
        "analytics_sheets._sheets_client"
    ) as make_client:
        result = sheets_export.run_sync(write=False, drive=Mock(), github_runs=[])
    assert result["mode"] == "dry-run"
    assert result["writes"] == 0
    make_client.assert_not_called()


def test_source_unavailable_signals_actions_failure():
    with patch("analytics_sheets.run_sync", return_value={
        "mode": "source_unavailable", "writes": 0, "archive_status": "error",
        "github_status": "ok"
    }):
        assert sheets_export.main(["--write"]) == 1


def test_invalid_spreadsheet_id_fails_closed_before_sheets_api_call():
    with patch.dict(os.environ, {"ANALYTICS_SHEET_ID": "not a real id", "ANALYTICS_SHEETS_CREDENTIALS_JSON": "{}"}, clear=True), patch(
        "analytics_sheets.load_archive_records", return_value=([], "ok")
    ), patch("analytics_sheets._drive_publications", return_value=([], [], [], {})), patch(
        "analytics_sheets._sheets_client"
    ) as make_sheets:
        result = sheets_export.run_sync(write=True, drive=Mock(), github_runs=[])
    assert result["mode"] == "disabled"
    assert result["reason"] == "spreadsheet id format invalid"
    make_sheets.assert_not_called()
