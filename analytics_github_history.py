"""Restore the last Meta analytics snapshot from GitHub Actions artifacts.

Read-only restore; uploading is handled by the non-publishing daily_stats workflow.
A missing first archive is not the same as a failed API request.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import requests

REPOSITORY = "emirhankaya985-cloud/auto-video-publisher"
ARTIFACT_NAME = "meta-daily-analytics-history"
HISTORY_FILE = "daily_video_views.jsonl"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024


def restore_history(target: str | Path, *, token: str | None = None,
                    get=None) -> dict:
    """Restore a previous scheduled report's history, or return first-run status.

    Raises a sanitized RuntimeError if the API or existing artifact is
    inaccessible. Callers must NOT replace the last known archive after that.
    """
    token = os.getenv("GITHUB_TOKEN", "") if token is None else token
    if not token:
        raise RuntimeError("GitHub archive token unavailable")
    get = requests.get if get is None else get
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    endpoint = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts"
    try:
        response = get(endpoint, headers=headers,
                       params={"name": ARTIFACT_NAME, "per_page": 100},
                       timeout=25, allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError("GitHub archive listing unavailable")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
            raise RuntimeError("GitHub archive listing invalid")
        artifacts = payload["artifacts"]
        if len(artifacts) >= 100 or payload.get("total_count", 0) > 100:
            raise RuntimeError("GitHub archive history pagination incomplete")
        matching = [
            row for row in artifacts
            if isinstance(row, dict) and row.get("name") == ARTIFACT_NAME
            and row.get("expired") is False
            and isinstance(row.get("workflow_run"), dict)
            and row["workflow_run"].get("head_branch") == "main"
            and row["workflow_run"].get("id") != _current_run_id()
            and type(row.get("id")) is int and row["id"] > 0
        ]
        if not matching:
            if any(not isinstance(row, dict) for row in artifacts):
                raise RuntimeError("GitHub archive listing invalid")
            return {"status": "first_snapshot", "source_run": None}
        latest = max(matching, key=lambda row: row.get("created_at") or "")
        archive_url = (f"https://api.github.com/repos/{REPOSITORY}/actions/"
                       f"artifacts/{latest['id']}/zip")
        # GitHub returns a short-lived redirect to artifact storage. Requests
        # removes GitHub authorization when following a cross-host redirect.
        result = get(archive_url, headers=headers, timeout=45, allow_redirects=True)
        if result.status_code != 200 or len(result.content) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("GitHub archive download unavailable")
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            names = archive.namelist()
            if names != [HISTORY_FILE]:
                raise RuntimeError("GitHub archive file layout invalid")
            if archive.getinfo(HISTORY_FILE).file_size > MAX_ARCHIVE_BYTES:
                raise RuntimeError("GitHub archive exceeds size limit")
            raw = archive.read(HISTORY_FILE)
        # Validate the structure before making any changes to the target.
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("GitHub archive exceeds size limit")
        for line in raw.decode("utf-8").splitlines():
            if line.strip() and not isinstance(json.loads(line), dict):
                raise RuntimeError("GitHub archive history row invalid")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {"status": "restored", "source_run": latest["workflow_run"]["id"]}
    except (requests.RequestException, ValueError, UnicodeError, KeyError,
            zipfile.BadZipFile, OSError, TypeError) as exc:
        raise RuntimeError(f"GitHub archive could not be verified ({type(exc).__name__})") from None


def _current_run_id():
    value = os.getenv("GITHUB_RUN_ID", "")
    return int(value) if value.isdecimal() else None
