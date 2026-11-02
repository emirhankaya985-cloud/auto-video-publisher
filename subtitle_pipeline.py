"""Optional speech captions during local media preparation, before any upload.

Only explicit source-language routes are eligible. A missing local model does
not turn a TXT synopsis into dialogue, and failures preserve the original MP4.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from offline_subtitles import transcribe_local

LANGUAGES = {"film": "tr", "film_second": "tr"}


def prepare_subtitles(video, route, directory, *, transcriber=transcribe_local,
                      runner=subprocess.run):
    """Return (video_path, receipt); never publishes or downloads a model."""
    original = Path(video).resolve()
    if os.getenv("AUTO_SUBTITLES_ENABLED", "false").lower() != "true":
        return original, {"status": "disabled"}
    if route not in LANGUAGES:
        return original, {"status": "source_language_unverified"}
    model = os.getenv("SUBTITLE_MODEL_DIR", "")
    if not model or not Path(model).is_dir():
        return original, {"status": "unavailable", "reason": "local_model_missing"}
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "subtitled.mp4"
    try:
        with tempfile.TemporaryDirectory(dir=directory) as work:
            work = Path(work)
            receipt = transcriber(original, work / "captions.srt", model,
                                  language=LANGUAGES[route])
            # Fixed relative filename and style: source names never enter an
            # FFmpeg filter expression. Preserve duration and optional audio.
            result = runner([
                "ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(original),
                "-map", "0:v:0", "-map", "0:a?", "-vf",
                "subtitles=filename=captions.srt:force_style='FontName=DejaVu Sans,FontSize=18,Outline=2,MarginV=24'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "copy", "-movflags", "+faststart", str(output),
            ], cwd=work, capture_output=True, timeout=600)
            if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
                raise RuntimeError("subtitle_render_failed")
            # Keep the exact SRT with the receipt in the operations artifact.
            (directory / "captions.srt").write_bytes((work / "captions.srt").read_bytes())
        return output, {"status": "burned_in", "language": LANGUAGES[route],
                        "segments": receipt["segments"], "source_modified": False}
    except Exception as exc:
        output.unlink(missing_ok=True)
        return original, {"status": "unavailable", "reason": "subtitle_preparation_failed",
                          "error_type": type(exc).__name__}
