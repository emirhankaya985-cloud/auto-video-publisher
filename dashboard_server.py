"""Password-protected, read-only UI over daily analytics snapshots."""
from __future__ import annotations
import hmac,json,os
from datetime import date,datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
ARCHIVE=Path(os.getenv("ANALYTICS_ARCHIVE_PATH",ROOT/"dashboard-data"/"daily_video_views.jsonl"))
TZ=ZoneInfo("Europe/Istanbul")

def _authorized(handler):
    expected=os.getenv("DASHBOARD_PASSWORD","")
    return bool(expected) and hmac.compare_digest(handler.headers.get("Authorization",""),"Bearer "+expected)

def _read():
    latest={}
    if not ARCHIVE.exists(): return []
    with ARCHIVE.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:r=json.loads(line)
            except (ValueError,TypeError):continue
            if not isinstance(r,dict) or r.get("metric") not in {"lifetime_views","follower_count","snapshot_status"}:continue
            key=(r.get("period"),r.get("account"),r.get("platform"),r.get("entity_type"),r.get("entity_id"),r.get("metric"))
            latest[key]=r
    return list(latest.values())

def build_payload():
    rows=_read();points={}
    for r in rows: points[(r.get("account"),r.get("platform"),r.get("period"),r.get("metric"),r.get("entity_type"))]=r
    groups=sorted({(r.get("account"),r.get("platform")) for r in rows if r.get("account") and r.get("platform")})
    accounts=[]
    for account,platform in groups:
        candidates=[r for r in rows if r.get("account")==account and r.get("platform")==platform and r.get("metric")=="lifetime_views" and r.get("entity_type")=="account"]
        day=max((r.get("period","") for r in candidates),default="")
        current=points.get((account,platform,day,"lifetime_views","account"))
        snap=points.get((account,platform,day,"snapshot_status","account"))
        followers=[r for r in rows if r.get("account")==account and r.get("platform")==platform and r.get("period")==day and r.get("metric")=="follower_count" and r.get("status")=="ok"]
        valid=bool(current and current.get("status")=="ok" and type(current.get("value")) is int and current["value"]>=0)
        item={"account":account,"platform":platform,"current_views":current.get("value") if valid else None,"followers":followers[-1].get("value") if followers else None,"video_count":snap.get("value") if snap and snap.get("status")=="ok" else None,"status":"ok" if valid else "incomplete","measured_at":(current or {}).get("measured_at"),"latest_day":day,"history":[]}
        try:end=date.fromisoformat(day)
        except ValueError:end=None
        for name,days in (("daily",1),("weekly",7),("monthly",30)):
            base_day=(end-timedelta(days=days)).isoformat() if end else ""
            base=points.get((account,platform,base_day,"lifetime_views","account"))
            item[name+"_delta"]=current["value"]-base["value"] if valid and base and base.get("status")=="ok" and type(base.get("value")) is int else None
        for r in candidates:
            item["history"].append({"date":r.get("period"),"value":r.get("value") if r.get("status")=="ok" and type(r.get("value")) is int else None})
        item["history"].sort(key=lambda x:x["date"] or "")
        accounts.append(item)
    measured=max((a.get("measured_at") or "" for a in accounts),default=None)
    return {"measured_at":measured,"accounts":accounts}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=="/healthz":
            self.send_response(200);self.end_headers();self.wfile.write(b"ok");return
        if self.path in ("/","/index.html"):
            body=(ROOT/"dashboard.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
        if self.path=="/api/analytics":
            if not _authorized(self):self.send_response(401);self.send_header("Cache-Control","no-store");self.end_headers();return
            body=json.dumps(build_payload(),ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
        self.send_error(404)
    def log_message(self,*_):return

if not os.getenv("DASHBOARD_PASSWORD"):raise SystemExit("DASHBOARD_PASSWORD is required")
ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
