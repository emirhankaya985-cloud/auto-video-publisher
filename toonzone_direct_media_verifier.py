"""Read-only, exact-ID Instagram reconciliation for ToonZone S01.

No Meta POST, content upload, state repair, or permission/token mutation.
A bounded account-media listing can omit older posts. This probe reads only
an archived, source-bound IG media ID and checks its live owner/caption/date.
Absence or an API error never authorizes a duplicate upload.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests

PAGE_ID = "1298191963387372"
IG_USER_ID = "17841477404255851"
ROOT = Path("toonzone-direct-id-audit")
API = "https://graph.facebook.com/v24.0/"
SOURCE = re.compile(r"^S01E(0[1-9]|1[0-2])_.+_Part([1-4])\.mp4$")
HASH = re.compile(r"^[a-f0-9]{64}$")


def caption_digest(text):
    if not isinstance(text, str):
        return None
    # Matches the existing publisher's normalized caption_key().
    text = re.sub(r"https://www\.etsy\.com/\S+", "", text)
    text = re.sub(r"\bEtsy:\s*", "", text, flags=re.I)
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def candidates(state):
    """Exactly one archive binding per season/episode/part; no inference."""
    entries = state.get("entries") if isinstance(state, dict) else None
    if not isinstance(entries, dict):
        raise ValueError("publisher_state_unavailable")
    indexes = {}
    for entry in entries.values():
        if not isinstance(entry, dict) or entry.get("route") != "toonzone" or entry.get("platform") != "instagram":
            continue
        name = entry.get("file") or ""
        match = SOURCE.fullmatch(str(name))
        if not match:
            continue
        key = (int(match.group(1)), int(match.group(2)))
        if key in indexes:
            raise ValueError("duplicate_archived_source_slot")
        indexes[key] = entry
    rows = []
    for episode in range(1, 13):
        for part in range(1, 5):
            key = (episode, part)
            entry = indexes.get(key) or {}
            media_id = str(entry.get("post_id") or "")
            digest = str(entry.get("caption_hash") or "")
            id_valid = media_id.isdecimal() and len(media_id) >= 10
            digest_valid = bool(HASH.fullmatch(digest))
            done = entry.get("status") == "done"
            ok = (done and id_valid and digest_valid
                  and entry.get("route") == "toonzone" and entry.get("platform") == "instagram")
            archive_issue = (
                None if ok else
                "archive_source_slot_missing" if not entry else
                "archive_status_not_done" if not done else
                "archive_post_id_invalid" if not id_valid else
                "legacy_file_id_provenance_marker" if digest.startswith("verified-file-id:") else
                "archive_caption_digest_not_sha256" if not digest_valid else
                "archive_route_mismatch"
            )
            rows.append({
                "slot": f"S01E{episode:02d} Part{part}",
                "file": entry.get("file") if entry else None,
                "post_id": media_id if id_valid else None,
                "caption_hash": digest if digest_valid else None,
                "eligible": ok,
                "archive_issue": archive_issue,
            })
    post_ids = [r["post_id"] for r in rows if r["post_id"]]
    if len(post_ids) != len(set(post_ids)):
        raise ValueError("same_media_id_bound_to_multiple_sources")
    return rows


def read_json(get, url, token, fields):
    try:
        response = get(
            url, headers={"Authorization": "Bearer " + token},
            params={"fields": fields}, timeout=15, allow_redirects=False)
        body = response.json()
        http = response.status_code
        if http != 200 or not isinstance(body, dict) or body.get("error"):
            err = body.get("error") if isinstance(body, dict) else None
            code = err.get("code") if isinstance(err, dict) else None
            subcode = err.get("error_subcode") if isinstance(err, dict) else None
            return None, {"reason": "provider_get_rejected", "http_status": http,
                          "graph_code": code if type(code) is int else None,
                          "graph_subcode": subcode if type(subcode) is int else None}
        return body, None
    except (requests.RequestException, ValueError, TypeError):
        return None, {"reason": "provider_read_unavailable"}


def identity_username(page, *, get=requests.get):
    """Pin the Page/IG association and read owner username before media GETs."""
    if (not isinstance(page, dict) or str(page.get("page_id")) != PAGE_ID
            or str(page.get("instagram_id")) != IG_USER_ID
            or not isinstance(page.get("page_token"), str) or not page["page_token"]):
        return None, "page_identity_not_pinned"
    body, err = read_json(get, API + IG_USER_ID, page["page_token"], "id,username")
    if err:
        return None, err["reason"]
    username = body.get("username") if isinstance(body, dict) else None
    if str(body.get("id")) != IG_USER_ID or not isinstance(username, str) or not username.strip():
        return None, "ig_owner_not_verified"
    return username.strip(), None


def inspect_post(candidate, *, owner_username, token, get=requests.get):
    """Source-linked metadata proof, never a claim about uploaded video bytes."""
    base = {"slot": candidate["slot"], "file": candidate["file"], "post_id": candidate["post_id"]}
    if not candidate["eligible"]:
        return {**base, "status": "held",
                "reason": candidate.get("archive_issue") or "archive_receipt_unverified"}
    media_id = candidate["post_id"]
    body, error = read_json(
        get, API + media_id, token,
        "id,caption,username,timestamp,media_type")
    if error:
        return {**base, "status": "held", **error}
    if str(body.get("id")) != media_id:
        reason = "provider_id_mismatch"
    elif str(body.get("username") or "").casefold() != owner_username.casefold():
        reason = "media_owner_mismatch"
    elif body.get("media_type") != "VIDEO":
        reason = "media_not_video"
    elif caption_digest(body.get("caption")) != candidate["caption_hash"]:
        reason = "caption_hash_mismatch"
    else:
        try:
            stamp = datetime.fromisoformat(str(body["timestamp"]).replace("Z", "+00:00"))
            reason = None if stamp.tzinfo else "timestamp_unverified"
        except (KeyError, ValueError, TypeError):
            reason = "timestamp_unverified"
    if reason:
        return {**base, "status": "held", "reason": reason}
    return {**base, "status": "verified_live_exact_id_owner_caption_time",
            "verified_timestamp": stamp.isoformat()}


def episode_4_to_12_readonly_rollup(rows):
    """Only verified live, exact owner/caption/ID matches count as completed."""
    if not isinstance(rows, list):
        raise ValueError("toonzone_verified_rows_required")
    result = {}
    for episode in range(4, 13):
        prefix = f"S01E{episode:02d} Part"
        pieces = [item for item in rows if isinstance(item, dict)
                  and str(item.get("slot", "")).startswith(prefix)]
        verified = [row for row in pieces if
                    row.get("status") == "verified_live_exact_id_owner_caption_time"]
        result[f"S01E{episode:02d}"] = {
            "expected_parts": 4,
            "live_verified_parts": len(verified),
            "held_or_unverified_parts": 4 - len(verified),
            "provider_post_ids": [row["post_id"] for row in verified],
            "status": "all_four_live_verified" if len(verified) == 4
                      else "held_no_reupload_without_exact_proof",
        }
    return result


def audit(state, page, *, get=requests.get, secondary_token=None):
    rows = candidates(state)
    username, identity_error = identity_username(page, get=get)
    if identity_error:
        return {"schema": 1, "mode": "strict_read_only", "status": "identity_blocked",
                "reason": identity_error, "total": len(rows), "rows": [],
                "media_posts_created": 0, "state_mutations": 0}
    # Both tokens are read-only, discovered from the same verified User/Page
    # association; an alternate token cannot substitute for source proof.
    alt_ok = (isinstance(secondary_token, str) and bool(secondary_token)
              and not any(ch.isspace() for ch in secondary_token)
              and secondary_token != page["page_token"])
    output = []
    for item in rows:
        primary = inspect_post(
            item, owner_username=username, token=page["page_token"], get=get)
        current = primary
        # Meta's object-not-readable (100/33) is ambiguous: either ID absent
        # or a token/permission context problem. Only this exact error
        # authorizes a single GET with the User token, never a POST.
        if (alt_ok and item["eligible"] and primary.get("status") == "held"
                and primary.get("reason") == "provider_get_rejected"
                and primary.get("http_status") == 400
                and primary.get("graph_code") == 100
                and primary.get("graph_subcode") == 33):
            second = inspect_post(
                item, owner_username=username, token=secondary_token, get=get)
            if second["status"].startswith("verified_live_exact"):
                current = {**second, "verified_via": "user_token_direct_get"}
            else:
                current = {
                    **primary, "secondary_attempted": True,
                    "secondary_status": "held",
                    "secondary_reason": second.get("reason", "unknown"),
                    "secondary_http_status": second.get("http_status"),
                    "secondary_graph_code": second.get("graph_code"),
                    "secondary_graph_subcode": second.get("graph_subcode"),
                }
        output.append(current)
        last = output[-1]
        secondary_limited = last.get("secondary_http_status") == 429 or last.get("secondary_graph_code") in {4, 17, 32, 613}
        if (last.get("http_status") == 429 or last.get("graph_code") in {4, 17, 32, 613}
                or secondary_limited):
            # Stop early: never hammer Meta once throttled.
            for leftover in rows[len(output):]:
                output.append({"slot": leftover["slot"], "file": leftover["file"],
                               "post_id": leftover["post_id"], "status": "held",
                               "reason": "rate_limited_stop"})
            break
    verified = sum(x["status"].startswith("verified_live_exact") for x in output)
    prior = [x for x in output if x["slot"].startswith(tuple(f"S01E{i:02d}" for i in (1, 2, 3)))]
    current = [x for x in output if x not in prior]
    verified_current = sum(x["status"].startswith("verified_live_exact") for x in current)
    return {"schema": 1, "mode": "strict_read_only",
            "status": "all_verified" if verified == 48 else "held_partial",
            "total": len(output), "verified": verified,
            "episodes_1_to_3_verified": sum(x["status"].startswith("verified_live_exact") for x in prior),
            "episodes_4_to_12_verified": verified_current,
            "episodes_4_to_12_missing_or_unverified": 36 - verified_current,
            "episodes_4_to_12": episode_4_to_12_readonly_rollup(output),
            "rows": output, "media_posts_created": 0, "state_mutations": 0,
            "owner_verified": True, "reenqueue_authorized": False,
            "secondary_token_query_enabled": bool(alt_ok),
            "secondary_queries": sum(bool(x.get("secondary_attempted") or x.get("verified_via")) for x in output)}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        if (os.getenv("GITHUB_REPOSITORY") != "emirhankaya985-cloud/auto-video-publisher"
                or os.getenv("GITHUB_REF") != "refs/heads/main"
                or os.getenv("PUBLISH_ACCOUNT_SCOPE") != "toonzone"):
            raise ValueError("trusted_readonly_scope_required")
        from meta_auth_loader import load_meta_auth
        from meta_page_token_health import check_page
        from public_link_runtime import restore
        pages = load_meta_auth()["pages"]
        selected = [p for p in pages if p.get("page_name") == "ToonZone"
                    and str(p.get("page_id")) == PAGE_ID and str(p.get("instagram_id")) == IG_USER_ID]
        if len(selected) != 1 or check_page(selected[0]).get("status") != "identity_verified":
            raise ValueError("page_preflight_unverified")
        report = audit(restore(), selected[0], secondary_token=os.getenv("META_ACCESS_TOKEN"))
    except Exception as exc:
        # No arbitrary provider exception strings or secrets in artifacts.
        report = {"schema": 1, "mode": "strict_read_only", "status": "blocked",
                  "reason": type(exc).__name__ if isinstance(exc, (ValueError, RuntimeError))
                  else "read_failure", "media_posts_created": 0, "state_mutations": 0}
    (ROOT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"},
                     ensure_ascii=False), flush=True)
    return 0 if report.get("status") in {"all_verified", "held_partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
