"""Import only timestamped, current-run publication receipts into Neon.

This consumes the Meta publisher's own per-route result artifacts. It never
calls a social API, never infers historical publication times, and persists no
caption or token data.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import urlsplit

REPOSITORY = "emirhankaya985-cloud/auto-video-publisher"
WORKFLOW_NAME = "Public link Meta automation"
API = "https://api.github.com"

# Exact Neon source_key values. The two Film Facebook pages intentionally map
# through separate publisher routes even though they share one display name.
SOURCE_KEYS = {
    ("tarladaki", "facebook"): "c5858e349baa978e32a0e47fcc429e8e1225d50d92815192208a2ba141dec884",
    ("tarladaki", "instagram"): "83ca12a6e74bf8fb2d751ddb8fb6eafb97eb71c8f69c4a512c8df9a6a80f4320",
    ("penguen", "facebook"): "7dea55061348a1d5ca1d36278d70d85a1e632e3c872e224da8827107ad1212d0",
    ("penguen", "instagram"): "2bb97f2253e0c837a3f8429eac57d55b31c6cc97558923528abb78ae9e59658b",
    ("gonle", "facebook"): "76f38c99adda011c47338606c53dfc77b74f9d5b48ae7faadd29fbd4bf33623d",
    ("gonle", "instagram"): "2d4632636afd66cd89d183b7c23d8de1474e1141cf16bfc4358e6fdec0bd7f72",
    ("daily_laugh", "facebook"): "fcff98c9df6d6c9b0cf572fd92ca61ac36d62c4a6995b1e85cb63eb87ab7ec55",
    ("daily_laugh", "instagram"): "d579212638e6eba69fd50a4df818ec45a7bcaf667777d3ae9d36c9ff76373915",
    ("film", "facebook"): "d89554d0afef24f8505d60447c05f2403a00f09e6625bd977f5fe612fc2db18e",
    ("film_second", "facebook"): "d5594ff0546e044dcec4bba4b066bf0a359ac48cc608ed7f3c5897151598a05d",
    ("film", "instagram"): "833920d60bf9f35b0e0c1bf4284aa66016e5420261cb980bcfef4d38553b8f4e",
    ("toonzone", "facebook"): "b46f78fb4e5947be642712ffd5e382323b433719efe6b64c837a8ec60a81072f",
    ("toonzone", "instagram"): "1e01c58ae84478c573c108ae828b5f77ed982261f1c28e9e762da152567fa660",
}
ROUTES = tuple(sorted({route for route, _platform in SOURCE_KEYS}))
SAFE_FAILURE_REASONS = frozenset({
    "neon_database_url_missing", "wrong_neon_connection_scope",
    "untrusted_publisher_run", "publisher_run_not_trusted",
    "result_artifact_too_large", "result_artifact_shape_invalid",
    "artifact_redirect_not_https", "result_artifact_invalid",
    "result_state_invalid", "unknown_publisher_route",
    "publisher_artifact_list_invalid", "duplicate_publisher_route_artifact",
    "publisher_artifact_url_invalid", "current_run_publication_receipt_invalid",
    "current_run_publication_timestamp_missing",
    "conflicting_duplicate_publication_receipt", "wrong_neon_database",
})


def safe_failure_reason(exc: Exception) -> str:
    """Return only a fixed diagnostic; provider exceptions may contain URLs/secrets."""
    if isinstance(exc, ValueError) and str(exc) in SAFE_FAILURE_REASONS:
        return str(exc)
    return "sync_failed"


def _request(url: str, token: str, *, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "985-neon-publication-receipts",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _download_artifact(url: str, token: str) -> bytes:
    """Follow GitHub's artifact redirect without forwarding the API token."""
    class _StopRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "985-neon-publication-receipts",
    })
    try:
        opener = urllib.request.build_opener(_StopRedirect)
        with opener.open(req, timeout=30) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("result_artifact_too_large")
        return data
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise
        location = exc.headers.get("Location", "")
        if urlsplit(location).scheme != "https":
            raise ValueError("artifact_redirect_not_https") from None
    # The redirect target is a time-limited signed URL. Never send GH_TOKEN to it.
    with urllib.request.urlopen(location, timeout=90) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("result_artifact_too_large")
    return data


def trusted_run(run_id: str, token: str, *, repository: str) -> dict:
    if repository != REPOSITORY or not run_id.isdecimal() or not token:
        raise ValueError("untrusted_publisher_run")
    raw = _request(f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}", token)
    run = json.loads(raw)
    if (str(run.get("id")) != run_id or run.get("name") != WORKFLOW_NAME
            or run.get("path") != ".github/workflows/public_link_schedule.yml"
            or run.get("head_branch") != "main" or run.get("status") != "completed"
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or not run.get("head_sha")):
        raise ValueError("publisher_run_not_trusted")
    return run


def _state_from_zip(archive: bytes) -> dict:
    if len(archive) > 32 * 1024 * 1024:
        raise ValueError("result_artifact_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = [name for name in bundle.namelist()
                     if PurePosixPath(name).name == "state.json"]
            if len(names) != 1 or bundle.getinfo(names[0]).file_size > 32 * 1024 * 1024:
                raise ValueError("result_artifact_shape_invalid")
            state = json.loads(bundle.read(names[0]).decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("result_artifact_invalid") from None
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise ValueError("result_state_invalid")
    return state


def _published_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def receipt_rows(state: dict, *, route: str, source_run_id: str,
                 source_run_url: str) -> list[dict]:
    if route not in ROUTES:
        raise ValueError("unknown_publisher_route")
    rows = {}
    for entry in state["entries"].values():
        if not isinstance(entry, dict):
            continue
        if (entry.get("route") != route or entry.get("status") != "done"
                or str(entry.get("publication_run_id", "")) != source_run_id):
            continue
        platform = entry.get("platform")
        post_id = entry.get("post_id")
        occurred_at = _published_at(entry.get("published_at_utc"))
        source_key = SOURCE_KEYS.get((route, platform))
        if not source_key or not isinstance(post_id, str) or not re.fullmatch(r"[0-9]{1,128}", post_id):
            raise ValueError("current_run_publication_receipt_invalid")
        if occurred_at is None:
            raise ValueError("current_run_publication_timestamp_missing")
        filename = PurePosixPath(str(entry.get("file") or "")).name
        content_ref = f"{route}/{filename}" if filename else route
        row = {
            "source_key": source_key,
            "platform_post_id": post_id,
            "content_ref": content_ref[:512],
            "occurred_at": occurred_at,
            "details": {
                "source": "github_actions_link_state_result",
                "route": route,
                "platform": platform,
                "source_run_id": source_run_id,
                "source_run_url": source_run_url,
            },
        }
        key = (source_key, post_id)
        if key in rows and rows[key] != row:
            raise ValueError("conflicting_duplicate_publication_receipt")
        rows[key] = row
    return list(rows.values())


def artifact_rows(run_id: str, token: str, run: dict) -> list[dict]:
    raw = _request(f"{API}/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100", token)
    artifacts = json.loads(raw).get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("publisher_artifact_list_invalid")
    by_name = {a.get("name"): a for a in artifacts if isinstance(a, dict)}
    result = []
    for route in ROUTES:
        matches = [a for a in artifacts if isinstance(a, dict)
                   and a.get("name") == f"link-state-result-{route}"]
        if len(matches) > 1:
            raise ValueError("duplicate_publisher_route_artifact")
        artifact = matches[0] if matches else None
        if not artifact or artifact.get("expired"):
            continue
        download_url = artifact.get("archive_download_url")
        if not isinstance(download_url, str) or not download_url.startswith(API + "/"):
            raise ValueError("publisher_artifact_url_invalid")
        state = _state_from_zip(_download_artifact(download_url, token))
        result.extend(receipt_rows(
            state, route=route, source_run_id=run_id,
            source_run_url=str(run.get("html_url") or ""),
        ))
    unique = {}
    for row in result:
        key = (row["source_key"], row["platform_post_id"])
        if key in unique and unique[key] != row:
            raise ValueError("conflicting_duplicate_publication_receipt")
        unique[key] = row
    return list(unique.values())


def map_account_rows(rows: list[dict], account_pairs: list[tuple]) -> tuple[list[tuple], int]:
    by_key = defaultdict(list)
    for account_id, source_key in account_pairs:
        by_key[source_key].append(account_id)
    mapped, skipped = [], 0
    for row in rows:
        ids = by_key.get(row["source_key"], [])
        if len(ids) != 1:
            skipped += 1
            continue
        mapped.append((ids[0], row))
    return mapped, skipped


def ingest(conn, rows: list[dict]) -> tuple[int, int]:
    inserted = 0
    mapping_skipped = 0
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != "neondb":
            raise ValueError("wrong_neon_database")
        source_keys = sorted({row["source_key"] for row in rows})
        cur.execute("SELECT id,source_key FROM social_accounts WHERE source_key=ANY(%s)",
                    (source_keys,))
        mapped, mapping_skipped = map_account_rows(rows, cur.fetchall())
        for account_id, row in mapped:
            cur.execute("""INSERT INTO publication_events(
                    account_id, platform_post_id, content_ref, status, occurred_at, details)
                VALUES (%s,%s,%s,'published',%s,%s::jsonb)
                ON CONFLICT (account_id, platform_post_id) DO NOTHING""", (
                account_id, row["platform_post_id"], row["content_ref"],
                row["occurred_at"], json.dumps(row["details"], sort_keys=True),
            ))
            inserted += cur.rowcount
    return inserted, mapping_skipped


def main() -> int:
    run_id = os.getenv("SOURCE_RUN_ID", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "")
    db_url = os.getenv("DASHBOARD_DATABASE_URL", "").strip()
    try:
        if not db_url:
            raise ValueError("neon_database_url_missing")
        parsed = urlsplit(db_url)
        if (parsed.scheme not in {"postgres", "postgresql"}
                or not (parsed.hostname or "").endswith(".neon.tech")
                or parsed.path.lstrip("/") != "neondb"
                or not parsed.username or not parsed.password):
            raise ValueError("wrong_neon_connection_scope")
        run = trusted_run(run_id, token, repository=repository)
        rows = artifact_rows(run_id, token, run)
        if not rows:
            print(json.dumps({"status": "synced", "source_run_id": run_id,
                              "verified_receipts": 0, "inserted": 0,
                              "mapping_skipped": 0,
                              "timestamp_missing_historical_rows_imported": 0}, sort_keys=True))
            return 0
        import psycopg
        conn = psycopg.connect(db_url, connect_timeout=10, sslmode="require")
        try:
            inserted, mapping_skipped = ingest(conn, rows)
        finally:
            conn.close()
        print(json.dumps({"status": "synced", "source_run_id": run_id,
                          "verified_receipts": len(rows), "inserted": inserted,
                          "mapping_skipped": mapping_skipped,
                          "timestamp_missing_historical_rows_imported": 0}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "blocked", "reason": safe_failure_reason(exc),
                          "source_run_id": run_id}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
