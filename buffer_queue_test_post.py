"""Queue one explicitly confirmed Buffer test post on TarladaFasulye X."""
from __future__ import annotations

import json
import os
import sys

from buffer_connection_audit import (
    ACCOUNT_QUERY,
    CHANNEL_QUERY,
    BufferConnectionError,
    _post_graphql,
)


API_KEY_ENV = "BUFFER_API_KEY_1"
CONFIRM_ENV = "BUFFER_TEST_POST_CONFIRMED"
TARGET_CHANNEL_ID = "6b0836838541f09ecbafa822"
TARGET_CHANNEL_NAME = "TarladaFasulye"
TEST_TEXT = "Buffer bağlantı testi ✅ Otomatik paylaşım kuyruğu doğrulanıyor."
RECENT_POSTS_QUERY = """query RecentPosts($input: PostsInput!) {
  posts(first: 100, input: $input) {
    edges { node { id text dueAt status channelId } }
  }
}"""
QUEUE_POST_MUTATION = """mutation QueueBufferTestPost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id channelId dueAt status } }
    ... on MutationError { message }
  }
}"""


def _load_x_target(api_key, *, post=None):
    account_data = _post_graphql(api_key, ACCOUNT_QUERY, post=post)
    account = account_data.get("account")
    organizations = account.get("organizations") if isinstance(account, dict) else None
    if not isinstance(organizations, list):
        raise BufferConnectionError("organization_list_unavailable")
    matches = []
    for organization in organizations:
        organization_id = organization.get("id") if isinstance(organization, dict) else None
        if not isinstance(organization_id, str) or not organization_id:
            raise BufferConnectionError("organization_identity_unavailable")
        data = _post_graphql(api_key, CHANNEL_QUERY, {"organizationId": organization_id}, post=post)
        channels = data.get("channels")
        if not isinstance(channels, list):
            raise BufferConnectionError("channel_list_unavailable")
        for channel in channels:
            if not isinstance(channel, dict):
                raise BufferConnectionError("invalid_channel_record")
            if (channel.get("id") == TARGET_CHANNEL_ID
                    and str(channel.get("name", "")).casefold() == TARGET_CHANNEL_NAME.casefold()
                    and str(channel.get("service", "")).casefold() in {"twitter", "x"}):
                matches.append((organization_id, channel))
    if len(matches) != 1:
        raise BufferConnectionError("target_x_channel_missing_or_ambiguous")
    organization_id, channel = matches[0]
    if channel.get("isDisconnected") is not False:
        raise BufferConnectionError("target_x_channel_disconnected")
    if channel.get("isQueuePaused") is not False:
        raise BufferConnectionError("target_x_queue_paused_or_unknown")
    return organization_id, channel


def queue_test_post(api_key, confirmed, *, post=None):
    if not confirmed:
        raise BufferConnectionError("explicit_queue_confirmation_required")
    if not isinstance(api_key, str) or not api_key.strip():
        raise BufferConnectionError("api_key_missing")
    api_key = api_key.strip()
    organization_id, channel = _load_x_target(api_key, post=post)
    posts_data = _post_graphql(
        api_key,
        RECENT_POSTS_QUERY,
        {"input": {"organizationId": organization_id,
                   "filter": {"channelIds": [TARGET_CHANNEL_ID]}}},
        post=post,
    )
    posts_result = posts_data.get("posts")
    edges = posts_result.get("edges") if isinstance(posts_result, dict) else None
    if not isinstance(edges, list):
        raise BufferConnectionError("recent_posts_unavailable")
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict) and node.get("text") == TEST_TEXT:
            return {
                "status": "already_queued",
                "post_id": node.get("id"),
                "channel": TARGET_CHANNEL_NAME,
                "due_at": node.get("dueAt"),
                "posting_performed": False,
            }

    result = _post_graphql(
        api_key,
        QUEUE_POST_MUTATION,
        {"input": {
            "text": TEST_TEXT,
            "channelId": channel["id"],
            "schedulingType": "automatic",
            "mode": "addToQueue",
            "source": "buffer-connection-test",
        }},
        post=post,
    )
    payload = result.get("createPost")
    if not isinstance(payload, dict) or not isinstance(payload.get("post"), dict):
        # Never echo a provider message into logs; response bodies are untrusted.
        raise BufferConnectionError("queue_creation_failed")
    created = payload["post"]
    if created.get("channelId") != TARGET_CHANNEL_ID or not created.get("id"):
        raise BufferConnectionError("queue_creation_response_mismatch")
    return {
        "status": "queued",
        "post_id": created["id"],
        "channel": TARGET_CHANNEL_NAME,
        "due_at": created.get("dueAt"),
        "posting_performed": True,
    }


def main():
    result = queue_test_post(
        os.environ.get(API_KEY_ENV, ""),
        os.environ.get(CONFIRM_ENV, "").strip().lower() == "true",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Buffer X queue test\n\n")
            summary.write(f"Status: `{result['status']}`; channel: `{result['channel']}`\n\n")
            summary.write(f"Buffer post ID: `{result['post_id']}`; next slot: `{result['due_at'] or 'unknown'}`\n\n")
            summary.write("One test message was added to the existing Buffer queue; no other posts were changed.\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BufferConnectionError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1)
