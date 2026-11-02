"""Owner-only Telegram control helpers. No polling or publishing on import."""
import io
import json
import os
import zipfile
from datetime import datetime, timezone

import requests

REPO = "emirhankaya985-cloud/auto-video-publisher"
API = "https://api.github.com/repos/" + REPO


def headers(token):
    if not token or not isinstance(token, str) or any(c in token for c in "\r\n"):
        raise RuntimeError("GitHub credential missing")
    return {"Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json"}


def toggle_schedule(enable, *, session=requests):
    """Write only existing scheduler variable; verify by GET; no retry."""
    if type(enable) is not bool:
        raise ValueError("Boolean required")
    if os.getenv("TELEGRAM_CONTROL_ENABLED", "false").lower() != "true":
        raise RuntimeError("Telegram schedule control not enabled")
    auth = headers(os.getenv("GITHUB_CONTROL_TOKEN", ""))
    url = API + "/actions/variables/LINK_AUTOMATION_ENABLED"
    requested = "true" if enable else "false"
    try:
        changed = session.patch(url, headers=auth,
                                json={"name": "LINK_AUTOMATION_ENABLED",
                                      "value": requested},
                                timeout=15, allow_redirects=False)
        if changed.status_code != 204:
            raise RuntimeError("Schedule change rejected")
        checked = session.get(url, headers=auth, timeout=15,
                              allow_redirects=False)
        if checked.status_code != 200 or checked.json().get("value") != requested:
            raise RuntimeError("Schedule change unverified")
    except requests.RequestException:
        raise RuntimeError("Schedule status unknown") from None
    return ("Planlı otomasyon etkin; içerik/hak ve yayın kilitleri korunuyor."
            if enable else "Planlı otomasyon kapalı; devam eden işler ayrıca denetlenmeli.")


def stock_summary(*, session=requests):
    """Inspect latest successful main publisher operations stock ZIP, read-only."""
    auth = headers(os.getenv("GITHUB_TOKEN", ""))
    response = session.get(API + "/actions/workflows/public_link_schedule.yml/runs",
                           headers=auth,
                           params={"branch": "main", "status": "success", "per_page": 5},
                           timeout=20, allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError("Verified stock runs unavailable")
    for run in response.json().get("workflow_runs", []):
        if (run.get("head_branch") != "main" or run.get("conclusion") != "success"
                or type(run.get("id")) is not int):
            continue
        result = session.get(API + f"/actions/runs/{run['id']}/artifacts",
                             headers=auth, timeout=20, allow_redirects=False)
        if result.status_code != 200:
            continue
        matches = [x for x in result.json().get("artifacts", [])
                   if x.get("name") == "publication-operations"
                   and x.get("expired") is False and type(x.get("id")) is int]
        if len(matches) != 1:
            continue
        result = session.get(API + f"/actions/artifacts/{matches[0]['id']}/zip",
                             headers=auth, timeout=30, allow_redirects=True)
        if result.status_code != 200 or len(result.content) > 8_000_000:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
                info = archive.getinfo("content-stock.json")
                if info.file_size > 250_000:
                    continue
                data = json.loads(archive.read(info))
            if (not isinstance(data, dict) or not isinstance(data.get('accounts'), list)
                    or not isinstance(data.get('measured_at'), str)):
                continue
            lines = ["Son başarılı stok ölçümü: " + data['measured_at']]
            for row in data['accounts'][:15]:
                if not isinstance(row, dict):
                    continue
                n = row.get("remaining")
                count = str(n) if type(n) is int else "N/A"
                lines.append(f"{str(row.get('account','?'))[:45]} / {str(row.get('platform','N/A'))[:15]}: {count} aday")
            if len(lines) > 1:
                lines.append("Yalnızca aday içerikler; kesin yayın garantisi değildir.")
                return "\n".join(lines)
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile):
            continue
    raise RuntimeError("Verified stock artifact unavailable")
