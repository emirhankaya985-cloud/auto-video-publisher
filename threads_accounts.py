"""Per-account Threads secrets and identity settings. No network access here.

A token never falls back to a different account. Connection checks work before
a public video host is configured; posting requires its own additional gate.
"""
from dataclasses import dataclass
import os

THREADS_ROUTE_PREFIXES = {
    "tarladaki": "TARLADAKI",
    "penguen": "PENGUEN",
    "gonle": "GONLE",
    "daily_laugh": "DAILY_LAUGH",
    "film": "FILM",
    "toonzone": "TOONZONE",
}


@dataclass(frozen=True)
class ThreadsAccount:
    route: str
    token: str
    username: str
    expected_user_id: str
    video_url_template: str


def threads_route_enabled(route, *, environ=None):
    env = os.environ if environ is None else environ
    prefix = THREADS_ROUTE_PREFIXES.get(route)
    return bool(prefix and env.get(f"ENABLE_{prefix}_THREADS", "").strip().lower() == "true")


def threads_account_config(route, *, require_enabled=True, require_media=True, environ=None):
    env = os.environ if environ is None else environ
    prefix = THREADS_ROUTE_PREFIXES.get(route)
    if not prefix:
        raise ValueError("Bilinmeyen Threads hesabı.")
    if require_enabled and not threads_route_enabled(route, environ=env):
        raise RuntimeError(f"{route}: Threads yayın izni kapalı.")
    token = env.get(f"{prefix}_THREADS_ACCESS_TOKEN", "").strip()
    if route == "penguen" and not token:
        token = env.get("THREADS_ACCESS_TOKEN", "").strip()
    username = env.get(f"{prefix}_THREADS_USERNAME", "").strip().lstrip("@")
    expected_id = env.get(f"{prefix}_THREADS_USER_ID", "").strip()
    template = env.get(f"{prefix}_THREADS_VIDEO_URL_TEMPLATE", "").strip()
    missing = []
    if not token:
        missing.append(f"{prefix}_THREADS_ACCESS_TOKEN")
    if not username:
        missing.append(f"{prefix}_THREADS_USERNAME")
    if require_media and not template:
        missing.append(f"{prefix}_THREADS_VIDEO_URL_TEMPLATE")
    if missing:
        raise RuntimeError("Threads yapılandırması eksik: " + ", ".join(missing))
    if any(c.isspace() for c in token):
        raise RuntimeError("Threads token biçimi hatalı.")
    if template and not template.startswith("https://"):
        raise RuntimeError("Threads video URL şablonu HTTPS olmalı.")
    return ThreadsAccount(route, token, username, expected_id, template)


def threads_result_key(route):
    if route not in THREADS_ROUTE_PREFIXES:
        raise ValueError("Bilinmeyen Threads hesabı.")
    return "threads" if route == "penguen" else f"threads_{route}"
