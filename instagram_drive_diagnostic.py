"""Read-only Instagram MP4 diagnostics for explicitly selected Drive files."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

from cloud_omnichannel_publisher import get_drive_client


ALLOWED_REF = "refs/heads/fix/stage-1-publisher-reliability"
KNOWN_FAILED_SLOT = "2026-10-13-20-gonle"


def _list_folder_mp4s(drive, folder_id):
    files = []
    page_token = None
    while True:
        response = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,mimeType,parents,appProperties)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return [
                file for file in files
                if str(file.get("name", "")).lower().endswith(".mp4")
            ]


def select_diagnostic_files(files, failed_id="", comparison_id=""):
    if not failed_id:
        failed_id = next(
            (
                item["id"] for item in files
                if (item.get("appProperties") or {}).get("claimed_route_slot") == KNOWN_FAILED_SLOT
            ),
            "",
        )
    if not failed_id:
        raise ValueError("Bilinen başarısız Gönle slotu için MP4 bulunamadı.")
    if not comparison_id:
        comparison_id = next(
            (
                item["id"] for item in files
                if item["id"] != failed_id
                and (item.get("appProperties") or {}).get("done_ig_slot")
            ),
            "",
        )
    if failed_id == comparison_id:
        raise ValueError("Tanılama dosyaları birbirinden farklı olmalı.")
    return failed_id, comparison_id


def _download_mp4(drive, folder_id, file_id, destination):
    if not file_id:
        raise ValueError("Tanılama için reddedilen MP4 dosya ID'si gerekli.")
    metadata = drive.files().get(
        fileId=file_id, fields="id,name,mimeType,parents,size"
    ).execute()
    if folder_id not in (metadata.get("parents") or []):
        raise ValueError("Seçilen dosya Gönle Drive klasöründe değil.")
    if not str(metadata.get("name", "")).lower().endswith(".mp4"):
        raise ValueError("Seçilen Drive dosyası MP4 değil.")

    request = drive.files().get_media(fileId=file_id)
    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request, chunksize=4 * 1024 * 1024)
        complete = False
        while not complete:
            _, complete = downloader.next_chunk()


def _probe(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=format_name,duration:stream=index,codec_type,codec_name,profile,width,height,r_frame_rate,avg_frame_rate,pix_fmt,sample_rate,channels",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(result.stdout)


def _summarize(label, probe, path):
    streams = probe.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video:
        raise ValueError("MP4 içinde video akışı bulunamadı.")
    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    fmt = probe.get("format", {})
    print(f"{label}:")
    print(f"  container={fmt.get('format_name', 'unknown')}")
    print(f"  duration_seconds={fmt.get('duration', 'unknown')}")
    print(
        "  video="
        f"{video.get('codec_name', 'unknown')}/"
        f"{video.get('profile', 'unknown')} "
        f"{video.get('width', '?')}x{video.get('height', '?')} "
        f"fps={video.get('avg_frame_rate') or video.get('r_frame_rate', 'unknown')} "
        f"pix_fmt={video.get('pix_fmt', 'unknown')}"
    )
    if audio:
        print(
            "  audio="
            f"{audio.get('codec_name', 'unknown')}/"
            f"{audio.get('profile', 'unknown')} "
            f"sample_rate={audio.get('sample_rate', 'unknown')} "
            f"channels={audio.get('channels', 'unknown')}"
        )
    else:
        print("  audio=none")
    print(f"  full_decode={'PASS' if decode.returncode == 0 else 'FAIL'}")
    if decode.returncode != 0:
        raise ValueError("MP4 tam decode kontrolünden geçemedi.")


def main():
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise SystemExit("Tanılama yalnızca workflow_dispatch ile çalışabilir.")
    if os.environ.get("GITHUB_REF") != ALLOWED_REF:
        raise SystemExit("Tanılama yalnızca onaylı PR branch'inde çalışabilir.")
    folder_id = os.environ.get("GONLE_DUSEN_DRIVE_FOLDER_ID", "").strip()
    failed_id = os.environ.get("DIAGNOSTIC_FAILED_FILE_ID", "").strip()
    comparison_id = os.environ.get("DIAGNOSTIC_COMPARISON_FILE_ID", "").strip()
    if not folder_id or (failed_id and failed_id == comparison_id):
        raise SystemExit("Gönle klasörü ve farklı dosya kimlikleri gerekli.")

    try:
        drive = get_drive_client()
        files = _list_folder_mp4s(drive, folder_id)
        failed_id, comparison_id = select_diagnostic_files(files, failed_id, comparison_id)
        with tempfile.TemporaryDirectory(prefix="ig-mp4-diagnostic-") as temp_dir:
            temp = Path(temp_dir)
            failed_path = temp / "rejected.mp4"
            _download_mp4(drive, folder_id, failed_id, failed_path)
            _summarize("Meta tarafından reddedilen MP4", _probe(failed_path), failed_path)
            if comparison_id:
                comparison_path = temp / "comparison.mp4"
                _download_mp4(drive, folder_id, comparison_id, comparison_path)
                _summarize("Başarılı yayın karşılaştırması", _probe(comparison_path), comparison_path)
            else:
                print("Başarılı Gönle Instagram karşılaştırma dosyası bulunamadı.")
    except Exception as exc:
        # Hata metinleri dosya adlarını, Drive kimliklerini veya içerik parçalarını
        # içerebileceği için Actions loglarına aktarılmaz.
        raise SystemExit(f"Tanılama başarısız: {type(exc).__name__}; hassas ayrıntılar gizlendi.") from None


if __name__ == "__main__":
    main()
