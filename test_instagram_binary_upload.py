import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from cloud_omnichannel_publisher import (
    ETSY_LINK,
    MetaAPIError,
    _instagram_caption,
    _upload_instagram_binary,
    upload_instagram_reel,
)


class InstagramBinaryUploadTests(unittest.TestCase):
    def test_curl_streams_video_and_keeps_token_out_of_argv(self):
        token = "EAAtestSecret123"
        with tempfile.NamedTemporaryFile() as video:
            video.write(b"abcde")
            video.flush()
            result = subprocess.CompletedProcess([], 0, '{"success":true,"message":"ok"}\n5|200', "")
            with patch("cloud_omnichannel_publisher.subprocess.run", return_value=result) as run:
                response = _upload_instagram_binary(
                    "https://rupload.facebook.com/ig-api-upload/123?secret=signed", token, video.name, 5
                )
        self.assertTrue(response["success"])
        args, kwargs = run.call_args
        self.assertNotIn(token, " ".join(args[0]))
        self.assertNotIn("secret=signed", " ".join(args[0]))
        self.assertIn("--data-binary", args[0])
        self.assertTrue(any(arg.endswith(video.name) for arg in args[0]))
        self.assertIn(f"Authorization: OAuth {token}", kwargs["input"])
        self.assertIn("file_size: 5", kwargs["input"])
        self.assertIn('url = "https://rupload.facebook.com/ig-api-upload/123?secret=signed"', kwargs["input"])
        self.assertEqual(response["_uploaded_bytes"], 5)

    def test_rejects_untrusted_upload_url_without_running_curl(self):
        bad_urls = [
            "http://rupload.facebook.com/ig-api-upload/1",
            "https://rupload.facebook.com.evil.example/1",
            "https://evil@rupload.facebook.com/1",
            "https://rupload.facebook.com:444/1",
            "https://rupload.facebook.com:bad/1",
        ]
        with patch("cloud_omnichannel_publisher.subprocess.run") as run:
            for url in bad_urls:
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    _upload_instagram_binary(url, "EAAtest", "video.mp4", 5)
        run.assert_not_called()

    def test_reports_http_error_without_exposing_token(self):
        result = subprocess.CompletedProcess(
            [], 0, '{"error":{"message":"Rejected","type":"OAuthException","code":100,"error_subcode":2207009}}\n5|400', ""
        )
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), patch("cloud_omnichannel_publisher.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Rejected") as raised:
                _upload_instagram_binary("https://rupload.facebook.com/1", "EAAsecret", "video.mp4", 5)
        self.assertNotIn("EAAsecret", str(raised.exception))
        self.assertIsInstance(raised.exception, MetaAPIError)
        self.assertEqual(raised.exception.stage, "Instagram ikili video aktarımı")
        self.assertEqual(raised.exception.http_status, 400)
        self.assertEqual(raised.exception.subcode, 2207009)

    def test_reports_rupload_processing_details(self):
        result = subprocess.CompletedProcess(
            [], 0,
            '{"debug_info":{"type":"ProcessingFailedError","message":"Unsupported video stream","is_retriable":false}}\n5|400',
            "",
        )
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), patch("cloud_omnichannel_publisher.subprocess.run", return_value=result):
            with self.assertRaises(MetaAPIError) as raised:
                _upload_instagram_binary("https://rupload.facebook.com/1", "EAAsecret", "video.mp4", 5)
        message = str(raised.exception)
        self.assertIn("ProcessingFailedError", message)
        self.assertIn("Unsupported video stream", message)
        self.assertIn("yeniden_denenebilir=False", message)

    def test_nested_json_meta_error_and_sensitive_values_are_preserved_safely(self):
        payload = '{"error":{"message":"{\\"type\\":\\"ProcessingFailedError\\",\\"message\\":\\"Bad https://signed.example/video?access_token=hidden\\",\\"code\\":2207009,\\"fbtrace_id\\":\\"trace123\\"}"}}'
        result = subprocess.CompletedProcess([], 0, payload + "\n5|400", "")
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), patch(
            "cloud_omnichannel_publisher.subprocess.run", return_value=result
        ):
            with self.assertRaises(MetaAPIError) as raised:
                _upload_instagram_binary("https://rupload.facebook.com/1", "EAAsecret", "video.mp4", 5)
        self.assertIn("ProcessingFailedError", str(raised.exception))
        self.assertIn("2207009", str(raised.exception))
        self.assertIn("trace123", str(raised.exception))
        self.assertNotIn("hidden", str(raised.exception))
        self.assertNotIn("signed.example", str(raised.exception))

    def test_file_size_mismatch_fails_before_upload_request(self):
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=6), patch(
            "cloud_omnichannel_publisher.subprocess.run"
        ) as run:
            with self.assertRaisesRegex(RuntimeError, "boyutu eşleşmiyor"):
                _upload_instagram_binary("https://rupload.facebook.com/1", "EAAsecret", "video.mp4", 5)
        run.assert_not_called()

    def test_actual_transferred_bytes_must_match_declared_size(self):
        result = subprocess.CompletedProcess([], 0, '{"success":true}\n4|200', "")
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), patch(
            "cloud_omnichannel_publisher.subprocess.run", return_value=result
        ):
            with self.assertRaises(MetaAPIError) as raised:
                _upload_instagram_binary("https://rupload.facebook.com/1", "EAAsecret", "video.mp4", 5)
        self.assertIn("aktarilan_bayt=4/5", str(raised.exception))

    def test_caption_keeps_unique_description_and_link_at_end(self):
        caption = "Episode-specific title\n\nEpisode-specific notes #reels\n\n" + ETSY_LINK
        output = _instagram_caption(caption)
        self.assertIn("Episode-specific notes", output)
        self.assertEqual(output.count(ETSY_LINK), 1)
        self.assertTrue(output.endswith(ETSY_LINK))
        self.assertLessEqual(len(_instagram_caption("x" * 3000)), 2200)

    def test_platform_specific_caption_does_not_receive_global_store_link(self):
        caption = "Platform-specific caption #reels"
        self.assertEqual(_instagram_caption(caption, append_store_link=False), caption)

    def test_status_poll_requests_only_supported_container_fields(self):
        """A status poll must not fail with Graph #100 before publish."""
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), \
             patch("cloud_omnichannel_publisher._sha256_file", return_value="a" * 64), \
             patch("cloud_omnichannel_publisher._upload_instagram_binary"), \
             patch("cloud_omnichannel_publisher.time.sleep"), \
             patch("cloud_omnichannel_publisher.requests.post") as post, \
             patch("cloud_omnichannel_publisher.requests.get") as get:
            post.side_effect = [
                Mock(status_code=200, json=lambda: {"id": "container", "uri": "https://rupload.facebook.com/1"}),
                Mock(status_code=200, json=lambda: {"id": "media"}),
            ]
            get.side_effect = [
                Mock(status_code=200, json=lambda: {"status_code": "FINISHED"}),
                Mock(status_code=200, json=lambda: {
                    "id": "media", "permalink": "https://www.instagram.com/reel/actual/",
                }),
            ]
            self.assertEqual(upload_instagram_reel({"instagram_id": "ig", "page_token": "secret"}, "video.mp4", "caption"), "media")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["fields"], "status_code,status")
        self.assertEqual(get.call_args_list[1].args[0], "https://graph.facebook.com/v24.0/media")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["fields"], "id,permalink")
        self.assertEqual(post.call_count, 2)  # Container creation + exactly one publish.

    def _rejected_binary(self, status, *, code=None, uploaded=5, publish=False):
        error=MetaAPIError("Instagram ikili video aktarımı",400,message="ProcessingFailed",code=code,
                           upload_bytes=5,uploaded_bytes=uploaded)
        with patch("cloud_omnichannel_publisher.os.path.getsize",return_value=5), \
             patch("cloud_omnichannel_publisher._sha256_file",return_value="a"*64), \
             patch("cloud_omnichannel_publisher._upload_instagram_binary",side_effect=error) as binary, \
             patch("cloud_omnichannel_publisher.time.sleep"), \
             patch("cloud_omnichannel_publisher.requests.post") as post, \
             patch("cloud_omnichannel_publisher.requests.get") as get:
            post.side_effect=[Mock(status_code=200,json=lambda:{"id":"12345","uri":"https://rupload.facebook.com/1"}),
                              Mock(status_code=200,json=lambda:{"id":"67890"})]
            get.return_value=Mock(status_code=200,json=lambda:{"id":"12345","status_code":status})
            try:
                out=upload_instagram_reel({"instagram_id":"11","page_token":"secret"},"video.mp4","caption",publish=publish)
            except Exception as exc:
                out=exc
            return out,binary.call_count,post.call_count,get.call_count

    def test_full_binary_400_finished_container_is_not_reuploaded(self):
        out,binary,post,get=self._rejected_binary("FINISHED")
        self.assertEqual(out,{"container_id":"12345","status":"FINISHED","published":False})
        self.assertEqual((binary,post,get),(1,1,1))

    def test_full_binary_400_finished_can_publish_same_container_once(self):
        out,binary,post,get=self._rejected_binary("FINISHED",publish=True)
        self.assertEqual(out,"67890")
        self.assertEqual((binary,post),(1,2))

    def test_binary_400_error_published_and_expired_never_publish(self):
        for state in ("ERROR","PUBLISHED","EXPIRED"):
            with self.subTest(state=state):
                out,binary,post,get=self._rejected_binary(state,publish=True)
                self.assertIsInstance(out,MetaAPIError)
                self.assertEqual(out.container_status,state)
                self.assertEqual((binary,post),(1,1))

    def test_partial_transfer_and_policy_errors_never_continue(self):
        for options in ({"uploaded":4},{"code":368},{"code":190}):
            out,binary,post,get=self._rejected_binary("FINISHED",publish=True,**options)
            self.assertIsInstance(out,MetaAPIError)
            self.assertEqual((binary,post,get),(1,1,0))

    def test_reels_tags_are_sent_at_container_creation_only(self):
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), \
             patch("cloud_omnichannel_publisher._sha256_file", return_value="a" * 64), \
             patch("cloud_omnichannel_publisher._upload_instagram_binary"), \
             patch("cloud_omnichannel_publisher.time.sleep"), \
             patch("cloud_omnichannel_publisher.requests.post") as post, \
             patch("cloud_omnichannel_publisher.requests.get") as get:
            post.side_effect = [
                Mock(status_code=200, json=lambda: {"id": "container", "uri": "https://rupload.facebook.com/1"}),
                Mock(status_code=200, json=lambda: {"id": "media"}),
            ]
            get.side_effect = [
                Mock(status_code=200, json=lambda: {"status_code": "FINISHED"}),
                Mock(status_code=200, json=lambda: {"id": "media", "permalink": "https://www.instagram.com/reel/id/"}),
            ]
            self.assertEqual(
                upload_instagram_reel(
                    {"instagram_id": "ig", "page_token": "secret"}, "video.mp4",
                    "Cristiano Ronaldo @cristiano #CR7",
                    append_store_link=False, user_tags=["cristiano"],
                ), "media"
            )
        import json
        init = post.call_args_list[0].kwargs["data"]
        self.assertEqual(json.loads(init["user_tags"]), [{"username": "cristiano"}])
        self.assertIn("@cristiano", init["caption"])
        self.assertNotIn("user_tags", post.call_args_list[1].kwargs["data"])
        self.assertEqual(post.call_count, 2)

    def test_reels_only_falls_back_for_explicit_user_tags_400_before_publish(self):
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), \
             patch("cloud_omnichannel_publisher._sha256_file", return_value="a" * 64), \
             patch("cloud_omnichannel_publisher._upload_instagram_binary"), \
             patch("cloud_omnichannel_publisher.time.sleep"), \
             patch("cloud_omnichannel_publisher.requests.post") as post, \
             patch("cloud_omnichannel_publisher.requests.get") as get:
            post.side_effect = [
                Mock(ok=False, status_code=400, headers={}, text="",
                     json=lambda: {"error": {"message": "Invalid parameter user_tags", "code": 100}}),
                Mock(ok=True, status_code=200,
                     json=lambda: {"id": "safe-container", "uri": "https://rupload.facebook.com/1"}),
                Mock(ok=True, status_code=200, json=lambda: {"id": "media"}),
            ]
            get.side_effect = [
                Mock(ok=True, status_code=200, json=lambda: {"status_code": "FINISHED"}),
                Mock(ok=True, status_code=200, json=lambda: {"id": "media", "permalink": "https://www.instagram.com/reel/safe/"}),
            ]
            self.assertEqual(
                upload_instagram_reel(
                    {"instagram_id": "ig", "page_token": "secret"}, "video.mp4",
                    "Ronaldo @cristiano", user_tags=["cristiano"],
                    append_store_link=False,
                ), "media"
            )
        self.assertIn("user_tags", post.call_args_list[0].kwargs["data"])
        self.assertNotIn("user_tags", post.call_args_list[1].kwargs["data"])
        self.assertIn("@cristiano", post.call_args_list[1].kwargs["data"]["caption"])
        self.assertEqual(post.call_count, 3)  # one rejected tag container, plain container, one publish

    def test_generic_container_http400_with_tags_stays_blocked_no_retry(self):
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), \
             patch("cloud_omnichannel_publisher.requests.post") as post, \
             patch("cloud_omnichannel_publisher._upload_instagram_binary") as binary:
            post.return_value = Mock(
                ok=False, status_code=400, headers={}, text="",
                json=lambda: {"error": {"message": "Invalid video metadata", "code": 100}},
            )
            with self.assertRaises(MetaAPIError):
                upload_instagram_reel(
                    {"instagram_id": "ig", "page_token": "secret"}, "video.mp4",
                    "Ronaldo @cristiano", user_tags=["cristiano"],
                )
        post.assert_called_once()
        binary.assert_not_called()

    def test_invalid_user_tag_is_rejected_before_any_api_post(self):
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), \
             patch("cloud_omnichannel_publisher.requests.post") as post:
            with self.assertRaisesRegex(ValueError, "Invalid Instagram username"):
                upload_instagram_reel(
                    {"instagram_id": "ig", "page_token": "secret"},
                    "video.mp4", "caption", user_tags=["not valid user"]
                )
        post.assert_not_called()

    def test_upload_only_waits_for_finished_container_without_publishing(self):
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), \
             patch("cloud_omnichannel_publisher._sha256_file", return_value="a" * 64), \
             patch("cloud_omnichannel_publisher._upload_instagram_binary") as binary, \
             patch("cloud_omnichannel_publisher.time.sleep"), \
             patch("cloud_omnichannel_publisher.requests.post") as post, \
             patch("cloud_omnichannel_publisher.requests.get") as get:
            post.return_value = Mock(
                status_code=200,
                json=lambda: {"id": "container-only", "uri": "https://rupload.facebook.com/1"},
            )
            get.return_value = Mock(status_code=200, json=lambda: {"status_code": "FINISHED"})
            result = upload_instagram_reel(
                {"instagram_id": "ig", "page_token": "secret"},
                "video.mp4", "caption", publish=False,
            )
        self.assertEqual(result, {
            "container_id": "container-only", "status": "FINISHED", "published": False
        })
        binary.assert_called_once()
        post.assert_called_once()
        post.assert_called_once_with(
            "https://graph.facebook.com/v24.0/ig/media",
            data={
                "access_token": "secret", "upload_type": "resumable",
                "media_type": "REELS", "caption": "caption\n\n" + ETSY_LINK,
            },
            timeout=30,
        )

    def test_reused_container_id_is_blocked_before_binary_upload(self):
        with patch("cloud_omnichannel_publisher.os.path.getsize", return_value=5), \
             patch("cloud_omnichannel_publisher.requests.post") as post, \
             patch("cloud_omnichannel_publisher._upload_instagram_binary") as binary:
            post.return_value = Mock(status_code=200, json=lambda: {
                "id": "already-used", "uri": "https://rupload.facebook.com/1",
            })
            with self.assertRaisesRegex(RuntimeError, "tekrarlanan container"):
                upload_instagram_reel(
                    {"instagram_id": "ig", "page_token": "secret"}, "video.mp4", "caption",
                    publish=False, forbidden_container_ids={"already-used"},
                )
        binary.assert_not_called()
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
