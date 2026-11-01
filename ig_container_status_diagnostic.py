"""Read-only status check for known rejected IG resumable upload containers."""
import json
import os
import re
from pathlib import Path
import requests

PINNED = {
 "film_part16": ("1239298989276639", "17841477990224124", "17903621700599675"),
 "toonzone_part3": ("1298191963387372", "17841477404255851", "17909360826580142"),
 "film_avanak_part10_oct30": ("1239298989276639", "17841477990224124", "17904577569599675"),
 "toonzone_s01e07_part3_oct30": ("1298191963387372", "17841477404255851", "17910279864580142"),
}
# Exact result-ledger containers from run 41301342606. Read-only diagnosis;
# the name is verified with live Page GET before its discovered credentials
# are used. No source/container is selected heuristically.
NAMED_PINNED = {
 "tarladaki_192_nov01": ("Tarladaki Fasulye", "18111440750133751"),
 "penguen_193_nov01": ("Beyinsiz Penguen", "18120540917054769"),
}
STATES = frozenset(("IN_PROGRESS", "FINISHED", "PUBLISHED", "ERROR", "EXPIRED"))

def inspect(pages, key, get=None, *, binding=None):
    get = get or requests.get
    pid, ig, cid = binding if binding is not None else PINNED[key]
    result = {"route": key, "container_id": cid, "posts_sent": 0}
    page = next((p for p in pages if str(p.get("page_id")) == pid), None)
    if not page or str(page.get("instagram_id")) != ig or not page.get("page_token"):
        return {**result, "status": "BLOCKED", "reason": "page_ig_identity_mismatch"}
    try:
        res = get("https://graph.facebook.com/v24.0/" + cid,
                  headers={"Authorization": "Bearer " + page["page_token"]},
                  params={"fields": "status_code,status"}, timeout=20,
                  allow_redirects=False)
        data = res.json()
        if not isinstance(data, dict):
            return {**result, "status": "UNVERIFIED", "reason": "invalid_meta_body"}
        if res.status_code != 200 or data.get("error"):
            err = data.get("error")
            code = err.get("code") if isinstance(err, dict) else None
            return {**result, "status": "UNVERIFIED", "reason": "graph_get_rejected",
                    "http_status": res.status_code,
                    "graph_code": code if isinstance(code, int) else None}
        if str(data.get("id", cid)) != cid:
            return {**result, "status": "BLOCKED", "reason": "container_id_mismatch"}
        state = data.get("status_code")
        if state not in STATES:
            return {**result, "status": "UNVERIFIED", "reason": "unknown_meta_status"}
        detail = str(data.get("status") or "").lower()
        # Only fixed categories / documented numeric error codes; never emit
        # raw provider status text, tokens or signed source URLs.
        categories = [key for key, words in {
            "duration": ("duration", "too long", "too short"),
            "codec": ("codec", "h264", "h.264", "aac"),
            "dimensions": ("dimension", "aspect ratio", "resolution"),
            "copyright_or_policy": ("copyright", "policy", "rights"),
            "processing": ("processing", "process failed"),
        }.items() if any(word in detail for word in words)]
        codes = sorted(set(re.findall(r"\b2207\d{3}\b", detail)))
        return {**result, "status": state,
                "status_detail_present": bool(data.get("status")),
                "detail_categories": categories, "detail_codes": codes,
                "instruction": "do_not_reupload_or_publish"}
    except (requests.RequestException, ValueError, TypeError):
        return {**result, "status": "UNVERIFIED", "reason": "read_failure"}

def inspect_named(pages, key, get=None):
    """Read an exact known container only after a live Page/IG identity GET."""
    from meta_page_token_health import check_page
    get = get or requests.get
    name, cid = NAMED_PINNED[key]
    result = {"route": key, "container_id": cid, "posts_sent": 0}
    matches = [page for page in pages if page.get("page_name") == name]
    if len(matches) != 1:
        return {**result, "status": "BLOCKED", "reason": "page_ig_identity_mismatch"}
    page = matches[0]
    identity = check_page(page, get=get)
    if identity.get("status") != "identity_verified" or not identity.get("instagram_identity_checked"):
        return {**result, "status": "BLOCKED", "reason": "page_ig_identity_mismatch"}
    return inspect(pages, key, get=get, binding=(str(page["page_id"]), str(page["instagram_id"]), cid))


def main():
    from meta_auth_loader import load_meta_auth
    try:
        auth = load_meta_auth()
        pages = auth.get("pages") if isinstance(auth, dict) else None
        if not isinstance(pages, list):
            raise ValueError("Meta page list missing")
        result = {"checks": ([inspect(pages, key) for key in PINNED]
                             + [inspect_named(pages, key) for key in NAMED_PINNED]),
                  "post_requests": 0, "published": False}
    except Exception:
        result = {"checks": [], "post_requests": 0, "published": False,
                  "reason": "credential_or_read_failure"}
    message = json.dumps(result, ensure_ascii=False, indent=2)
    print(message)
    Path("ig-container-readonly-result.json").write_text(message, encoding="utf-8")
    return 0 if result["checks"] and all(row["status"] in STATES for row in result["checks"]) else 1

if __name__ == "__main__":
    raise SystemExit(main())
