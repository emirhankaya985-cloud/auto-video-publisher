"""Refresh an uncertain Instagram upload's container phase with a safe GET."""
from datetime import datetime, timezone
import re

import requests

from cloud_omnichannel_publisher import GRAPH_API_VERSION


PRE_PUBLISH_STAGES = frozenset({
    "Instagram ikili video aktarımı",
    "Instagram video işleme durumu",
})
KNOWN_STATUSES = frozenset({
    "FINISHED", "ERROR", "EXPIRED", "IN_PROGRESS", "PUBLISHED",
})


def refresh_pre_publish_container_status(route, entry, page, *, history_reconciled=False, get=None):
    """Return a fresh container status and update only diagnostic state.

    This is intentionally GET-only. Call only after remote post history has
    been fetched successfully. The publisher's retry classifier still decides
    whether a terminal status is eligible for another binary upload.
    """
    if (history_reconciled is not True
            or not isinstance(entry, dict) or not isinstance(page, dict)):
        return None
    failure = entry.get("failure")
    if not isinstance(failure, dict):
        return None
    container_id = str(failure.get("container_id") or "")
    if (entry.get("route") != route
            or entry.get("platform") != "instagram"
            or entry.get("status") != "uncertain"
            or failure.get("stage") not in PRE_PUBLISH_STAGES
            or failure.get("http_status") != 400
            or entry.get("container_publish_attempted")
            or not re.fullmatch(r"[0-9]{8,32}", container_id)
            or not str(page.get("page_id") or "").isdecimal()
            or not str(page.get("instagram_id") or "").isdecimal()
            or not page.get("page_token")):
        return None
    # Re-check only statuses that may be stale or inconclusive. Terminal
    # states already feed the existing classifier and need no extra API call.
    if failure.get("container_status") not in {None, "", "UNKNOWN", "UNVERIFIED", "IN_PROGRESS"}:
        return None

    binding = entry.get("container_resume")
    if isinstance(binding, dict) and str(binding.get("container_id")) != container_id:
        return None

    get = get or requests.get
    try:
        response = get(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}",
            headers={"Authorization": "Bearer " + page["page_token"]},
            params={"fields": "id,status_code,status"}, timeout=20,
            allow_redirects=False,
        )
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None
    if (response.status_code != 200 or not isinstance(payload, dict)
            or payload.get("error")
            or str(payload.get("id", container_id)) != container_id):
        return None
    status = payload.get("status_code") or payload.get("status")
    if not isinstance(status, str) or status not in KNOWN_STATUSES:
        return None

    # Keep a timestamped observation; do not infer publication from container
    # status and do not erase any existing intent or publication history.
    failure["container_status"] = status
    failure["container_status_checked_at_utc"] = datetime.now(timezone.utc).isoformat()
    return status
