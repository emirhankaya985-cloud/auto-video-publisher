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
X_ACCOUNT_KEYS = (
    "tarladaki",
    "gonle",
    "penguen",
    "daily_laugh",
    "film",
    "toonzone",
)
CHANNEL_MAPPING_ENV = "BUFFER_X_CHANNELS_JSON"


class BufferConnectionError(RuntimeError):
    """Safe error with no provider body, request headers, or credential material."""


def validate_channel_mapping(raw_mapping, x_channels):
    """Validate account-to-channel IDs against an already-read X channel inventory.

    This is intentionally pure: it makes no provider requests and never queues posts.
    The JSON object maps the six stable account keys to Buffer channel IDs.
    """
    if not isinstance(raw_mapping, str) or not raw_mapping.strip():
        return {
            "status": "not_configured",
            "reason": "mapping_variable_missing",
            "missing_accounts": list(X_ACCOUNT_KEYS),
            "accounts": {},
        }
    try:
        mapping = json.loads(raw_mapping)
    except (TypeError, ValueError):
        return {"status": "invalid", "reason": "invalid_json", "missing_accounts": [], "accounts": {}}
    if not isinstance(mapping, dict):
        return {"status": "invalid", "reason": "mapping_must_be_object", "missing_accounts": [], "accounts": {}}
    unknown = sorted(key for key in mapping if key not in X_ACCOUNT_KEYS)
    malformed = any(not isinstance(key, str) or not isinstance(value, str) or not value.strip()
                    for key, value in mapping.items())
    if unknown or malformed:
        return {
            "status": "invalid",
            "reason": "unknown_account_key" if unknown else "channel_id_must_be_nonempty_string",
            "unknown_accounts": unknown,
            "missing_accounts": [key for key in X_ACCOUNT_KEYS if key not in mapping],
            "accounts": {},
        }
    channel_ids = [value.strip() for value in mapping.values()]
    if len(channel_ids) != len(set(channel_ids)):
        return {"status": "invalid", "reason": "duplicate_configured_channel_id",
                "missing_accounts": [key for key in X_ACCOUNT_KEYS if key not in mapping], "accounts": {}}

    accounts = {}
    inventory = x_channels if isinstance(x_channels, list) else []
    for account_key, channel_id in mapping.items():
        matches = [channel for channel in inventory
                   if isinstance(channel, dict) and channel.get("channel_id") == channel_id.strip()]
        if not matches:
            accounts[account_key] = {"status": "channel_not_found"}
        elif len(matches) != 1:
            accounts[account_key] = {"status": "ambiguous_channel_id"}
        elif matches[0].get("connected") is not True:
            accounts[account_key] = {"status": "disconnected", "channel_name": matches[0].get("name")}
        else:
            accounts[account_key] = {
                "status": "connected",
                "channel_id": channel_id.strip(),
                "channel_name": matches[0].get("name"),
                "queue_paused": matches[0].get("queue_paused"),
            }
    missing = [key for key in X_ACCOUNT_KEYS if key not in mapping]
    complete = not missing and all(value["status"] == "connected" for value in accounts.values())
    return {
        "status": "complete" if complete else "incomplete",
        "reason": None if complete else "mapping_or_channel_health_incomplete",
        "missing_accounts": missing,
        "accounts": accounts,
    }


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


def audit(api_key: str, *, post=None, channel_mapping_json=None):
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

    result = {
        "status": "connected" if x_channels else "connected_no_x_channels",
        "organization_count": len(organizations),
        "x_channel_count": len(x_channels),
        "x_channels": x_channels,
        "posting_performed": False,
    }
    result["channel_mapping"] = validate_channel_mapping(channel_mapping_json, x_channels)
    return result


def main():
    key = os.environ.get(API_KEY_ENV, "")
    result = audit(key, channel_mapping_json=os.environ.get(CHANNEL_MAPPING_ENV, ""))
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
            mapping = result["channel_mapping"]
            summary.write(f"\nAccount mapping: `{mapping['status']}`\n")
            for account_key in mapping.get("missing_accounts", []):
                summary.write(f"- {account_key}: channel mapping missing\n")
            for account_key, account in mapping.get("accounts", {}).items():
                channel_name = account.get("channel_name") or "unresolved"
                summary.write(f"- {account_key}: {account['status']} ({channel_name})\n")
            summary.write("\nNo posts were created, queued, edited, or deleted.\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BufferConnectionError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1)
