import unittest
from unittest.mock import Mock, patch

from threads_publisher import (
    build_threads_video_url, publish_threads_video, threads_configured,
    validate_threads_identity,
)


class ThreadsPublisherTests(unittest.TestCase):
    def test_route_is_disabled_unless_all_settings_are_present(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(threads_configured())
        with patch.dict("os.environ", {
            "ENABLE_PENGUEN_THREADS": "true",
            "THREADS_ACCESS_TOKEN": "secret",
            "PENGUEN_THREADS_USERNAME": "beyinsizpenguen",
            "PENGUEN_THREADS_VIDEO_URL_TEMPLATE": "https://media.example/{file_id}",
        }, clear=True):
            self.assertTrue(threads_configured())

    def test_video_url_template_encodes_identifiers(self):
        self.assertEqual(
            build_threads_video_url("https://media.example/{file_id}/{filename}", "a/b", "clip one.mp4"),
            "https://media.example/a%2Fb/clip%20one.mp4",
        )
        with self.assertRaises(ValueError):
            build_threads_video_url("http://media.example/{file_id}", "x", "x.mp4")

    def test_identity_check_is_read_only_and_pins_expected_profile(self):
        session = Mock()
        session.get.return_value = Mock(
            json=lambda: {"id": "user-1", "username": "beyinsizpenguen"},
            raise_for_status=Mock(),
        )
        self.assertEqual(
            validate_threads_identity(token="secret", expected_username="@BeyinsizPenguen", session=session),
            {"id": "user-1", "username": "beyinsizpenguen"},
        )
        session.post.assert_not_called()

    def test_publishes_only_after_account_match_and_finished_container(self):
        session = Mock()
        session.get.side_effect = [
            Mock(json=lambda: {"id": "user-1", "username": "beyinsizpenguen"}, raise_for_status=Mock()),
            Mock(json=lambda: {"status": "FINISHED"}, raise_for_status=Mock()),
        ]
        session.post.side_effect = [
            Mock(json=lambda: {"id": "container-1"}, raise_for_status=Mock()),
            Mock(json=lambda: {"id": "post-1"}, raise_for_status=Mock()),
        ]
        result = publish_threads_video(
            "https://media.example/video.mp4", "Penguen video", token="do-not-log",
            expected_username="@BeyinsizPenguen", session=session, poll_interval=0,
        )
        self.assertEqual(result, "post-1")
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(session.post.call_args_list[0].args[0], "https://graph.threads.net/v1.0/user-1/threads")
        self.assertEqual(session.post.call_args_list[1].kwargs["params"], {"creation_id": "container-1"})

    def test_wrong_account_stops_before_container_creation(self):
        session = Mock()
        session.get.return_value = Mock(
            json=lambda: {"id": "other-user", "username": "someone_else"},
            raise_for_status=Mock(),
        )
        with self.assertRaisesRegex(RuntimeError, "beklenen Beyinsiz Penguen"):
            publish_threads_video(
                "https://media.example/video.mp4", "text", token="secret",
                expected_username="beyinsizpenguen", session=session,
            )
        session.post.assert_not_called()

    def test_invalid_media_url_fails_before_api_call(self):
        session = Mock()
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            publish_threads_video("http://private/video.mp4", "text", token="secret",
                                  expected_username="beyinsizpenguen", session=session)
        session.get.assert_not_called()
        session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
