"""Read-only production Meta identity and permission audit.

Never prints access tokens or page tokens and contains no publishing call.
"""
import json
import os
import re
import sys
import traceback
import unicodedata
from pathlib import Path

from connection_audit import AuditError, graph_get, graph_list, google_client, safe_error
from new_meta_routes import EXCLUDED_META_PAGES, ROUTES, verified_pages

REQUIRED_PERMISSIONS = frozenset({
    "pages_show_list", "pages_read_engagement", "pages_manage_posts",
    "instagram_basic", "instagram_content_publish", "read_insights",
    "instagram_manage_insights",
})
FILM_CLAIM_FILE_ID = "1dhKwAI9LPpUEniIfqNuWKrY8EQuM67xZ"
FILM_PAGE_ID = "1239298989276639"
FILM_AUDIT_FILES = {
    "Yoksul_1986_Part_1.mp4": "17VUvr-CaB7-NPc9d8Ukr7rXDyTDFUqqr",
    "Yoksul_1986_Part_2.mp4": "1dhKwAI9LPpUEniIfqNuWKrY8EQuM67xZ",
    "Yoksul_1986_Part_3.mp4": "1IJloVdio5n6NY4UpxQTgIps7peZ8dv7c",
    "Yoksul_1986_Part_4.mp4": "11j94Mfe39BADmBXu0EUZ6RrckD7YudJT",
    "Yoksul_1986_Part_5.mp4": "1FlxhrUoqtmpNGU68C-8HNVJCcRy2KBdx",
}
FILM_KNOWN_FB_IDS = {
    "1IJloVdio5n6NY4UpxQTgIps7peZ8dv7c": ("2415483262192096", "1494339649202618"),
    "11j94Mfe39BADmBXu0EUZ6RrckD7YudJT": ("1737090337355286", "2095433004391736"),
}
FILM_STATE_KEYS = (
    "claimed_route_slot", "claimed_at", "last_route_slot", "failed_route_slot",
    "film_used", "film_done", "intent_fb_film_1_slot", "intent_fb_film_2_slot",
    "intent_ig_slot", "intent_yt_film_slot", "done_fb_film_1_slot",
    "done_fb_film_2_slot", "done_ig_slot", "done_yt_film_slot",
    "failure_fb_film_1_count", "failure_fb_film_2_count", "failure_ig_count",
    "failure_yt_film_count", "failure_slot_fb_film_1", "failure_slot_fb_film_2",
    "failure_slot_ig", "failure_slot_yt_film", "result_fb_film_1",
    "result_fb_film_2", "result_ig", "result_yt_film",
    "published_fb_film_1", "published_fb_film_2", "published_ig",
    "platform_result_fb_film_1", "platform_result_fb_film_2", "platform_result_ig",
    "platform_slot_fb_film_1", "platform_slot_fb_film_2", "platform_slot_ig",
    "film_part3_ig_recovery_used", "film_part4_ig_recovery_used",
    "film_part5_recovery_used", "film_part5_recovery_from",
)


def token_format_flags(token):
    value = token if isinstance(token, str) else ""
    return {
        "empty": value == "",
        "leading_whitespace": bool(value) and value[0].isspace(),
        "trailing_whitespace": bool(value) and value[-1].isspace(),
        "contains_line_break": "\n" in value or "\r" in value,
        "surrounded_by_quote": len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0],
    }


def safe_meta_error(exc, diagnostic):
    frames = traceback.extract_tb(exc.__traceback__)
    result = {
        "error_type": type(exc).__name__,
        "phase": diagnostic.get("phase", "audit_setup"),
        "http_status": diagnostic.get("http_status"),
        "token_format": diagnostic.get("token_format", token_format_flags("")),
        "traceback": [
            {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in frames
        ],
    }
    if isinstance(exc, AuditError):
        for key in ("audit_error", "code", "subcode", "type", "variable"):
            if key in exc.details:
                result[key] = exc.details[key]
    return result


def audit_meta(access_token=None, meta_auth=None, diagnostic=None):
    diagnostic = diagnostic if diagnostic is not None else {}
    token = access_token if access_token is not None else os.environ.get("META_ACCESS_TOKEN", "")
    diagnostic.update({
        "phase": "credential_configuration",
        "http_status": None,
        "token_format": token_format_flags(token),
    })
    auth = meta_auth if meta_auth is not None else json.loads(os.environ.get("META_AUTH_JSON") or "{}")
    if not token:
        raise AuditError("missing_credential", variable="META_ACCESS_TOKEN")
    configured = verified_pages(auth)
    live_rows = graph_list(
        "me/accounts", token, "id,name,instagram_business_account{id,username}",
        diagnostic=diagnostic,
    )
    live = {row.get("name"): row for row in live_rows if row.get("name") not in EXCLUDED_META_PAGES}
    live_by_id = {str(row.get("id")): row for row in live_rows if row.get("id")}
    permissions = graph_get("me/permissions", token, diagnostic=diagnostic).get("data", [])
    granted = {row.get("permission") for row in permissions if row.get("status") == "granted"}
    missing = sorted(REQUIRED_PERMISSIONS - granted)
    results = []
    target_names = sorted({target.page_name for route in ROUTES.values() for target in route.targets})
    for name in target_names:
        matching_targets = [target for route in ROUTES.values() for target in route.targets
                            if target.page_name == name]
        expected_id = next((target.page_id for target in matching_targets if target.page_id), None)
        saved = next((row for row in configured.values()
                      if expected_id and str(row.get("page_id")) == str(expected_id)), None)
        if saved is None:
            saved = configured.get(name)
        current = live_by_id.get(str(expected_id)) if expected_id else live.get(name)
        status, reason = "passed", None
        if not saved or not current:
            status, reason = "blocked", "configured_or_live_page_missing"
        elif str(saved.get("page_id")) != str(current.get("id")):
            status, reason = "blocked", "page_id_mismatch"
        else:
            needs_ig = any(t.page_name == name and t.platform == "instagram" for r in ROUTES.values() for t in r.targets)
            current_ig = str((current.get("instagram_business_account") or {}).get("id") or "")
            if needs_ig and (not saved.get("instagram_id") or str(saved.get("instagram_id")) != current_ig):
                status, reason = "blocked", "instagram_id_mismatch"
        results.append({"page_name": name, "page_id": str(current.get("id")) if current else None,
                        "instagram_id": str((current.get("instagram_business_account") or {}).get("id")) if current and current.get("instagram_business_account") else None,
                        "status": status, "reason": reason})
    return {"accounts": results, "required_permissions_complete": not missing,
            "missing_permissions": missing, "excluded_pages": sorted(EXCLUDED_META_PAGES),
            "publishing_performed": False,
            "token_format": diagnostic.get("token_format", token_format_flags(token))}


def audit_film_claim(file_id=None, meta_auth=None, drive=None):
    """Read-only reconcile one claimed Film MP4 against Drive ledger and IG history."""
    file_id = file_id or os.environ.get("FILM_CLAIM_AUDIT_FILE_ID", "")
    if file_id != FILM_CLAIM_FILE_ID:
        raise AuditError("film_claim_file_not_allowlisted")
    auth = meta_auth if meta_auth is not None else json.loads(os.environ.get("META_AUTH_JSON") or "{}")
    pages = verified_pages(auth)
    configured = next((row for row in pages.values() if str(row.get("page_id")) == FILM_PAGE_ID), None)
    if not configured or not configured.get("instagram_id"):
        raise AuditError("film_instagram_identity_not_configured")
    token = configured.get("page_token")
    if not token:
        raise AuditError("film_page_token_missing")
    if drive is None:
        drive, _ = google_client("DRIVE_TOKEN_JSON", "drive")
    folder_id = ROUTES["film"].folder_id
    video = drive.files().get(
        fileId=file_id,
        fields="id,name,parents,trashed,md5Checksum,appProperties",
    ).execute()
    if video.get("trashed") or folder_id not in (video.get("parents") or []):
        raise AuditError("film_file_parent_or_deleted_mismatch")
    identity = graph_get(FILM_PAGE_ID, token, fields="id,name,instagram_business_account{id}")
    ig = identity.get("instagram_business_account") or {}
    if str(identity.get("id")) != FILM_PAGE_ID or str(ig.get("id")) != str(configured["instagram_id"]):
        raise AuditError("film_instagram_identity_mismatch")
    records = graph_list(
        f"{configured['instagram_id']}/media", token, "id,caption,permalink,timestamp",
    )
    props = video.get("appProperties") or {}
    saved_id = str(props.get("result_ig") or "").rstrip("/").split("/")[-1]
    id_matches = [row for row in records if saved_id and str(row.get("id")) == saved_id]
    stem = Path(video.get("name", "")).stem
    normalized_name = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", stem).casefold()).split()
    caption_candidates = []
    for row in records:
        caption = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", row.get("caption", "")).casefold())
        if normalized_name and all(re.search(rf"\b{re.escape(token)}\b", caption) for token in normalized_name):
            caption_candidates.append({key: row.get(key) for key in ("id", "permalink", "timestamp")})
    status = "published_id_match" if id_matches else (
        "caption_candidate_review_required" if caption_candidates else "no_current_post_match"
    )
    return {
        "file_id": file_id,
        "name": video.get("name"),
        "drive_parent_verified": True,
        "claim": props.get("claimed_route_slot"),
        "claimed_at": props.get("claimed_at"),
        "film_used": props.get("film_used") == "1",
        "drive_result_ig_present": bool(saved_id),
        "instagram_history_complete": True,
        "historical_deletions_verifiable": False,
        "instagram_posts_checked": len(records),
        "result": status,
        "id_matches": [{key: row.get(key) for key in ("id", "permalink", "timestamp")} for row in id_matches],
        "caption_candidates": caption_candidates,
        "publishing_performed": False,
    }


def audit_film_publications(meta_auth=None, drive=None):
    """Reconcile the current Film inventory and selected platform results read-only."""
    auth = meta_auth if meta_auth is not None else json.loads(os.environ.get("META_AUTH_JSON") or "{}")
    pages = verified_pages(auth)
    by_id = {str(row.get("page_id")): row for row in pages.values()}
    fb1 = by_id.get("1239298989276639")
    fb2 = by_id.get("854990964375370")
    if not fb1 or not fb2 or not fb1.get("instagram_id"):
        raise AuditError("film_platform_identity_missing")
    if not fb1.get("page_token") or not fb2.get("page_token"):
        raise AuditError("film_page_token_missing")
    if drive is None:
        drive, _ = google_client("DRIVE_TOKEN_JSON", "drive")

    folder_id = ROUTES["film"].folder_id
    folder = drive.files().get(fileId=folder_id, fields="id,appProperties").execute()
    inventory, page_token = [], None
    while True:
        page = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,mimeType,parents,size,md5Checksum,videoMediaMetadata,appProperties)",
            pageSize=1000, **({"pageToken": page_token} if page_token else {}),
        ).execute()
        inventory.extend(page.get("files", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    selected = {}
    for expected_name, file_id in FILM_AUDIT_FILES.items():
        item = next((row for row in inventory if row.get("id") == file_id), None)
        if not item or item.get("name") != expected_name or folder_id not in (item.get("parents") or []):
            raise AuditError("film_allowlisted_file_identity_mismatch", file_id=file_id)
        selected[file_id] = item

    # Audit the complete canonical Yoksul episode sequence, not only parts that
    # previously needed hand-written recovery rules. Non-canonical duplicates
    # such as "Part_5 (1).mp4" are deliberately excluded.
    canonical_parts = {}
    for item in inventory:
        match = re.fullmatch(r"Yoksul_1986_Part_(\d+)\.mp4", item.get("name", ""), re.I)
        if not match:
            continue
        part_number = int(match.group(1))
        if (item.get("mimeType") != "video/mp4"
                or folder_id not in (item.get("parents") or [])):
            raise AuditError("film_yoksul_part_identity_mismatch", file_id=item.get("id"))
        if part_number in canonical_parts:
            raise AuditError("film_yoksul_duplicate_part_number", part=part_number)
        canonical_parts[part_number] = item
    folder_props = folder.get("appProperties") or {}
    if not canonical_parts or str(folder_props.get("film_active_key", "")).casefold() != "yoksul_1986":
        raise AuditError("film_yoksul_inventory_missing_or_inactive")
    for file_id, item in selected.items():
        if canonical_parts.get(int(Path(item["name"]).stem.rsplit("_", 1)[1])) != item:
            raise AuditError("film_allowlist_not_in_canonical_inventory", file_id=file_id)
    selected = {
        item["id"]: item
        for _part_number, item in sorted(canonical_parts.items())
    }

    ig_token = fb1["page_token"]
    fb1_identity = graph_get("1239298989276639", fb1["page_token"], fields="id")
    fb2_identity = graph_get("854990964375370", fb2["page_token"], fields="id")
    ig_identity = graph_get(
        "1239298989276639", ig_token, fields="id,instagram_business_account{id}",
    )
    if (str(fb1_identity.get("id")) != "1239298989276639"
            or str(fb2_identity.get("id")) != "854990964375370"
            or str(ig_identity.get("id")) != "1239298989276639" or str(
        (ig_identity.get("instagram_business_account") or {}).get("id")
    ) != str(fb1["instagram_id"])):
        raise AuditError("film_instagram_identity_mismatch")
    ig_rows = graph_list(f"{fb1['instagram_id']}/media", ig_token, "id,caption,permalink,timestamp")

    facebook_history = {}
    for page_name, page in (("Facebook 1", fb1), ("Facebook 2", fb2)):
        try:
            facebook_history[page_name] = {
                "status": "complete",
                "rows": graph_list(
                    f"{page['page_id']}/videos", page["page_token"],
                    "id,description,permalink_url,created_time,from",
                ),
            }
        except AuditError as exc:
            facebook_history[page_name] = {
                "status": "incomplete", "rows": [],
                "http_status": exc.details.get("http_status"),
                "code": exc.details.get("code"), "subcode": exc.details.get("subcode"),
                "reason": exc.details.get("audit_error"),
            }

    def media_id(value):
        return str(value or "").rstrip("/").split("/")[-1]

    def ig_matches(item):
        props = item.get("appProperties") or {}
        saved_id = media_id(props.get("result_ig"))
        by_saved_id = [row for row in ig_rows if saved_id and str(row.get("id")) == saved_id]
        stem = Path(item.get("name", "")).stem
        tokens = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", stem).casefold()).split()
        candidates = []
        for row in ig_rows:
            caption = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", row.get("caption", "")).casefold())
            if tokens and all(re.search(rf"\b{re.escape(token)}\b", caption) for token in tokens):
                candidates.append({key: row.get(key) for key in ("id", "permalink", "timestamp")})
        return saved_id, by_saved_id, candidates

    fb_posts = []
    for file_id, item in selected.items():
        props = item.get("appProperties") or {}
        saved = (media_id(props.get("result_fb_film_1")), media_id(props.get("result_fb_film_2")))
        expected = FILM_KNOWN_FB_IDS.get(file_id, (None, None))
        pages_for_file = []
        for page_name, page in (("Facebook 1", fb1), ("Facebook 2", fb2)):
            expected_id = expected[0 if page_name == "Facebook 1" else 1]
            saved_id = saved[0 if page_name == "Facebook 1" else 1]
            post_id = saved_id or expected_id
            verification = {"page": page_name, "post_id": post_id, "status": "no_recorded_id"}
            if post_id:
                try:
                    row = graph_get(
                        post_id, page["page_token"],
                        fields="id,permalink_url,created_time,from",
                    )
                    author = row.get("from") or {}
                    verification.update({
                        "status": "verified" if str(author.get("id")) == str(page["page_id"]) else "author_mismatch",
                        "post_id": row.get("id"), "permalink": row.get("permalink_url"),
                        "created_time": row.get("created_time"),
                        "author_page_id": author.get("id"),
                    })
                except AuditError as exc:
                    verification.update({"status": "api_rejected", "http_status": exc.details.get("http_status"),
                                         "code": exc.details.get("code"), "subcode": exc.details.get("subcode")})
            name_tokens = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", Path(item.get("name", "")).stem).casefold()).split()
            history = facebook_history[page_name]
            candidates = []
            for row in history["rows"]:
                description = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", row.get("description", "")).casefold())
                author = row.get("from") or {}
                if (name_tokens and all(re.search(rf"\b{re.escape(token)}\b", description) for token in name_tokens)
                        and str(author.get("id")) == str(page["page_id"])):
                    candidates.append({key: row.get(key) for key in ("id", "permalink_url", "created_time")})
            verification["history_status"] = history["status"]
            verification["caption_candidates"] = candidates
            if history["status"] != "complete":
                verification["history_error"] = {key: history.get(key) for key in ("reason", "http_status", "code", "subcode")}
            pages_for_file.append(verification)
        saved_ig, ig_id_matches, ig_caption_candidates = ig_matches(item)
        props = item.get("appProperties") or {}
        state = {key: props.get(key) for key in FILM_STATE_KEYS if props.get(key) is not None}
        fb_posts.append({
            "part": int(Path(item["name"]).stem.rsplit("_", 1)[1]),
            "file_id": file_id, "name": item.get("name"), "size": item.get("size"),
            "md5Checksum": item.get("md5Checksum"),
            "durationMillis": (item.get("videoMediaMetadata") or {}).get("durationMillis"),
            "state": state, "facebook": pages_for_file,
            "instagram": {
                "saved_result_id_present": bool(saved_ig),
                "id_matches": [{key: row.get(key) for key in ("id", "permalink", "timestamp")} for row in ig_id_matches],
                "caption_candidates": ig_caption_candidates,
                "history_checked": len(ig_rows),
            },
            "youtube_configured": bool(os.environ.get("TOKEN_FILM_YOUTUBE_JSON")),
        })

    def sort_key(item):
        name = item.get("name", "").casefold()
        return ([int(value) for value in re.findall(r"\d+", name)], name)

    inventory_rows = [
        {"id": row.get("id"), "name": row.get("name"), "size": row.get("size"),
         "durationMillis": (row.get("videoMediaMetadata") or {}).get("durationMillis"),
         "state": {key: (row.get("appProperties") or {}).get(key)
                   for key in FILM_STATE_KEYS if (row.get("appProperties") or {}).get(key) is not None}}
        for row in sorted(inventory, key=sort_key) if row.get("name", "").lower().endswith(".mp4")
    ]
    active_key = (folder.get("appProperties") or {}).get("film_active_key")
    active_part_rows = []
    for row in inventory_rows:
        match = re.match(r"^(?P<film>.+?)[ _.-]+part[ _.-]?(?P<part>\d+)(?:\s+\(\d+\))?$", Path(row["name"]).stem, re.I)
        if match and re.sub(r"[^\w]+", " ", match.group("film").casefold()).split() == str(active_key or "").casefold().split():
            active_part_rows.append({"part": int(match.group("part")), "id": row["id"],
                                     "name": row["name"], "used": row["state"].get("film_used") == "1" or row["state"].get("film_done") == "1",
                                     "claim": row["state"].get("claimed_route_slot")})
    unused_parts = sorted(row["part"] for row in active_part_rows if not row["used"])
    return {
        "film_folder_id": folder_id,
        "film_active_key": (folder.get("appProperties") or {}).get("film_active_key"),
        "active_film_parts": active_part_rows,
        "next_unused_part_number": unused_parts[0] if unused_parts else None,
        "film_mp4_inventory": inventory_rows,
        "selected_part_audits": fb_posts,
        "instagram_history_complete": True,
        "facebook_history_status": {name: value["status"] for name, value in facebook_history.items()},
        "historical_deletions_verifiable": False,
        "publishing_performed": False,
        "drive_mutations_performed": False,
    }


if __name__ == "__main__":
    diagnostic = {}
    try:
        if sys.argv[1:] == ["--film-claim"]:
            report = audit_film_claim()
        elif sys.argv[1:] == ["--film-publications"]:
            report = audit_film_publications()
        else:
            report = audit_meta(diagnostic=diagnostic)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report.get("result") == "caption_candidate_review_required":
            raise SystemExit(2)
        if "accounts" in report and (not report["required_permissions_complete"] or any(row["status"] != "passed" for row in report["accounts"])):
            raise SystemExit(1)
    except Exception as exc:
        error = safe_error(exc) if sys.argv[1:] == ["--film-claim"] else safe_meta_error(exc, diagnostic)
        print(json.dumps(error, ensure_ascii=False))
        raise SystemExit(1)
