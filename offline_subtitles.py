"""Offline, opt-in captions from actual speech (not a fabricated TXT summary).

For zero-network operation, provide a previously installed faster-whisper
CTranslate2 model DIRECTORY. Nothing downloads or publishes automatically.
"""
from __future__ import annotations
import argparse
import math
import os
import tempfile
from pathlib import Path


def _timestamp(seconds):
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("invalid subtitle time")
    milliseconds = round(seconds * 1000)
    h, rem = divmod(milliseconds, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_srt(segments, *, max_segments=10000):
    output = []
    end_prior = 0.0
    for index, item in enumerate(segments, 1):
        if index > max_segments:
            raise ValueError("too many subtitle segments")
        start, end, text = item
        if not isinstance(text, str):
            raise ValueError("subtitle text invalid")
        text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if not text:
            continue
        if not (isinstance(start, (int, float)) and isinstance(end, (int, float))
                and math.isfinite(start) and math.isfinite(end) and
                0 <= start <= end <= 10800 and start + 0.05 >= end_prior):
            raise ValueError("overlapping or invalid subtitle timestamps")
        output.append(f"{len(output)+1}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}\n")
        end_prior = end
    if not output:
        raise ValueError("no verified speech segments")
    return "\n".join(output) + "\n"


def transcribe_local(video, destination, model_directory, *, language="tr", model_factory=None):
    video = Path(video)
    destination = Path(destination)
    directory = Path(model_directory)
    if not video.is_file() or video.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
        raise ValueError("source video missing or unsupported")
    if not directory.is_dir():
        raise ValueError("local speech model directory missing")
    if language not in {"tr", "en", "de"}:
        raise ValueError("explicit speech language required")
    if destination.exists():
        raise FileExistsError("subtitle file already exists; refusing overwrite")
    if model_factory is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("local faster-whisper is not installed") from None
        model_factory = WhisperModel
    model = model_factory(str(directory), device="cpu", compute_type="int8",
                          local_files_only=True)
    segments, _info = model.transcribe(str(video), language=language,
                                      vad_filter=True, beam_size=3)
    srt = build_srt((s.start, s.end, s.text) for s in segments)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("subtitle file already exists; refusing overwrite")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                         dir=destination.parent, suffix=".tmp",
                                         delete=False) as file:
            file.write(srt)
            tmp = Path(file.name)
        # Fail closed if another process placed an SRT after our first check.
        if destination.exists():
            raise FileExistsError("subtitle destination changed")
        os.link(tmp, destination)
        return {"status": "srt_created", "segments": srt.count(" --> "),
                "language": language, "auto_published": False}
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Offline speech-to-SRT: never publishes")
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--language", default="tr", choices=["tr", "en", "de"])
    args = parser.parse_args()
    print(transcribe_local(args.video, args.out, args.model_dir,
                           language=args.language))


if __name__ == "__main__":
    main()
