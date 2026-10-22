"""Small, opt-in client for publishing Penguen videos to the Threads API.

Threads video posts require a publicly reachable HTTPS video URL. This module
does not upload local files or change their sharing permissions; callers must
provide a URL from an explicitly configured media host.
"""
import os
import time
from urllib.parse import quote

import requests


THREADS_API_BASE = "https://graph.threads.net/v1.0"


def threads_configured():
    """Return true only when the Penguen Threads route is explicitly enabled."""
    return (
        os.getenv("ENABLE_PENGUEN_THREADS", "false").strip().lower() == "true"
        and bool(os.getenv("THREADS_ACCESS_TOKEN", "").strip())
        and bool(os.getenv("PENGUEN_THREADS_USERNAME", "").strip())
        and bool(os.getenv("PENGUEN_THREADS_VIDEO_URL_TEMPLATE", "").strip())
    )


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def validate_threads_identity(*, token=None, expected_username=None,
                              session=requests, timeout=20):
    """Read-only check that the bearer token belongs to the expected profile."""
    token = (token if token is not None else os.getenv("THREADS_ACCESS_TOKEN", "")).strip()
    expected_username = (expected_username if expected_username is not None else os.getenv("PENGUEN_THREADS_USERNAME", "")).strip().lstrip("@").casefold()
    if not token or not expected_username:
        raise RuntimeError("Threads bağlantı denetimi için token ve Penguen kullanıcı adı gerekli.")
    response = session.get(
        f"{THREADS_API_BASE}/me", params={"fields": "id,username"},
        headers=_auth_headers(token), timeout=timeout,
    )
    response.raise_for_status()
    identity = response.json()
    user_id = str(identity.get("id") or "")
    username = str(identity.get("username") or "").lstrip("@")
    if not user_id or username.casefold() != expected_username:
        raise RuntimeError("Threads token beklenen Beyinsiz Penguen hesabıyla eşleşmedi.")
    return {"id": user_id, "username": username}


def build_threads_video_url(template, file_id, filename):
    """Expand a configured public media-host URL without exposing it to logs."""
    url = template.format(file_id=quote(str(file_id), safe=""), filename=quote(str(filename), safe=""))
    if not url.startswith("https://"):
        raise ValueError("Threads video URL template must produce an HTTPS URL.")
    return url


def publish_threads_video(video_url, text, *, token=None, expected_username=None,
                          session=requests, poll_interval=5, timeout=20,
                          max_polls=120):
    """Create, wait for, and publish one video post; returns the Threads ID.

    No automatic retry is performed for create/publish calls because their
    outcome can be ambiguous after a network failure.
    """
    token = (token if token is not None else os.getenv("THREADS_ACCESS_TOKEN", "")).strip()
    expected_username = (expected_username if expected_username is not None else os.getenv("PENGUEN_THREADS_USERNAME", "")).strip()
    if not token or not expected_username:
        raise RuntimeError("Threads bağlantısı eksik: THREADS_ACCESS_TOKEN ve Penguen Threads kullanıcı adı gerekli.")
    if not isinstance(video_url, str) or not video_url.startswith("https://"):
        raise ValueError("Threads videosu için herkese açık HTTPS video URL'si gerekli.")

    headers = _auth_headers(token)
    identity = validate_threads_identity(
        token=token, expected_username=expected_username,
        session=session, timeout=timeout,
    )
    user_id = identity["id"]

    response = session.post(
        f"{THREADS_API_BASE}/{user_id}/threads",
        params={"media_type": "VIDEO", "video_url": video_url, "text": text},
        headers=headers, timeout=timeout,
    )
    response.raise_for_status()
    container_id = response.json().get("id")
    if not container_id:
        raise RuntimeError("Threads API container yanıtında ID yok.")

    for attempt in range(max_polls):
        status_response = session.get(
            f"{THREADS_API_BASE}/{container_id}",
            params={"fields": "status,status_code"}, headers=headers, timeout=timeout,
        )
        status_response.raise_for_status()
        status = status_response.json().get("status")
        if status == "FINISHED":
            break
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Threads video container reached terminal status: {status}.")
        if attempt + 1 < max_polls:
            time.sleep(poll_interval)
    else:
        raise TimeoutError("Threads video container did not finish before the polling limit.")

    publish_response = session.post(
        f"{THREADS_API_BASE}/{user_id}/threads_publish",
        params={"creation_id": container_id}, headers=headers, timeout=timeout,
    )
    publish_response.raise_for_status()
    post_id = publish_response.json().get("id")
    if not post_id:
        raise RuntimeError("Threads publish yanıtında gönderi ID'si yok.")
    return post_id
