from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from instagram_media_compat import (
    _transcode_film_compact,
    _transcode_film_timeline,
    _validate_remux_timing,
    check_full_decode,
    compatibility_issues,
    create_diagnostic_clip,
    is_compatible,
    log_media_diagnostics,
    mp4_atom_structure,
    prepare_instagram_upload,
    remux_mp4_faststart,
)


def supported_probe():
    return {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "30.0"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30/1",
                "r_frame_rate": "30/1",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "field_order": "progressive",
                "start_time": "0",
                "duration": "30.0",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "start_time": "0",
                "duration": "30.0",
            },
        ],
    }


ATOM_OK = {"valid": True, "moov_offset": 0, "mdat_offset": 100, "moov_front": True, "edit_list": False}
ATOM_LATE = {"valid": True, "moov_offset": 100, "mdat_offset": 0, "moov_front": False, "edit_list": False}
ATOM_LATE_EDIT = {"valid": True, "moov_offset": 100, "mdat_offset": 0, "moov_front": False, "edit_list": True}


def mp4_box(kind, payload=b""):
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


class InstagramMediaCompatibilityTests(unittest.TestCase):
    def test_mp4_atom_parser_detects_moov_position_and_nested_edit_list(self):
        edit_list = mp4_box(b"elst", b"\x00\x00\x00\x00")
        edts = mp4_box(b"edts", edit_list)
        trak = mp4_box(b"trak", edts)
        moov = mp4_box(b"moov", trak)
        mdat = mp4_box(b"mdat", b"media")
        with tempfile.TemporaryDirectory() as directory:
            front = Path(directory) / "front.mp4"
            front.write_bytes(mp4_box(b"ftyp", b"isom") + moov + mdat)
            structure = mp4_atom_structure(front)
            self.assertTrue(structure["valid"])
            self.assertTrue(structure["moov_front"])
            self.assertTrue(structure["edit_list"])
            trailing = Path(directory) / "trailing.mp4"
            trailing.write_bytes(mp4_box(b"ftyp", b"isom") + mdat + mp4_box(b"moov", mp4_box(b"trak")))
            trailing_structure = mp4_atom_structure(trailing)
            self.assertTrue(trailing_structure["valid"])
            self.assertFalse(trailing_structure["moov_front"])
            self.assertFalse(trailing_structure["edit_list"])

    def test_edit_list_is_reported_as_mp4_compatibility_issue(self):
        issues = compatibility_issues(supported_probe(), 1024, True, has_edit_list=True)
        self.assertIn("MP4 edit list (edts/elst) bulunuyor", issues)

    def test_remux_timing_guard_rejects_duration_or_av_sync_shift(self):
        before = supported_probe()
        after = supported_probe()
        before["format"]["duration"] = after["format"]["duration"] = "30"
        before["streams"][0].update(start_time="0", duration="30")
        before["streams"][1].update(start_time="0.05", duration="29.95")
        after["streams"][0].update(start_time="0", duration="30")
        after["streams"][1].update(start_time="0.3", duration="29.7")
        with self.assertRaisesRegex(RuntimeError, "A/V ofsetini değiştirdi"):
            _validate_remux_timing(before, after)
        after["streams"][1]["start_time"] = "0.05"
        after["format"]["duration"] = "32"
        with self.assertRaisesRegex(RuntimeError, "toplam süresi değişti"):
            _validate_remux_timing(before, after)

    def test_edit_list_remux_sync_failure_uses_geometry_preserving_transcode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"source")
            output = Path(directory) / "normalized.mp4"
            with patch("instagram_media_compat.probe", side_effect=[supported_probe(), supported_probe()]), \
                 patch("instagram_media_compat.mp4_atom_structure", return_value=ATOM_LATE_EDIT), \
                 patch("instagram_media_compat.remux_mp4_faststart", side_effect=RuntimeError("MP4 faststart remux doğrulanamadı: Remux A/V ofsetini değiştirdi")), \
                 patch("instagram_media_compat._transcode_film_timeline") as transcode:
                def write_output(src, dst):
                    Path(dst).write_bytes(b"transcoded")
                    return Path(dst)
                transcode.side_effect = write_output
                result = prepare_instagram_upload(source, output, prefer_remux=True, return_method=True)
            self.assertEqual(result, (output, "transcode"))
            transcode.assert_called_once_with(source, output)

    def test_film_timeline_transcode_preserves_geometry_and_aac_lc(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "film.mp4"
            media = supported_probe()
            with patch("instagram_media_compat.probe", return_value=media), \
                 patch("instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK), \
                 patch("instagram_media_compat.compatibility_issues", return_value=[]), \
                 patch("instagram_media_compat.check_full_decode"), \
                 patch("instagram_media_compat._validate_remux_timing"), \
                 patch("instagram_media_compat.subprocess.run") as run:
                run.side_effect = lambda command, **_kwargs: Path(command[-1]).write_bytes(b"out")
                self.assertEqual(_transcode_film_timeline("source.mp4", output), output)
            command = run.call_args.args[0]
            self.assertIn("setsar=1", command)
            self.assertNotIn("scale=1080:1920", command)
            self.assertIn("aac_low", command)
            self.assertIn("+faststart", command)
            self.assertIn("open_gop=0", " ".join(command))

    def test_film_compact_command_matches_successful_full_length_profile(self):
        with patch("instagram_media_compat.subprocess.run") as run:
            _transcode_film_compact(Path("source.mp4"), Path("output.mp4"))
        command = run.call_args.args[0]
        for value in ("360:640", "main", "3.0", "25", "500k", "800k",
                      "aac_low", "44100", "+faststart"):
            self.assertTrue(any(value in str(arg) for arg in command), value)

    def test_film_compact_transcodes_large_or_vp9_source_and_decodes_output(self):
        source_probe = supported_probe()
        source_probe["streams"][0].update(codec_name="vp9", profile="Profile 0", width=720, height=1280)
        output_probe = supported_probe()
        output_probe["streams"][0].update(profile="Main", width=360, height=640, avg_frame_rate="25/1")
        with patch("instagram_media_compat.probe", side_effect=[source_probe, output_probe]), patch(
            "instagram_media_compat.mp4_atom_structure", side_effect=[ATOM_OK, ATOM_OK]
        ), patch("instagram_media_compat.os.path.getsize", return_value=1024), patch(
            "instagram_media_compat._transcode_film_compact"
        ) as transcode, patch("instagram_media_compat.check_full_decode") as decode:
            result = prepare_instagram_upload("source.mp4", "output.mp4", prefer_remux=True, film_compact=True)
        self.assertEqual(result, Path("output.mp4"))
        transcode.assert_called_once_with(Path("source.mp4"), Path("output.mp4"))
        decode.assert_called_once_with(Path("output.mp4"))

    def test_film_compact_reencodes_apparently_compliant_main_stream(self):
        source_probe = supported_probe()
        source_probe["streams"][0].update(profile="Main", width=360, height=640)
        with patch("instagram_media_compat.probe", side_effect=[source_probe, source_probe]), patch(
            "instagram_media_compat.mp4_atom_structure", side_effect=[ATOM_LATE, ATOM_OK]
        ), patch("instagram_media_compat.os.path.getsize", return_value=1024), patch(
            "instagram_media_compat._transcode_film_compact"
        ) as transcode, patch("instagram_media_compat.remux_mp4_faststart") as remux, patch(
            "instagram_media_compat.check_full_decode"
        ):
            prepare_instagram_upload("source.mp4", "output.mp4", prefer_remux=True, film_compact=True)
        transcode.assert_called_once()
        remux.assert_not_called()

    def test_toonzone_cover_composite_forces_verified_compact_transcode(self):
        media = supported_probe()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cover-composite.mp4"
            output = Path(directory) / "normalized.mp4"
            source.write_bytes(b"cover-composite")

            def write_output(src, dst):
                Path(dst).write_bytes(b"normalized")
                return Path(dst)

            with patch("instagram_media_compat.probe", return_value=media), \
                 patch("instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK), \
                 patch("instagram_media_compat._transcode_film_compact", side_effect=write_output) as transcode, \
                 patch("instagram_media_compat.check_full_decode") as decode:
                result = prepare_instagram_upload(
                    source, output, toonzone_compact=True, return_method=True
                )

            self.assertEqual(result, (output, "transcode"))
            transcode.assert_called_once_with(source, output)
            decode.assert_called_once_with(output)

    def test_full_diagnostic_remuxes_without_reencoding_and_validates_faststart(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "full-remux.mp4"
            media = supported_probe()
            def fake_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b"remuxed")
            with patch("instagram_media_compat.subprocess.run") as run, patch(
                "instagram_media_compat.probe", return_value=media
            ), patch("instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK):
                run.side_effect = fake_ffmpeg
                self.assertEqual(remux_mp4_faststart("source.mp4", output), output)
            command = run.call_args.args[0]
            self.assertIn("copy", command)
            self.assertIn("+faststart", command)
            self.assertIn("0", command)

    def test_media_diagnostics_log_only_file_fingerprint_and_codec_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "video.mp4"
            path.write_bytes(b"media")
            with patch("instagram_media_compat.probe", return_value=supported_probe()), patch(
                "instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK
            ), patch("instagram_media_compat._sha256", return_value="a" * 64), patch(
                "builtins.print"
            ) as log:
                log_media_diagnostics("Film kaynak MP4", path)
        message = log.call_args.args[0]
        self.assertIn("sha256=" + "a" * 64, message)
        self.assertIn("bytes=5", message)
        self.assertIn("faststart=true", message)
        self.assertIn("video=h264/", message)
        self.assertNotIn("access_token", message)

    def test_full_decode_checks_video_and_optional_audio_without_output(self):
        with patch("instagram_media_compat.subprocess.run") as run:
            self.assertTrue(check_full_decode("source.mp4"))
        command = run.call_args.args[0]
        self.assertIn("-xerror", command)
        self.assertIn("0:v:0", command)
        self.assertIn("0:a:0?", command)
        self.assertEqual(command[-2:], ["null", "-"])

    def test_full_decode_failure_is_fail_closed(self):
        with patch(
            "instagram_media_compat.subprocess.run",
            side_effect=__import__("subprocess").CalledProcessError(1, ["ffmpeg"]),
        ):
            with self.assertRaisesRegex(RuntimeError, "tam decode kontrolü başarısız"):
                check_full_decode("source.mp4")

    def test_diagnostic_clip_is_short_and_normalized_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "diagnostic.mp4"
            output.write_bytes(b"mock mp4")
            media = supported_probe()
            media["format"]["duration"] = "15.0"
            with patch("instagram_media_compat.subprocess.run") as run, patch(
                "instagram_media_compat.probe", return_value=media
            ), patch("instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK):
                self.assertEqual(create_diagnostic_clip("source.mp4", output, 15), output)
            command = run.call_args.args[0]
            self.assertIn("15", command)
            self.assertIn("-fps_mode", command)
            self.assertIn("cfr", command)
            self.assertIn("aac_low", command)
            self.assertIn("+faststart", command)

    def test_diagnostic_clip_rejects_out_of_range_duration_before_ffmpeg(self):
        with patch("instagram_media_compat.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "5-60"):
                create_diagnostic_clip("source.mp4", "diagnostic.mp4", 120)
        run.assert_not_called()

    def test_compliant_original_is_not_transcoded(self):
        with patch("instagram_media_compat.probe", return_value=supported_probe()), patch(
            "instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK
        ), patch("instagram_media_compat.os.path.getsize", return_value=1024), patch(
            "instagram_media_compat._transcode_vertical"
        ) as transcode:
            result = prepare_instagram_upload("source.mp4", "temp/converted.mp4")
        self.assertEqual(result, Path("source.mp4"))
        transcode.assert_not_called()

    def test_noncompliant_original_uses_and_verifies_ffmpeg_fallback(self):
        invalid = supported_probe()
        invalid["streams"][0]["pix_fmt"] = "yuv422p"
        with patch("instagram_media_compat.probe", side_effect=[invalid, supported_probe()]), patch(
            "instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK
        ), patch("instagram_media_compat.os.path.getsize", return_value=1024), patch(
            "instagram_media_compat._transcode_vertical"
        ) as transcode:
            result = prepare_instagram_upload("source.mp4", "temp/converted.mp4")
        self.assertEqual(result, Path("temp/converted.mp4"))
        transcode.assert_called_once_with(Path("source.mp4"), Path("temp/converted.mp4"))

    def test_film_moov_only_issue_uses_stream_copy_remux_instead_of_upscale(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"source")
            output = Path(directory) / "converted.mp4"
            media = supported_probe()

            def remux(_source, target):
                Path(target).write_bytes(b"remuxed")
                return Path(target)

            with patch("instagram_media_compat.probe", side_effect=[media, media]), patch(
                "instagram_media_compat.mp4_atom_structure", side_effect=[ATOM_LATE, ATOM_OK]
            ), patch("instagram_media_compat.remux_mp4_faststart", side_effect=remux) as remux_call, patch(
                "instagram_media_compat._transcode_vertical"
            ) as transcode:
                result = prepare_instagram_upload(source, output, prefer_remux=True)
            self.assertEqual(result, output)
            remux_call.assert_called_once_with(source, output)
            transcode.assert_not_called()

    def test_invalid_fallback_is_rejected_before_upload(self):
        invalid = supported_probe()
        invalid["streams"][0]["codec_name"] = "mpeg4"
        with patch("instagram_media_compat.probe", side_effect=[invalid, invalid]), patch(
            "instagram_media_compat.mp4_atom_structure", return_value=ATOM_OK
        ), patch("instagram_media_compat.os.path.getsize", return_value=1024), patch(
            "instagram_media_compat._transcode_vertical"
        ):
            with self.assertRaisesRegex(RuntimeError, "doğrulamadan geçemedi"):
                prepare_instagram_upload("source.mp4", "temp/converted.mp4")

    def test_rejects_out_of_range_fps_resolution_audio_and_duration(self):
        cases = []
        bad_fps = supported_probe()
        bad_fps["streams"][0]["avg_frame_rate"] = "20/1"
        cases.append((bad_fps, 1024, True))
        bad_width = supported_probe()
        bad_width["streams"][0]["width"] = 2000
        cases.append((bad_width, 1024, True))
        bad_audio = supported_probe()
        bad_audio["streams"][1]["sample_rate"] = "96000"
        cases.append((bad_audio, 1024, True))
        bad_duration = supported_probe()
        bad_duration["format"]["duration"] = "901"
        cases.append((bad_duration, 1024, True))
        bad_atom_order = supported_probe()
        cases.append((bad_atom_order, 1024, False))
        for media, size, moov_front in cases:
            with self.subTest(media=media, moov_front=moov_front):
                self.assertFalse(is_compatible(media, size, moov_front))

    def test_reports_precise_compatibility_reasons(self):
        invalid = supported_probe()
        invalid["streams"][0]["avg_frame_rate"] = "20/1"
        invalid["streams"][1]["codec_name"] = "mp3"
        issues = compatibility_issues(invalid, 1024, False)
        self.assertIn("FPS 23-60 aralığında değil", issues)
        self.assertIn("ses codec AAC değil", issues)
        self.assertIn("MP4 moov atomu önde değil", issues)

    def test_rejects_non_lc_aac_profile(self):
        he_aac = supported_probe()
        he_aac["streams"][1]["profile"] = "HE-AAC"
        issues = compatibility_issues(he_aac, 1024, True)
        self.assertIn("ses profili AAC-LC değil", issues)

    def test_rejects_known_over_limit_video_bitrate(self):
        over_limit = supported_probe()
        over_limit["streams"][0]["bit_rate"] = "26000000"
        issues = compatibility_issues(over_limit, 1024, True)
        self.assertIn("video bitrate 25 Mbps sınırını aşıyor", issues)

    def test_transcode_uses_conservative_meta_profile_and_bitrate(self):
        invalid = supported_probe()
        invalid["streams"][0]["pix_fmt"] = "yuv422p"
        with patch("instagram_media_compat.probe", side_effect=[invalid, supported_probe()]), patch(
            "instagram_media_compat.mp4_atom_structure", side_effect=[ATOM_OK, ATOM_OK]
        ), patch("instagram_media_compat.os.path.getsize", return_value=1024), patch(
            "instagram_media_compat.subprocess.run"
        ) as run:
            run.side_effect = [None]
            prepare_instagram_upload("source.mp4", "temp/converted.mp4")
        command = run.call_args.args[0]
        self.assertIn("-profile:v", command)
        self.assertIn("high", command)
        self.assertIn("-level:v", command)
        self.assertIn("4.1", command)
        self.assertIn("-maxrate", command)
        self.assertIn("6M", command)
        self.assertIn("-use_editlist", command)
        self.assertIn("0", command)
        self.assertIn("-x264-params", command)
        self.assertTrue(any("open_gop=0" in item for item in command))
        self.assertIn("-profile:a", command)
        self.assertIn("aac_low", command)


if __name__ == "__main__":
    unittest.main()
