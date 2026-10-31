"""Read-only, redacted early Meta auth gate for scheduled publisher.

Checks current user token discovery before installing video extras. Does not
refresh credentials, mutate secrets, POST to Meta, or change publication state.
"""
import json
import re

from meta_auth_loader import load_meta_auth

SAFE_GRAPH_ERROR = re.compile(
    r"^Meta hesap erişimi reddedildi \(HTTP (\d{3}), kod (\d{1,6}|unknown), "
    r"alt_kod (\d{1,6}|unknown)\)$"
)


def check_auth(loader=load_meta_auth):
    try:
        auth = loader()
        pages = auth.get("pages") if isinstance(auth, dict) else None
        if not isinstance(pages, list) or not pages:
            return {"status": "blocked", "reason": "no_approved_meta_pages", "publishing_tested": False}
        if any(not isinstance(page, dict) or
               not str(page.get("page_id") or "").isdigit() or
               not isinstance(page.get("page_token"), str) or
               not page["page_token"].strip() for page in pages):
            return {"status": "blocked", "reason": "invalid_page_config", "publishing_tested": False}
        return {"status": "identity_discovered", "page_count": len(pages), "publishing_tested": False}
    except RuntimeError as exc:
        match = SAFE_GRAPH_ERROR.fullmatch(str(exc))
        if match:
            code, subcode = match.group(2), match.group(3)
            return {"status": "blocked", "reason": "meta_auth_rejected",
                    "http_status": int(match.group(1)),
                    "graph_code": int(code) if code.isdigit() else None,
                    "graph_subcode": int(subcode) if subcode.isdigit() else None,
                    "publishing_tested": False}
        return {"status": "blocked", "reason": "auth_discovery_unavailable", "publishing_tested": False}
    except Exception:
        return {"status": "blocked", "reason": "invalid_auth_configuration", "publishing_tested": False}


def main():
    report = check_auth()
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if report["status"] == "identity_discovered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
