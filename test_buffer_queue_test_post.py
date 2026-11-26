import unittest
from unittest.mock import Mock

from buffer_connection_audit import API_URL, BufferConnectionError
from buffer_queue_test_post import (
    TEST_TEXT,
    TARGET_CHANNEL_ID,
    queue_test_post,
)


def response(data):
    return Mock(status_code=200, ok=True, json=lambda: {"data": data})


def read_setup(*, queue_paused=False):
    return [
        response({"account": {"organizations": [{"id": "org-test"}]}}),
        response({"channels": [{
            "id": TARGET_CHANNEL_ID, "name": "TarladaFasulye", "service": "twitter",
            "isDisconnected": False, "isQueuePaused": queue_paused,
        }]}),
    ]


class BufferQueueTestPostTests(unittest.TestCase):
    def test_requires_explicit_confirmation_before_any_request(self):
        post = Mock()
        with self.assertRaisesRegex(BufferConnectionError, "explicit_queue_confirmation_required"):
            queue_test_post("key", False, post=post)
        post.assert_not_called()

    def test_queues_one_fixed_test_post_in_existing_queue(self):
        key = "secret-test-key"
        responses = read_setup() + [
            response({"posts": {"edges": []}}),
            response({"createPost": {"post": {
                "id": "post-test", "channelId": TARGET_CHANNEL_ID,
                "dueAt": "2026-11-27T05:57:00Z", "status": "scheduled",
            }}}),
        ]
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return responses.pop(0)

        result = queue_test_post(key, True, post=post)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["post_id"], "post-test")
        self.assertEqual(result["channel"], "TarladaFasulye")
        self.assertTrue(result["posting_performed"])
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(url == API_URL for url, _ in calls))
        self.assertNotIn(key, str(result))
        mutation = calls[-1][1]["json"]["query"]
        self.assertIn("mutation QueueBufferTestPost", mutation)
        variables = calls[-1][1]["json"]["variables"]["input"]
        self.assertEqual(variables["channelId"], TARGET_CHANNEL_ID)
        self.assertEqual(variables["text"], TEST_TEXT)
        self.assertEqual(variables["mode"], "addToQueue")
        self.assertEqual(variables["schedulingType"], "automatic")

    def test_existing_test_post_is_not_duplicated(self):
        responses = read_setup() + [response({"posts": {"edges": [{"node": {
            "id": "existing-post", "text": TEST_TEXT,
            "dueAt": "2026-11-27T05:57:00Z", "status": "scheduled",
            "channelId": TARGET_CHANNEL_ID,
        }}]}})]
        calls = []

        def post(url, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        result = queue_test_post("key", True, post=post)

        self.assertEqual(result["status"], "already_queued")
        self.assertEqual(result["post_id"], "existing-post")
        self.assertFalse(result["posting_performed"])
        self.assertEqual(len(calls), 3)

    def test_paused_queue_fails_before_post_creation(self):
        responses = read_setup(queue_paused=True)
        post = Mock(side_effect=responses)
        with self.assertRaisesRegex(BufferConnectionError, "target_x_queue_paused_or_unknown"):
            queue_test_post("key", True, post=post)
        self.assertEqual(post.call_count, 2)

    def test_graphql_errors_do_not_leak_provider_text_or_key(self):
        key = "private-key"
        responses = read_setup() + [Mock(status_code=200, ok=True, json=lambda: {
            "errors": [{"message": f"do not reveal {key}", "extensions": {"code": "FORBIDDEN"}}]
        })]
        post = Mock(side_effect=responses)
        with self.assertRaises(BufferConnectionError) as caught:
            queue_test_post(key, True, post=post)
        self.assertEqual(str(caught.exception), "graphql_error:FORBIDDEN")
        self.assertNotIn(key, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
