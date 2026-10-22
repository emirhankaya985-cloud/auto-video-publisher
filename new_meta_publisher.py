"""Fail-closed execution primitives for disabled new Meta routes.

The scheduled workflows do not import this module yet. It is safe to dry-run
without Meta credentials and contains no implicit route activation.
"""
import hashlib
from batch_api_client import BatchGate
from publication_safety import new_meta_route_enabled
from new_meta_routes import ROUTES, dry_run_route, page_for_target, toonzone_metadata_draft
from ordered_channels import CHANNELS, analyze_files

# Import the already-tested low-level uploaders only as adapters.  The route
# definitions remain disabled by default and these functions are never called
# unless the caller opts in explicitly for a controlled production run.
from cloud_omnichannel_publisher import (
    upload_facebook_reel as _upload_facebook_reel,
    upload_instagram_reel as _upload_instagram_reel,
)

TERMINAL_NO_RETRY = frozenset({"submitted", "confirmed", "unknown", "failed"})
FILM_TARGETS = ("film_magrasi_fb", "filmmagrasi1_fb", "film_magrasi_ig")


def target_status_key(target):
    return "nm_" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]


def film_reconciliation_candidate(files):
    """Return the earliest Film part and only its still-pending targets."""
    report = analyze_files(files, CHANNELS["film_primary"])
    for order, stem, video, text in report["ordered"]:
        if order[0] in report["blocked_series"] or text is None:
            continue
        props = video.get("appProperties") or {}
        states = {target: props.get(target_status_key(target)) for target in FILM_TARGETS}
        if all(state == "confirmed" for state in states.values()):
            continue
        if any(state in {"submitted", "unknown", "failed"} for state in states.values()):
            return {"blocked": True, "reason": "manual_remote_reconciliation_required",
                    "stem": stem, "video": video, "states": states}
        pending = [target for target, state in states.items() if state != "confirmed"]
        return {"blocked": False, "stem": stem, "video": video, "text": text,
                "pending_targets": pending, "states": states}
    return None


def toonzone_candidate(files, reviews_by_file_id):
    """Select ordered content without TXT only after explicit review and rights."""
    report = analyze_files(files, CHANNELS["cartoon_tr"])
    for order, stem, video, _text in report["ordered"]:
        props = video.get("appProperties") or {}
        if props.get(target_status_key("toonzone_fb")) == "confirmed" and props.get(target_status_key("toonzone_ig")) == "confirmed":
            continue
        review = reviews_by_file_id.get(video["id"])
        try:
            metadata = toonzone_metadata_draft(review, rights_approved=bool(review and review.get("rights_approved")))
        except RuntimeError:
            continue
        return {"order": order, "stem": stem, "video": video, "metadata": metadata}
    return None


def _caption_from_review(review):
    """Build a caption without inventing metadata for an unreviewed video."""
    if not isinstance(review, dict):
        return ""
    title = str(review.get("title") or "").strip()
    description = str(review.get("description") or review.get("summary") or "").strip()
    if title and description:
        return f"{title}\n\n{description}"
    return title or description


def build_meta_callbacks(route_key, meta_auth, video_path, *, publishing_enabled=False,
                         facebook_uploader=None, instagram_uploader=None):
    """Return upload callbacks for a route, disabled unless explicitly opted in.

    ``video_path`` is captured so the existing publisher adapters receive the
    actual MP4 rather than a review object.  The default returns an empty map;
    this keeps dry-runs and scheduled jobs publishing-free by construction.
    Injected uploaders make the adapter unit-testable without Meta API calls.
    """
    if publishing_enabled is not True:
        return {}
    if not video_path:
        raise ValueError("video_path zorunlu")
    route = ROUTES[route_key]
    fb_upload = facebook_uploader or _upload_facebook_reel
    ig_upload = instagram_uploader or _upload_instagram_reel
    callbacks = {}
    for target in route.targets:
        page = page_for_target(meta_auth, target)
        if page is None:
            raise RuntimeError(f"Meta hedefi doğrulanmadı: {target.page_name}")
        uploader = ig_upload if target.platform == "instagram" else fb_upload

        def callback(review, *, _page=page, _uploader=uploader):
            remote = _uploader(_page, str(video_path), _caption_from_review(review))
            if isinstance(remote, dict):
                return remote
            return {"id": str(remote)}

        callbacks[target.key] = callback
    return callbacks


def execute_plan(route_key, meta_auth, selected_video, callbacks, content_review,
                 rights_approved, state_writer, gate_factory=BatchGate,
                 publishing_enabled=False):
    """Execute explicitly enabled callbacks; never retries uncertain outcomes."""
    plan = dry_run_route(route_key, meta_auth, selected_video, rights_approved)
    results = []
    # The production switch is deliberately separate from route definitions.
    # A callback map alone must never be enough to publish during a dry-run.
    if publishing_enabled is not True:
        return [{"target": target["target"], "status": "skipped", "reason": "publishing_disabled"}
                for target in plan]
    if not new_meta_route_enabled(route_key):
        return [{"target": target["target"], "status": "skipped", "reason": "route_disabled"}
                for target in plan]
    for target in plan:
        key = target["target"]
        callback = callbacks.get(key)
        if callback is None:
            results.append({"target": key, "status": "skipped", "reason": "callback_missing"})
            continue
        current = (selected_video.get("appProperties") or {}).get(target_status_key(key))
        if current in TERMINAL_NO_RETRY:
            results.append({"target": key, "status": "skipped", "reason": current})
            continue
        gate = gate_factory(key, target["platform"], selected_video["id"], target["drive_folder_id"])
        if not gate.enabled or not gate.claim():
            results.append({"target": key, "status": "skipped", "reason": "claim_denied"})
            continue
        state_writer(key, "submitted")
        try:
            remote = callback(content_review)
        except Exception as exc:
            # Once a publish callback started, absence of a local response is not
            # proof that the remote post does not exist. Fail closed as unknown.
            state_writer(key, "unknown")
            gate.finish("unknown", error=type(exc).__name__)
            results.append({"target": key, "status": "unknown"})
            continue
        remote_id = str(remote.get("id") or "")
        remote_url = str(remote.get("url") or "")
        if not remote_id:
            state_writer(key, "unknown")
            gate.finish("unknown", error="missing_remote_id")
            results.append({"target": key, "status": "unknown"})
            continue
        state_writer(key, "confirmed")
        gate.finish("confirmed", remote_id=remote_id, remote_url=remote_url)
        results.append({"target": key, "status": "confirmed", "remote_id": remote_id, "remote_url": remote_url})
    return results
