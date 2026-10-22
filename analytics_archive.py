"""Provider-neutral analytics archive with idempotent daily snapshot upserts.

This module deliberately performs no API calls and no publishing. Collectors can
store whatever a provider actually returns without inventing missing metrics.
JSONL is the canonical durable format; CSV is an optional human-readable export.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

SCHEMA = (
    "measured_at", "timezone", "account", "platform", "entity_type",
    "entity_id", "published_at", "metric", "value", "unit", "period", "source_api",
    "source_metric", "status",
)


def make_record(*, measured_at: str, timezone: str, account: str,
                platform: str, entity_type: str, metric: str,
                value: Any = None, unit: str | None = None,
                period: str | None = None, source_api: str | None = None,
                source_metric: str | None = None, entity_id: str | None = None,
                published_at: str | None = None,
                status: str = "ok") -> dict[str, Any]:
    if status not in {"ok", "unavailable", "error"}:
        raise ValueError("status must be ok, unavailable or error")
    return {"measured_at": measured_at, "timezone": timezone,
            "account": account, "platform": platform,
            "entity_type": entity_type, "entity_id": entity_id,
            "published_at": published_at,
            "metric": metric, "value": value, "unit": unit,
            "period": period, "source_api": source_api,
            "source_metric": source_metric, "status": status}


def append_records(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    """Append records once; identical records are not duplicated."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.dumps(json.loads(line), sort_keys=True, ensure_ascii=False))
    added = 0
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            missing = set(SCHEMA) - set(record)
            if missing:
                raise ValueError(f"missing archive fields: {sorted(missing)}")
            key = json.dumps(record, sort_keys=True, ensure_ascii=False)
            if key in existing:
                continue
            handle.write(key + "\n")
            existing.add(key)
            added += 1
    return added


def upsert_records(path: str | Path, records: Iterable[dict[str, Any]],
                   *, preserve_success_on_failure: bool = False) -> int:
    """Idempotently upsert daily records, optionally preserving last valid runs.

    The daily reporter enables this flag so an API failure on a same-day rerun
    cannot replace earlier valid views with missing/errored values.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    key_fields = ("period", "account", "platform", "entity_type", "entity_id", "metric")
    existing = {}
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for column in SCHEMA:
                row.setdefault(column, None)
            existing[tuple(row.get(field) for field in key_fields)] = row
    incoming = list(records)
    # Group success and failure are account/platform snapshots, not just
    # individual rows. If a rerun has failed or reports fewer videos than a
    # previous successful same-day run, keep that whole group's last valid
    # records instead of mixing a new smaller lifetime total with old videos.
    failed_groups = set()
    if preserve_success_on_failure:
        for record in incoming:
            if record.get("entity_type") != "account" or record.get("metric") != "snapshot_status":
                continue
            key = tuple(record.get(field) for field in key_fields)
            old = existing.get(key)
            if not old or old.get("status") != "ok":
                continue
            new_count, old_count = record.get("value"), old.get("value")
            try:
                inventory_shrank = (new_count is None or old_count is None or
                                    int(new_count) < int(old_count))
            except (ValueError, TypeError):
                inventory_shrank = True
            if record.get("status") != "ok" or inventory_shrank:
                failed_groups.add((record.get("period"), record.get("account"),
                                   record.get("platform")))
    changed = 0
    for record in incoming:
        missing = set(SCHEMA) - set(record)
        if missing:
            raise ValueError(f"missing archive fields: {sorted(missing)}")
        key = tuple(record.get(field) for field in key_fields)
        if preserve_success_on_failure:
            group = (record.get("period"), record.get("account"), record.get("platform"))
            if group in failed_groups:
                continue
            old = existing.get(key)
            if (old and old.get("status") == "ok" and record.get("status") != "ok"):
                continue
        if existing.get(key) != record:
            existing[key] = record
            changed += 1
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for row in existing.values():
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return changed


def export_csv(jsonl_path: str | Path, csv_path: str | Path) -> int:
    """Export the canonical archive to an Excel-compatible UTF-8 CSV."""
    rows = []
    for line in Path(jsonl_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    target = Path(csv_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
