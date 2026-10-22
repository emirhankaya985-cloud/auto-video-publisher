"""Read-only, redacted Meta saved-page-token diagnostic; no publishing."""
import json
import os
import sys
import unicodedata
import requests

EXPECTED = {"Tarladaki Fasulye", "Beyinsiz Penguen", "Gönle Düşen",
            "Daily Laugh Lab", "Film Mağarası", "Filmmagrasi", "ToonZone"}

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
        return {**out, "status": "identity_verified", "reason": None,
                "instagram_identity_checked": bool(instagram)}
    except requests.RequestException as exc:
        return {**out, "reason": "network_error", "exception_type": type(exc).__name__}
    except Exception as exc:
        # Exception messages can contain credentials: never print them.
        return {**out, "reason": "client_error", "exception_type": type(exc).__name__}


def audit(auth, get=requests.get):
    if not isinstance(auth, dict) or not isinstance(auth.get("pages"), list):
        return {"status": "blocked", "reason": "missing_or_invalid_META_AUTH_JSON", "accounts": []}
    rows, names, ids = [], set(), set()
    for page in auth["pages"]:
        if not isinstance(page, dict):
            return {"status": "blocked", "reason": "invalid_entry", "accounts": rows}
        name = canonical_page_name(page)
        if name not in EXPECTED:
            continue
        pid = str(page.get("page_id") or "")
        if name in names or (pid and pid in ids):
            rows.append({"page_name": name, "status": "blocked", "reason": "duplicate_configuration",
                         "publishing_tested": False})
            continue
        names.add(name)
        if pid:
            ids.add(pid)
        rows.append(check_page(page, get=get))
    missing = sorted(EXPECTED - names)
    passed = not missing and rows and all(row["status"] == "identity_verified" for row in rows)
    return {"status": "identity_verified" if passed else "attention_needed",
            "accounts": rows, "missing_page_names": missing,
            "publishing_tested": False, "user_token_tested": False,
            "note": "Identity GET does not prove publishing permissions."}


def main():
    try:
        auth = json.loads(os.getenv("META_AUTH_JSON") or "null")
    except (ValueError, TypeError):
        auth = None
    result = audit(auth)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "identity_verified" else 1


if __name__ == "__main__":
    sys.exit(main())
