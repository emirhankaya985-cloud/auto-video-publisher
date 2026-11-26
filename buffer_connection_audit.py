"""Read-only Buffer connection audit. This module never creates or changes posts."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests


API_URL = "https://api.buffer.com"
API_KEY_ENV = "BUFFER_API_KEY_1"
TIMEOUT_SECONDS = 20
ACCOUNT_QUERY = "query { account { id organizations { id } } }"
CHANNEL_QUERY = """query BufferChannels($organizationId: OrganizationId!) {
  channels(input: { organizationId: $organizationId }) {
    id name displayName service isDisconnected isQueuePaused
  }
}"""
X_SERVICES = {"twitter", "x"}


class BufferConnectionError(RuntimeError):
    """Safe error with no provider body, request headers, or credential material."""


def _post_graphql(api_key: str, query: str, variables=None, *, post=None):
    post = post or requests.post
    try:
        response = post(
            API_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise BufferConnectionError(f"network_error:{type(exc).__name__}") from None
    if response.status_code == 401:
        raise BufferConnectionError("unauthorized")
    if response.status_code == 403:
        raise BufferConnectionError("forbidden_or_scope_missing")
    if not response.ok:
        raise BufferConnectionError(f"http_error:{response.status_code}")
    try:
        body = response.json()
    except (ValueError, AttributeError):
        raise BufferConnectionError("invalid_json") from None
    if not isinstance(body, dict):
        raise BufferConnectionError("invalid_response")
    errors = body.get("errors")
    if errors:
        code = None
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            extensions = errors[0].get("extensions")
            if isinstance(extensions, dict):
                candidate = extensions.get("code")
                if isinstance(candidate, str) and re.fullmatch(r"[A-Z0-9_]{1,40}", candidate):
                    code = candidate
        raise BufferConnectionError(f"graphql_error:{code or 'unknown'}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise BufferConnectionError("missing_data")
    return data


def audit(api_key: str, *, post=None):
    if not isinstance(api_key, str) or not api_key.strip():
        raise BufferConnectionError("api_key_missing")
    account_data = _post_graphql(api_key.strip(), ACCOUNT_QUERY, post=post)
    account = account_data.get("account")
    organizations = account.get("organizations") if isinstance(account, dict) else None
    if not isinstance(organizations, list):
        raise BufferConnectionError("organization_list_unavailable")

    x_channels = []
    for organization in organizations:
        organization_id = organization.get("id") if isinstance(organization, dict) else None
        if not isinstance(organization_id, str) or not organization_id.strip():
            raise BufferConnectionError("organization_identity_unavailable")
        data = _post_graphql(
            api_key.strip(), CHANNEL_QUERY,
            {"organizationId": organization_id}, post=post,
        )
        channels = data.get("channels")
        if not isinstance(channels, list):
            raise BufferConnectionError("channel_list_unavailable")
        for channel in channels:
            if not isinstance(channel, dict):
                raise BufferConnectionError("invalid_channel_record")
            service = channel.get("service")
            if not isinstance(service, str) or service.strip().casefold() not in X_SERVICES:
                continue
            channel_id = channel.get("id")
            name = channel.get("name")
            if not isinstance(channel_id, str) or not channel_id.strip() or not isinstance(name, str):
                raise BufferConnectionError("x_channel_identity_unavailable")
            x_channels.append({
                "channel_id": channel_id,
                "name": name,
                "display_name": channel.get("displayName"),
                "service": service,
                "connected": channel.get("isDisconnected") is False,
                "queue_paused": channel.get("isQueuePaused"),
            })

    return {
        "status": "connected" if x_channels else "connected_no_x_channels",
        "organization_count": len(organizations),
        "x_channel_count": len(x_channels),
        "x_channels": x_channels,
        "posting_performed": False,
    }


def main():
    key = os.environ.get(API_KEY_ENV, "")
    result = audit(key)
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(rendered)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write("## Buffer read-only connection check\n\n")
            summary.write(f"Status: `{result['status']}`; X channels: {result['x_channel_count']}\n\n")
            for channel in result["x_channels"]:
                connected = "connected" if channel["connected"] else "disconnected"
                paused = "yes" if channel["queue_paused"] is True else (
                    "no" if channel["queue_paused"] is False else "unknown"
                )
                summary.write(
                    f"- {channel['name']} (`{channel['channel_id']}`): {connected}; queue paused: {paused}\n"
                )
            summary.write("\nNo posts were created, queued, edited, or deleted.\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BufferConnectionError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1)
