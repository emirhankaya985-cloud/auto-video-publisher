import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import toonzone_instagram_first_three as batch
from cloud_omnichannel_publisher import create_instagram_cover_video, upload_instagram_reel


class Tests(unittest.TestCase):
    def test_explicit_first_frame_reaches_container_creation(self):
        with patch('cloud_omnichannel_publisher.os.path.getsize', return_value=5), \
                patch('cloud_omnichannel_publisher._sha256_file', return_value='a' * 64), \
                patch('cloud_omnichannel_publisher._upload_instagram_binary'), \
                patch('cloud_omnichannel_publisher.time.sleep'), \
                patch('cloud_omnichannel_publisher.requests.post') as post, \
                patch('cloud_omnichannel_publisher.requests.get') as get:
            post.side_effect = [Mock(status_code=200, json=lambda: {'id': '1', 'uri': 'https://rupload.facebook.com/1'}),
                                Mock(status_code=200, json=lambda: {'id': '2'})]
            get.side_effect = [Mock(status_code=200, json=lambda: {'status_code': 'FINISHED'}),
                               Mock(status_code=200, json=lambda: {'id': '2', 'permalink': 'https://www.instagram.com/reel/test/'})]
            upload_instagram_reel({'instagram_id': '7', 'page_token': 'test'}, 'file.mp4', 'text', thumb_offset=0)
        self.assertEqual(post.call_args_list[0].kwargs['data']['thumb_offset'], 0)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_real_first_frame_preserves_full_three_by_four_cover_on_landscape_source(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = Image.new('RGB', (300, 400), 'white')
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 299, 39), fill='red')
            draw.rectangle((0, 360, 299, 399), fill='green')
            draw.rectangle((0, 40, 39, 359), fill='blue')
            image.save(root / 'cover.png')
            subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=640x360:d=1:r=25',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(root / 'source.mp4')],
                           check=True, capture_output=True)
            output = create_instagram_cover_video(root / 'source.mp4', root / 'cover.png', root / 'out.mp4', preserve_full_cover=True)
            subprocess.run(['ffmpeg', '-y', '-i', str(output), '-frames:v', '1', str(root / 'frame.png')],
                           check=True, capture_output=True)
            with Image.open(root / 'frame.png') as frame:
                self.assertEqual(frame.size, (1080, 1920))
            self.assertLess(batch.cover_distance(root / 'cover.png', root / 'frame.png'), 0.04)

    def test_bad_published_thumbnail_stops_before_the_next_part_and_preserves_post_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = 'd' * 64
            record = dict(status='reserved', intent_run_id='42', user_id=batch.EXPECTED_INSTAGRAM_ID,
                          source_id='source', file='S01E01_Title_Part1.mp4', caption='text',
                          cover_sha256='hash', last_seen='2026-11-05T12:00:00+00:00')
            item = dict(key=key, id='source', name=record['file'], text='text', cover_path='cover.png')
            batch.archive.save(root / 'history.json', {'schema': 1, 'records': {key: record}})
            batch.archive.save(root / 'plan.json', {'run_id': '42', 'user_id': batch.EXPECTED_INSTAGRAM_ID, 'plans': [item, item]})
            with patch.object(batch, 'ROOT', root), patch.object(batch, 'HISTORY', root / 'history.json'), \
                    patch.object(batch, 'PLAN', root / 'plan.json'), patch.object(batch, 'page_for_toonzone'), \
                    patch.object(batch, 'instagram_identity', return_value=batch.EXPECTED_INSTAGRAM_ID), \
                    patch.object(batch, 'digest', return_value='hash'), \
                    patch('public_link_runtime.download_verified_publication_video', return_value=root / 'source.mp4'), \
                    patch('cloud_omnichannel_publisher.create_instagram_cover_video', return_value=root / 'covered.mp4'), \
                    patch('instagram_media_compat.prepare_instagram_upload', return_value=root / 'video.mp4'), \
                    patch.object(batch.subprocess, 'run'), \
                    patch.object(batch, 'cover_distance', side_effect=[0.0, 0.8]), \
                    patch.object(batch, 'thumbnail', return_value={'id': '123', 'caption': 'text', 'media_type': 'VIDEO',
                                                                 'permalink': 'https://www.instagram.com/reel/test/'}), \
                    patch('cloud_omnichannel_publisher.upload_instagram_reel', return_value='123') as upload, \
                    patch.dict(os.environ, {'FIRST_THREE_INTENT_ARCHIVED': 'true'}):
                with self.assertRaisesRegex(RuntimeError, 'stopped_before_next_part'):
                    batch.execute('42')
            self.assertEqual(upload.call_count, 1)
            result = batch.archive.read(root / 'history.json')['records'][key]
            self.assertEqual(result['post_id'], '123')
            self.assertEqual(result['status'], 'attempted')


if __name__ == '__main__':
    unittest.main()
