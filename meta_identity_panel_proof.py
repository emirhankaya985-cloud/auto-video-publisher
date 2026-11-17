"""Single-use account identity proof for the connected 985 dashboard.

Read-only Meta Graph GETs; never publish or print access tokens, page tokens,
Gmail identifiers, raw API payloads, or account credentials. Names alone and
known configured IDs do NOT constitute a verified provider identity.
"""
import json
import re
from datetime import datetime,timezone
from meta_page_token_health import check_page,canonical_page_name
from stats_reporter import META_TARGETS

INT=re.compile(r"^[0-9]{4,22}$")


def verify(auth, check=check_page, now=None):
    if not isinstance(auth,dict) or not isinstance(auth.get("pages"),list):
        return {"status":"blocked","reason":"invalid_saved_page_discovery","identities":[]}
    pages={}
    for raw in auth["pages"]:
        if not isinstance(raw,dict):continue
        canonical=canonical_page_name(raw)
        if canonical in pages:
            pages[canonical]=None  # duplicate name is inherently ambiguous
        elif canonical:
            pages[canonical]=raw
    stamped=(now or datetime.now(timezone.utc)).isoformat()
    rows=[]
    for owner,page_name,platform in META_TARGETS:
        raw=pages.get(page_name)
        if not raw:
            rows.append({"account":owner,"platform":platform,"page":page_name,
                         "status":"unverified","reason":"missing_or_ambiguous_page"})
            continue
        verified=check(raw)
        if verified.get("status")!="identity_verified":
            rows.append({"account":owner,"platform":platform,"page":page_name,
                         "status":"unverified","reason":str(verified.get("reason") or "api_not_verified")[:90]})
            continue
        page_id=str(raw.get("page_id") or "")
        ig_id=str(raw.get("instagram_id") or "")
        target=ig_id if platform=="Instagram" else page_id
        if not INT.fullmatch(page_id) or not INT.fullmatch(target):
            rows.append({"account":owner,"platform":platform,"page":page_name,
                         "status":"unverified","reason":"missing_graph_account_identity"})
            continue
        if platform=="Instagram" and verified.get("instagram_identity_checked") is not True:
            rows.append({"account":owner,"platform":platform,"page":page_name,
                         "status":"unverified","reason":"instagram_identity_not_checked"})
            continue
        rows.append({"account":owner,"platform":platform,"page":page_name,
                     "status":"identity_verified","platform_account_id":target,
                     "source_page_id":page_id,"verified_at":stamped,
                     "evidence":"Live Meta Graph API identity GET, verified page/IG pair"})
    good=[row for row in rows if row["status"]=="identity_verified"]
    ids=[(r["platform"],r["platform_account_id"]) for r in good]
    if len(set(ids))!=len(ids):
        # Never merge two labels into a single provider ID.
        return {"status":"blocked","reason":"duplicate_provider_identity","identities":[]}
    return {"status":"verified_partial" if len(good)<len(rows) else "verified_all",
            "verified":len(good),"expected":len(rows),"identities":rows,
            "publishing_performed":False,"telegram_sent":False,
            "crm_mutated":False}


def main():
    try:
        from meta_auth_loader import load_meta_auth
        data=verify(load_meta_auth())
    except Exception:
        data={"status":"blocked","reason":"credential_or_provider_unavailable",
              "identities":[],"publishing_performed":False}
    # Output is a single JSON object of public provider account IDs, proven
    # names and a known-schema reason; never include live auth data.
    print("PANEL_IDENTITY_PROOF "+json.dumps(data,ensure_ascii=False,sort_keys=True))
    return 0 if data.get("verified",0)>0 else 1


if __name__=="__main__":
    raise SystemExit(main())
