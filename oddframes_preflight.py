"""Owner's seventh account preflight, with no inferred identities or publish writes.

This does not add OddFrames to publication while folder, Meta Page, IG identity
and explicit content rights remain unverified. Exposes precise missing gates.
"""
import json
import os
import re


def readiness(*, environ=None, pages=None):
    env = os.environ if environ is None else environ
    missing = []
    for key in ("ODDFRAMES_DRIVE_FOLDER_ID", "ODDFRAMES_PAGE_ID",
                "ODDFRAMES_INSTAGRAM_ID"):
        if not env.get(key, "").strip():
            missing.append(key)
    if env.get("ENABLE_ODDFRAMES_ROUTES", "").lower() != "true":
        missing.append("ENABLE_ODDFRAMES_ROUTES")
    if env.get("ODDFRAMES_RIGHTS_APPROVED", "").lower() != "true":
        missing.append("ODDFRAMES_RIGHTS_APPROVED")
    if missing:
        return {"route": "oddframes", "status": "blocked_configuration_or_rights",
                "missing": missing, "authorized_to_publish": False}
    folder = env["ODDFRAMES_DRIVE_FOLDER_ID"].strip()
    page_id, ig_id = (env["ODDFRAMES_PAGE_ID"].strip(),
                      env["ODDFRAMES_INSTAGRAM_ID"].strip())
    if (not re.fullmatch(r"[a-zA-Z0-9_-]{20,128}", folder)
            or not re.fullmatch(r"[0-9]{8,30}", page_id)
            or not re.fullmatch(r"[0-9]{8,30}", ig_id)):
        return {"route": "oddframes", "status": "invalid_identity_settings",
                "authorized_to_publish": False}
    if pages is None:
        return {"route": "oddframes", "status": "meta_identity_unverified",
                "authorized_to_publish": False}
    if not isinstance(pages, (list, tuple)):
        return {"route": "oddframes", "status": "meta_identity_unverified",
                "authorized_to_publish": False}
    found = [p for p in pages if isinstance(p, dict)
             and p.get("page_name") == "OddFrames"]
    if (len(found) != 1
            or str(found[0].get("page_id") or "") != page_id
            or str(found[0].get("instagram_id") or "") != ig_id
            or not found[0].get("page_token")):
        return {"route": "oddframes", "status": "meta_identity_mismatch",
                "authorized_to_publish": False}
    return {"route": "oddframes", "status": "preflight_ready_no_publication",
            "authorized_to_publish": False,
            "requires_publisher_integration": True}


def main():
    from meta_auth_loader import load_meta_auth
    # Evaluate missing gates before any authenticated Meta call.
    initial = readiness()
    if initial["status"] != "meta_identity_unverified" and initial["status"] != "preflight_ready_no_publication":
        if initial["status"] in {"blocked_configuration_or_rights", "invalid_identity_settings"}:
            print(json.dumps(initial, ensure_ascii=False), flush=True)
            return 0
    try:
        pages = load_meta_auth().get("pages", [])
    except Exception:
        result = {"route": "oddframes", "status": "meta_identity_read_failed",
                  "authorized_to_publish": False}
    else:
        result = readiness(pages=pages)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
