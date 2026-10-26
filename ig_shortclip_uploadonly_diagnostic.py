"""One-time *unpublished* 15s Meta IG upload diagnostic for two exact source MP4s.

Creates a NEW temporary, unpublished media container only for diagnostic use.
Never calls media_publish; never touches the producer's state/claim/plan.
The full-length failed Reels and their existing container IDs remain blocked.
"""
import json
import os
import tempfile
from pathlib import Path

SOURCES = (
    ("film", "Yoksul_1986_Part_16.mp4",
     "1239298989276639", "17841477990224124"),
    ("toonzone", "S01E03_Caffeinated_Concert_Tickets_Part3.mp4",
     "1298191963387372", "17841477404255851"),
)


def require_explicit_one_shot():
    if (os.getenv("GITHUB_EVENT_NAME") != "push"
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("IG_SHORTCLIP_UPLOADONLY_APPROVED") != "true"):
        raise RuntimeError("Unpublished short-clip diagnostic requires approved main push")
    if os.getenv("GITHUB_REPOSITORY") != "emirhankaya985-cloud/auto-video-publisher":
        raise RuntimeError("Diagnostic repo identity mismatch")


def selected_video(files, exact_filename):
    matches = [item for item in files.values()
               if item.get("name") == exact_filename
               and isinstance(item.get("id"), str) and item["id"].strip()]
    if len(matches) != 1:
        raise RuntimeError("Exact source filename is missing or ambiguous")
    return matches[0]


def upload_only_trial(page, source, original_name, workdir, *, diagnostic_clip=None, upload=None):
    """Upload only 15 seconds; exact source is the sole input; never publish."""
    if diagnostic_clip is None:
        from instagram_media_compat import create_diagnostic_clip
        diagnostic_clip = create_diagnostic_clip
    if upload is None:
        from cloud_omnichannel_publisher import upload_instagram_reel
        upload = upload_instagram_reel
    path = diagnostic_clip(source, Path(workdir) / "upload_only_15s.mp4", 15)
    if not Path(path).is_file() or Path(path).stat().st_size <= 0:
        raise RuntimeError("Short diagnostic media missing or empty")
    result = upload(
        page, str(path),
        "Unpublished compatibility check, no scheduled Reel",
        append_store_link=False, publish=False,
    )
    if (not isinstance(result, dict) or result.get("published") is not False
            or result.get("status") != "FINISHED"
            or not str(result.get("container_id") or "").isdecimal()):
        raise RuntimeError("Instagram upload-only did not return a verified FINISHED container")
    return {"status": "FINISHED_NOT_PUBLISHED",
            "container_id": str(result["container_id"]), "post_id": None}


def execute(*, inventory=None, download=None, loader=None,
            trial=None, paused=None, gate=None):
    # Each independent unpublished diagnostic must enforce its own release gate.
    (gate or require_explicit_one_shot)()
    # An injected test inventory must never import public_link_runtime:
    # it depends on gdown, available on the production publisher runner but
    # deliberately absent from the zero-credential CI regression environment.
    if inventory is None or download is None:
        from public_link_runtime import FOLDERS, inventory as real_inventory, download as real_download
        inventory = inventory or real_inventory
        download = download or real_download
    else:
        FOLDERS = {route: route for route, _, _, _ in SOURCES}
    if loader is None:
        from meta_auth_loader import load_meta_auth
        loader = load_meta_auth
    if paused is None:
        from publication_safety import route_paused
        paused = route_paused
    if trial is None:
        trial = upload_only_trial
    # Check BOTH owner-approved route and rights switches before a single
    # external write, and only permit the two pinned Page+IG identities.
    for route, _, _, _ in SOURCES:
        if paused(route):
            raise RuntimeError("Content rights/route switch is off; no diagnostic upload")
    auth = loader()
    pages = auth.get("pages") if isinstance(auth, dict) else None
    if not isinstance(pages, list):
        raise RuntimeError("Saved Meta page identities unavailable")
    verified = []
    for route, filename, page_id, ig_id in SOURCES:
        candidates = [p for p in pages if str(p.get("page_id")) == page_id
                      and str(p.get("instagram_id")) == ig_id
                      and isinstance(p.get("page_token"), str)
                      and p["page_token"]]
        if len(candidates) != 1:
            raise RuntimeError("Pinned Film/ToonZone account identity mismatch")
        verified.append((route, filename, candidates[0]))
    rows = []
    for route, filename, page in verified:
        try:
            files = inventory(FOLDERS[route])
            item = selected_video(files, filename)
            with tempfile.TemporaryDirectory(prefix="safe-ig-upload-only-") as folder:
                root = Path(folder)
                source = download(item["id"], root / "source.mp4")
                result = trial(page, source, filename, root)
            rows.append({"route": route, "file": filename,
                         "status": result["status"],
                         "diagnostic_container_id": result["container_id"],
                         "published": False, "post_id": None})
        except Exception as exc:
            # NEVER display raw provider error body, token or private URLs.
            status = getattr(exc, "http_status", None)
            rows.append({"route": route, "file": filename, "status": "FAILED",
                         "exception_class": type(exc).__name__,
                         "http_status": status if type(status) is int else None,
                         "published": False, "post_id": None})
    return {"schema": 1, "mode": "15s_unpublished_ig_upload_only",
            "existing_intents_changed": False, "media_publish_calls": 0,
            "files": rows}


def main():
    report = execute()
    message = json.dumps(report, ensure_ascii=False, indent=2)
    print(message)
    Path("ig-shortclip-uploadonly-result.json").write_text(message + "\n", encoding="utf-8")
    return 0 if report["files"] and all(
        item["status"] == "FINISHED_NOT_PUBLISHED" for item in report["files"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
