"""Read-only, redacted Meta saved-page-token diagnostic; no publishing."""
import json
import os
import sys
from pathlib import Path
import unicodedata
import requests
from api_capacity_guard import capacity_from_headers

EXPECTED = {"Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen",
            "Daily Laugh Lab", "Film Mağarası", "Filmmagrasi", "ToonZone"}
SCOPE_TO_PAGE = {
    "tarladaki": "Tarladaki Fasulye",
    "penguen": "Beyinsiz Penguen",
    "gonle": "Gönle Düşen",
    "daily_laugh": "Daily Laugh Lab",
    "film": "Film Mağarası",
    "film_second": "Filmmagrasi",
    "toonzone": "ToonZone",
}

# Immutable production IDs outweigh old display labels, which may be misspelled.
KNOWN_PAGE_IDS = {
    "1239298989276639": "Film Mağarası",
    "854990964375370": "Filmmagrasi",
    "1298191963387372": "ToonZone",
}


def _normalized_name(value):
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


CANONICAL_NAMES = {_normalized_name(name): name for name in EXPECTED}
CANONICAL_NAMES.update({
    # Actual historical page labels; exact known production page IDs take priority.
    "filmmagrası": "Film Mağarası",
    "filmmagrası1": "Filmmagrasi",
    "filmmagrsi": "Film Mağarası",
    "filmmagrsi1": "Filmmagrasi",
    "filmmagrasi1": "Filmmagrasi",
})


def canonical_page_name(page):
    page_id = str(page.get("page_id") or "").strip()
    if page_id in KNOWN_PAGE_IDS:
        return KNOWN_PAGE_IDS[page_id]
    return CANONICAL_NAMES.get(_normalized_name(page.get("page_name")))



def check_page(page, get=requests.get):
    name = canonical_page_name(page)
    pid = str(page.get("page_id") or "").strip()
    token = page.get("page_token")
    instagram = str(page.get("instagram_id") or "").strip()
    out = {"page_name": name, "status": "blocked", "publishing_tested": False}
    if name not in EXPECTED or not pid.isdecimal() or not isinstance(token, str) or not token or token != token.strip():
        return {**out, "reason": "invalid_configuration"}
    if instagram and not instagram.isdecimal():
        return {**out, "reason": "invalid_instagram_id"}
    try:
        response = get(
            f"https://graph.facebook.com/v24.0/{pid}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "id,name,instagram_business_account{id}"},
            timeout=20,
        )
        body = response.json()
        if not isinstance(body, dict):
            return {**out, "reason": "invalid_api_response"}
        if not response.ok or body.get("error"):
            err = body.get("error") if isinstance(body.get("error"), dict) else {}
            code, sub = err.get("code"), err.get("error_subcode")
            reason = ("token_expired" if (code, sub) == (190, 463) else
                      "invalid_or_revoked_token" if code == 190 else
                      "access_denied" if response.status_code in (401, 403) else "api_rejected")
            return {**out, "reason": reason, "http_status": response.status_code,
                    "code": code if isinstance(code, int) else None,
                    "subcode": sub if isinstance(sub, int) else None}
        if str(body.get("id")) != pid:
            return {**out, "reason": "page_id_mismatch"}
        if name not in {"Film Mağarası", "Filmmagrasi", "ToonZone"} and str(body.get("name") or "").casefold() != name.casefold():
            return {**out, "reason": "page_name_mismatch"}
        live_ig = str((body.get("instagram_business_account") or {}).get("id") or "")
        if instagram and live_ig != instagram:
            return {**out, "reason": "instagram_id_mismatch"}
        capacity = capacity_from_headers(getattr(response, "headers", {}))
        # 95% observed usage fails the existing preflight CLOSED. 80% is a
        # redacted warning; missing headers are unknown, never read as zero.
        return {**out, "status": "capacity_hold" if capacity["status"] == "hold" else "identity_verified",
                "reason": "observed_api_capacity_95_percent" if capacity["status"] == "hold" else None,
                "api_capacity": capacity, "instagram_identity_checked": bool(instagram)}
    except requests.RequestException as exc:
        return {**out, "reason": "network_error", "exception_type": type(exc).__name__}
    except Exception as exc:
        # Exception messages can contain credentials: never print them.
        return {**out, "reason": "client_error", "exception_type": type(exc).__name__}


def audit(auth, get=requests.get):
    if not isinstance(auth, dict) or not isinstance(auth.get("pages"), list):
        return {"status": "blocked", "reason": "invalid_discovered_page_configuration", "accounts": []}
    scope = os.getenv("PUBLISH_ACCOUNT_SCOPE", "").strip()
    if scope and scope not in SCOPE_TO_PAGE:
        return {"status": "blocked", "reason": "invalid_account_scope", "accounts": []}
    expected = {SCOPE_TO_PAGE[scope]} if scope else EXPECTED
    rows, names, ids = [], set(), set()
    # Reject duplicate/conflicting page identities even across scopes, without
    # requiring sibling providers to answer an API GET for this account.
    all_pages = [p for p in auth["pages"] if isinstance(p, dict)]
    id_names = {}
    for page in all_pages:
        pid = str(page.get("page_id") or "").strip()
        if pid and canonical_page_name(page) in EXPECTED:
            id_names.setdefault(pid, set()).add(canonical_page_name(page))
    for page in auth["pages"]:
        if not isinstance(page, dict):
            return {"status": "blocked", "reason": "invalid_entry", "accounts": rows}
        name = canonical_page_name(page)
        if name not in expected:
            continue
        pid = str(page.get("page_id") or "")
        if len(id_names.get(pid, set())) > 1:
            rows.append({"page_name": name, "status": "blocked",
                         "reason": "shared_page_id_conflict", "publishing_tested": False})
            names.add(name)
            continue
        if name in names or (pid and pid in ids):
            rows.append({"page_name": name, "status": "blocked", "reason": "duplicate_configuration",
                         "publishing_tested": False})
            continue
        names.add(name)
        if pid:
            ids.add(pid)
        rows.append(check_page(page, get=get))
    missing = sorted(expected - names)
    passed = not missing and rows and all(row["status"] == "identity_verified" for row in rows)
    return {"status": "identity_verified" if passed else "attention_needed",
            "accounts": rows, "missing_page_names": missing,
            "publishing_tested": False, "user_token_tested": False,
            "note": "Identity GET does not prove publishing permissions."}


def verified_pages(result):
    """Only fully verified, unambiguous page identities may publish.

    A broken Film identity must not block a separately verified ToonZone.
    A duplicate/conflicting identity fails closed for that page.
    """
    if not isinstance(result, dict) or not isinstance(result.get("accounts"), list):
        return []
    blocked = {r.get("page_name") for r in result["accounts"]
               if isinstance(r, dict) and r.get("status") != "identity_verified"}
    return sorted({r.get("page_name") for r in result["accounts"]
                   if isinstance(r, dict) and r.get("status") == "identity_verified"
                   and r.get("page_name") in EXPECTED} - blocked)


def archive_partial_preflight(result):
    """Persist a redacted per-account allowlist before any Meta write."""
    verified = verified_pages(result)
    if not verified:
        return False
    target = Path(os.getenv("META_PREFLIGHT_REPORT_PATH",
                            "link-runtime/meta-preflight.json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "schema": 1,
        "status": "identity_verified" if result.get("status") == "identity_verified"
                  else "partial_identity_verified",
        "verified_pages": verified,
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(target)
    return True


def main():
    try:
        from meta_auth_loader import load_meta_auth
        auth = load_meta_auth()
    except Exception as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc) if type(exc) is RuntimeError
                          else "invalid_meta_configuration", "publishing_tested": False}))
        return 1
    result = audit(auth)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if os.getenv("META_PREFLIGHT_PARTIAL_OK", "false").lower() == "true":
        # Keep a single invalid user token or zero healthy Pages fail-closed.
        # Do NOT infer that a verified identity has publishing rights.
        return 0 if archive_partial_preflight(result) else 1
    return 0 if result["status"] == "identity_verified" else 1


if __name__ == "__main__":
    sys.exit(main())
