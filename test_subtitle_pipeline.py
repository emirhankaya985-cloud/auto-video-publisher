import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from subtitle_pipeline import prepare_subtitles


class SubtitlePipelineTests(unittest.TestCase):
    def test_disabled_or_unverified_route_never_transcribes(self):
        transcribe = Mock()
        with patch.dict(os.environ, {'AUTO_SUBTITLES_ENABLED': 'false'}):
            _, receipt = prepare_subtitles('clip.mp4', 'film', 'unused', transcriber=transcribe)
        self.assertEqual(receipt['status'], 'disabled')
        with patch.dict(os.environ, {'AUTO_SUBTITLES_ENABLED': 'true'}):
            _, receipt = prepare_subtitles('clip.mp4', 'toonzone', 'unused', transcriber=transcribe)
        self.assertEqual(receipt['status'], 'source_language_unverified')
        transcribe.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                         'Dedicated advanced CI installs FFmpeg for this test')
    def test_real_ffmpeg_burn_preserves_original_and_keeps_srt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source'with,characters.mp4"
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi',
                            '-i', 'testsrc2=size=320x240:rate=10', '-t', '2',
                            '-c:v', 'libx264', str(source)], check=True, capture_output=True)
            original = source.read_bytes()
            (root / 'model').mkdir()
            def transcribe(video, destination, model, **kwargs):
                Path(destination).write_text('1\n00:00:00,100 --> 00:00:01,500\nTürkçe altyazı testi\n', encoding='utf-8')
                return {'segments': 1}
            with patch.dict(os.environ, {'AUTO_SUBTITLES_ENABLED': 'true',
                                         'SUBTITLE_MODEL_DIR': str(root / 'model')}):
                output, receipt = prepare_subtitles(source, 'film', root / 'output', transcriber=transcribe)
            self.assertEqual(receipt['status'], 'burned_in')
            self.assertNotEqual(output.read_bytes(), original)
            self.assertEqual(source.read_bytes(), original)
            self.assertTrue((root / 'output' / 'captions.srt').is_file())

    def test_failed_transcription_returns_original_and_redacts_details(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'model').mkdir()
            source = root / 'clip.mp4'
            source.write_bytes(b'original')
            with patch.dict(os.environ, {'AUTO_SUBTITLES_ENABLED': 'true',
                                         'SUBTITLE_MODEL_DIR': str(root / 'model')}):
                output, receipt = prepare_subtitles(source, 'film', root / 'output',
                    transcriber=Mock(side_effect=RuntimeError('private provider text')))
            self.assertEqual(output, source.resolve())
            self.assertEqual(receipt['status'], 'unavailable')
            self.assertNotIn('private', str(receipt))
