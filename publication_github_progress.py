"""Read-only publication progress from the publisher's authoritative ledger."""
from __future__ import annotations

import io
import json
import os
import zipfile

import requests

REPOSITORY = "emirhankaya985-cloud/auto-video-publisher"
MAX_BYTES = 20 * 1024 * 1024


def restore_publication_state(*, token=None, get=None):
    """Load newest main ledger; never silently replace missing history with zero."""
    token = os.getenv("GITHUB_TOKEN", "") if token is None else token
    if not token:
        raise RuntimeError("GitHub publication token unavailable")
    get = get or requests.get
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{REPOSITORY}/actions/"
    rows = []
    try:
        for name in ("link-state-result", "link-state-intent"):
            for page in range(1, 21):
                response = get(base + "artifacts", headers=headers,
                               params={"name": name, "per_page": 100, "page": page},
                               timeout=25, allow_redirects=False)
                if response.status_code != 200:
                    raise RuntimeError("GitHub publication listing unavailable")
                payload = response.json()
                batch = payload.get("artifacts") if isinstance(payload, dict) else None
                if not isinstance(batch, list):
                    raise RuntimeError("GitHub publication listing invalid")
                for row in batch:
                    if not isinstance(row, dict):
                        raise RuntimeError("GitHub publication listing invalid")
                    run = row.get("workflow_run") or {}
                    if (row.get("name") == name and row.get("expired") is False
                            and isinstance(run, dict) and run.get("head_branch") == "main"
                            and type(run.get("id")) is int and type(row.get("id")) is int):
                        rows.append(row)
                if len(batch) < 100:
                    break
            else:
                raise RuntimeError("GitHub publication pagination incomplete")
        if not rows:
            raise RuntimeError("GitHub publication history unavailable")
        latest = max(rows, key=lambda r: (r["workflow_run"]["id"],
                                         r["name"] == "link-state-result", r["id"]))
        response = get(base + f"artifacts/{latest['id']}/zip", headers=headers,
                       timeout=45, allow_redirects=True)
        if response.status_code != 200 or len(response.content) > MAX_BYTES:
            raise RuntimeError("GitHub publication download unavailable")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            if len(names) != 1 or names[0] != "state.json":
                raise RuntimeError("GitHub publication archive invalid")
            if archive.getinfo(names[0]).file_size > MAX_BYTES:
                raise RuntimeError("GitHub publication archive too large")
            state = json.loads(archive.read(names[0]))
        if (not isinstance(state, dict) or state.get("schema") != 1
                or not isinstance(state.get("entries"), dict)
                or any(not isinstance(row, dict) for row in state["entries"].values())):
            raise RuntimeError("GitHub publication state invalid")
        return state
    except (requests.RequestException, ValueError, TypeError, KeyError, OSError,
            zipfile.BadZipFile) as exc:
        raise RuntimeError(f"GitHub publication state unavailable ({type(exc).__name__})") from None


def ledger_progress(state, route, day, target):
    """Count unique confirmed posts and fulfilled daily platform quotas.

    Completion means every destination reached that many slots; independent
    destination queues need not publish identical source files.
    """
    mapping = {("film", "facebook"): "fb_film_1",
               ("film_second", "facebook"): "fb_film_2",
               ("film", "instagram"): "ig"} if route == "film" else {
                   (route, "facebook"): "fb", (route, "instagram"): "ig"}
    platforms = {key: {"success": 0, "failure": 0, "uncertain": 0,
                       "latest_slot": None, "latest_status": "N/A"}
                 for key in mapping.values()}
    post_sources = {key: {} for key in platforms}
    failed_sources, uncertain_sources = set(), set()
    for entry_key, row in state["entries"].items():
        key = mapping.get((row.get("route"), row.get("platform")))
        if key is None or row.get("day") != day:
            continue
        parts = str(entry_key).split(":", 2)
        if len(parts) != 3 or parts[:2] != [row.get("route"), row.get("platform")]:
            continue
        source = str(row.get("duplicate_of_file_id") or parts[2])
        status = row.get("status")
        post = str(row.get("post_id") or "").strip()
        slot = str(row.get("slot") or row.get("day"))
        platform = platforms[key]
        if status == "done" and post:
            post_sources[key].setdefault(post, set()).add(source)
            label = "başarılı"
        elif status in {"failed", "failure", "error"} or (status == "ready" and row.get("failure")):
            platform["failure"] += 1
            failed_sources.add(source)
            label = "başarısız"
        elif status in {"uncertain", "intent", "pending"} or status == "done":
            platform["uncertain"] += 1
            uncertain_sources.add(source)
            label = "sonuç belirsiz"
        else:
            continue
        if platform["latest_slot"] is None or slot >= platform["latest_slot"]:
            platform.update(latest_slot=slot, latest_status=label)
    for key, groups in post_sources.items():
        platforms[key]["success"] = len(groups)
    completed = min(target, min(p["success"] for p in platforms.values()))
    return {"target": target, "completed": completed,
            "posts": sum(p["success"] for p in platforms.values()),
            "expected_posts": target * len(platforms), "failures": len(failed_sources),
            "uncertain": len(uncertain_sources), "platforms": platforms,
            "completion_basis": "per_platform_quota"}
