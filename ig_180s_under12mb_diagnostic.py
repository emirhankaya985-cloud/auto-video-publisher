"""Exactly two owner-rights-pinned 180s SMALL unpublished IG upload probes.

Purpose: distinguish 180s duration from previous 42MB single-binary rupload
failure; both 15s (~5MB) probes reached FINISHED. Do not publish, reset claims,
touch FB, retry preexisting containers or advertise these drafts as Reels.
"""
import json
import os
from pathlib import Path
import subprocess

from ig_shortclip_uploadonly_diagnostic import execute

MAX_TEST_BYTES = 12_000_000


def low_size_full_clip(source, target, run=subprocess.run):
    from instagram_media_compat import (
        probe, mp4_atom_structure, compatibility_issues, check_full_decode
    )
    source, target = Path(source), Path(target)
    if not source.is_file() or source.stat().st_size < 1024:
        raise RuntimeError("Exact-source MP4 unavailable for diagnostic")
    original = probe(source)
    dur = float(original.get("format", {}).get("duration") or 0)
    if not 178 <= dur <= 188:
        raise RuntimeError("Only audited approximately-180-second source is supported")
    args = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-t", "180", "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,"
               "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        "-r", "30", "-fps_mode", "cfr", "-c:v", "libx264",
        "-profile:v", "main", "-level:v", "4.0", "-preset", "veryfast",
        # This is a processing experiment, not a quality-approved publish.
        # The 180s output targets ~9MB to separate transfer size from length.
        "-b:v", "300k", "-maxrate", "420k", "-bufsize", "840k",
        "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60",
        "-sc_threshold", "0", "-x264-params", "keyint=60:min-keyint=60:scenecut=0:open_gop=0",
        "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "96k",
        "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        "-use_editlist", "0", "-avoid_negative_ts", "make_zero",
        "-map_metadata", "-1", str(target)
    ]
    try:
        run(args, check=True, capture_output=True, timeout=900)
        out_bytes = target.stat().st_size
        if not 0 < out_bytes <= MAX_TEST_BYTES:
            raise RuntimeError("Diagnostic binary did not meet 12MB limit")
        media = probe(target)
        seconds = float(media.get("format", {}).get("duration") or 0)
        if not 178 <= seconds <= 182:
            raise RuntimeError("Diagnostic output must retain 180s duration")
        atoms = mp4_atom_structure(target)
        issues = compatibility_issues(
            media, out_bytes, atoms["moov_front"], atoms["edit_list"], atoms["valid"]
        )
        if issues:
            raise RuntimeError("Diagnostic video not Meta-compatible")
        check_full_decode(target)
        return target
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
        target.unlink(missing_ok=True)
        raise RuntimeError("Long unpublished diagnostic media preparation failed") from None


def trial(page, source, filename, workdir, encode=low_size_full_clip, upload=None):
    if upload is None:
        from cloud_omnichannel_publisher import upload_instagram_reel
        upload = upload_instagram_reel
    video = encode(source, Path(workdir) / "180s_under12mb_unpublished.mp4")
    if not Path(video).is_file() or Path(video).stat().st_size > MAX_TEST_BYTES:
        raise RuntimeError("Diagnostic not eligible for upload")
    # This never invokes media_publish. No write to existing intent ledger.
    result = upload(page, str(video), "Unpublished 180s size diagnostic, do not publish",
                    append_store_link=False, publish=False)
    if (not isinstance(result, dict) or result.get("status") != "FINISHED"
            or result.get("published") is not False
            or not str(result.get("container_id") or "").isdecimal()):
        raise RuntimeError("Long diagnostic did not reach FINISHED without publishing")
    return {"status": "FINISHED_NOT_PUBLISHED", "container_id": str(result["container_id"])}


def main():
    if os.environ.get("IG_LONGCLIP_UPLOADONLY_APPROVED") != "true":
        raise RuntimeError("This test requires the dedicated one-time long diagnostic gate")
    report = execute(trial=trial)
    report["mode"] = "180s_under12MB_unpublished_IG_upload_only"
    report["max_test_bytes"] = MAX_TEST_BYTES
    content = json.dumps(report, indent=2, ensure_ascii=False)
    print(content)
    Path("ig-180s-low-size-unpublished.json").write_text(content + "\n", encoding="utf-8")
    return 0 if len(report["files"]) == 2 and all(
        r["status"] == "FINISHED_NOT_PUBLISHED" for r in report["files"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
