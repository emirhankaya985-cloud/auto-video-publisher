"""Pass compliant Instagram media through; transcode only when required."""

import json
import hashlib
import os
import subprocess
from pathlib import Path


MAX_FILE_BYTES = 1_000_000_000


def _fps(value):
    try:
        numerator, denominator = str(value).split("/", 1)
        denominator = float(denominator)
        return float(numerator) / denominator if denominator else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def probe(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=format_name,duration,bit_rate,size:stream=codec_type,codec_name,profile,level,bit_rate,width,height,avg_frame_rate,r_frame_rate,pix_fmt,sample_aspect_ratio,field_order,sample_rate,channels,time_base,start_time,duration,color_space,color_transfer,color_primaries",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(result.stdout)


def _media_summary(media):
    video = next((item for item in media.get("streams", []) if item.get("codec_type") == "video"), {})
    audio = next((item for item in media.get("streams", []) if item.get("codec_type") == "audio"), {})
    duration = media.get("format", {}).get("duration", "unknown")
    fps = video.get("avg_frame_rate") or video.get("r_frame_rate") or "unknown"
    video_text = "/".join(str(video.get(key) or "?") for key in ("codec_name", "profile", "level"))
    audio_text = "/".join(str(audio.get(key) or "?") for key in ("codec_name", "profile")) if audio else "none"
    return (
        f"duration={duration}s; video={video_text}; "
        f"container_bps={media.get('format', {}).get('bit_rate','?')}; "
        f"size={video.get('width','?')}x{video.get('height','?')}; "
        f"pix_fmt={video.get('pix_fmt','?')}; fps={fps}; "
        f"video_bps={video.get('bit_rate','?')}; time_base={video.get('time_base','?')}; "
        f"field_order={video.get('field_order','?')}; sar={video.get('sample_aspect_ratio','?')}; "
        f"color={video.get('color_primaries','?')}/{video.get('color_transfer','?')}/{video.get('color_space','?')}; "
        f"audio={audio_text}; sample_rate={audio.get('sample_rate','?') if audio else '?'}; "
        f"channels={audio.get('channels','?') if audio else '?'}; "
        f"audio_bps={audio.get('bit_rate','?') if audio else '?'}"
    )


def log_media_diagnostics(label, path):
    media_path = Path(path)
    media = probe(media_path)
    size_bytes = media_path.stat().st_size
    atoms = mp4_atom_structure(media_path)
    faststart = atoms["moov_front"]
    print(
        f"Instagram medya tanısı: {label}; sha256={_sha256(media_path)}; "
        f"bytes={size_bytes}; faststart={str(faststart).lower()}; "
        f"moov_offset={atoms['moov_offset']}; mdat_offset={atoms['mdat_offset']}; "
        f"edit_list={str(atoms['edit_list']).lower()}; atom_structure_valid={str(atoms['valid']).lower()}; "
        f"{_media_summary(media)}.",
        flush=True,
    )
    return media


def check_full_decode(path):
    """Decode all source audio/video packets without creating an output file."""
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror",
             "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?", "-f", "null", "-"],
            check=True, capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Film Instagram tam decode kontrolü başarısız oldu.") from None
    return True


def _read_mp4_boxes(media, start, end):
    """Yield bounded ISO-BMFF boxes from a parent atom."""
    offset = start
    while offset + 8 <= end:
        media.seek(offset)
        header = media.read(16)
        if len(header) < 8:
            return
        size = int.from_bytes(header[:4], "big")
        kind = header[4:8]
        header_size = 8
        if size == 1:
            if len(header) < 16:
                return
            size = int.from_bytes(header[8:16], "big")
            header_size = 16
        elif size == 0:
            size = end - offset
        if size < header_size or offset + size > end:
            return
        yield kind, offset, offset + size, offset + header_size
        offset += size


def mp4_atom_structure(path):
    """Inspect real MP4 atom structure, including moov/trak/edts/elst."""
    file_size = os.path.getsize(path)
    moov_offset = mdat_offset = None
    has_edit_list = False
    valid = True
    with open(path, "rb") as media:
        top = list(_read_mp4_boxes(media, 0, file_size))
        if not top or top[-1][2] != file_size:
            valid = False
        for kind, offset, box_end, payload_start in top:
            if kind == b"moov" and moov_offset is None:
                moov_offset = offset
                moov_children = list(_read_mp4_boxes(media, payload_start, box_end))
                if payload_start < box_end and (not moov_children or moov_children[-1][2] != box_end):
                    valid = False
                for child, _child_start, child_end, child_payload in moov_children:
                    if child != b"trak":
                        continue
                    trak_children = list(_read_mp4_boxes(media, child_payload, child_end))
                    if child_payload < child_end and (not trak_children or trak_children[-1][2] != child_end):
                        valid = False
                    for trak_child, _trak_start, trak_end, trak_payload in trak_children:
                        if trak_child != b"edts":
                            continue
                        edit_children = list(_read_mp4_boxes(media, trak_payload, trak_end))
                        if trak_payload < trak_end and (not edit_children or edit_children[-1][2] != trak_end):
                            valid = False
                        for edit_child, _edit_start, _edit_end, _edit_payload in edit_children:
                            has_edit_list |= edit_child == b"elst"
            elif kind == b"mdat" and mdat_offset is None:
                mdat_offset = offset
    return {
        "valid": valid,
        "moov_offset": moov_offset,
        "mdat_offset": mdat_offset,
        "moov_front": moov_offset is not None and mdat_offset is not None and moov_offset < mdat_offset,
        "edit_list": has_edit_list,
    }


def mp4_moov_precedes_mdat(path):
    """Check top-level MP4 atom order without exposing or decoding media contents."""
    return mp4_atom_structure(path)["moov_front"]


def is_compatible(media, size_bytes, moov_front=True, has_edit_list=False, atom_structure_valid=True):
    return not compatibility_issues(media, size_bytes, moov_front, has_edit_list, atom_structure_valid)


def compatibility_issues(media, size_bytes, moov_front=True, has_edit_list=False, atom_structure_valid=True):
    fmt = media.get("format", {})
    streams = media.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video:
        return ["video akışı yok"]
    format_names = set(str(fmt.get("format_name", "")).split(","))
    fps = _fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    duration = float(fmt.get("duration") or 0)
    ratio = float(video.get("width") or 0) / max(float(video.get("height") or 0), 1)
    issues = []
    checks = (
        ("mp4" in format_names, "kapsayıcı MP4 değil"),
        (video.get("codec_name") in ("h264", "hevc"), "video codec H.264/HEVC değil"),
        (0 < int(video.get("width") or 0) <= 1920, "video genişliği geçersiz"),
        (0 < int(video.get("height") or 0), "video yüksekliği geçersiz"),
        (0.01 <= ratio <= 10, "en-boy oranı geçersiz"),
        (23 <= fps <= 60, "FPS 23-60 aralığında değil"),
        (video.get("pix_fmt", "").endswith("420p"), "piksel biçimi 4:2:0 değil"),
        (video.get("sample_aspect_ratio", "1:1") in ("1:1", "N/A"), "piksel oranı 1:1 değil"),
        (video.get("field_order", "unknown") in ("progressive", "unknown"), "video interlaced"),
        (3 <= duration <= 900, "süre 3-900 saniye aralığında değil"),
        (size_bytes <= MAX_FILE_BYTES, "dosya 1 GB sınırını aşıyor"),
        (moov_front, "MP4 moov atomu önde değil"),
        (not has_edit_list, "MP4 edit list (edts/elst) bulunuyor"),
        (atom_structure_valid, "MP4 atom yapısı geçersiz"),
    )
    issues.extend(message for ok, message in checks if not ok)
    # Meta's Reels limit is 25 Mbps.  Some files omit bit_rate in ffprobe;
    # absence is not treated as a failure, but a known over-limit stream is.
    try:
        bitrate = int(video.get("bit_rate") or 0)
    except (TypeError, ValueError):
        bitrate = 0
    if bitrate and bitrate > 25_000_000:
        issues.append("video bitrate 25 Mbps sınırını aşıyor")
    if audio:
        if audio.get("codec_name") != "aac":
            issues.append("ses codec AAC değil")
        if audio.get("profile") not in (None, "", "LC", "AAC Low Complexity", "unknown"):
            issues.append("ses profili AAC-LC değil")
        if not 0 < int(audio.get("sample_rate") or 0) <= 48000:
            issues.append("ses örnekleme hızı geçersiz")
        if int(audio.get("channels") or 0) not in (1, 2):
            issues.append("ses kanal sayısı mono/stereo değil")
    return issues


def _transcode_vertical(source, output):
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        # Conservative H.264/AAC profile for Meta's binary Reels processor.
        # Explicit bitrate/profile avoids CRF peaks that can be rejected even
        # when the container and dimensions look valid to ffprobe.
        "-r", "30", "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.1",
        # Keep long Film parts comfortably below Meta's processing ceiling;
        # the previous 8M/12M profile produced a 184 MB upload that Meta
        # rejected even after codec/container normalization.
        "-preset", "veryfast", "-b:v", "4M", "-maxrate", "6M", "-bufsize", "12M",
        "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
        "-x264-params", "keyint=60:min-keyint=60:scenecut=0:open_gop=0",
        "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-use_editlist", "0", "-avoid_negative_ts", "make_zero",
        "-flags", "+cgop", "-tag:v", "avc1",
        "-map_metadata", "-1", str(output),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError):
        output.unlink(missing_ok=True)
        raise RuntimeError("Instagram için güvenli FFmpeg dönüşümü başarısız oldu.") from None


def _transcode_film_compact(source, output):
    """Match the Film profile whose full-length upload reached FINISHED."""
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=360:640:force_original_aspect_ratio=decrease,"
               "pad=360:640:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        "-r", "25", "-fps_mode", "cfr",
        "-c:v", "libx264", "-profile:v", "main", "-level:v", "3.0",
        "-preset", "veryfast", "-b:v", "500k", "-maxrate", "800k",
        "-bufsize", "1600k", "-pix_fmt", "yuv420p", "-g", "50",
        "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k",
        "-ar", "44100", "-ac", "2", "-movflags", "+faststart",
        "-use_editlist", "0", "-avoid_negative_ts", "make_zero",
        "-map_metadata", "-1", str(output),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError):
        output.unlink(missing_ok=True)
        raise RuntimeError("Film Instagram compact dönüşümü başarısız oldu.") from None


def create_diagnostic_clip(source, output, duration_seconds=15):
    """Create a short, standards-compliant temporary clip for upload-only diagnosis."""
    try:
        duration_seconds = int(duration_seconds)
    except (TypeError, ValueError):
        raise ValueError("Tanı klibi süresi tam sayı olmalı.") from None
    if not 5 <= duration_seconds <= 60:
        raise ValueError("Tanı klibi 5-60 saniye aralığında olmalı.")
    output = Path(output)
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-t", str(duration_seconds),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        "-r", "30", "-fps_mode", "cfr",
        "-c:v", "libx264", "-profile:v", "main", "-level:v", "4.0",
        "-preset", "veryfast", "-b:v", "2500k", "-maxrate", "3500k", "-bufsize", "5M",
        "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60",
        "-x264-params", "keyint=60:min-keyint=60:scenecut=0:open_gop=0",
        "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-use_editlist", "0", "-avoid_negative_ts", "make_zero",
        "-map_metadata", "-1", str(output),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
        media = probe(output)
        size_bytes = output.stat().st_size
        atoms = mp4_atom_structure(output)
        if compatibility_issues(media, size_bytes, atoms["moov_front"], atoms["edit_list"], atoms["valid"]):
            raise RuntimeError("Tanı klibi Meta uyumluluk doğrulamasından geçemedi.")
        duration = float(media.get("format", {}).get("duration") or 0)
        if not 3 <= duration <= duration_seconds + 2:
            raise RuntimeError("Tanı klibi beklenen süre aralığında değil.")
        return output
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
        output.unlink(missing_ok=True)
        raise RuntimeError("Instagram tanı klibi üretilemedi veya doğrulanamadı.") from None


def remux_mp4_faststart(source, output):
    """Repackage an MP4 without re-encoding audio/video, moving moov forward."""
    output = Path(output)
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
        "-movflags", "+faststart", "-use_editlist", "0",
        "-map_metadata", "-1", str(output),
    ]
    try:
        source_media = probe(source)
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
        media = probe(output)
        size_bytes = output.stat().st_size
        atoms = mp4_atom_structure(output)
        issues = compatibility_issues(media, size_bytes, atoms["moov_front"], atoms["edit_list"], atoms["valid"])
        print(
            f"Instagram remux denetimi: source_duration={source_media.get('format', {}).get('duration','?')}; "
            f"output_duration={media.get('format', {}).get('duration','?')}; "
            f"moov_front={str(atoms['moov_front']).lower()}; edit_list={str(atoms['edit_list']).lower()}; "
            f"issues={';'.join(issues) or 'none'}.", flush=True,
        )
        if issues:
            raise RuntimeError("Yeniden paketlenen medya uyumsuz: " + "; ".join(issues))
        _validate_remux_timing(source_media, media)
        return output
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
        output.unlink(missing_ok=True)
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"Instagram MP4 remux başarısız: {reason[:300]}.", flush=True)
        raise RuntimeError(f"MP4 faststart remux doğrulanamadı: {reason[:200]}") from None


def _transcode_film_timeline(source, output):
    """Re-encode without scaling when removing an edit list would shift A/V timing."""
    output = Path(output)
    source_media = probe(source)
    video = next((item for item in source_media.get("streams", []) if item.get("codec_type") == "video"), {})
    fps = _fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    gop = max(24, min(120, round(fps * 2))) if fps else 60
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-vf", "setsar=1",
        "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "23", "-pix_fmt", "yuv420p", "-g", str(gop), "-keyint_min", str(gop),
        "-sc_threshold", "0", "-x264-params", f"keyint={gop}:min-keyint={gop}:scenecut=0:open_gop=0",
        "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-use_editlist", "0", "-avoid_negative_ts", "make_zero",
        "-map_metadata", "-1", str(output),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)
        output_media = probe(output)
        atoms = mp4_atom_structure(output)
        issues = compatibility_issues(
            output_media, output.stat().st_size, atoms["moov_front"], atoms["edit_list"], atoms["valid"]
        )
        if issues:
            raise RuntimeError("Timeline dönüşümü uyumsuz: " + "; ".join(issues))
        check_full_decode(output)
        _validate_remux_timing(source_media, output_media)
        return output
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
        output.unlink(missing_ok=True)
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise RuntimeError(f"Film A/V senkron dönüşümü başarısız: {reason[:200]}") from None


def _validate_remux_timing(source_media, output_media):
    """Fail closed if a stream-copy remux drops streams or materially shifts A/V."""
    source_streams = [item for item in source_media.get("streams", []) if item.get("codec_type") in ("video", "audio")]
    output_streams = [item for item in output_media.get("streams", []) if item.get("codec_type") in ("video", "audio")]
    for kind in ("video", "audio"):
        before = next((item for item in source_streams if item.get("codec_type") == kind), None)
        after = next((item for item in output_streams if item.get("codec_type") == kind), None)
        if bool(before) != bool(after) or (before and before.get("codec_name") != after.get("codec_name")):
            raise RuntimeError("Remux akışları korumadı")
        if before and before.get("start_time") is not None and after.get("start_time") is not None:
            if abs(float(before["start_time"]) - float(after["start_time"])) > 1.0:
                raise RuntimeError(
                    f"Remux {kind} başlangıç zamanını değiştirdi: {before['start_time']}->{after['start_time']}"
                )
        if before and before.get("duration") is not None and after.get("duration") is not None:
            if abs(float(before["duration"]) - float(after["duration"])) > 1.0:
                raise RuntimeError(f"Remux {kind} süresini değiştirdi: {before['duration']}->{after['duration']}")
    before_duration = float(source_media.get("format", {}).get("duration") or 0)
    after_duration = float(output_media.get("format", {}).get("duration") or 0)
    if not before_duration or not after_duration or abs(before_duration - after_duration) > 1.0:
        raise RuntimeError(f"Remux toplam süresi değişti: {before_duration}->{after_duration}")
    before_video = next((item for item in source_streams if item.get("codec_type") == "video"), None)
    before_audio = next((item for item in source_streams if item.get("codec_type") == "audio"), None)
    after_video = next((item for item in output_streams if item.get("codec_type") == "video"), None)
    after_audio = next((item for item in output_streams if item.get("codec_type") == "audio"), None)
    if before_video and before_audio and not all(
        item and item.get("start_time") is not None for item in (before_video, before_audio, after_video, after_audio)
    ):
        raise RuntimeError("Remux ses-görüntü zaman damgaları doğrulanamadı")
    if all(item and item.get("start_time") is not None for item in (before_video, before_audio, after_video, after_audio)):
        old_offset = float(before_audio["start_time"]) - float(before_video["start_time"])
        new_offset = float(after_audio["start_time"]) - float(after_video["start_time"])
        if abs(old_offset - new_offset) > 0.1:
            raise RuntimeError(f"Remux A/V ofsetini değiştirdi: {old_offset:.3f}s->{new_offset:.3f}s")


def prepare_instagram_upload(
    source, converted_path, prefer_remux=False, film_compact=False,
    toonzone_compact=False, return_method=False,
):
    """Return the original if compliant; otherwise convert and verify before upload."""
    source = Path(source)
    converted_path = Path(converted_path)
    compact_profile = film_compact or toonzone_compact
    try:
        original_probe = probe(source)
        atoms = mp4_atom_structure(source)
        original_issues = compatibility_issues(
            original_probe, os.path.getsize(source), atoms["moov_front"], atoms["edit_list"], atoms["valid"]
        )
        original_ok = not original_issues
    except (OSError, ValueError, subprocess.SubprocessError):
        original_probe = {}
        original_ok = False
        original_issues = ["FFprobe kaynağı okuyamadı"]
    if compact_profile:
        # Film's successful compact profile is also forced for ToonZone's
        # cover-composited output: the generic compatibility checks previously
        # let that output pass through unchanged despite Meta rejecting it.
        original_issues.append("IG kompakt bitstream normalizasyonu gerekli")
        original_ok = False
    if original_ok:
        source_hash = _sha256(source) if source.exists() else "unavailable"
        print(
            f"Instagram kaynak medya doğrulandı; orijinal kullanılacak "
            f"(sha256={source_hash}, bytes={os.path.getsize(source)}, faststart=true; "
            f"{_media_summary(original_probe)}).",
            flush=True,
        )
        return (source, "direct") if return_method else source

    source_hash = _sha256(source) if source.exists() else "unavailable"
    print(
        f"Instagram kaynak medya uyumsuz (sha256={source_hash}, "
        f"bytes={os.path.getsize(source)}; {_media_summary(original_probe)}): "
        + "; ".join(original_issues),
        flush=True,
    )
    atom_only_issues = {"MP4 moov atomu önde değil", "MP4 edit list (edts/elst) bulunuyor"}
    if prefer_remux and not film_compact and set(original_issues) and set(original_issues) <= atom_only_issues:
        try:
            remuxed = remux_mp4_faststart(source, converted_path)
            remuxed_probe = probe(remuxed)
            print(
                f"Instagram faststart remux kullanıldı; akışlar yeniden kodlanmadı "
                f"(sha256={_sha256(remuxed)}, bytes={remuxed.stat().st_size}, "
                f"faststart=true; {_media_summary(remuxed_probe)}).",
                flush=True,
            )
            return (remuxed, "remux") if return_method else remuxed
        except RuntimeError as exc:
            if "A/V ofsetini değiştirdi" not in str(exc) or "MP4 edit list (edts/elst) bulunuyor" not in original_issues:
                raise
            print(
                "Instagram edit-list remux sonrası A/V zamanlaması kaydı; çözünürlük korunarak kontrollü transcode kullanılacak.",
                flush=True,
            )
            normalized = _transcode_film_timeline(source, converted_path)
            normalized_probe = probe(normalized)
            print(
                f"Instagram Film timeline transcode kullanıldı (sha256={_sha256(normalized)}, "
                f"bytes={normalized.stat().st_size}; faststart=true; "
                f"{_media_summary(normalized_probe)}).", flush=True,
            )
            return (normalized, "transcode") if return_method else normalized
    if compact_profile:
        _transcode_film_compact(source, converted_path)
    else:
        _transcode_vertical(source, converted_path)
    try:
        converted_probe = probe(converted_path)
        atoms = mp4_atom_structure(converted_path)
        converted_ok = not compatibility_issues(
            converted_probe, os.path.getsize(converted_path), atoms["moov_front"], atoms["edit_list"], atoms["valid"]
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        converted_ok = False
    if not converted_ok:
        converted_path.unlink(missing_ok=True)
        raise RuntimeError("Dönüştürülen Instagram videosu doğrulamadan geçemedi; yükleme durduruldu.")
    if compact_profile:
        check_full_decode(converted_path)
    converted_hash = _sha256(converted_path) if converted_path.exists() else "unavailable"
    print(
        f"Instagram medya kontrolü için FFmpeg yedeği kullanıldı "
        f"(sha256={converted_hash}, bytes={os.path.getsize(converted_path)}, faststart=true; "
        f"{_media_summary(converted_probe)}).",
        flush=True,
    )
    return (converted_path, "transcode") if return_method else converted_path


def _sha256(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as media:
        for chunk in iter(lambda: media.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
