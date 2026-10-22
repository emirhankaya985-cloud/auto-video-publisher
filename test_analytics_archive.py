from analytics_archive import append_records, export_csv, make_record, upsert_records


def test_archive_is_append_only_and_idempotent(tmp_path):
    record = make_record(measured_at="2026-10-15T12:00:00+03:00", timezone="Europe/Istanbul",
                         account="Tarladaki Fasulye", platform="youtube",
                         entity_type="account", metric="view_count", value=1234,
                         unit="views", period="snapshot", source_api="youtube.data.v3",
                         source_metric="statistics.viewCount")
    path = tmp_path / "archive.jsonl"
    assert append_records(path, [record, record]) == 1
    assert append_records(path, [record]) == 0
    csv_path = tmp_path / "archive.csv"
    assert export_csv(path, csv_path) == 1
    assert "view_count" in csv_path.read_text(encoding="utf-8-sig")


def test_daily_snapshot_upsert_replaces_same_video_without_duplicates(tmp_path):
    path = tmp_path / "daily.jsonl"
    base = dict(measured_at="2026-10-19T23:59:00+03:00", timezone="Europe/Istanbul",
                account="acct", platform="YouTube", entity_type="video", entity_id="v1",
                published_at="2026-10-01T00:00:00Z", metric="view_count", unit="views",
                period="2026-10-19", source_api="youtube.data.v3", source_metric="viewCount")
    first = make_record(**base, value=100)
    later = make_record(**base, value=120)
    assert upsert_records(path, [first]) == 1
    assert upsert_records(path, [later]) == 1
    assert upsert_records(path, [later]) == 0
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert '"value": 120' in rows[0]
