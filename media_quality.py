"""Bounded local decode, black-screen and silence checks, before any upload."""
import json
import re
import subprocess
from pathlib import Path


def run(command, *, timeout):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('quality_check_unavailable') from None
    if result.returncode:
        raise RuntimeError('media_decode_failed')
    return result


def inspect_video(path, *, runner=run):
    path = str(Path(path).resolve())
    info = json.loads(runner(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                              '-of', 'json', path], timeout=30).stdout)
    streams = info.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    duration = float(info.get('format', {}).get('duration', 0))
    if (not video or not 0 < duration < 10800 or
            min(int(video.get('width', 0)), int(video.get('height', 0))) < 144):
        raise RuntimeError('invalid_video_format')
    # Sample beginning, middle and end. Do not call this exhaustive QC.
    window = min(8., duration)
    offsets = sorted({0., max(0., duration / 2 - window / 2), max(0., duration - window)})
    audio = any(s.get('codec_type') == 'audio' for s in streams)
    black, silent = [], []
    for offset in offsets:
        command = ['ffmpeg', '-nostdin', '-hide_banner', '-v', 'info', '-xerror',
                   '-ss', str(offset), '-i', path, '-t', str(window),
                   '-vf', 'blackdetect=d=0.2:pix_th=0.10', '-map', '0:v:0']
        if audio:
            command += ['-map', '0:a:0', '-af', 'volumedetect']
        command += ['-f', 'null', '-']
        log = runner(command, timeout=60).stderr
        intervals = [float(x) for x in re.findall(r'black_duration:([0-9.]+)', log)]
        black.append(sum(intervals) >= window * .95)
        if audio:
            peaks = re.findall(r'max_volume:\s*(-?inf|[-0-9.]+) dB', log)
            if not peaks:
                raise RuntimeError('audio_measurement_unavailable')
            silent.append(float(peaks[-1]) < -55.)
    if all(black):
        raise RuntimeError('black_screen_samples')
    if not audio or all(silent):
        raise RuntimeError('silent_audio_samples')
    return dict(status='passed_samples', duration=duration, samples=len(offsets),
                audio_present=audio, black_samples=sum(black), silent_samples=sum(silent),
                scope='up to three 8-second samples; not exhaustive')
