import unittest
from datetime import datetime, timezone

from buffer_x import (BufferClient, BufferError, CHANNELS, CREATE_POST_MUTATION,
                      check_channel_allowlist, fingerprint, validate_media_url)


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}

    def json(self):
        return self._body


class BufferClientTests(unittest.TestCase):
    def test_missing_api_key_fails_closed(self):
        with self.assertRaisesRegex(BufferError, "api_key_missing"):
            BufferClient("")

    def test_discovery_only_returns_x_services(self):
        responses = [FakeResponse(body={"data": {"account": {"organizations": [{"id": "org1"}]}}}),
                     FakeResponse(body={"data": {"channels": [
                         {"id": "x1", "service": "twitter", "isDisconnected": False, "isLocked": False},
                         {"id": "ig1", "service": "instagram"}]}})]
        client = BufferClient("not-a-real-secret", post=lambda *a, **k: responses.pop(0))
        self.assertEqual([c["id"] for c in client.discover_x_channels()], ["x1"])

    def test_401_and_429_are_classified_without_body_leak(self):
        for response, code, retry in [(FakeResponse(401), "api_key_invalid", None),
                                      (FakeResponse(429, headers={"Retry-After": "37"}), "rate_limited", 37)]:
            client = BufferClient("secret", post=lambda *a, _r=response, **k: _r)
            with self.assertRaises(BufferError) as caught:
                client.graphql("query { account { id } }")
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.retry_after, retry)
            self.assertNotIn("secret", str(caught.exception))

    def test_rate_limit_header_windows_are_parsed(self):
        from buffer_x import parse_rate_limit_headers
        values = parse_rate_limit_headers({"RateLimit": '"150-in-15min";r=120;t=60, "600-in-1day";r=590;t=3600, "3000-in-30days";r=2990;t=1000'})
        self.assertEqual(values["15m_remaining"], 120)
        self.assertEqual(values["24h_remaining"], 590)
        self.assertEqual(values["30d_remaining"], 2990)

    def test_video_payload_uses_documented_graphql_shape_and_timing(self):
        seen = {}
        def fake_post(url, **kwargs):
            seen.update(kwargs)
            return FakeResponse(body={"data": {"createPost": {"__typename": "PostActionSuccess",
                "post": {"id": "p1", "status": "scheduled", "channelId": "x1"}}}})
        client = BufferClient("secret", post=fake_post)
        post, _ = client.create_video_post(channel_id="x1", video_url="https://cdn.example/video.mp4",
            text="clip #tag", due_at=datetime(2026, 11, 26, 12, tzinfo=timezone.utc))
        self.assertEqual(post["id"], "p1")
        self.assertEqual(seen["json"]["variables"]["input"]["mode"], "customScheduled")
        self.assertEqual(seen["json"]["variables"]["input"]["dueAt"], "2026-11-26T12:00:00.000Z")
        self.assertEqual(seen["json"]["variables"]["input"]["assets"][0]["video"]["url"], "https://cdn.example/video.mp4")

    def test_create_timeout_is_marked_uncertain_not_retryable(self):
        import requests
        client = BufferClient("secret", post=lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
        with self.assertRaises(BufferError) as caught:
            client.create_video_post(channel_id="x1", video_url="https://cdn.example/video.mp4", text="x")
        self.assertTrue(caught.exception.uncertain)

    def test_allowlist_requires_exact_connected_x_channel(self):
        discovered = [{"id": "x1", "service": "twitter", "isDisconnected": False, "isLocked": False}]
        self.assertTrue(check_channel_allowlist("Film Sahneleri", "x1", discovered, {"Film Sahneleri": "x1"}))
        self.assertFalse(check_channel_allowlist("Film Mağarası", "x1", discovered, {"Film Sahneleri": "x1"}))
        self.assertFalse(check_channel_allowlist("Film Sahneleri", "x1", [{**discovered[0], "isLocked": True}], {"Film Sahneleri": "x1"}))

    def test_idempotency_and_channel_catalog_are_stable(self):
        self.assertEqual(fingerprint("film", "drive1", "A #b", "https://x/a.mp4?a=1"),
                         fingerprint("film", "drive1", "A #b", "https://x/a.mp4?a=2"))
        self.assertIn("Film Sahneleri", CHANNELS)
        self.assertEqual(len(CHANNELS), 7)
        self.assertIn("CreatePostInput", CREATE_POST_MUTATION)

    def test_media_validation_rejects_redirects_and_non_mp4(self):
        self.assertFalse(validate_media_url("http://host/video.mp4", head=lambda *a, **k: None))
        self.assertFalse(validate_media_url("https://host/video.mov", head=lambda *a, **k: None))
        bad = FakeResponse(302, headers={"Content-Length": "20", "Content-Type": "video/mp4"})
        self.assertFalse(validate_media_url("https://host/video.mp4", head=lambda *a, **k: bad))
        good = FakeResponse(200, headers={"Content-Length": "20", "Content-Type": "video/mp4"})
        self.assertTrue(validate_media_url("https://host/video.mp4", head=lambda *a, **k: good))


if __name__ == "__main__":
    unittest.main()
