"""One-time read-only Threads /me public ID proof for 985 Control Center.

This never creates, edits, deletes, or publishes content and never prints a
token. Reuses existing validated identity GET and strict username/user-id
binding; one broken account must not block verifying unrelated accounts.
"""
import json
import re
from datetime import datetime,timezone
from check_threads_connection import verify_route,safe_provider_failure

ROUTE_NAMES={
 "tarladaki":"🌱 Tarladaki Fasulye",
 "penguen":"🐧 Beyinsiz Penguen",
 "gonle":"❤️ Gönle Düşen",
 "daily_laugh":"😂 Daily Laugh Lab",
 "film":"🎬 Film Mağarası",
 "toonzone":"📺 ToonZone",
}
NUMERIC_ID=re.compile(r"^[0-9]{4,25}$")


def audit(probe=None, now=None):
    probe=verify_route if probe is None else probe
    stamped=(now or datetime.now(timezone.utc)).isoformat()
    results=[]
    for route,account in ROUTE_NAMES.items():
        try:
            identity=probe(route)
            identifier=str(identity.get("id") or "")
            if not NUMERIC_ID.fullmatch(identifier):
                raise RuntimeError("invalid_numeric_threads_id")
            results.append({"route":route,"account":account,"platform":"Threads",
                            "status":"identity_verified","platform_account_id":identifier,
                            "verified_at":stamped,
                            "evidence":"Live Threads Graph API GET /me and expected username"})
        except Exception as exc:
            safe=safe_provider_failure(exc)
            results.append({"route":route,"account":account,"platform":"Threads",
                            "status":"unverified",
                            "reason":safe.get("reason","connection_or_identity_unverified"),
                            "http_status":safe.get("http_status"),
                            "graph_code":safe.get("graph_code")})
    good=[r for r in results if r["status"]=="identity_verified"]
    if len({r["platform_account_id"] for r in good})!=len(good):
        return {"status":"blocked","reason":"duplicate_threads_provider_identity",
                "verified":0,"expected":len(results),"identities":[],
                "publishing_performed":False}
    return {"status":"verified_all" if len(good)==len(results) else "verified_partial",
            "verified":len(good),"expected":len(results),"identities":results,
            "publishing_performed":False,"telegram_sent":False,"crm_mutated":False}


def main():
    info=audit()
    print("PANEL_THREADS_IDENTITY_PROOF "+json.dumps(info,ensure_ascii=False,sort_keys=True))
    return 0 if info.get("verified",0)>0 else 1


if __name__=="__main__":
    raise SystemExit(main())
